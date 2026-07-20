"""Fire detector: a small lighter flame must be caught; skin and static
orange must not. These are the two field-reported failure modes."""

import pathlib
import sys

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pyrosight.vision.fire import FireDetector


def _room(v: int = 60) -> np.ndarray:
    """Dim indoor background."""
    frame = np.full((480, 640, 3), (v, v, v), dtype=np.uint8)
    return frame


def _draw_lighter_flame(frame: np.ndarray, cx: int, cy: int, jitter: int) -> None:
    """~12x24 px flame: saturated orange fringe + white-hot core."""
    cv2.ellipse(frame, (cx + jitter, cy), (8, 14), 0, 0, 360, (0, 120, 255), -1)
    cv2.ellipse(frame, (cx + jitter, cy + 2), (4, 8), 0, 0, 360, (245, 250, 255), -1)


def test_lighter_flame_detected():
    det = FireDetector()
    results = []
    for i in range(6):
        frame = _room()
        _draw_lighter_flame(frame, 320, 240, jitter=(i % 3) - 1)  # flicker
        results = det.detect(frame)
    assert len(results) == 1, "small flame with white core must be detected"
    r = results[0]
    assert r["white_core_px"] >= 6
    assert r["conf"] >= 0.5, f"flickering cored flame should be likely+: {r}"
    # Box localizes the flame.
    x1, y1, x2, y2 = r["box"]
    assert abs((x1 + x2) / 2 - 320) < 25 and abs((y1 + y2) / 2 - 240) < 25


def test_skin_tone_not_detected():
    det = FireDetector()
    results = []
    for i in range(6):
        frame = _room(120)
        # Face-sized skin patch (BGR ~ warm skin: hue in orange band but
        # moderate saturation/brightness), slight movement.
        cv2.ellipse(frame, (320 + (i % 3), 200), (60, 80), 0, 0, 360,
                    (140, 165, 215), -1)
        results = det.detect(frame)
    assert results == [], f"skin must never register as fire: {results}"


def test_static_orange_capped_possible():
    det = FireDetector()
    results = []
    for _ in range(6):
        frame = _room()
        # Bright saturated orange rectangle (hi-vis gear), perfectly static,
        # no white core.
        cv2.rectangle(frame, (200, 200), (280, 300), (0, 140, 255), -1)
        results = det.detect(frame)
    if results:  # if the brightness gate lets it through at all...
        assert all(r["conf"] <= 0.38 for r in results), \
            "static orange must stay in the possible tier"


def test_white_lamp_alone_not_fire():
    det = FireDetector()
    results = []
    for _ in range(6):
        frame = _room()
        # Bare white blob (ceiling lamp): white-hot band but NO colored ring.
        cv2.circle(frame, (500, 100), 20, (255, 255, 255), -1)
        results = det.detect(frame)
    assert results == [], f"a lamp with no colored fringe is not fire: {results}"
