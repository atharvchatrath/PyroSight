"""Breadcrumbs, heading filter, and guidance instructions."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pyrosight.config import NavConfig
from pyrosight.navigation.breadcrumbs import BreadcrumbTrail
from pyrosight.navigation.guidance import GuidanceEngine
from pyrosight.navigation.heading import HeadingFilter


def test_heading_wraparound():
    hf = HeadingFilter(alpha=0.5)
    hf.update(350.0)
    hf.update(10.0)  # crossing north must not average to ~180
    assert hf.heading_deg < 20.0 or hf.heading_deg > 340.0
    assert HeadingFilter.cardinal(0) == "N"
    assert HeadingFilter.cardinal(90) == "E"
    assert HeadingFilter.cardinal(225) == "SW"


def test_breadcrumb_trail_and_return():
    bc = BreadcrumbTrail(spacing_m=1.0)
    for i in range(11):
        bc.update_absolute(0.0, i * 0.5)  # walk 5 m north
    assert bc.entry == (0.0, 0.0)
    assert len(bc.crumbs) >= 4
    d = bc.distance_to_entry_m()
    assert 4.0 < d < 7.0
    target = bc.return_target()
    assert target is not None
    assert target[1] < 5.0  # points back toward entry


def test_mark_entry_anchors_the_trail_without_a_position_fix():
    """'mark entry' at the door, before any stride has been dead-reckoned.

    Field failure this covers: live mode with no IMU has no position estimate
    yet, and the command used to ack "ENTRY POINT MARKED" while recording
    nothing — leaving return-to-entry with no anchor for the rest of the
    incident.
    """
    bc = BreadcrumbTrail(spacing_m=1.0)
    assert bc.position is None
    bc.mark_entry_here()
    assert bc.entry == (0.0, 0.0), "entry must exist immediately after marking"
    assert bc.position == (0.0, 0.0)

    # And the trail keeps working from that origin.
    for _ in range(6):
        bc.update_step(0.0)          # six strides north
    assert len(bc.crumbs) >= 3
    assert bc.distance_to_entry_m() > 2.0
    assert bc.return_target() is not None


def test_mark_entry_rebases_an_existing_trail():
    bc = BreadcrumbTrail(spacing_m=1.0)
    for i in range(6):
        bc.update_absolute(0.0, float(i))
    bc.mark_entry_here()
    assert bc.entry == (0.0, 5.0), "re-marking anchors at the current position"
    assert len(bc.crumbs) == 1


def test_guidance_exit_live_and_memory():
    g = GuidanceEngine(NavConfig())
    g.set_objective("find_exit")
    bc = BreadcrumbTrail()
    bc.update_absolute(0.0, 0.0)
    exit_track = {"cls": "exit_sign", "tier": "confirmed", "conf": 0.95,
                  "box": [300, 100, 340, 130], "dist_ft": 30.0}
    nav = g.update([exit_track], 0.0, bc, 640)
    assert nav["target"]["source"] == "live"
    assert "EXIT" in nav["instruction"]
    # Exit disappears: guidance falls back to remembered bearing.
    nav2 = g.update([], 0.0, bc, 640)
    assert nav2["target"] is not None
    assert nav2["target"]["source"] == "memory"
    assert "LAST SEEN" in nav2["instruction"]


def test_guidance_blocked_by_fire_ahead():
    g = GuidanceEngine(NavConfig())
    g.set_objective("find_exit")
    bc = BreadcrumbTrail()
    bc.update_absolute(0.0, 0.0)
    fire = {"cls": "fire", "tier": "confirmed", "conf": 0.9,
            "box": [300, 200, 360, 300], "dist_ft": 10.0}
    nav = g.update([fire], 0.0, bc, 640)
    assert nav["status"] == "BLOCKED"
    assert "HAZARD" in nav["instruction"]


def test_memory_target_drops_stale_distance():
    """Bearing survives operator movement (re-derived against heading), range
    does not. A remembered target older than a few seconds must report no
    distance rather than a figure that is no longer true."""
    import time as _time
    g = GuidanceEngine(NavConfig())
    g.set_objective("locate_victim")
    bc = BreadcrumbTrail()
    bc.update_absolute(0.0, 0.0)
    victim = {"cls": "person", "tier": "confirmed", "conf": 0.9,
              "box": [300, 200, 340, 400], "dist_ft": 19.0}
    g.update([victim], 0.0, bc, 640)          # sighting recorded
    nav = g.update([], 0.0, bc, 640)          # immediately after: range kept
    assert nav["target"]["source"] == "memory"
    assert nav["target"]["dist_ft"] == 19.0
    # Age the memory past the range-validity window.
    g._last_victim["ts"] = _time.time() - 30.0
    nav2 = g.update([], 0.0, bc, 640)
    assert nav2["target"] is not None                  # bearing still useful
    assert nav2["target"]["dist_ft"] is None           # range withheld
    assert "FT" not in nav2["instruction"]
