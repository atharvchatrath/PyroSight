"""Cross-class conflict resolution.

Per-class NMS compares like with like and is structurally blind to two
DIFFERENT classes claiming the same pixels. That ambiguity used to reach the
HUD intact — a wall opening rendered as a stacked "DOOR 46% / WINDOW 41%" —
handing the operator a decision to make in smoke, which is exactly the
decision the platform exists to make for them.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pyrosight.config import TrackerConfig, VisionConfig
from pyrosight.vision import classes as taxonomy
from pyrosight.vision.detector import resolve_class_conflicts, suppress_decoys
from pyrosight.vision.tracker import TemporalTracker


def test_one_opening_gets_one_answer():
    dets = [
        {"cls": "door", "conf": 0.46, "box": [100, 50, 180, 240]},
        {"cls": "window", "conf": 0.41, "box": [104, 54, 176, 236]},
    ]
    out = resolve_class_conflicts(dets)
    assert len(out) == 1
    assert out[0]["cls"] == "door"


def test_human_in_a_doorway_keeps_both_marks():
    """Different conflict groups never compete, however much they overlap."""
    dets = [
        {"cls": "door", "conf": 0.60, "box": [100, 50, 180, 240]},
        {"cls": "person", "conf": 0.72, "box": [110, 90, 170, 238]},
    ]
    out = resolve_class_conflicts(dets)
    assert {d["cls"] for d in out} == {"door", "person"}


def test_consequence_breaks_the_tie_toward_the_human():
    """Equal confidence must not resolve to the cheaper mistake."""
    dets = [
        {"cls": "firefighter", "conf": 0.70, "box": [100, 50, 160, 240]},
        {"cls": "person", "conf": 0.70, "box": [102, 52, 158, 238]},
    ]
    out = resolve_class_conflicts(dets)
    assert len(out) == 1 and out[0]["cls"] == "person"


def test_disjoint_objects_both_survive():
    dets = [
        {"cls": "door", "conf": 0.50, "box": [0, 0, 60, 200]},
        {"cls": "window", "conf": 0.50, "box": [400, 0, 460, 200]},
    ]
    assert len(resolve_class_conflicts(dets)) == 2


def test_decoy_beats_a_weak_person():
    person = [{"cls": "person", "conf": 0.64, "box": [10, 10, 60, 150]}]
    poster = [{"cls": taxonomy.DECOY, "conf": 0.81, "box": [8, 8, 62, 152]}]
    assert suppress_decoys(person, poster) == []


def test_confident_human_survives_a_decoy():
    """A decoy vetoes only when it actually wins the pixels."""
    person = [{"cls": "person", "conf": 0.88, "box": [10, 10, 60, 150]}]
    poster = [{"cls": taxonomy.DECOY, "conf": 0.81, "box": [8, 8, 62, 152]}]
    assert len(suppress_decoys(person, poster)) == 1


def test_unconfident_decoy_cannot_veto_anything():
    person = [{"cls": "person", "conf": 0.30, "box": [10, 10, 60, 150]}]
    weak = [{"cls": taxonomy.DECOY, "conf": 0.20, "box": [8, 8, 62, 152]}]
    assert len(suppress_decoys(person, weak)) == 1


def test_decoy_elsewhere_in_frame_is_irrelevant():
    person = [{"cls": "person", "conf": 0.50, "box": [10, 10, 60, 150]}]
    poster = [{"cls": taxonomy.DECOY, "conf": 0.95, "box": [400, 10, 460, 150]}]
    assert len(suppress_decoys(person, poster)) == 1


def test_competing_tracks_resolve_over_time():
    """Two tracks can both mature if the detector alternates between them.

    Frame-level resolution cannot catch this: each class wins its own frame
    fairly. The tracker settles it on accumulated evidence instead.
    """
    tracker = TemporalTracker(TrackerConfig(), VisionConfig())
    door = {"cls": "door", "conf": 0.80, "box": [100, 50, 180, 240]}
    window = {"cls": "window", "conf": 0.55, "box": [104, 54, 176, 236]}
    visible = []
    for i in range(12):
        visible = tracker.update([door] if i % 2 else [window], (640, 480))
    assert [t["cls"] for t in visible] == ["door"]
