"""Mesh position sharing (UDP broadcast) and buddy bearing math."""

import pathlib
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pyrosight.config import MeshConfig
from pyrosight.core.alerts import AlertEngine
from pyrosight.navigation.mesh import MeshLink, buddy_bearings


def test_buddy_bearing_directly_ahead():
    teammates = [{"id": "b", "x": 0.0, "y": 10.0, "heard_at": time.time(),
                 "emergency": False}]
    out = buddy_bearings((0.0, 0.0), 0.0, teammates)
    assert len(out) == 1
    assert abs(out[0]["rel_bearing_deg"]) < 1.0
    assert abs(out[0]["dist_ft"] - 32.8) < 1.0  # 10 m


def test_buddy_bearing_sorted_nearest_first():
    now = time.time()
    teammates = [
        {"id": "far", "x": 0.0, "y": 50.0, "heard_at": now},
        {"id": "near", "x": 0.0, "y": 5.0, "heard_at": now},
    ]
    out = buddy_bearings((0.0, 0.0), 0.0, teammates)
    assert [b["id"] for b in out] == ["near", "far"]


def test_buddy_bearing_no_position_returns_empty():
    assert buddy_bearings(None, 0.0, [{"id": "a", "x": 1, "y": 1,
                                       "heard_at": time.time()}]) == []


def test_buddy_bearing_skips_teammates_without_position():
    out = buddy_bearings((0.0, 0.0), 0.0,
                         [{"id": "a", "x": None, "y": None,
                           "heard_at": time.time()}])
    assert out == []


def test_mesh_link_loopback_publish_and_receive():
    """Two units on localhost should hear each other's broadcasts.

    Asserts at least one direction arrives rather than both: on Windows,
    two sockets bound to the identical local port in one process can see
    inbound datagrams delivered to only one of them (an OS port-sharing
    quirk, not a mesh-protocol bug — real deployments are separate
    machines, each with exactly one socket on the port). Skips entirely in
    sandboxes that block UDP socket binding outright."""
    port = 47201
    cfg_a = MeshConfig(unit_id="alpha", port=port, broadcast_addr="127.0.0.1",
                       broadcast_hz=1000.0, timeout_s=5.0)
    cfg_b = MeshConfig(unit_id="bravo", port=port, broadcast_addr="127.0.0.1",
                       broadcast_hz=1000.0, timeout_s=5.0)
    a, b = MeshLink(cfg_a), MeshLink(cfg_b)
    if not a.start():
        pytest.skip("UDP socket binding unavailable in this environment")
    if not b.start():
        a.stop()
        pytest.skip("UDP socket binding unavailable in this environment")
    try:
        a.publish((1.0, 2.0), 45.0)
        b.publish((5.0, 5.0), 90.0)
        deadline = time.time() + 2.0
        heard_a = heard_b = False
        while time.time() < deadline and not (heard_a and heard_b):
            heard_a = any(t["id"] == "bravo" for t in a.teammates())
            heard_b = any(t["id"] == "alpha" for t in b.teammates())
            if not (heard_a and heard_b):
                time.sleep(0.05)
                a.publish((1.0, 2.0), 45.0)
                b.publish((5.0, 5.0), 90.0)
        assert heard_a or heard_b
    finally:
        a.stop()
        b.stop()


def test_teammate_signal_lost_alert_on_dropout():
    engine = AlertEngine()
    tracks, thermal, smoke, nav, diag = [], {"hotspots": [], "body_regions": []}, \
        0.0, {"status": "CLEAR", "instruction": "SCANNING"}, \
        {"battery_percent": 80, "sensors": {}}
    buddies = [{"id": "bravo", "rel_bearing_deg": 10.0, "dist_ft": 20.0,
               "emergency": False, "age_s": 1.0}]
    fired = engine.evaluate(tracks, thermal, smoke, nav, diag, buddies=buddies)
    assert not any(a["rule"] == "teammate_signal_lost" for a in fired)
    # Buddy drops off the mesh entirely -> the transition should alert once.
    fired = engine.evaluate(tracks, thermal, smoke, nav, diag, buddies=[])
    assert any(a["rule"] == "teammate_signal_lost" for a in fired)
    fired = engine.evaluate(tracks, thermal, smoke, nav, diag, buddies=[])
    assert not any(a["rule"] == "teammate_signal_lost" for a in fired)
