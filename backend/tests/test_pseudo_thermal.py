"""
RGB-derived thermal estimate: it must never invent a temperature that would
trip a hotspot, a heat alert, or a fire label.

The hotspot threshold is 90 °C (config.hotspot_temp_c). Anything the estimate
reports above that becomes a first-class "heat source" downstream, so the
estimate is only allowed to reach flame temperatures where the image actually
contains flame evidence — a blown-out core inside a colored ring, with skin
chroma excluded.
"""

import pathlib
import sys

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pyrosight.vision.pseudo_thermal import estimate_from_rgb

HOTSPOT_C = 90.0


def _room(v: int = 90) -> np.ndarray:
    return np.full((480, 640, 3), (v, v, v), dtype=np.uint8)


def test_warm_lit_face_stays_below_hotspot_threshold():
    frame = _room()
    cv2.ellipse(frame, (320, 220), (70, 95), 0, 0, 360, (100, 150, 230), -1)
    cv2.ellipse(frame, (320, 235), (8, 11), 0, 0, 360, (250, 252, 255), -1)
    temp = estimate_from_rgb(frame)
    assert float(temp.max()) < HOTSPOT_C, (
        f"skin must not read as a heat source: {float(temp.max()):.0f} °C"
    )


def test_hi_vis_orange_stays_below_hotspot_threshold():
    frame = _room()
    cv2.rectangle(frame, (200, 200), (300, 320), (0, 140, 255), -1)
    temp = estimate_from_rgb(frame)
    assert float(temp.max()) < HOTSPOT_C


def test_real_flame_still_reads_hot():
    frame = _room(60)
    cv2.ellipse(frame, (320, 240), (16, 28), 0, 0, 360, (0, 120, 255), -1)
    cv2.ellipse(frame, (320, 244), (8, 16), 0, 0, 360, (245, 250, 255), -1)
    temp = estimate_from_rgb(frame)
    assert float(temp.max()) >= 250.0, (
        f"a cored flame must still estimate hot: {float(temp.max()):.0f} °C"
    )
