"""
SITL world model: a synthetic single-corridor building used when no real
hardware is attached (macOS / Windows development, demos, CI).

Design intent — honesty about what is simulated:
  * The world produces *sensor-level* outputs: an RGB frame, a thermal
    temperature field (deg C), and IMU heading. The real perception
    algorithms (hotspot extraction, smoke estimation, HSV fire detection,
    tracking, fusion, navigation) then run unmodified on those outputs.
  * Neural-network detections are the one exception: YOLO cannot recognize
    the stylized figures, so in sim mode the world emits ground-truth boxes
    degraded by realistic noise (confidence falloff with smoke + distance,
    dropouts, jitter). The degradation happens *before* the tracker, so the
    temporal-confidence machinery is exercised exactly as it would be live.

Coordinate frame: meters. +Y runs from the entry (y=0) into the building,
+X is right when facing +Y. Yaw is compass-style: 0 deg = +Y, positive
clockwise. Camera height 1.6 m.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

CORRIDOR_HALF_W = 1.2
CORRIDOR_LEN = 20.0
WALL_H = 2.6
CAM_H = 1.6
LOOP_PERIOD = 140.0

AMBIENT_C = 24.0


@dataclass
class Entity:
    """A detectable thing in the world."""
    kind: str                 # taxonomy class name
    x: float
    y: float
    width: float              # meters (billboard width or wall-run length)
    z_lo: float
    z_hi: float
    wall_mounted: bool = False  # True: quad lies along the wall plane
    base_conf: float = 0.9
    temp_c: Optional[float] = None  # thermal signature (None = no signature)
    label: str = ""


# Camera keyframes: (t, x, y, yaw_deg). Linear interpolation, shortest-arc yaw.
KEYFRAMES: List[Tuple[float, float, float, float]] = [
    (0.0, 0.0, 0.5, 0.0),
    (8.0, 0.0, 3.5, 0.0),
    (11.0, 0.0, 3.5, -60.0),   # inspect door A (left)
    (14.0, 0.0, 3.5, 0.0),
    (22.0, 0.0, 7.5, 0.0),
    (26.0, 0.0, 7.5, -35.0),   # inspect fire (left wall)
    (30.0, 0.0, 7.5, 55.0),    # inspect door B (right)
    (34.0, 0.0, 7.5, 0.0),
    (42.0, 0.2, 10.5, 0.0),
    (46.0, 0.2, 10.5, 45.0),   # inspect victim
    (54.0, 0.2, 10.5, 45.0),
    (58.0, 0.2, 10.5, 0.0),
    (64.0, 0.0, 15.0, 0.0),
    (68.0, 0.0, 15.0, 55.0),   # inspect window (right)
    (72.0, 0.0, 15.0, 0.0),
    (80.0, 0.0, 18.5, 0.0),
    (88.0, 0.0, 18.5, 0.0),    # face the exit
    (94.0, 0.0, 18.5, 180.0),  # turn around
    (120.0, 0.0, 6.0, 180.0),  # walk back toward entry
    (132.0, 0.0, 1.0, 180.0),
    (137.0, 0.0, 1.0, 0.0),    # turn to face in again
    (140.0, 0.0, 0.5, 0.0),
]


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _lerp_angle(a: float, b: float, t: float) -> float:
    d = (b - a + 180.0) % 360.0 - 180.0
    return (a + d * t) % 360.0


class SimWorld:
    """Single source of truth shared by all simulated sensors."""

    def __init__(self, seed: int = 7):
        self.t0 = time.time()
        self.rng = random.Random(seed)
        self.exit_pos = (0.0, CORRIDOR_LEN)
        self.entities: List[Entity] = [
            Entity("door", -CORRIDOR_HALF_W, 4.0, 0.9, 0.0, 2.0,
                   wall_mounted=True, base_conf=0.82, label="DOOR A"),
            Entity("door", CORRIDOR_HALF_W, 8.0, 0.9, 0.0, 2.0,
                   wall_mounted=True, base_conf=0.82, temp_c=62.0, label="DOOR B"),
            Entity("door", -CORRIDOR_HALF_W, 13.0, 0.9, 0.0, 2.0,
                   wall_mounted=True, base_conf=0.78, label="STAIRWELL"),
            Entity("window", CORRIDOR_HALF_W, 16.0, 1.1, 0.9, 2.1,
                   wall_mounted=True, base_conf=0.74, label="WINDOW"),
            Entity("door", 0.0, CORRIDOR_LEN, 0.9, 0.0, 2.0,
                   wall_mounted=True, base_conf=0.86, label="EXIT DOOR"),
            Entity("exit_sign", 0.0, CORRIDOR_LEN, 0.6, 2.15, 2.45,
                   wall_mounted=True, base_conf=0.93, label="EXIT SIGN"),
            Entity("person", 0.7, 11.0, 0.7, 0.0, 1.0,
                   base_conf=0.88, temp_c=34.0, label="VICTIM"),
            Entity("firefighter", -0.6, 6.0, 0.6, 0.0, 1.8,
                   base_conf=0.85, temp_c=36.0, label="FF-2"),
        ]
        self.fire_pos = (-1.05, 9.0)

    # ---- time & environment ----

    def now(self) -> float:
        return time.time() - self.t0

    def loop_t(self) -> float:
        return self.now() % LOOP_PERIOD

    def smoke_density(self) -> float:
        """0..1, builds over the first 3 minutes then plateaus + breathes."""
        t = self.now()
        base = min(0.72, 0.12 + t / 240.0)
        return max(0.0, min(1.0, base + 0.05 * math.sin(t * 0.31)))

    def fire_temp_c(self) -> float:
        t = self.now()
        growth = min(1.0, t / 150.0)
        flicker = 60.0 * math.sin(t * 7.1) + 40.0 * math.sin(t * 13.7)
        return 420.0 + 380.0 * growth + flicker

    def fire_size(self) -> float:
        """Approx flame envelope height in meters."""
        return 0.7 + 0.9 * min(1.0, self.now() / 150.0)

    # ---- camera (firefighter head) pose ----

    def camera_pose(self) -> Tuple[float, float, float]:
        """Returns (x, y, yaw_deg) with head sway and bob applied to yaw."""
        t = self.loop_t()
        kfs = KEYFRAMES
        for i in range(len(kfs) - 1):
            t0, x0, y0, w0 = kfs[i]
            t1, x1, y1, w1 = kfs[i + 1]
            if t0 <= t <= t1:
                f = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
                x = _lerp(x0, x1, f)
                y = _lerp(y0, y1, f)
                yaw = _lerp_angle(w0, w1, f)
                sway = 7.0 * math.sin(self.now() * 2.0 * math.pi * 0.22)
                return x, y, (yaw + sway) % 360.0
        x, y, yaw = kfs[-1][1], kfs[-1][2], kfs[-1][3]
        return x, y, yaw

    def moving_entities_tick(self) -> None:
        """FF-2 paces slowly along the corridor."""
        t = self.now()
        for e in self.entities:
            if e.kind == "firefighter":
                e.y = 6.0 + 1.6 * math.sin(t * 0.18)

    # ---- projection ----

    @staticmethod
    def to_cam(px: float, py: float, cam: Tuple[float, float, float]) -> Tuple[float, float]:
        """World (x, y) -> camera-frame (right, forward)."""
        cx, cy, yaw = cam
        dx, dy = px - cx, py - cy
        rad = math.radians(yaw)
        fwd = dx * math.sin(rad) + dy * math.cos(rad)
        right = dx * math.cos(rad) - dy * math.sin(rad)
        return right, fwd

    @staticmethod
    def project(right: float, fwd: float, z: float,
                w: int, h: int, fx: float) -> Optional[Tuple[float, float]]:
        if fwd < 0.15:
            return None
        u = w / 2.0 + fx * right / fwd
        v = h / 2.0 - fx * (z - CAM_H) / fwd
        return u, v

    # ---- ground-truth detections (sim stand-in for the neural detector) ----

    def detections(self, w: int, h: int, fx: float) -> List[Dict]:
        """Noisy ground-truth boxes in image space, pre-degraded to mimic a
        real edge detector operating through smoke."""
        self.moving_entities_tick()
        cam = self.camera_pose()
        density = self.smoke_density()
        out: List[Dict] = []
        for e in self.entities:
            box = self._entity_bbox(e, cam, w, h, fx)
            if box is None:
                continue
            x1, y1, x2, y2 = box
            if x2 - x1 < 6 or y2 - y1 < 6:
                continue
            right, fwd = self.to_cam(e.x, e.y, cam)
            dist = math.hypot(right, fwd)
            # Visibility falls with smoke and distance (Beer-Lambert-ish).
            vis = math.exp(-density * dist * 0.16)
            conf = e.base_conf * (0.45 + 0.55 * vis)
            conf += self.rng.uniform(-0.06, 0.06)
            conf = max(0.0, min(0.99, conf))
            dropout_p = 0.04 + 0.55 * (1.0 - vis)
            if conf < 0.15 or self.rng.random() < dropout_p:
                continue
            j = 3.0
            out.append({
                "cls": e.kind,
                "conf": round(conf, 3),
                "box": [
                    max(0.0, x1 + self.rng.uniform(-j, j)),
                    max(0.0, y1 + self.rng.uniform(-j, j)),
                    min(float(w), x2 + self.rng.uniform(-j, j)),
                    min(float(h), y2 + self.rng.uniform(-j, j)),
                ],
                "dist_m": dist,
                "label_hint": e.label,
            })
        # Fire region as a detection too (corroborated by thermal + HSV).
        fire_box = self._fire_bbox(cam, w, h, fx)
        if fire_box is not None:
            out.append({
                "cls": "fire", "conf": round(self.rng.uniform(0.8, 0.95), 3),
                "box": list(fire_box),
                "dist_m": math.hypot(*self.to_cam(*self.fire_pos, cam=cam)),
                "label_hint": "FIRE",
            })
        return out

    def _entity_bbox(self, e: Entity, cam, w: int, h: int,
                     fx: float) -> Optional[Tuple[float, float, float, float]]:
        if e.wall_mounted:
            # Quad runs along the wall (constant x for side walls; along x
            # for the far wall at y == CORRIDOR_LEN).
            if abs(e.y - CORRIDOR_LEN) < 1e-6:
                corners = [(e.x - e.width / 2, e.y), (e.x + e.width / 2, e.y)]
            else:
                corners = [(e.x, e.y - e.width / 2), (e.x, e.y + e.width / 2)]
        else:
            # Billboard facing the camera.
            corners = [(e.x - e.width / 2, e.y), (e.x + e.width / 2, e.y)]
        pts = []
        for (px, py) in corners:
            right, fwd = self.to_cam(px, py, cam)
            for z in (e.z_lo, e.z_hi):
                p = self.project(right, fwd, z, w, h, fx)
                if p is None:
                    return None
                pts.append(p)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x1, x2 = min(xs), max(xs)
        y1, y2 = min(ys), max(ys)
        if x2 < 0 or x1 > w or y2 < 0 or y1 > h:
            return None
        return x1, y1, x2, y2

    def _fire_bbox(self, cam, w: int, h: int,
                   fx: float) -> Optional[Tuple[float, float, float, float]]:
        fx_w, fy_w = self.fire_pos
        size = self.fire_size()
        right, fwd = self.to_cam(fx_w, fy_w, cam)
        p_lo = self.project(right, fwd, 0.0, w, h, fx)
        p_hi = self.project(right, fwd, size, w, h, fx)
        if p_lo is None or p_hi is None:
            return None
        half_w_px = fx * (size * 0.45) / max(fwd, 0.2)
        x1 = p_lo[0] - half_w_px
        x2 = p_lo[0] + half_w_px
        y1, y2 = p_hi[1], p_lo[1]
        if x2 < 0 or x1 > w or y2 < 0 or y1 > h:
            return None
        return (max(0.0, x1), max(0.0, y1), min(float(w), x2), min(float(h), y2))

    # ---- truth for navigation (stands in for UWB / dead reckoning) ----

    def true_position(self) -> Tuple[float, float]:
        x, y, _ = self.camera_pose()
        return x, y

    def heading_deg(self) -> float:
        return self.camera_pose()[2]
