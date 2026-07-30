"""
Physiological load monitoring. read() returns:
  {"heart_rate_bpm", "core_temp_c", "spo2_pct", "exertion"}  (exertion 0..1)

  * BlePhysioStrap  — placeholder for a BLE chest strap (e.g. Polar H10).
                      No pairing flow is wired up yet, so this always
                      reports OFFLINE rather than inventing vitals — a
                      fabricated heart rate is worse than an absent one.
  * SimulatedPhysio — SITL exertion model: heart rate and core temperature
                      climb with movement and time-in-IDLH, with a decay
                      toward baseline when still, so the alert thresholds
                      have real work to do in the demo.
"""

from __future__ import annotations

import random
import time
from typing import Any, Dict, Optional

from ..sim.world import SimWorld
from .base import Sensor, SensorHealth


class BlePhysioStrap(Sensor):
    name = "physio_ble"
    kind = "physio"

    def start(self) -> bool:
        try:
            import bleak  # type: ignore  # noqa: F401
        except ImportError:
            self._health = SensorHealth.OFFLINE
            self._detail = "bleak not installed — no BLE HR strap"
            return False
        # Device discovery/pairing isn't implemented yet — a real deployment
        # would scan for a configured MAC here. Report offline honestly
        # rather than fabricate vitals from a strap we never connected to.
        self._health = SensorHealth.OFFLINE
        self._detail = "BLE HR strap pairing not configured"
        return False

    def read(self) -> Optional[Dict[str, Any]]:
        return None


class SimulatedPhysio(Sensor):
    name = "physio_sim"
    kind = "physio"

    def __init__(self, world: SimWorld):
        super().__init__()
        self._world = world
        self._rng = random.Random(29)
        self._hr = 92.0
        self._core = 37.0
        self._last_pos = None
        self._t0 = time.time()

    def start(self) -> bool:
        self._started = True
        self._health = SensorHealth.SIMULATED
        self._detail = "SITL exertion model (movement + time-in-IDLH)"
        return True

    def read(self) -> Optional[Dict[str, Any]]:
        self._mark_read()
        x, y, _yaw = self._world.camera_pose()
        moving = False
        if self._last_pos is not None:
            moving = ((x - self._last_pos[0]) ** 2
                      + (y - self._last_pos[1]) ** 2) ** 0.5 > 1e-4
        self._last_pos = (x, y)

        elapsed = time.time() - self._t0
        # Heart rate climbs under exertion plus slow heat/time exposure,
        # recovers toward a resting baseline when still.
        target = 92.0 + (55.0 if moving else 0.0) + min(30.0, elapsed / 12.0)
        self._hr += (target - self._hr) * 0.06 + self._rng.uniform(-1.5, 1.5)
        self._hr = max(60.0, min(200.0, self._hr))

        core_target = 37.0 + min(2.6, elapsed / 300.0) + (0.15 if moving else 0.0)
        self._core += (core_target - self._core) * 0.02 + self._rng.uniform(-0.03, 0.03)

        exertion = max(0.0, min(1.0, (self._hr - 80.0) / 120.0))
        return {
            "heart_rate_bpm": round(self._hr, 1),
            "core_temp_c": round(self._core, 2),
            "spo2_pct": round(max(90.0, 99.0 - exertion * 4.0
                                  + self._rng.uniform(-0.5, 0.5)), 1),
            "exertion": round(exertion, 2),
        }
