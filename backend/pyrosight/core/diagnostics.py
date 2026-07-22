"""
System diagnostics: CPU / memory / temperature / battery, plus aggregated
sensor health. Works on Raspberry Pi, macOS, Windows, and generic Linux —
anything that is unavailable on a platform reports None rather than failing.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import DATA_DIR

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:  # pragma: no cover - psutil is in requirements
    PSUTIL_AVAILABLE = False


def _pi_cpu_temp_c() -> Optional[float]:
    """Raspberry Pi / Linux thermal zone. None elsewhere."""
    zone = Path("/sys/class/thermal/thermal_zone0/temp")
    try:
        return int(zone.read_text().strip()) / 1000.0
    except (OSError, ValueError):
        return None


class Diagnostics:
    """Cheap to poll: heavy values are sampled at most every `interval` s."""

    def __init__(self, interval: float = 2.0):
        self._interval = interval
        self._last_sample = 0.0
        self._cached: Dict[str, Any] = {}
        self._boot_ts = time.time()
        # Simulated battery for SITL demos: drains ~1% / 45 s from 98%.
        self._sim_battery_start = 98.0
        self._batt_history: List[Tuple[float, float]] = []

    def sample(self, fps: float, latency_ms: float,
               sensor_health: Dict[str, Dict[str, Any]],
               sim_mode: bool) -> Dict[str, Any]:
        now = time.time()
        if now - self._last_sample >= self._interval:
            self._last_sample = now
            self._cached = self._collect(sim_mode)
        out = dict(self._cached)
        out["fps"] = round(fps, 1)
        out["latency_ms"] = round(latency_ms, 1)
        out["uptime_s"] = int(now - self._boot_ts)
        out["sensors"] = sensor_health
        return out

    def _collect(self, sim_mode: bool) -> Dict[str, Any]:
        cpu = mem = disk = None
        if PSUTIL_AVAILABLE:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory().percent
            try:
                disk = psutil.disk_usage(str(DATA_DIR.parent)).percent
            except (OSError, ValueError):
                disk = None
        temp = _pi_cpu_temp_c()
        battery = self._battery(sim_mode)
        runtime_min = self._runtime_estimate(battery)
        return {
            "cpu_percent": cpu,
            "mem_percent": mem,
            "disk_percent": disk,
            "cpu_temp_c": temp,
            "battery_percent": battery,
            "runtime_min": runtime_min,
            "power_state": self._power_state(battery),
        }

    def _runtime_estimate(self, battery: Optional[float]) -> Optional[int]:
        """Estimate minutes remaining from the observed battery drain rate."""
        if battery is None:
            return None
        now = time.time()
        self._batt_history.append((now, battery))
        self._batt_history = [(t, b) for (t, b) in self._batt_history
                              if now - t <= 300.0]
        if len(self._batt_history) < 2:
            return None
        (t0, b0), (t1, b1) = self._batt_history[0], self._batt_history[-1]
        dt_min = (t1 - t0) / 60.0
        drained = b0 - b1
        if dt_min < 0.3 or drained <= 0.05:
            return None
        rate = drained / dt_min  # %/min
        return int(max(0.0, battery / rate)) if rate > 0 else None

    @staticmethod
    def _power_state(battery: Optional[float]) -> str:
        if battery is None:
            return "unknown"
        if battery < 12:
            return "critical"
        if battery < 25:
            return "saver"
        return "normal"

    def _battery(self, sim_mode: bool) -> Optional[float]:
        if PSUTIL_AVAILABLE:
            try:
                batt = psutil.sensors_battery()
                if batt is not None:
                    return round(batt.percent, 1)
            except (AttributeError, NotImplementedError, OSError):
                pass
        if sim_mode:
            elapsed = time.time() - self._boot_ts
            return round(max(5.0, self._sim_battery_start - elapsed / 45.0), 1)
        return None
