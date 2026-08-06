"""
Detection hysteresis — two thresholds, not one.

A single confidence gate makes a detector flicker. Confidence on a real
object is noisy; when it wanders across the gate, the detection is deleted
and recreated several times a second on something that never moved. Raising
or lowering the gate does not fix that, because the flicker is not caused by
the gate's height — it is caused by there being only one of them.

So: the full floor opens a track, a reduced floor sustains one. These tests
pin both halves, and the asymmetry between them: easier to keep a victim than
to invent one.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pyrosight.config import TrackerConfig, VisionConfig
from pyrosight.vision import classes as taxonomy
from pyrosight.vision.tracker import TemporalTracker


def _det(conf, cls="person", box=(100, 80, 150, 240)):
    """A detection as the detector would emit it, `weak` flag included."""
    return {"cls": cls, "conf": conf, "box": list(box),
            "weak": conf < taxonomy.enter_threshold(cls)}


def test_keep_bar_is_below_enter_bar():
    for cls in ("person", "door", "fire", "exit_sign", "window"):
        assert taxonomy.keep_threshold(cls) < taxonomy.enter_threshold(cls)


def test_keep_bar_is_not_a_free_pass():
    """Reduced, not removed. A near-zero score still proves nothing."""
    for cls in ("person", "door", "fire"):
        assert taxonomy.keep_threshold(cls) > 0.05


def test_weak_detection_cannot_invent_a_victim():
    tracker = TemporalTracker(TrackerConfig(), VisionConfig())
    weak = _det(0.45)          # under the 0.60 person floor
    assert weak["weak"] is True
    for _ in range(30):
        tracker.update([weak], (640, 480))
    assert tracker.tracks == []


def test_weak_detection_sustains_a_track_already_open():
    """The whole point: evidence that convinced us a moment ago keeps a
    victim on the display while it decays."""
    tracker = TemporalTracker(TrackerConfig(), VisionConfig())
    for _ in range(6):
        tracker.update([_det(0.82)], (640, 480))   # open it strongly
    assert len(tracker.tracks) == 1

    visible = []
    for _ in range(25):                            # then let it decay
        visible = tracker.update([_det(0.45)], (640, 480))
    assert len(tracker.tracks) == 1, "track was dropped by weak evidence"
    assert visible and visible[0]["cls"] == "person"


def test_track_identity_survives_a_confidence_dip():
    """A flickering label is bad; a NEW ID each time is worse — it breaks the
    victim count, which is the number a search actually turns on."""
    tracker = TemporalTracker(TrackerConfig(), VisionConfig())
    for _ in range(6):
        tracker.update([_det(0.82)], (640, 480))
    first_id = tracker.tracks[0].id

    for _ in range(10):
        tracker.update([_det(0.44)], (640, 480))   # dip under the open bar
    for _ in range(6):
        tracker.update([_det(0.85)], (640, 480))   # and recover

    assert len(tracker.tracks) == 1
    assert tracker.tracks[0].id == first_id


def test_sustained_weak_evidence_stays_honest():
    """Sustaining a track is not the same as trusting it. A track held up
    only by weak evidence must not read as confirmed."""
    tracker = TemporalTracker(TrackerConfig(), VisionConfig())
    for _ in range(6):
        tracker.update([_det(0.82)], (640, 480))
    visible = []
    for _ in range(40):
        visible = tracker.update([_det(0.40)], (640, 480))
    assert visible[0]["tier"] != "confirmed"


def test_nothing_at_all_still_ends_the_track():
    """Hysteresis must not make tracks immortal — no detection is no
    detection, and the track has to die."""
    tracker = TemporalTracker(TrackerConfig(), VisionConfig())
    cfg = TrackerConfig()
    for _ in range(6):
        tracker.update([_det(0.82)], (640, 480))
    for _ in range(cfg.max_misses + 2):
        tracker.update([], (640, 480))
    assert tracker.tracks == []
