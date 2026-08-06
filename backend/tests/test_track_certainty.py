"""Certainty, corroboration, and staleness.

The published `conf` answers "is this class call right", not "how did these
pixels score". Those are different questions, and conflating them is what made
the HUD hedge a thermally-confirmed body down to POSSIBLE while the Lepton was
looking straight at it.

The property that keeps the change honest — and that these tests exist to
pin — is that certainty may only exceed detector confidence when a SECOND,
INDEPENDENT witness agrees. No corroboration, no promotion, ever.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pyrosight.config import TrackerConfig, VisionConfig
from pyrosight.vision.tracker import STALE_MISSES, TemporalTracker


def _run(frames, **det):
    tracker = TemporalTracker(TrackerConfig(), VisionConfig())
    base = {"cls": "person", "conf": 0.62, "box": [100, 80, 150, 240]}
    base.update(det)
    visible = []
    for _ in range(frames):
        visible = tracker.update([dict(base)], (640, 480))
    return visible[0]


def test_thermal_confirmation_promotes_to_a_named_call():
    t = _run(20, thermal_confirmed=True)
    assert t["display"] == "HUMAN"
    assert t["tier"] == "confirmed"
    assert t["conf"] > t["raw_conf"]


def test_uncorroborated_evidence_is_never_promoted():
    """The load-bearing guarantee. Persistence alone proves nothing."""
    t = _run(60)
    assert t["conf"] == t["raw_conf"]


def test_persistence_alone_cannot_reach_the_confirmed_tier():
    """A sustained hallucination must never talk itself into an alarm.

    Track.update() already allows a small persistence bonus, hard-ceilinged
    at +0.08 over the best raw detection confidence actually seen. That
    whisker is deliberate and stays. What must hold is the consequence: with
    no independent witness, evidence that sits below the confirmed bar stays
    below it forever, however long the track runs.
    """
    vis = VisionConfig()
    short, long = _run(5), _run(60)
    assert long["conf"] - short["conf"] <= 0.08
    assert long["tier"] != "confirmed"
    assert long["conf"] < vis.confirmed_conf


def test_raw_confidence_is_still_reported():
    t = _run(20, thermal_confirmed=True)
    assert 0.0 < t["raw_conf"] < t["conf"]


def test_detector_cadence_is_not_an_occlusion():
    """A single missed pass is the detector's duty cycle, not a lost object.

    Marking it stale made every label on the HUD strobe between confident and
    POSSIBLE at half the frame rate.
    """
    tracker = TemporalTracker(TrackerConfig(), VisionConfig())
    det = {"cls": "door", "conf": 0.80, "box": [100, 50, 180, 240]}
    for _ in range(6):
        tracker.update([det], (640, 480))
    visible = tracker.update([], (640, 480))  # one missed pass
    assert visible[0]["coasting"] is True
    assert visible[0]["stale"] is False
    assert visible[0]["display"] == "DOOR"


def test_a_real_occlusion_does_report_stale():
    tracker = TemporalTracker(TrackerConfig(), VisionConfig())
    det = {"cls": "door", "conf": 0.80, "box": [100, 50, 180, 240]}
    for _ in range(6):
        tracker.update([det], (640, 480))
    visible = []
    for _ in range(STALE_MISSES):
        visible = tracker.update([], (640, 480))
    assert visible[0]["stale"] is True


def test_stale_tracks_lose_the_corroboration_bonus():
    tracker = TemporalTracker(TrackerConfig(), VisionConfig())
    det = {"cls": "person", "conf": 0.62, "box": [100, 80, 150, 240],
           "thermal_confirmed": True}
    for _ in range(20):
        tracker.update([det], (640, 480))
    fresh = tracker.update([det], (640, 480))[0]
    visible = []
    for _ in range(STALE_MISSES):
        visible = tracker.update([], (640, 480))
    assert visible[0]["conf"] < fresh["conf"]


def test_window_is_labelled_as_an_exit():
    tracker = TemporalTracker(TrackerConfig(), VisionConfig())
    det = {"cls": "window", "conf": 0.85, "box": [300, 60, 380, 200],
           "rgb_corroborated": True}
    visible = []
    for _ in range(10):
        visible = tracker.update([det], (640, 480))
    assert visible[0]["display"] == "WINDOW EXIT"
    assert visible[0]["category"] == "egress"
