"""
Exit signs and windows: the objects that decide whether someone gets out.

The open-vocabulary model scores both low indoors, so everything it says about
them lands in the POSSIBLE tier. These classical detectors give the fusion
stage a second, independent witness — and the evidence policy that follows
from it is the point: one good witness surfaces the way out, two witnesses
confirm it, and neither one alone is allowed to claim certainty.
"""

import pathlib
import sys

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pyrosight.vision.egress import ExitSignDetector, WindowDetector
from pyrosight.vision.fusion import EGRESS_CLASSICAL_CAP, fuse

THERMAL = {"hotspots": [], "body_regions": []}


def _room(v: int = 55) -> np.ndarray:
    return np.full((480, 640, 3), (v, v, v), dtype=np.uint8)


def _exit_sign(frame, x=300, y=120, w=60, h=26, bgr=(60, 235, 60)):
    cv2.rectangle(frame, (x, y), (x + w, y + h), bgr, -1)


# ------------------------------------------------------------- exit signs

def test_illuminated_green_exit_sign_is_found():
    frame = _room()
    _exit_sign(frame)
    hits = ExitSignDetector().detect(frame)
    assert len(hits) == 1, f"a lit green sign must be found: {hits}"
    x1, y1, x2, y2 = hits[0]["box"]
    assert abs((x1 + x2) / 2 - 330) < 12 and abs((y1 + y2) / 2 - 133) < 12
    assert hits[0]["conf"] >= 0.45


def test_red_exit_sign_variant_is_found():
    frame = _room()
    _exit_sign(frame, bgr=(50, 50, 240))
    assert len(ExitSignDetector().detect(frame)) == 1


def test_dull_green_paint_is_not_an_exit_sign():
    """Unlit paint is the same hue but not self-illuminated."""
    frame = _room(120)
    _exit_sign(frame, bgr=(70, 125, 70))     # darker than the wall
    assert ExitSignDetector().detect(frame) == []


def test_tall_green_object_is_not_an_exit_sign():
    """Signs are wider than tall; a lit green column is something else."""
    frame = _room()
    _exit_sign(frame, w=26, h=90)
    assert ExitSignDetector().detect(frame) == []


# ---------------------------------------------------------------- windows

def test_daylight_window_is_found_in_a_dark_room():
    frame = _room(35)
    cv2.rectangle(frame, (420, 120), (560, 300), (225, 228, 230), -1)
    cv2.rectangle(frame, (420, 120), (560, 300), (90, 90, 90), 3)   # frame edge
    cv2.line(frame, (490, 120), (490, 300), (90, 90, 90), 3)        # mullion
    hits = WindowDetector().detect(frame)
    assert len(hits) >= 1, "a bright opening in a dark room must be found"
    assert hits[0]["conf"] >= 0.40


def test_uniformly_bright_scene_has_no_window_signature():
    assert WindowDetector().detect(_room(230)) == []


def test_light_spilling_on_a_wall_is_not_a_window():
    """The distinguishing feature is a boundary, not brightness."""
    frame = _room(35)
    yy, xx = np.mgrid[0:480, 0:640]
    glow = np.clip(255 * np.exp(-(((xx - 490) / 120.0) ** 2
                                  + ((yy - 210) / 150.0) ** 2)), 0, 255).astype(np.uint8)
    frame = np.maximum(frame, np.dstack([glow, glow, glow]))
    assert WindowDetector().detect(frame) == [], "a soft gradient has no edge"


# ------------------------------------------------------------ evidence policy

def test_classical_only_egress_is_reported_but_not_confirmed():
    out = fuse([], [], THERMAL, (640, 480), (160, 120),
               egress_regions=[{"cls": "exit_sign", "conf": 0.85,
                                "box": [300, 120, 360, 146]}])
    assert len(out) == 1, "one witness still puts the exit on the HUD"
    assert out[0]["conf"] <= EGRESS_CLASSICAL_CAP
    assert out[0]["conf"] < 0.75, "one witness must not reach CONFIRMED"


def test_two_witnesses_promote_the_exit():
    neural = [{"cls": "exit_sign", "conf": 0.34, "box": [300, 120, 360, 146]}]
    out = fuse(neural, [], THERMAL, (640, 480), (160, 120),
               egress_regions=[{"cls": "exit_sign", "conf": 0.8,
                                "box": [302, 121, 358, 145]}])
    assert len(out) == 1, "agreeing witnesses describe one sign, not two"
    assert out[0]["rgb_corroborated"] is True
    assert out[0]["conf"] > 0.34, "corroboration must raise the claim"


def test_disagreeing_witnesses_stay_separate():
    """A sign here and a window over there are two different objects."""
    neural = [{"cls": "exit_sign", "conf": 0.4, "box": [40, 40, 100, 66]}]
    out = fuse(neural, [], THERMAL, (640, 480), (160, 120),
               egress_regions=[{"cls": "window", "conf": 0.7,
                                "box": [400, 100, 560, 300]}])
    assert len(out) == 2
    assert {d["cls"] for d in out} == {"exit_sign", "window"}
