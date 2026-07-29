"""
Stereo depth (Waveshare dual IMX219): disparity -> metric range.

Validated against synthetic pairs with a known pixel shift, because
`depth = fx * baseline / disparity` is exactly checkable. If this drifts, the
range readings on the HUD are wrong in a way no visual inspection catches.
"""

import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pyrosight.sensors.stereo import DEPTH_W, StereoDepth, load_calibration

FX_AT_640 = 500.0
BASELINE_M = 0.06


def _stereo_pair(disparity_at_depth_res: int, seed: int = 3):
    """640x480 pair where a textured patch is shifted by a known disparity
    (expressed in depth-map pixels, which is what the matcher sees)."""
    rng = np.random.default_rng(seed)
    w, h = 640, 480
    left = (rng.random((h, w, 3)) * 60 + 20).astype(np.uint8)
    right = left.copy()
    patch = (rng.random((160, 160, 3)) * 255).astype(np.uint8)
    shift = int(round(disparity_at_depth_res * (w / DEPTH_W)))
    left[160:320, 300:460] = patch
    right[160:320, 300 - shift:460 - shift] = patch
    return left, right


def _expected_depth(disparity: int) -> float:
    return (FX_AT_640 * (DEPTH_W / 640.0) * BASELINE_M) / disparity


def test_disparity_to_metric_depth():
    sd = StereoDepth(FX_AT_640, BASELINE_M)
    for disparity in (8, 12, 20):
        left, right = _stereo_pair(disparity)
        sd.compute(left, right)
        got = sd.distance_for_box([300, 160, 460, 320], (640, 480))
        assert got is not None, f"no match at disparity {disparity}"
        expected = _expected_depth(disparity)
        assert abs(got - expected) / expected < 0.10, \
            f"disparity {disparity}: got {got:.2f} m, expected {expected:.2f} m"


def test_closer_object_reads_nearer():
    """Monotonicity: larger disparity must mean a nearer reading."""
    sd = StereoDepth(FX_AT_640, BASELINE_M)
    depths = []
    for disparity in (8, 16):
        left, right = _stereo_pair(disparity)
        sd.compute(left, right)
        depths.append(sd.distance_for_box([300, 160, 460, 320], (640, 480)))
    assert all(d is not None for d in depths)
    assert depths[1] < depths[0]


def test_untextured_scene_reports_unknown():
    """A flat, textureless wall gives no reliable match. The correct output is
    None (range unknown) — not a confident wrong number."""
    sd = StereoDepth(FX_AT_640, BASELINE_M)
    flat = np.full((480, 640, 3), 90, dtype=np.uint8)
    sd.compute(flat, flat.copy())
    assert sd.distance_for_box([200, 150, 400, 350], (640, 480)) is None


def test_calibration_defaults_are_flagged():
    """An uncalibrated rig must say so: the datasheet geometry is a starting
    point, not a measurement."""
    calib = load_calibration()
    assert "fx_at_640" in calib and "baseline_m" in calib
    assert isinstance(calib["calibrated"], bool)
