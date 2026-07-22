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


def test_hsv_color_alone_never_creates_fire():
    """The life-safety rule: HSV flame-color alone (the webcam false-fire
    trap — skin, warm light, screen glow) NEVER creates a fire track. Only
    the neural detector can, with color/thermal as corroboration."""
    thermal = {"hotspots": [], "body_regions": []}
    hsv_only = [{"cls": "fire", "conf": 0.6, "box": [10, 10, 60, 60],
                 "source": "hsv", "flicker": 0.2}]
    fused = fuse([], hsv_only, thermal, (640, 480), (160, 120))
    assert not any(d["cls"] == "fire" for d in fused)


def test_neural_fire_uncorroborated_is_possible_not_alarmed():
    """A neural fire with no flicker/thermal support is shown as an honest
    POSSIBLE fire (capped below the confirmed tier) — never dropped (so real
    fire still surfaces), but marked uncorroborated so it does not alarm."""
    thermal = {"hotspots": [], "body_regions": []}
    neural_fire = {"cls": "fire", "conf": 0.9, "box": [100, 100, 200, 260]}
    fused = fuse([neural_fire], [], thermal, (640, 480), (160, 120))
    fire = next(d for d in fused if d["cls"] == "fire")
    assert fire["thermal_confirmed"] is False
    assert fire["rgb_corroborated"] is False
    assert fire["conf"] <= 0.55  # possible tier, no alarm

    # A weak neural guess below the floor is dropped outright.
    weak = {"cls": "fire", "conf": 0.2, "box": [10, 10, 60, 60]}
    assert not any(d["cls"] == "fire"
                   for d in fuse([weak], [], thermal, (640, 480), (160, 120)))


def test_fire_confirmed_by_two_rgb_sources():
    """Neural fire + flickering flame region at the same place -> trusted
    (the honest RGB-only path). This is the ONLY way fire shows without a
    thermal camera."""
    thermal = {"hotspots": [], "body_regions": []}
    neural_fire = {"cls": "fire", "conf": 0.7, "box": [100, 100, 200, 260]}
    flicker = [{"cls": "fire", "conf": 0.6, "box": [110, 110, 190, 250],
                "source": "hsv", "flicker": 0.12, "white_core_px": 20}]
    fused = fuse([neural_fire], flicker, thermal, (640, 480), (160, 120))
    fire = next(d for d in fused if d["cls"] == "fire")
    assert fire["rgb_corroborated"] is True


def test_thermal_hotspot_promoted():
    thermal = {"hotspots": [{"box": [100, 20, 130, 50], "max_temp_c": 500.0,
                             "mean_temp_c": 400.0, "area_px": 500,
                             "severity": "critical"}],
               "body_regions": []}
    fused = fuse([], [], thermal, (640, 480), (160, 120))
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
    # Person: derived thermal gives no confidence boost or confirmation.
    assert p["thermal_confirmed"] is False and p["conf"] == 0.60
    # Fire: derived thermal is NOT corroboration, so the fire stays an
    # uncorroborated POSSIBLE (never self-confirmed into an alarm).
    fire_out = next(d for d in fused if d["cls"] == "fire")
    assert fire_out["thermal_confirmed"] is False
    assert fire_out["rgb_corroborated"] is False
    assert fire_out["conf"] <= 0.55
    # No hotspot promotion from a derived field.
    assert not any(d["cls"] == "hotspot" for d in fused)


def test_colorize_shapes():
    img = ThermalAnalyzer.colorize(_field())
    assert img.shape == (120, 160, 3)
    assert img.dtype == np.uint8
