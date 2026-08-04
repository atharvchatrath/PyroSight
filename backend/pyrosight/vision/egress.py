"""
Classical egress detection: illuminated exit signs and daylight windows.

The open-vocabulary model knows the words "exit sign" and "window", but scores
them low indoors — an exit sign is small, and a window is a bright hole with
no texture. Everything the model produces for them therefore lands in the
POSSIBLE tier, which is the correct honest label for a lone weak signal but a
poor outcome when the thing being labelled is the way out of a burning
building.

Both objects have signatures that classical CV reads far more reliably than a
general detector does:

  * EXIT SIGN — a self-illuminated saturated green (or red) rectangle, wider
    than tall, markedly brighter than the wall it is mounted on. It is one of
    the few genuinely engineered visual targets in a building: standardised
    colour, standardised shape, lit from behind.
  * WINDOW — in a smoke-filled interior the exterior is the brightest thing in
    frame by a wide margin: a bright, low-saturation, straight-edged region
    against a dark room.

These run every frame beside the fire detector and are fused as corroboration
(vision/fusion.py) exactly like flame flicker: neural + classical agreeing
promotes the detection, classical alone still surfaces the object but stays
honestly below the confirmed tier.
"""

from __future__ import annotations

from typing import Any, Dict, List

import cv2
import numpy as np

# Exit-sign illumination bands (OpenCV HSV). Green is the international
# standard (ISO 7010 / EU); red is the common North American variant.
GREEN_LO, GREEN_HI = (40, 90, 110), (90, 255, 255)
RED_LO_A, RED_HI_A = (0, 120, 120), (8, 255, 255)
RED_LO_B, RED_HI_B = (170, 120, 120), (179, 255, 255)

SIGN_MIN_AREA_FRAC = 0.00035   # a sign down the corridor is small
SIGN_MAX_AREA_FRAC = 0.06      # bigger than this is a lit panel, not a sign
SIGN_MIN_ASPECT = 1.15         # exit signs are wider than tall
SIGN_MAX_ASPECT = 4.5
SIGN_MIN_FILL = 0.55           # roughly rectangular
SIGN_OVER_SCENE_V = 25.0       # self-illuminated: brighter than the room

WINDOW_MIN_AREA_FRAC = 0.004
WINDOW_MAX_AREA_FRAC = 0.40
WINDOW_MIN_FILL = 0.60
WINDOW_OVER_SCENE_V = 55.0     # daylight against an interior
WINDOW_MAX_SAT = 90            # daylight is washed out, not coloured
# An opening has a hard boundary; light spilling across a wall does not.
# Measured on synthetic references: a framed opening scores ~0.11 of its
# perimeter band as Canny edges, a smooth light gradient scores 0.000.
WINDOW_EDGE_PAD = 4
WINDOW_MIN_PERIMETER_EDGE = 0.05

_K5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))


def _regions(mask: np.ndarray, frame_area: float, min_frac: float,
             max_frac: float, min_fill: float) -> List[Dict[str, Any]]:
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, _K5)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, _K5)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out: List[Dict[str, Any]] = []
    for c in contours:
        area = cv2.contourArea(c)
        if area <= 0:
            continue
        frac = area / frame_area
        if frac < min_frac or frac > max_frac:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if w < 4 or h < 4:
            continue
        fill = area / float(w * h)       # rectangularity
        if fill < min_fill:
            continue
        out.append({"box": [float(x), float(y), float(x + w), float(y + h)],
                    "area_frac": frac, "fill": fill, "w": w, "h": h})
    return out


