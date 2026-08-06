"""
Bench-test mode (PYROSIGHT_ALLOW_SCREENS).

The platform refuses to call a person on a monitor or a poster a victim. On a
fireground that is load-bearing: the failure it prevents is sending a crew to
a wall. Indoors on a desk it is indistinguishable from a bug, because the
obvious way to test is to hold up a phone.

The flag exists to make bench testing possible. These tests exist to make
sure it can never be switched on by accident, and never switched on quietly.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pyrosight.config import VisionConfig, load_config
from pyrosight.core.events import FrameStore, TelemetryHub
from pyrosight.pipeline.engine import PerceptionEngine
from pyrosight.vision import classes as taxonomy
from pyrosight.vision.detector import suppress_decoys


def _engine(allow_screens: bool):
    cfg = load_config()
    cfg.mode = "sim"
    cfg.engine.record_incidents = False
    cfg.vision.allow_screens = allow_screens
    return PerceptionEngine(cfg, TelemetryHub(), FrameStore())


def test_defaults_to_off():
    """Nothing in the repo may ship with the safety net disabled."""
    assert VisionConfig().allow_screens is False
    assert load_config().vision.allow_screens is False


def test_off_state_is_not_announced():
    assert _engine(False).prefs["bench_mode"] is False


def test_on_state_is_announced_to_the_hud():
    """A helmet that will accept a photograph as a victim must not look
    identical to one that will not."""
    assert _engine(True).prefs["bench_mode"] is True


def test_decoy_veto_still_works_by_default():
    person = [{"cls": "person", "conf": 0.64, "box": [10, 10, 60, 150]}]
    poster = [{"cls": taxonomy.DECOY, "conf": 0.81, "box": [8, 8, 62, 152]}]
    assert suppress_decoys(person, poster) == []
