"""
Track identity under the two conditions that break it in the field.

  1. The detector re-crops a person between frames (full body -> torso). IoU
     collapses, the real track coasts, and a second track opens on the same
     human: one victim reported as two.
  2. Two victims stand close together. First-come association lets an older
     track claim the nearer person's box, so the ids — and the distances
     printed next to them — swap between bodies mid-rescue.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pyrosight.config import TrackerConfig, VisionConfig
from pyrosight.vision.tracker import TemporalTracker

FRAME = (640, 480)


def _tracker():
    return TemporalTracker(TrackerConfig(), VisionConfig())


def det(cls, conf, box):
    return {"cls": cls, "conf": conf, "box": list(box)}


def _confirm(tracker, box, n=4, conf=0.9):
    """Feed the same detection until the track is confirmed."""
    for _ in range(n):
        tracker.update([det("person", conf, box)], FRAME)


def test_recropped_box_keeps_one_identity():
    tr = _tracker()
    full = (300, 100, 400, 460)
    torso = (315, 110, 390, 250)      # IoU with `full` is ~0.25

    _confirm(tr, full)
    ids_before = {t.id for t in tr.tracks}
    assert len(ids_before) == 1

    # Detector tightens to the torso for several frames.
    for _ in range(4):
        tr.update([det("person", 0.85, torso)], FRAME)

    assert len(tr.tracks) == 1, (
        f"a re-cropped box must not fork the track: {[t.box for t in tr.tracks]}")
    assert {t.id for t in tr.tracks} == ids_before, "identity must survive"


def test_two_close_victims_keep_their_own_identities():
    tr = _tracker()
    left = (150, 120, 250, 460)
    right = (300, 120, 400, 460)
    for _ in range(4):
        tr.update([det("person", 0.9, left), det("person", 0.9, right)], FRAME)
    assert len(tr.tracks) == 2

    by_x = sorted(tr.tracks, key=lambda t: t.box[0])
    left_id, right_id = by_x[0].id, by_x[1].id

    # Both step slightly right; the boxes now sit between their old positions.
    for _ in range(3):
        tr.update([det("person", 0.9, (170, 120, 270, 460)),
                   det("person", 0.9, (320, 120, 420, 460))], FRAME)

    assert len(tr.tracks) == 2, "no phantom third victim"
    by_x_after = sorted(tr.tracks, key=lambda t: t.box[0])
    assert by_x_after[0].id == left_id, "left victim kept their id"
    assert by_x_after[1].id == right_id, "right victim kept their id"


def test_a_genuinely_new_person_still_opens_a_track():
    tr = _tracker()
    _confirm(tr, (100, 120, 200, 460))
    assert len(tr.tracks) == 1
    for _ in range(4):
        tr.update([det("person", 0.9, (100, 120, 200, 460)),
                   det("person", 0.9, (450, 120, 550, 460))], FRAME)
    assert len(tr.tracks) == 2, "a second victim must be reported"


def test_one_person_reaches_the_hud_once():
    """End to end through the public surface the HUD consumes."""
    tr = _tracker()
    boxes = [(300, 100, 400, 460), (305, 100, 402, 455), (315, 110, 390, 250),
             (302, 100, 399, 458), (316, 112, 392, 248)]
    visible = []
    for b in boxes * 2:
        visible = tr.update([det("person", 0.9, b)], FRAME)
    persons = [v for v in visible if v["cls"] == "person"]
    assert len(persons) == 1, f"HUD would show {len(persons)} victims: {persons}"
