"""
Heading filter: EMA smoothing of IMU yaw with correct 0/360 wraparound.
The BNO085 does its own 9-DoF fusion, so a light filter is enough to kill
the residual jitter that would make the HUD compass swim.
"""

from __future__ import annotations

from typing import Optional


class HeadingFilter:
    def __init__(self, alpha: float = 0.30):
        self._alpha = alpha
        self._heading: Optional[float] = None

    @property
    def heading_deg(self) -> float:
        return self._heading if self._heading is not None else 0.0

    def update(self, yaw_deg: Optional[float]) -> float:
        if yaw_deg is None:
            return self.heading_deg
        yaw = yaw_deg % 360.0
        if self._heading is None:
            self._heading = yaw
        else:
            delta = (yaw - self._heading + 180.0) % 360.0 - 180.0
            self._heading = (self._heading + self._alpha * delta) % 360.0
        return self._heading

    @staticmethod
    def cardinal(deg: float) -> str:
        names = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                 "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        return names[int((deg % 360.0 + 11.25) // 22.5) % 16]
