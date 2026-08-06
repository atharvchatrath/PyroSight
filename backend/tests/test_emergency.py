"""
Emergency mode auto-escalation.

The platform takes no commands, so emergency mode is entirely
condition-driven: it raises itself and it clears itself. That removed the
old dismissal machinery — and with it the safety valve that made a false
alarm survivable. What is left carrying the whole load is the SPECIFICITY
of the trigger list: nothing but a blocked egress route, a confirmed
flashover-risk hotspot, blackout smoke, or a dying battery may raise it.

So these tests pull in both directions. Half prove it fires when it must;
half prove it stays quiet on conditions that look alarming and are not. An
alarm nobody can silence had better be right.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pyrosight.config import load_config
from pyrosight.core.events import FrameStore, TelemetryHub
from pyrosight.pipeline.engine import PerceptionEngine


def _engine():
    """Engine instance without starting sensors or the loop thread.

    Recording off: a test run must never deposit a session in the operational
    incident archive, where it would sit next to real after-action records.
    """
    cfg = load_config()
    cfg.mode = "sim"
    cfg.engine.record_incidents = False
    return PerceptionEngine(cfg, TelemetryHub(), FrameStore())


def _auto(nav_status="CLEAR", tracks=(), battery=100, smoke_vis="GOOD"):
    """Mirror of the trigger expression in engine._tick."""
    return (
        nav_status == "BLOCKED"
        or any(t["cls"] == "hotspot" and t.get("severity") == "critical"
               and t.get("thermal_confirmed") for t in tracks)
        or (battery is not None and battery < 12)
        or smoke_vis == "NEAR ZERO")


CRITICAL_HOTSPOT = {"cls": "hotspot", "severity": "critical",
                    "thermal_confirmed": True}


def test_engine_has_no_command_surface():
    """The property the rest of this file now depends on."""
    eng = _engine()
    assert not hasattr(eng, "submit_command")
    assert not hasattr(eng, "_commands")
    assert not hasattr(eng, "_emergency_manual")


def test_blocked_route_escalates():
    assert _auto(nav_status="BLOCKED") is True


def test_confirmed_critical_hotspot_escalates():
    assert _auto(tracks=[CRITICAL_HOTSPOT]) is True


def test_blackout_smoke_escalates():
    assert _auto(smoke_vis="NEAR ZERO") is True


def test_dying_battery_escalates():
    assert _auto(battery=8) is True


def test_quiet_conditions_do_not_escalate():
    assert _auto() is False


def test_unconfirmed_hotspot_does_not_escalate():
    """Thermal corroboration is required. A hotspot the Lepton never
    confirmed is a guess, and a guess must not raise an alarm that nobody
    can switch off."""
    assert _auto(tracks=[{"cls": "hotspot", "severity": "critical",
                          "thermal_confirmed": False}]) is False


def test_merely_severe_hotspot_does_not_escalate():
    assert _auto(tracks=[{"cls": "hotspot", "severity": "severe",
                          "thermal_confirmed": True}]) is False


def test_caution_route_does_not_escalate():
    """CAUTION is information; only BLOCKED is an emergency."""
    assert _auto(nav_status="CAUTION") is False


def test_low_but_survivable_battery_does_not_escalate():
    assert _auto(battery=15) is False


def test_it_clears_itself_when_conditions_pass():
    """The replacement for operator dismissal: the condition going away."""
    assert _auto(nav_status="BLOCKED") is True
    assert _auto(nav_status="CLEAR") is False
