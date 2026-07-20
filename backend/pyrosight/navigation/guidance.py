"""
Guidance engine: turns tracks + heading + breadcrumbs into one simple,
glanceable instruction. The firefighter never reads a map — they get a
relative-bearing arrow, a distance, and a short imperative.

Objectives (set by voice command or dashboard):
  explore          — free movement; passively reports the best egress seen.
  find_exit        — arrow to the best exit evidence (exit sign > door >
                     window > remembered last-seen position).
  locate_victim    — arrow to the strongest person track / last-seen spot.
  return_to_entry  — follow the breadcrumb trail backwards.

Route safety: any confirmed fire/hotspot track inside the forward cone and
within range degrades status CLEAR -> CAUTION -> BLOCKED and the instruction
tells the operator which way to bias. Uncertainty is explicit: guidance from
a remembered (not currently visible) target is labeled MEMORY, degraded.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple

from ..config import NavConfig

FEET_PER_METER = 3.28084
RGB_FX_AT_640 = 522.0

EXIT_PREFERENCE = {"exit_sign": 3, "door": 2, "window": 1}


def _rel_bearing_from_box(box: List[float], frame_w: int) -> float:
    """Horizontal angle (deg) of a box center relative to camera axis."""
    cx = (box[0] + box[2]) / 2.0
    fx = RGB_FX_AT_640 * (frame_w / 640.0)
    return math.degrees(math.atan2(cx - frame_w / 2.0, fx))


def _norm180(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


class GuidanceEngine:
    def __init__(self, cfg: NavConfig):
        self.cfg = cfg
        self.objective = "explore"
        # Remembered absolute bearings/positions of interesting sightings.
        self._last_exit: Optional[Dict[str, Any]] = None    # {abs_bearing, dist_m, ts, cls}
        self._last_victim: Optional[Dict[str, Any]] = None

    def set_objective(self, objective: str) -> None:
        self.objective = objective

    # ------------------------------------------------------------------

    def update(self, tracks: List[Dict[str, Any]], heading_deg: float,
               breadcrumbs, frame_w: int) -> Dict[str, Any]:
        self._remember_sightings(tracks, heading_deg, frame_w)

        target = None
        if self.objective == "return_to_entry":
            target = self._target_entry(heading_deg, breadcrumbs)
        elif self.objective == "locate_victim":
            target = self._target_victim(tracks, heading_deg, frame_w)
        elif self.objective == "find_exit":
            target = self._target_exit(tracks, heading_deg, frame_w)
        else:  # explore: passive exit awareness
            target = self._target_exit(tracks, heading_deg, frame_w, passive=True)

        status, hazard_bias = self._route_safety(tracks, frame_w)
        instruction = self._instruction(target, status, hazard_bias)

        out = {
            "objective": self.objective,
            "status": status,
            "instruction": instruction,
            "target": target,
            "entry_distance_ft": None,
            "breadcrumbs": breadcrumbs.to_dict(),
        }
        d_entry = breadcrumbs.distance_to_entry_m()
        if d_entry is not None:
            out["entry_distance_ft"] = round(d_entry * FEET_PER_METER)
        return out

    # ------------------------------------------------------------------

    def _remember_sightings(self, tracks, heading_deg: float, frame_w: int) -> None:
        best_exit = None
        best_pref = 0
        for t in tracks:
            pref = EXIT_PREFERENCE.get(t["cls"], 0)
            if pref > 0 and t["tier"] != "possible" and pref >= best_pref:
                best_pref, best_exit = pref, t
        if best_exit is not None:
            rel = _rel_bearing_from_box(best_exit["box"], frame_w)
            self._last_exit = {
                "cls": best_exit["cls"],
                "abs_bearing": (heading_deg + rel) % 360.0,
                "dist_ft": best_exit.get("dist_ft"),
                "conf": best_exit["conf"],
                "ts": time.time(),
            }
        victims = [t for t in tracks if t["cls"] == "person"]
        if victims:
            v = max(victims, key=lambda t: t["conf"])
            rel = _rel_bearing_from_box(v["box"], frame_w)
            self._last_victim = {
                "abs_bearing": (heading_deg + rel) % 360.0,
                "dist_ft": v.get("dist_ft"),
                "conf": v["conf"],
                "ts": time.time(),
            }

    def _live_target(self, track, heading_deg: float, frame_w: int,
                     kind: str) -> Dict[str, Any]:
        rel = _rel_bearing_from_box(track["box"], frame_w)
        return {
            "kind": kind,
            "cls": track["cls"],
            "source": "live",
            "rel_bearing_deg": round(rel, 1),
            "dist_ft": track.get("dist_ft"),
            "conf": track["conf"],
        }

    def _memory_target(self, mem: Dict[str, Any], heading_deg: float,
                       kind: str) -> Optional[Dict[str, Any]]:
        if mem is None:
            return None
        age = time.time() - mem["ts"]
        if age > 120.0:  # stale memory is worse than admitting we don't know
            return None
        rel = _norm180(mem["abs_bearing"] - heading_deg)
        return {
            "kind": kind,
            "cls": mem.get("cls", "person"),
            "source": "memory",
            "age_s": round(age),
            "rel_bearing_deg": round(rel, 1),
            "dist_ft": mem.get("dist_ft"),
            "conf": round(max(0.2, mem["conf"] * math.exp(-age / 90.0)), 2),
        }

    def _target_exit(self, tracks, heading_deg, frame_w,
                     passive: bool = False) -> Optional[Dict[str, Any]]:
        best, best_pref = None, 0
        for t in tracks:
            pref = EXIT_PREFERENCE.get(t["cls"], 0)
            if pref > best_pref:
                best_pref, best = pref, t
        if best is not None:
            return self._live_target(best, heading_deg, frame_w, "exit")
        if passive:
            return None
        return self._memory_target(self._last_exit, heading_deg, "exit")

    def _target_victim(self, tracks, heading_deg, frame_w) -> Optional[Dict[str, Any]]:
        victims = [t for t in tracks if t["cls"] == "person"]
        if victims:
            v = max(victims, key=lambda t: t["conf"])
            return self._live_target(v, heading_deg, frame_w, "victim")
        return self._memory_target(self._last_victim, heading_deg, "victim")

    def _target_entry(self, heading_deg, breadcrumbs) -> Optional[Dict[str, Any]]:
        wp = breadcrumbs.return_target()
        pos = breadcrumbs.position
        if wp is None or pos is None:
            return None
        dx, dy = wp[0] - pos[0], wp[1] - pos[1]
        abs_bearing = math.degrees(math.atan2(dx, dy)) % 360.0
        d_entry = breadcrumbs.distance_to_entry_m()
        return {
            "kind": "entry",
            "cls": "entry",
            "source": "breadcrumbs",
            "rel_bearing_deg": round(_norm180(abs_bearing - heading_deg), 1),
            "dist_ft": round(d_entry * FEET_PER_METER) if d_entry else None,
            "conf": 0.9,
        }

    # ------------------------------------------------------------------

    def _route_safety(self, tracks, frame_w: int) -> Tuple[str, Optional[str]]:
        """Hazards in the forward cone degrade route status."""
        status = "CLEAR"
        bias: Optional[str] = None
        for t in tracks:
            if t["cls"] not in ("fire", "hotspot"):
                continue
            rel = _rel_bearing_from_box(t["box"], frame_w)
            if abs(rel) > self.cfg.route_cone_deg:
                continue
            dist_ft = t.get("dist_ft")
            near = dist_ft is None or dist_ft < self.cfg.route_hazard_range_m * FEET_PER_METER
            if not near:
                continue
            severe = (t["cls"] == "fire"
                      or t.get("severity") in ("severe", "critical"))
            if severe and status != "BLOCKED":
                status = "BLOCKED"
                bias = "LEFT" if rel > 0 else "RIGHT"
            elif status == "CLEAR":
                status = "CAUTION"
                bias = "LEFT" if rel > 0 else "RIGHT"
        return status, bias

    @staticmethod
    def _instruction(target: Optional[Dict[str, Any]], status: str,
                     bias: Optional[str]) -> str:
        if status == "BLOCKED":
            side = f" — BEAR {bias}" if bias else ""
            return f"HAZARD ON PATH{side}"
        if target is None:
            return "SCANNING FOR EGRESS"
        rel = target["rel_bearing_deg"]
        dist = target.get("dist_ft")
        name = {"exit": "EXIT", "victim": "VICTIM", "entry": "ENTRY"}[target["kind"]]
        mem = " (LAST SEEN)" if target.get("source") == "memory" else ""
        dist_txt = f" {int(dist)} FT" if dist else ""
        if abs(rel) <= 20:
            head = "AHEAD"
        elif abs(rel) >= 150:
            head = "BEHIND — TURN AROUND"
        elif rel > 0:
            head = "TO YOUR RIGHT" if rel > 60 else "AHEAD RIGHT"
        else:
            head = "TO YOUR LEFT" if rel < -60 else "AHEAD LEFT"
        caution = " • CAUTION" if status == "CAUTION" else ""
        return f"{name}{mem}: {head}{dist_txt}{caution}"
