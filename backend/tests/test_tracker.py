"""Temporal tracker: confidence dynamics, tiers, coasting, ranging."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pyrosight.config import TrackerConfig, VisionConfig
from pyrosight.vision.tracker import TemporalTracker, estimate_distance_m


def _det(cls="person", conf=0.9, box=(100, 100, 200, 400)):
    return {"cls": cls, "conf": conf, "box": list(box)}


def test_track_requires_persistence():
    tr = TemporalTracker(TrackerConfig(), VisionConfig())
    assert tr.update([_det()], (640, 480)) == []          # 1 hit: hidden
    assert tr.update([_det()], (640, 480)) == []          # 2 hits: hidden
    visible = tr.update([_det()], (640, 480))             # 3 hits: visible
    assert len(visible) == 1
    assert visible[0]["cls"] == "person"


def test_confidence_tiers_and_possible_label():
    tr = TemporalTracker(TrackerConfig(), VisionConfig())
    for _ in range(4):
        visible = tr.update([_det(conf=0.30)], (640, 480))
    assert visible[0]["tier"] == "possible"
    assert visible[0]["display"].startswith("POSSIBLE")

    tr2 = TemporalTracker(TrackerConfig(), VisionConfig())
    for _ in range(8):
        visible = tr2.update([_det(conf=0.92)], (640, 480))
    assert visible[0]["tier"] == "confirmed"
    assert not visible[0]["display"].startswith("POSSIBLE")


def test_confidence_never_exceeds_evidence():
    """A sustained low-confidence detection must NOT compound into a
    confident track — confidence is ceilinged by observed evidence."""
    tr = TemporalTracker(TrackerConfig(), VisionConfig())
    visible = []
    for _ in range(60):  # a full minute of weak evidence at 20 FPS
        visible = tr.update([_det(conf=0.38)], (640, 480))
    assert visible[0]["conf"] <= 0.46
    assert visible[0]["tier"] == "possible"
    assert visible[0]["display"].startswith("POSSIBLE")


def test_coasting_decays_confidence_then_dies():
    cfg = TrackerConfig()
    tr = TemporalTracker(cfg, VisionConfig())
    for _ in range(5):
        tr.update([_det(conf=0.9)], (640, 480))
    conf_before = tr.tracks[0].conf
    tr.update([], (640, 480))
    assert tr.tracks[0].conf < conf_before
    assert tr.tracks[0].misses == 1
    for _ in range(cfg.max_misses + 2):
        tr.update([], (640, 480))
    assert tr.tracks == []


def test_class_isolation():
    tr = TemporalTracker(TrackerConfig(), VisionConfig())
    for _ in range(4):
        visible = tr.update(
            [_det("person"), _det("door", 0.8, (105, 95, 205, 405))], (640, 480))
    # Same location, different classes -> two independent tracks.
    assert len({v["cls"] for v in visible}) == 2


def test_monocular_ranging_sane():
    # A 300px-tall person in a 640px frame at fx=522: d = 1.65*522/300 ≈ 2.9 m
    d = estimate_distance_m("person", [0, 0, 100, 300], 640)
    assert 2.5 < d < 3.3
    assert estimate_distance_m("fire", [0, 0, 100, 300], 640) is None
