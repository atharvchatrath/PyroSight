"""
A picture of a person is not a person.

A detector answers "person" for a poster, a television, a photo on a desk. In
a primary search that error sends a crew to a wall. Two independent cues
separate a body from an image of one, and they are applied with deliberately
different force:

  * FRAMED   — strong, specific evidence. Rejected outright.
  * STATIC   — weaker: an unconscious victim is also very still. Only lowers
               the claim below CONFIRMED, never removes the detection.
"""

import pathlib
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pyrosight.vision.spoof import StaticSubjectMonitor, framed_by_rectangle


def _room(v: int = 90) -> np.ndarray:
    return np.full((480, 640, 3), (v, v, v), dtype=np.uint8)


def _person_shape(frame, box, bgr=(70, 95, 140)):
    x1, y1, x2, y2 = (int(v) for v in box)
    cv2.rectangle(frame, (x1, y1), (x2, y2), bgr, -1)


# ------------------------------------------------------------------- framed

def test_person_on_a_screen_is_rejected():
    """A figure inside a monitor bezel: the classic false victim."""
    frame = _room(60)
    screen = (180, 120, 420, 320)
    cv2.rectangle(frame, screen[:2], screen[2:], (25, 25, 25), -1)      # bezel
    cv2.rectangle(frame, (188, 128), (412, 312), (120, 120, 120), -1)   # panel
    person = [235, 150, 360, 300]
    _person_shape(frame, person)
    hit = framed_by_rectangle(frame, person)
    assert hit is not None, "a person inside a screen bezel must be flagged"
    assert hit["subject_frac"] > 0.1


def test_a_real_person_in_a_room_is_not_flagged():
    frame = _room(80)
    person = [280, 140, 380, 430]
    _person_shape(frame, person)
    assert framed_by_rectangle(frame, person) is None, (
        "an unframed person must never be suppressed")


def test_a_person_standing_in_a_doorway_is_not_flagged_as_a_picture():
    """A doorway encloses a person too — but loosely, and it is a way out."""
    frame = _room(70)
    cv2.rectangle(frame, (250, 60), (420, 470), (40, 40, 40), 4)   # door frame
    person = [300, 200, 370, 460]
    _person_shape(frame, person)
    hit = framed_by_rectangle(frame, person)
    assert hit is None, f"doorways must not read as picture frames: {hit}"


def test_a_wall_sized_rectangle_is_not_a_picture_frame():
    frame = _room(70)
    cv2.rectangle(frame, (10, 10), (630, 470), (30, 30, 30), 5)
    person = [280, 150, 380, 440]
    _person_shape(frame, person)
    assert framed_by_rectangle(frame, person) is None


# ------------------------------------------------------------------- static

def _feed(monitor, track_id, box, samples=12, jitter=0.0, dt=0.5):
    """Simulate `samples` observations spread over time."""
    for i in range(samples):
        b = [box[0] + (i % 2) * jitter, box[1], box[2] + (i % 2) * jitter, box[3]]
        monitor.update(track_id, b)
        # Backdate history so the observation window is satisfied without
        # actually sleeping through it.
        monitor._hist[track_id][-1] = (
            time.time() - (samples - i) * dt,
            monitor._hist[track_id][-1][1],
            monitor._hist[track_id][-1][2],
        )


def test_a_motionless_subject_is_called_static():
    m = StaticSubjectMonitor()
    _feed(m, 1, [300, 100, 400, 460], jitter=0.0)
    assert m.is_static(1) is True


def test_a_living_person_is_not_called_static():
    m = StaticSubjectMonitor()
    _feed(m, 2, [300, 100, 400, 460], jitter=9.0)   # sway / breathing
    assert m.is_static(2) is False


def test_a_brief_glimpse_is_never_judged():
    """Too little history must not produce a verdict either way."""
    m = StaticSubjectMonitor()
    m.update(3, [300, 100, 400, 460])
    m.update(3, [301, 100, 401, 460])
    assert m.residual_motion(3) is None
    assert m.is_static(3) is False, "no verdict must not read as 'static'"


def test_finished_tracks_are_forgotten():
    m = StaticSubjectMonitor()
    _feed(m, 4, [300, 100, 400, 460])
    m.forget(live_ids=set())
    assert m.residual_motion(4) is None
