"""
Sensor abstraction. Every physical sensor (Pi Camera 3, FLIR Lepton 3.5,
BNO085) has a simulated twin so the full stack runs on any laptop — macOS,
Windows, Linux — with zero hardware attached. Future sensors (LiDAR, UWB,
gas) plug in by subclassing Sensor and registering with the SensorSuite.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class SensorHealth:
    OK = "ok"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    SIMULATED = "simulated"
    ESTIMATED = "estimated"  # derived from another sensor, not measured


class Sensor(ABC):
    """Lifecycle: start() -> read() many times -> stop()."""

    name: str = "sensor"
    kind: str = "generic"

    def __init__(self):
        self._started = False
        self._last_read_ts: float = 0.0
        self._health: str = SensorHealth.OFFLINE
        self._detail: str = ""

    @abstractmethod
    def start(self) -> bool:
        ...

    @abstractmethod
    def read(self) -> Optional[Any]:
        ...

    def stop(self) -> None:
        self._started = False

    def _mark_read(self) -> None:
        self._last_read_ts = time.time()

    def health(self) -> Dict[str, Any]:
        stale = (time.time() - self._last_read_ts) > 2.0 if self._last_read_ts else True
        status = self._health
        if self._started and stale and status in (SensorHealth.OK, SensorHealth.SIMULATED):
            status = SensorHealth.DEGRADED
        return {
            "name": self.name,
            "kind": self.kind,
            "status": status,
            "detail": self._detail,
            "last_read_age_s": round(time.time() - self._last_read_ts, 2)
            if self._last_read_ts else None,
        }
