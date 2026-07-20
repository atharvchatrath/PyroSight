"""
Visual yaw estimation: when no BNO085 is attached (laptop testing) or the
IMU drops mid-incident, camera pan can still drive the compass. Global
horizontal image shift between consecutive downsampled frames (phase
correlation, sub-pixel, ~0.3 ms at 96x72) converts to a yaw delta through
the pinhole model. It drifts — it is explicitly a degraded fallback and the
sensor status says so — but a drifting compass that responds to real motion
beats a frozen one.
"""

from __future__ import annotations

import math
from typing import Optional

import cv2
import numpy as np

FLOW_W, FLOW_H = 96, 72


class VisualYaw:
    def __init__(self, rgb_fx_at_640: float = 522.0):
        self._prev: Optional[np.ndarray] = None
        self._fx_at_640 = rgb_fx_at_640
        self.heading_deg = 0.0

    def update(self, frame_bgr: np.ndarray) -> float:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (FLOW_W, FLOW_H)).astype(np.float32)
        if self._prev is not None:
            (dx, _dy), response = cv2.phaseCorrelate(self._prev, small)
            # Low response = unreliable match (motion blur, occlusion): skip.
            if response > 0.05 and abs(dx) < FLOW_W * 0.5:
                fx_small = self._fx_at_640 * (FLOW_W / 640.0)
                # Camera panning right shifts image content left.
                yaw_delta = -math.degrees(math.atan2(dx, fx_small))
                self.heading_deg = (self.heading_deg + yaw_delta) % 360.0
        self._prev = small
        return self.heading_deg
