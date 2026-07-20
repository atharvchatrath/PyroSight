"""Thermal analysis and RGB+thermal fusion behavior."""

import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pyrosight.config import VisionConfig
from pyrosight.vision.fusion import fuse
from pyrosight.vision.thermal_analysis import ThermalAnalyzer


def _field(base=24.0):
    return np.full((120, 160), base, dtype=np.float32)


def test_hotspot_severity_tiers():
    an = ThermalAnalyzer(VisionConfig())
    temp = _field()
    temp[20:35, 20:35] = 120.0   # elevated
    temp[60:80, 60:80] = 300.0   # severe
    temp[90:110, 120:140] = 600.0  # critical
    result = an.analyze(temp)
    sev = {h["severity"] for h in result["hotspots"]}
    assert sev == {"elevated", "severe", "critical"}
    assert result["stats"]["max_c"] > 550


def test_body_band_detection():
    an = ThermalAnalyzer(VisionConfig())
    temp = _field()
    temp[50:70, 40:55] = 34.0
    result = an.analyze(temp)
    assert len(result["body_regions"]) == 1


def test_fusion_thermal_confirms_person():
    thermal = {
        "hotspots": [],
        "body_regions": [{"box": [40, 50, 55, 70], "max_temp_c": 34.0,
                          "mean_temp_c": 33.0, "area_px": 300}],
    }
    # RGB 640x480, thermal 160x120 -> scale x4: body box ≈ [160,200,220,280]
    person = {"cls": "person", "conf": 0.60, "box": [150, 180, 240, 300]}
    fused = fuse([person], [], thermal, (640, 480), (160, 120))
    p = fused[0]
    assert p["thermal_confirmed"] is True
    assert p["conf"] > 0.60


def test_fusion_unconfirmed_fire_capped_and_hotspot_promoted():
    thermal = {"hotspots": [{"box": [100, 20, 130, 50], "max_temp_c": 500.0,
                             "mean_temp_c": 400.0, "area_px": 500,
                             "severity": "critical"}],
               "body_regions": []}
    fake_fire = {"cls": "fire", "conf": 0.9, "box": [10, 10, 60, 60]}  # no heat
    fused = fuse([fake_fire], [], thermal, (640, 480), (160, 120))
    fire = next(d for d in fused if d["cls"] == "fire")
    assert fire["conf"] <= 0.60          # capped: no thermal support
    hot = next(d for d in fused if d["cls"] == "hotspot")
    assert hot["thermal_confirmed"] and hot["conf"] >= 0.9


def test_dependent_thermal_never_self_confirms():
    """RGB-derived thermal must not confirm detections made from the same
    pixels — the circular-confirmation bug that flooded the HUD with fake
    confirmed fires on webcam feeds."""
    thermal = {
        "hotspots": [{"box": [40, 45, 55, 70], "max_temp_c": 480.0,
                      "mean_temp_c": 400.0, "area_px": 400,
                      "severity": "critical"}],
        "body_regions": [{"box": [40, 50, 55, 70], "max_temp_c": 34.0,
                          "mean_temp_c": 33.0, "area_px": 300}],
    }
    person = {"cls": "person", "conf": 0.60, "box": [150, 180, 240, 300]}
    fire = {"cls": "fire", "conf": 0.9, "box": [160, 180, 220, 280]}
    fused = fuse([person, fire], [], thermal, (640, 480), (160, 120),
                 thermal_independent=False)
    p = next(d for d in fused if d["cls"] == "person")
    f = next(d for d in fused if d["cls"] == "fire")
    assert p["thermal_confirmed"] is False and p["conf"] == 0.60
    assert f["thermal_confirmed"] is False and f["conf"] <= 0.55
    # No hotspot promotion from a derived field.
    assert not any(d["cls"] == "hotspot" for d in fused)


def test_colorize_shapes():
    img = ThermalAnalyzer.colorize(_field())
    assert img.shape == (120, 160, 3)
    assert img.dtype == np.uint8
