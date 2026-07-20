"""
Renderers that turn the SimWorld into sensor-level imagery.

  * render_rgb()     -> BGR frame styled like a smoke-filled corridor. Flame
    particles use real fire hues so the HSV fire detector triggers honestly;
    smoke haze genuinely reduces contrast so the smoke estimator measures a
    real signal, not a piped-through constant.
  * render_thermal() -> float32 temperature field in deg C at Lepton 3.5
    resolution (160x120), with sensor noise. Hotspot extraction and body-
    heat fusion run on this exactly as they would on real Lepton output.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

import cv2
import numpy as np

from .world import (AMBIENT_C, CAM_H, CORRIDOR_HALF_W, CORRIDOR_LEN, WALL_H,
                    SimWorld)

RGB_FX = 522.0     # ~63 deg HFOV at 640 px
THERMAL_FX = 147.0  # ~57 deg HFOV at 160 px (Lepton 3.5)


def _project_quad(world: SimWorld, cam, corners3d, w: int, h: int,
                  fx: float) -> Optional[np.ndarray]:
    pts = []
    for (px, py, pz) in corners3d:
        right, fwd = world.to_cam(px, py, cam)
        p = world.project(right, fwd, pz, w, h, fx)
        if p is None:
            return None
        pts.append(p)
    return np.array(pts, dtype=np.int32)


def _shade(base: Tuple[int, int, int], dist: float, density: float) -> Tuple[int, int, int]:
    """Distance + smoke attenuation toward the haze color."""
    haze = (98, 96, 92)  # BGR gray, slightly warm
    a = 1.0 - math.exp(-(0.05 + density * 0.14) * dist)
    a = min(0.92, a)
    return tuple(int(b * (1 - a) + hz * a) for b, hz in zip(base, haze))


def render_rgb(world: SimWorld, w: int = 640, h: int = 480) -> np.ndarray:
    cam = world.camera_pose()
    cx, cy, _ = cam
    density = world.smoke_density()
    frame = np.full((h, w, 3), (30, 28, 26), dtype=np.uint8)

    polys: List[Tuple[float, np.ndarray, Tuple[int, int, int]]] = []
    step = 0.5

    def add_quad(corners3d, dist, color):
        q = _project_quad(world, cam, corners3d, w, h, RGB_FX)
        if q is not None:
            polys.append((dist, q, _shade(color, dist, density)))

    # End walls.
    for y_end in (CORRIDOR_LEN, 0.0):
        add_quad([(-CORRIDOR_HALF_W, y_end, 0), (CORRIDOR_HALF_W, y_end, 0),
                  (CORRIDOR_HALF_W, y_end, WALL_H), (-CORRIDOR_HALF_W, y_end, WALL_H)],
                 abs(y_end - cy) + 0.5, (66, 70, 74))

    # Floor / ceiling / side-wall slices.
    y = 0.0
    while y < CORRIDOR_LEN:
        y2 = min(y + step, CORRIDOR_LEN)
        mid = (y + y2) / 2.0
        dist = math.hypot(mid - cy, 0.0) + 0.01
        add_quad([(-CORRIDOR_HALF_W, y, 0), (CORRIDOR_HALF_W, y, 0),
                  (CORRIDOR_HALF_W, y2, 0), (-CORRIDOR_HALF_W, y2, 0)],
                 dist, (52, 60, 68))                       # floor: warm gray
        add_quad([(-CORRIDOR_HALF_W, y, WALL_H), (CORRIDOR_HALF_W, y, WALL_H),
                  (CORRIDOR_HALF_W, y2, WALL_H), (-CORRIDOR_HALF_W, y2, WALL_H)],
                 dist, (40, 40, 42))                       # ceiling: darker
        for wx in (-CORRIDOR_HALF_W, CORRIDOR_HALF_W):
            base = (78, 82, 86) if wx < 0 else (72, 76, 82)
            add_quad([(wx, y, 0), (wx, y2, 0), (wx, y2, WALL_H), (wx, y, WALL_H)],
                     math.hypot(wx - cx, mid - cy), base)
        y = y2

    # Doors / window / exit sign quads (drawn just on top of their wall).
    for e in world.entities:
        if not e.wall_mounted:
            continue
        if abs(e.y - CORRIDOR_LEN) < 1e-6:
            c3d = [(e.x - e.width / 2, e.y - 0.01, e.z_lo),
                   (e.x + e.width / 2, e.y - 0.01, e.z_lo),
                   (e.x + e.width / 2, e.y - 0.01, e.z_hi),
                   (e.x - e.width / 2, e.y - 0.01, e.z_hi)]
        else:
            inset = 0.02 if e.x < 0 else -0.02
            c3d = [(e.x + inset, e.y - e.width / 2, e.z_lo),
                   (e.x + inset, e.y + e.width / 2, e.z_lo),
                   (e.x + inset, e.y + e.width / 2, e.z_hi),
                   (e.x + inset, e.y - e.width / 2, e.z_hi)]
        dist = math.hypot(e.x - cx, e.y - cy) - 0.05
        if e.kind == "door":
            color = (28, 42, 90)          # dark wood
        elif e.kind == "window":
            color = (120, 96, 70)         # cool glass
        else:                             # exit sign: emissive green
            color = (60, 210, 40)
        q = _project_quad(world, cam, c3d, w, h, RGB_FX)
        if q is not None:
            polys.append((dist, q, color))

    # Painter's algorithm: far to near.
    for dist, q, color in sorted(polys, key=lambda p: -p[0]):
        if q is not None:
            cv2.fillPoly(frame, [q], color)

    _draw_people(world, cam, frame, w, h)
    _draw_fire(world, cam, frame, w, h)
    _apply_smoke(frame, density)

    noise = np.random.default_rng().normal(0, 4.0, frame.shape).astype(np.float32)
    frame = np.clip(frame.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    return frame


def _draw_people(world: SimWorld, cam, frame: np.ndarray, w: int, h: int) -> None:
    for e in world.entities:
        if e.kind not in ("person", "firefighter"):
            continue
        right, fwd = world.to_cam(e.x, e.y, cam)
        if fwd < 0.4:
            continue
        base = world.project(right, fwd, 0.0, w, h, RGB_FX)
        top = world.project(right, fwd, e.z_hi, w, h, RGB_FX)
        if base is None or top is None:
            continue
        px = int(base[0])
        y_top, y_bot = int(top[1]), int(base[1])
        body_h = max(4, y_bot - y_top)
        half_w = max(2, int(body_h * 0.22))
        if e.kind == "firefighter":
            body_c, head_c = (30, 190, 220), (60, 60, 60)  # hi-vis jacket
        else:
            body_c, head_c = (60, 55, 70), (140, 150, 170)  # victim, dim
        cv2.ellipse(frame, (px, y_bot - body_h // 3), (half_w, body_h // 3),
                    0, 0, 360, body_c, -1)
        cv2.circle(frame, (px, y_top + body_h // 8), max(2, body_h // 9), head_c, -1)
        if e.kind == "firefighter":  # reflective stripe
            cv2.line(frame, (px - half_w, y_bot - body_h // 3),
                     (px + half_w, y_bot - body_h // 3), (180, 230, 235), 2)


def _draw_fire(world: SimWorld, cam, frame: np.ndarray, w: int, h: int) -> None:
    fx_w, fy_w = world.fire_pos
    right, fwd = world.to_cam(fx_w, fy_w, cam)
    if fwd < 0.4:
        return
    size = world.fire_size()
    base = world.project(right, fwd, 0.0, w, h, RGB_FX)
    top = world.project(right, fwd, size, w, h, RGB_FX)
    if base is None or top is None:
        return
    px, py = int(base[0]), int(base[1])
    flame_h = max(6, py - int(top[1]))
    half_w = max(3, int(flame_h * 0.4))
    t = world.now()
    rng = np.random.default_rng(int(t * 30) % 100000)
    # Glow first (blended), then particles in real flame hues.
    glow = frame.copy()
    cv2.circle(glow, (px, py - flame_h // 2), int(flame_h * 0.9), (0, 90, 200), -1)
    cv2.addWeighted(glow, 0.35, frame, 0.65, 0, dst=frame)
    colors = [(0, 100, 240), (0, 160, 250), (0, 220, 255), (150, 245, 255)]
    for i in range(36):
        fy = rng.random()
        fx_off = (rng.random() - 0.5) * (1.0 - fy * 0.7)
        ex = px + int(fx_off * 2 * half_w)
        ey = py - int(fy * flame_h)
        r = max(1, int((1.0 - fy) * half_w * 0.5 + 1))
        cv2.circle(frame, (ex, ey), r, colors[min(3, int(fy * 4))], -1)


def _apply_smoke(frame: np.ndarray, density: float) -> None:
    h, w = frame.shape[:2]
    # Smoke banks at the ceiling: alpha ramps from bottom to top.
    ramp = np.linspace(0.30, 0.95, h, dtype=np.float32)[::-1].reshape(h, 1, 1)
    alpha = np.clip(ramp * density, 0.0, 0.9)
    smoke_color = np.array([132, 130, 126], dtype=np.float32)
    f = frame.astype(np.float32)
    f = f * (1.0 - alpha) + smoke_color * alpha
    # Global contrast loss with density.
    mean = f.mean()
    f = f * (1.0 - 0.35 * density) + mean * (0.35 * density)
    np.copyto(frame, np.clip(f, 0, 255).astype(np.uint8))


# ---------------------------------------------------------------------------
# Thermal
# ---------------------------------------------------------------------------

def render_thermal(world: SimWorld, w: int = 160, h: int = 120) -> np.ndarray:
    cam = world.camera_pose()
    density = world.smoke_density()
    temp = np.full((h, w), AMBIENT_C, dtype=np.float32)

    # Hot gas layer near the ceiling grows with smoke density.
    layer = np.linspace(1.0, 0.0, h, dtype=np.float32).reshape(h, 1)
    temp += (layer ** 2) * density * 95.0

    sources = []
    for e in world.entities:
        if e.temp_c is not None:
            sources.append((e.x, e.y, (e.z_lo + e.z_hi) / 2.0,
                            e.temp_c, max(0.35, e.width / 2.0)))
    sources.append((world.fire_pos[0], world.fire_pos[1],
                    world.fire_size() / 2.0, world.fire_temp_c(),
                    world.fire_size() * 0.55))

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    for (sx, sy, sz, s_temp, s_rad) in sources:
        right, fwd = world.to_cam(sx, sy, cam)
        p = world.project(right, fwd, sz, w, h, THERMAL_FX)
        if p is None:
            continue
        px, py = p
        if not (-w * 0.5 <= px <= w * 1.5 and -h * 0.5 <= py <= h * 1.5):
            continue
        dist = max(0.3, math.hypot(right, fwd))
        r_px = max(2.0, THERMAL_FX * s_rad / dist)
        d2 = ((xx - px) ** 2 + (yy - py) ** 2) / (r_px ** 2)
        blob = np.exp(-d2 * 1.2)
        # Radiation through smoke attenuates mildly (IR penetrates smoke).
        atten = math.exp(-density * dist * 0.03)
        temp = np.maximum(temp, AMBIENT_C + (s_temp - AMBIENT_C) * blob * atten)
        # Rising plume above the fire.
        if s_temp > 200:
            plume = np.exp(-(((xx - px) / (r_px * 0.7)) ** 2
                             + ((yy - (py - r_px * 1.6)) / (r_px * 1.8)) ** 2))
            temp = np.maximum(temp, AMBIENT_C + (s_temp * 0.45 - AMBIENT_C) * plume * atten)

    temp = cv2.GaussianBlur(temp, (5, 5), 1.2)
    temp += np.random.default_rng().normal(0, 0.6, temp.shape).astype(np.float32)
    return temp
