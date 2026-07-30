"""
Alert engine: converts pipeline observations into rate-limited, prioritized
alerts. Every rule has a cooldown so the HUD warns without nagging — alarm
fatigue kills attention exactly when it matters most.

Severity: critical > warning > info.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..config import PhysioConfig


class AlertEngine:
    COOLDOWNS = {
        "fire_detected": 20.0,
        "hotspot_critical": 20.0,
        "victim_detected": 15.0,
        "victim_close": 30.0,
        "low_visibility": 45.0,
        "route_blocked": 15.0,
        "battery_low": 120.0,
        "sensor_degraded": 60.0,
        "heat_stress": 60.0,
    }

    def __init__(self, physio_cfg: Optional[PhysioConfig] = None):
        self._last_fired: Dict[str, float] = {}
        self._latest: Optional[Dict[str, Any]] = None
        self._physio_cfg = physio_cfg or PhysioConfig()

    @property
    def latest(self) -> Optional[Dict[str, Any]]:
        return self._latest

    def evaluate(self, tracks: List[Dict[str, Any]], thermal: Dict[str, Any],
                 smoke_density: float, nav: Dict[str, Any],
                 diagnostics: Dict[str, Any],
                 physio: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        alerts: List[Dict[str, Any]] = []

        # Fire alerts are tier-gated: a confirmed track (thermal-corroborated
        # or sustained high evidence) goes critical; "likely" warns as
        # POSSIBLE FIRE; a "possible" tier never sounds an alarm — showing
        # a dashed box on the HUD is enough. False alarms teach operators
        # to ignore the banner, which is the deadliest failure mode.
        # Only CORROBORATED fire (thermal hotspot or flame flicker) sounds an
        # alarm. An uncorroborated neural "possible fire" is shown on the HUD
        # but never alarms — a false fire siren is never acceptable.
        fires = [t for t in tracks if t["cls"] == "fire" and t.get("corroborated")]
        if fires:
            worst = max(fires, key=lambda t: t["conf"])
            temp = worst.get("max_temp_c")
            temp_txt = f" {int(temp)}°C" if temp else ""
            if worst["tier"] == "confirmed":
                alerts.append(self._fire(
                    "fire_detected", "critical",
                    f"FIRE{temp_txt} — {int(worst['conf'] * 100)}%"))
            else:
                alerts.append(self._fire(
                    "fire_detected", "warning",
                    f"POSSIBLE FIRE{temp_txt} — {int(worst['conf'] * 100)}%"))

        crit_spots = [t for t in tracks if t["cls"] == "hotspot"
                      and t.get("severity") == "critical"
                      and t.get("thermal_confirmed")]
        if crit_spots:
            t = crit_spots[0]
            alerts.append(self._fire(
                "hotspot_critical", "critical",
                f"CRITICAL HOTSPOT {int(t.get('max_temp_c') or 0)}°C — POSSIBLE FLASHOVER"))

        victims = [t for t in tracks if t["cls"] == "person"]
        if victims:
            v = max(victims, key=lambda t: t["conf"])
            label = "VICTIM" if v["tier"] != "possible" else "POSSIBLE VICTIM"
            therm = " (THERMAL CONFIRMED)" if v["thermal_confirmed"] else ""
            if v.get("dist_ft") is not None and v["dist_ft"] < 10:
                alerts.append(self._fire(
                    "victim_close", "warning",
                    f"{label} {int(v['dist_ft'])} FT — RENDER AID{therm}"))
            else:
                alerts.append(self._fire(
                    "victim_detected", "info",
                    f"{label} DETECTED — {int(v['conf'] * 100)}%{therm}"))

        if smoke_density > 0.65:
            alerts.append(self._fire(
                "low_visibility", "warning",
                "VISIBILITY NEAR ZERO — SWITCH TO THERMAL"))

        if nav.get("status") == "BLOCKED":
            alerts.append(self._fire(
                "route_blocked", "warning", nav.get("instruction", "ROUTE BLOCKED")))

        battery = diagnostics.get("battery_percent")
        if battery is not None and battery < 20:
            alerts.append(self._fire(
                "battery_low", "warning", f"BATTERY {int(battery)}% — MANAGE POWER"))

        for kind, info in (diagnostics.get("sensors") or {}).items():
            if info.get("status") == "degraded":
                alerts.append(self._fire(
                    "sensor_degraded", "warning",
                    f"{kind.upper()} SENSOR DEGRADED"))

        # Physiological load: a firefighter cannot self-assess heat stress
        # under exertion — sustained elevated HR/core temp is a withdraw
        # signal that has to come from outside their own perception.
        if physio is not None:
            hr = physio.get("heart_rate_bpm")
            core = physio.get("core_temp_c")
            pc = self._physio_cfg
            if ((core is not None and core >= pc.core_temp_critical_c)
                    or (hr is not None and hr >= pc.hr_critical_bpm)):
                alerts.append(self._fire(
                    "heat_stress", "critical",
                    f"HEAT STRESS CRITICAL — HR {int(hr or 0)} "
                    f"CORE {core:.1f}°C — WITHDRAW NOW" if core is not None
                    else f"HEAT STRESS CRITICAL — HR {int(hr or 0)} — WITHDRAW NOW"))
            elif ((core is not None and core >= pc.core_temp_elevated_c)
                    or (hr is not None and hr >= pc.hr_elevated_bpm)):
                alerts.append(self._fire(
                    "heat_stress", "warning",
                    f"ELEVATED EXERTION — HR {int(hr or 0)} — MONITOR"))

        fired = [a for a in alerts if a is not None]
        if fired:
            self._latest = max(fired, key=lambda a:
                               {"critical": 2, "warning": 1, "info": 0}[a["severity"]])
        return fired

    def _fire(self, rule: str, severity: str, text: str) -> Optional[Dict[str, Any]]:
        now = time.time()
        if now - self._last_fired.get(rule, 0.0) < self.COOLDOWNS.get(rule, 30.0):
            return None
        self._last_fired[rule] = now
        return {"rule": rule, "severity": severity, "text": text, "ts": now}
