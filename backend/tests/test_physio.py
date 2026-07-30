"""Physiological load monitoring: simulated vitals + heat-stress alerting."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pyrosight.config import PhysioConfig
from pyrosight.core.alerts import AlertEngine
from pyrosight.sensors.physio import BlePhysioStrap, SimulatedPhysio
from pyrosight.sim.world import SimWorld


def _base_args():
    """Minimal evaluate() args for the non-physio rules to stay quiet."""
    thermal = {"hotspots": [], "body_regions": []}
    nav = {"status": "CLEAR", "instruction": "SCANNING"}
    diag = {"battery_percent": 80, "sensors": {}}
    return [], thermal, 0.0, nav, diag


def test_simulated_physio_reports_plausible_vitals():
    sensor = SimulatedPhysio(SimWorld())
    assert sensor.start() is True
    reading = sensor.read()
    assert 40.0 <= reading["heart_rate_bpm"] <= 220.0
    assert 34.0 <= reading["core_temp_c"] <= 42.0
    assert 0.0 <= reading["exertion"] <= 1.0


def test_ble_strap_reports_offline_without_bleak_or_pairing():
    """No real BLE pairing flow exists yet — this must stay honestly
    offline, never fabricate vitals."""
    strap = BlePhysioStrap()
    assert strap.start() is False
    assert strap.read() is None


def test_heat_stress_critical_on_high_heart_rate():
    engine = AlertEngine(PhysioConfig())
    tracks, thermal, smoke, nav, diag = _base_args()
    physio = {"heart_rate_bpm": 190.0, "core_temp_c": 37.5}
    fired = engine.evaluate(tracks, thermal, smoke, nav, diag, physio=physio)
    assert any(a["rule"] == "heat_stress" and a["severity"] == "critical"
              for a in fired)


def test_heat_stress_warning_on_elevated_core_temp():
    engine = AlertEngine(PhysioConfig())
    tracks, thermal, smoke, nav, diag = _base_args()
    physio = {"heart_rate_bpm": 100.0, "core_temp_c": 38.8}
    fired = engine.evaluate(tracks, thermal, smoke, nav, diag, physio=physio)
    assert any(a["rule"] == "heat_stress" and a["severity"] == "warning"
              for a in fired)


def test_no_heat_stress_alert_within_normal_range():
    engine = AlertEngine(PhysioConfig())
    tracks, thermal, smoke, nav, diag = _base_args()
    physio = {"heart_rate_bpm": 95.0, "core_temp_c": 37.1}
    fired = engine.evaluate(tracks, thermal, smoke, nav, diag, physio=physio)
    assert not any(a["rule"] == "heat_stress" for a in fired)


def test_heat_stress_respects_cooldown():
    engine = AlertEngine(PhysioConfig())
    tracks, thermal, smoke, nav, diag = _base_args()
    physio = {"heart_rate_bpm": 190.0, "core_temp_c": 37.5}
    first = engine.evaluate(tracks, thermal, smoke, nav, diag, physio=physio)
    second = engine.evaluate(tracks, thermal, smoke, nav, diag, physio=physio)
    assert any(a["rule"] == "heat_stress" for a in first)
    assert not any(a["rule"] == "heat_stress" for a in second)
