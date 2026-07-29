"""
Emergency mode: auto-escalation must be real, and operator dismissal must
actually stick. An alarm that cannot be cleared is one operators learn to
ignore — the deadliest failure mode in an alerting system.
"""

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pyrosight.config import load_config
from pyrosight.core.events import FrameStore, TelemetryHub
from pyrosight.pipeline.engine import PerceptionEngine


def _engine():
    """Engine instance without starting sensors or the loop thread."""
    cfg = load_config()
    cfg.mode = "sim"
    return PerceptionEngine(cfg, TelemetryHub(), FrameStore())


def _apply(engine, text: str) -> None:
    engine.submit_command(text)
    engine._apply_commands()


def test_manual_declaration_engages():
    eng = _engine()
    assert eng._emergency_manual is False
    _apply(eng, "emergency mode")
    assert eng._emergency_manual is True


def test_dismissal_suppresses_auto_retrigger():
    eng = _engine()
    _apply(eng, "emergency mode")
    _apply(eng, "cancel emergency")
    assert eng._emergency_manual is False
    # The suppression window is what makes the dismissal stick: without it
    # the auto-trigger re-fires on the very next frame.
    assert eng._emergency_suppress_until > time.time()
    remaining = eng._emergency_suppress_until - time.time()
    assert 30.0 < remaining <= 60.0


def test_manual_declaration_overrides_suppression():
    """After dismissing, the operator must still be able to declare an
    emergency immediately — suppression only gates the AUTO trigger."""
    eng = _engine()
    _apply(eng, "cancel emergency")
    assert eng._emergency_suppress_until > time.time()
    _apply(eng, "emergency mode")
    assert eng._emergency_manual is True
    assert eng._emergency_suppress_until == 0.0
