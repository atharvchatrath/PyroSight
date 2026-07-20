"""
RGB-derived thermal estimate — the honest fallback when no FLIR Lepton is
attached (e.g. laptop testing, or a failed thermal camera mid-incident).

This is an *estimate*, clearly labeled as such throughout the UI: flame-
colored regions map to fire temperatures, bright emissive areas map to
warm, everything else sits near ambient. It keeps the fusion pipeline,
hotspot analysis, and fused view coherent with what the RGB camera actually
sees, instead of fusing against a disconnected simulation.
"""

from __future__ import annotations

import cv2
import numpy as np

from .fire import build_fire_mask

AMBIENT_C = 22.0


def estimate_from_rgb(frame_bgr: np.ndarray, out_w: int = 160,
                      out_h: int = 120) -> np.ndarray:
    small = cv2.resize(frame_bgr, (out_w, out_h), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)

    # Base: bright surfaces read slightly warm (lamps, sunlit walls).
    temp = AMBIENT_C + (gray / 255.0) * 14.0

    # Flame regions (shared model with the fire detector, including
    # white-hot cores): map intensity to fire temperatures.
    fire_mask, _white_core = build_fire_mask(small, hsv)
    if int(np.count_nonzero(fire_mask)) > 0:
        intensity = (hsv[..., 2].astype(np.float32) / 255.0)
        fire_temp = 260.0 + intensity * 340.0
        temp = np.where(fire_mask > 0, np.maximum(temp, fire_temp), temp)

    temp = cv2.GaussianBlur(temp, (5, 5), 1.2)
    return temp.astype(np.float32)
