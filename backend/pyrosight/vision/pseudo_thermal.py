"""
RGB-derived thermal estimate — the honest fallback when no FLIR Lepton is
attached (e.g. laptop testing, or a failed thermal camera mid-incident).

This is an *estimate*, labeled as such everywhere it surfaces, and it is
deliberately conservative about the top of its range. Anything it reports
above the hotspot threshold would drive a heat alarm, so it may only reach
flame temperatures where the image contains actual flame evidence:

  * SKIN IS EXCLUDED. A face under warm indoor light lands squarely in the
    flame hue band. Mapping that to 300 °C put a fire on a tester's nose;
    the YCrCb skin-chroma mask now removes those pixels before any
    temperature is assigned.
  * A BLOWN-OUT CORE IS REQUIRED for flame temperatures. Flame-coloured
    pixels without one (wood, hi-vis fabric, warm lamplight, a red shirt)
    top out at WARM_MAX_C — visible on the ironbow as warm, but below the
    90 °C hotspot threshold, so an estimate can never manufacture a hotspot
    or an EXTREME HEAT alert on its own.

Fusion additionally treats this field as non-independent evidence, so it can
never confirm a detection either.
"""

from __future__ import annotations

import cv2
import numpy as np

from .fire import build_fire_mask, skin_mask

AMBIENT_C = 22.0
WARM_MAX_C = 68.0     # flame-coloured, no core: warm, not burning
CORE_DILATE = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))


def estimate_from_rgb(frame_bgr: np.ndarray, out_w: int = 160,
                      out_h: int = 120) -> np.ndarray:
    small = cv2.resize(frame_bgr, (out_w, out_h), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)

    # Base: bright surfaces read slightly warm (lamps, sunlit walls).
    temp = AMBIENT_C + (gray / 255.0) * 14.0

    # build_fire_mask removes skin chroma before the core-adjacency test, so a
    # nose highlight can never qualify as a flame core here either.
    fire_mask, white_core = build_fire_mask(small, hsv)
    not_skin = cv2.bitwise_not(skin_mask(small))
    fire_mask = cv2.bitwise_and(fire_mask, not_skin)
    white_core = cv2.bitwise_and(white_core, not_skin)

    if int(np.count_nonzero(fire_mask)) > 0:
        intensity = hsv[..., 2].astype(np.float32) / 255.0
        # Flame temperatures only where a blown-out core is present or
        # immediately adjacent — that is the combustion signature.
        core_zone = cv2.bitwise_and(fire_mask, cv2.dilate(white_core, CORE_DILATE))
        warm = AMBIENT_C + intensity * (WARM_MAX_C - AMBIENT_C)
        temp = np.where(fire_mask > 0, np.maximum(temp, warm), temp)
        if int(np.count_nonzero(core_zone)) > 0:
            fire_temp = 260.0 + intensity * 340.0
            temp = np.where(core_zone > 0, np.maximum(temp, fire_temp), temp)

    temp = cv2.GaussianBlur(temp, (5, 5), 1.2)
    return temp.astype(np.float32)