class ExitSignDetector:
    """Illuminated green/red exit signs."""

    def detect(self, frame_bgr: np.ndarray) -> List[Dict[str, Any]]:
        h, w = frame_bgr.shape[:2]
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        v = hsv[..., 2].astype(np.float32)
        scene_v = float(np.mean(v))

        green = cv2.inRange(hsv, np.array(GREEN_LO), np.array(GREEN_HI))
        red = (cv2.inRange(hsv, np.array(RED_LO_A), np.array(RED_HI_A))
               | cv2.inRange(hsv, np.array(RED_LO_B), np.array(RED_HI_B)))

        out: List[Dict[str, Any]] = []
        for mask, hue in ((green, "green"), (red, "red")):
            for r in _regions(mask, float(w * h), SIGN_MIN_AREA_FRAC,
                              SIGN_MAX_AREA_FRAC, SIGN_MIN_FILL):
                aspect = r["w"] / float(r["h"])
                if aspect < SIGN_MIN_ASPECT or aspect > SIGN_MAX_ASPECT:
                    continue
                x1, y1, x2, y2 = (int(b) for b in r["box"])
                region_v = float(np.mean(v[y1:y2, x1:x2]))
                if region_v < scene_v + SIGN_OVER_SCENE_V:
                    continue          # not self-illuminated: paint, not a sign
                # Evidence: rectangularity + how far it out-shines the room.
                conf = 0.45 + min(0.25, (region_v - scene_v) / 400.0)
                conf += min(0.15, (r["fill"] - SIGN_MIN_FILL) * 0.5)
                out.append({"cls": "exit_sign", "conf": round(min(0.9, conf), 3),
                            "box": r["box"], "source": "classical",
                            "hue": hue, "fill": round(r["fill"], 2)})
        return out


class WindowDetector:
    """Daylight openings — the brightest straight-edged region in a dark room."""

    def detect(self, frame_bgr: np.ndarray) -> List[Dict[str, Any]]:
        h, w = frame_bgr.shape[:2]
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        v = hsv[..., 2].astype(np.float32)
        s = hsv[..., 1]
        scene_v = float(np.mean(v))
        # Only meaningful when the room is darker than the opening; a
        # uniformly bright scene has no window signature to find.
        if scene_v > 200:
            return []

        bright = ((v >= scene_v + WINDOW_OVER_SCENE_V) & (s <= WINDOW_MAX_SAT))
        mask = (bright.astype(np.uint8)) * 255

        out: List[Dict[str, Any]] = []
        for r in _regions(mask, float(w * h), WINDOW_MIN_AREA_FRAC,
                          WINDOW_MAX_AREA_FRAC, WINDOW_MIN_FILL):
            x1, y1, x2, y2 = (int(b) for b in r["box"])
            # A window is an opening with a BOUNDARY: bright inside, sharp at
            # the edge. Looking for structure inside it is wrong — clear
            # daylight is featureless — so the test is on the perimeter, which
            # is exactly what separates an opening from light spilling across
            # a wall in a gradient.
            pad = WINDOW_EDGE_PAD
            ex1, ey1 = max(0, x1 - pad), max(0, y1 - pad)
            ex2, ey2 = min(w, x2 + pad), min(h, y2 + pad)
            edges = cv2.Canny(frame_bgr[ey1:ey2, ex1:ex2], 60, 160)
            band = np.zeros(edges.shape, dtype=np.uint8)
            cv2.rectangle(band, (x1 - ex1, y1 - ey1),
                          (x2 - ex1 - 1, y2 - ey1 - 1), 255, thickness=2 * pad)
            band_px = int(np.count_nonzero(band))
            edge_frac = (float(np.count_nonzero(cv2.bitwise_and(edges, band)))
                         / float(max(1, band_px)))
            if edge_frac < WINDOW_MIN_PERIMETER_EDGE:
                continue
            region_v = float(np.mean(v[y1:y2, x1:x2]))
            conf = 0.40 + min(0.25, (region_v - scene_v) / 300.0)
            conf += min(0.12, (r["fill"] - WINDOW_MIN_FILL) * 0.4)
            out.append({"cls": "window", "conf": round(min(0.85, conf), 3),
                        "box": r["box"], "source": "classical",
                        "fill": round(r["fill"], 2),
                        "edge_frac": round(edge_frac, 4)})
        return out


class EgressDetector:
    """Both egress cues in one call, for the engine's per-frame budget."""

    def __init__(self) -> None:
        self.signs = ExitSignDetector()
        self.windows = WindowDetector()

    def detect(self, frame_bgr: np.ndarray) -> List[Dict[str, Any]]:
        return self.signs.detect(frame_bgr) + self.windows.detect(frame_bgr)
