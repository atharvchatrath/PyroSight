"""Floor integrity: hole/drop-off detection from synthetic stereo depth."""

import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pyrosight.core.alerts import AlertEngine
from pyrosight.vision.floor import FloorIntegrityAnalyzer


def _flat_floor(h=240, w=320, depth_m=2.0):
    return np.full((h, w), depth_m, dtype=np.float32)


def test_flat_floor_has_no_hazards():
    an = FloorIntegrityAnalyzer()
    dmap = _flat_floor()
    hazards = an.analyze_depth(dmap, (640, 480))
    assert hazards == []


def test_drop_off_is_flagged():
    an = FloorIntegrityAnalyzer()
    dmap = _flat_floor(depth_m=2.0)
    h, w = dmap.shape
    # Bottom-right region of the floor band reads much farther than the
    # rest of its row -> a drop-off (e.g. a stairwell edge).
    dmap[int(h * 0.85):, int(w * 0.75):] = 3.2
    hazards = an.analyze_depth(dmap, (640, 480))
    assert any(hz["cls"] == "floor_hazard" and "DROP" in hz["label_hint"]
              for hz in hazards)


def test_void_is_flagged():
    an = FloorIntegrityAnalyzer()
    dmap = _flat_floor(depth_m=2.0)
    h, w = dmap.shape
    # A patch with no valid stereo match at all, surrounded by a healthy
    # floor -> unresolved void (classic hole signature).
    dmap[int(h * 0.85):, int(w * 0.75):] = np.nan
    hazards = an.analyze_depth(dmap, (640, 480))
    assert any(hz["cls"] == "floor_hazard" and "VOID" in hz["label_hint"]
              for hz in hazards)


def test_hazard_box_scaled_to_frame_size():
    an = FloorIntegrityAnalyzer()
    dmap = _flat_floor(depth_m=2.0)
    h, w = dmap.shape
    dmap[int(h * 0.85):, int(w * 0.75):] = np.nan
    hazards = an.analyze_depth(dmap, (1280, 960))
    assert hazards
    x1, y1, x2, y2 = hazards[0]["box"]
    assert 0 <= x1 < x2 <= 1280
    assert 0 <= y1 < y2 <= 960


def test_no_depth_map_returns_empty():
    an = FloorIntegrityAnalyzer()
    assert an.analyze(None, (640, 480)) == []


def test_floor_hazard_alert_fires_only_when_confirmed():
    engine = AlertEngine()
    thermal = {"hotspots": [], "body_regions": []}
    nav = {"status": "CLEAR", "instruction": "SCANNING"}
    diag = {"battery_percent": 80, "sensors": {}}
    possible = [{"cls": "floor_hazard", "tier": "possible", "conf": 0.4,
                "label_hint": "VOID — POSSIBLE HOLE"}]
    fired = engine.evaluate(possible, thermal, 0.0, nav, diag)
    assert not any(a["rule"] == "floor_hazard" for a in fired)

    confirmed = [{"cls": "floor_hazard", "tier": "confirmed", "conf": 0.9,
                 "label_hint": "VOID — POSSIBLE HOLE"}]
    fired = engine.evaluate(confirmed, thermal, 0.0, nav, diag)
    assert any(a["rule"] == "floor_hazard" and a["severity"] == "critical"
              for a in fired)
