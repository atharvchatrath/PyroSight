"""
Classical fire detection on the RGB stream.

A real flame — from a lighter up to a room fire — has a characteristic
signature that skin, wood, and hi-vis fabric do not:

  * a WHITE-HOT CORE: near-saturated brightness with LOW color saturation
    (the sensor blows out), fringed by
  * a COLORED RING of saturated orange/yellow, and
  * temporal FLICKER: the mask shimmers frame to frame.

The detector therefore builds two masks — colored flame and white-hot —
and only accepts white-hot pixels that sit adjacent to colored flame
(a bare white blob is a lamp; a bare orange blob might be a jacket).
Small regions are allowed (a lighter flame is ~100-400 px at webcam
range) but must be emissive-bright; confidence is assembled from the
evidence present (white core, flicker, size), and fusion caps anything
without independent thermal corroboration below the confirmed tier.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import cv2
import numpy as np

# Colored-flame bands (OpenCV hue 0-179).
ORANGE_LO, ORANGE_HI = (5, 140, 180), (22, 255, 255)
YELLOW_LO, YELLOW_HI = (22, 100, 200), (35, 255, 255)
# White-hot core: extremely bright, washed-out color.
WHITE_HOT_V_MIN = 235
WHITE_HOT_S_MAX = 130

MIN_AREA_FRAC = 0.0003     # ~90 px at 640x480: a small lighter flame
MAX_AREA_FRAC = 0.45       # larger = white balance / lighting, not flame
REGION_MIN_V = 190.0       # region must be emissive-bright ...
REGION_OVER_SCENE_V = 20.0  # ... and clearly brighter than the scene
WHITE_CORE_MIN_PX = 6      # glint-sized specks don't count as a core

# Kept for external callers (pseudo-thermal shares the exact same model of
# what "fire-colored" means so the two never disagree).
HSV_FIRE_RANGES = [(ORANGE_LO, ORANGE_HI), (YELLOW_LO, YELLOW_HI)]

_K3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
_K7 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
_K9 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))


def build_fire_mask(frame_bgr: np.ndarray,
                    hsv: np.ndarray = None) -> Tuple[np.ndarray, np.ndarray]:
    """Returns (fire_mask, white_core_mask). White-hot pixels only count
    when adjacent to colored flame — that adjacency is what separates a
    flame core from a lamp or a specular glint."""
    if hsv is None:
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    colored = (cv2.inRange(hsv, np.array(ORANGE_LO), np.array(ORANGE_HI))
               | cv2.inRange(hsv, np.array(YELLOW_LO), np.array(YELLOW_HI)))
    white = cv2.inRange(hsv, np.array((0, 0, WHITE_HOT_V_MIN)),
                        np.array((179, WHITE_HOT_S_MAX, 255)))
    ring = cv2.dilate(colored, _K9)
    white_core = cv2.bitwise_and(white, ring)
    return cv2.bitwise_or(colored, white_core), white_core


class FireDetector:
    def __init__(self):
        self._prev_mask: np.ndarray = None  # type: ignore[assignment]

    def detect(self, frame_bgr: np.ndarray) -> List[Dict[str, Any]]:
        h, w = frame_bgr.shape[:2]
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        v_chan = hsv[..., 2].astype(np.float32)
        scene_v = float(np.mean(v_chan))

        mask, white_core = build_fire_mask(frame_bgr, hsv)
        # Gentle cleanup only — a 5x5 opening would erase a lighter flame.
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, _K3)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, _K7)

        flicker = None
        if self._prev_mask is not None and self._prev_mask.shape == mask.shape:
            flicker = cv2.bitwise_xor(mask, self._prev_mask)
        self._prev_mask = mask

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        min_area = max(1.0, MIN_AREA_FRAC * w * h)
        max_area = MAX_AREA_FRAC * w * h
        out: List[Dict[str, Any]] = []
        for c in contours:
            area = cv2.contourArea(c)
            if area < min_area or area > max_area:
                continue
            x, y, bw, bh = cv2.boundingRect(c)

            region_mask = mask[y:y + bh, x:x + bw] > 0
            if not region_mask.any():
                continue
            white_px = int(np.count_nonzero(white_core[y:y + bh, x:x + bw]))
            has_core = white_px >= WHITE_CORE_MIN_PX

            # Emissive-brightness gate (a white core is itself proof of
            # emission, so core-bearing regions pass automatically).
            region_v = float(np.mean(v_chan[y:y + bh, x:x + bw][region_mask]))
            if not has_core and (region_v < REGION_MIN_V
                                 or region_v < scene_v + REGION_OVER_SCENE_V):
                continue

            flicker_ratio = 0.0
            if flicker is not None:
                region = flicker[y:y + bh, x:x + bw]
                flicker_ratio = (float(np.count_nonzero(region))
                                 / float(max(1, bw * bh)))

            # Evidence-assembled confidence.
            conf = 0.35
            if has_core:
                conf += 0.12
            conf += min(0.15, (area / (w * h)) * 3.0)
            if flicker_ratio < 0.02:
                conf = min(conf, 0.38)   # rock-steady: possible at best
            elif flicker_ratio > 0.05:
                conf = min(0.80, conf + 0.15)
            out.append({"cls": "fire", "conf": round(conf, 3),
                        "box": [float(x), float(y), float(x + bw), float(y + bh)],
                        "source": "hsv",
                        "flicker": round(flicker_ratio, 3),
                        "white_core_px": white_px})
        return out
