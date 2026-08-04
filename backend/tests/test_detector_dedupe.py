"""
One person must reach the HUD as one person.

The field failure: at close range a detector returns both a full-body box and
a head-and-shoulders box for the same human. Their IoU sits well under any
sane NMS threshold, so IoU-only suppression keeps both, the tracker opens two
ids, and the display reports two victims at the same distance — a counting
error on the single number a search is trying to establish.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pyrosight.vision.detector import (
    _box_iou,
    _containment,
    dedupe_same_class,
)


def det(cls, conf, box):
    return {"cls": cls, "conf": conf, "box": list(box)}


FULL_BODY = (300, 100, 400, 460)      # standing adult, close range
HEAD_SHOULDERS = (315, 110, 390, 230)  # upper-body crop of the same person


def test_the_failure_case_is_actually_invisible_to_iou():
    """Guards the premise: if IoU could see this, the fix would be pointless."""
    iou = _box_iou(list(FULL_BODY), list(HEAD_SHOULDERS))
    assert iou < 0.45, f"IoU {iou:.2f} would have been caught by plain NMS"
    assert _containment(list(HEAD_SHOULDERS), list(FULL_BODY)) > 0.9


def test_nested_person_boxes_collapse_to_one():
    out = dedupe_same_class(
        [det("person", 0.98, FULL_BODY), det("person", 0.46, HEAD_SHOULDERS)],
        iou_thr=0.45,
    )
    assert len(out) == 1, f"one human must yield one detection: {out}"
    assert out[0]["conf"] == 0.98, "the stronger evidence survives"
    assert out[0]["box"] == list(FULL_BODY)


def test_nesting_is_caught_in_either_direction():
    """The crop sometimes scores higher than the full body."""
    out = dedupe_same_class(
        [det("person", 0.91, HEAD_SHOULDERS), det("person", 0.55, FULL_BODY)],
        iou_thr=0.45,
    )
    assert len(out) == 1
    assert out[0]["conf"] == 0.91


def test_two_real_people_are_not_merged():
    a = det("person", 0.9, (100, 120, 200, 460))
    b = det("person", 0.8, (420, 120, 520, 460))   # a metre away, no overlap
    out = dedupe_same_class([a, b], iou_thr=0.45)
    assert len(out) == 2, "separate victims must stay separate"


def test_two_people_standing_close_are_not_merged():
    """Shoulder to shoulder: boxes touch, neither is inside the other."""
    a = det("person", 0.9, (200, 120, 300, 460))
    b = det("person", 0.85, (285, 120, 385, 460))
    out = dedupe_same_class([a, b], iou_thr=0.45)
    assert len(out) == 2


def test_a_person_in_a_doorway_never_suppresses_the_door():
    door = det("door", 0.8, (280, 60, 420, 470))
    person = det("person", 0.95, (300, 100, 400, 460))   # fully inside the door
    out = dedupe_same_class([door, person], iou_thr=0.45)
    assert len(out) == 2, "cross-class nesting is the normal case, not a dupe"
    assert {d["cls"] for d in out} == {"door", "person"}


def test_overlapping_duplicates_still_go_by_iou():
    a = det("person", 0.9, (300, 100, 400, 460))
    b = det("person", 0.7, (310, 105, 410, 465))   # same body, jittered box
    out = dedupe_same_class([a, b], iou_thr=0.45)
    assert len(out) == 1
