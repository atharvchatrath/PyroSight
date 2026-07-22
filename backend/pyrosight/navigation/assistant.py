"""
Smart AI Assistant — concise, spoken-style situational suggestions.

Distinct from alerts (which are urgent, rate-limited warnings): the
assistant offers calm, glanceable observations a partner might murmur —
"possible exit ahead", "high heat on your right", "doorway behind you",
"visibility dropping". One line at a time, rate-limited, only when it adds
something the firefighter can act on. Never invents certainty: it mirrors
the same confidence tiers as the rest of the stack ("possible" stays
"possible").
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


class SmartAssistant:
    def __init__(self, min_interval_s: float = 6.0):
        self._min_interval = min_interval_s
        self._last_ts = 0.0
        self._last_text = ""
        self._current: Optional[str] = None
        self._prev_visibility = "GOOD"

    @property
    def current(self) -> Optional[str]:
        return self._current

    def update(self, tracks: List[Dict[str, Any]], nav: Dict[str, Any],
               smoke_visibility: str, heading_deg: float) -> Optional[str]:
        candidates: List[str] = []

        # Visibility trend (fires on the transition, not continuously).
        order = {"GOOD": 0, "REDUCED": 1, "POOR": 2, "NEAR ZERO": 3,
                 "CALIBRATING": 0, "AWAITING FEED": 0}
        if order.get(smoke_visibility, 0) > order.get(self._prev_visibility, 0):
            candidates.append("Visibility decreasing — consider thermal")
        self._prev_visibility = smoke_visibility

        # Exit awareness from the guidance target.
        target = nav.get("target")
        if target and target["kind"] == "exit":
            rel = target["rel_bearing_deg"]
            side = self._side(rel)
            if target.get("source") == "memory":
                candidates.append(f"Previously observed exit {side}")
            elif abs(rel) <= 25:
                candidates.append("Possible exit ahead")
            else:
                candidates.append(f"Possible exit {side}")

        # Heat awareness.
        hazards = [t for t in tracks if t["cls"] in ("fire", "hotspot")]
        if hazards:
            h = max(hazards, key=lambda t: t.get("max_temp_c") or 0)
            # Bearing from box center relative to frame center is encoded in
            # nav route safety; approximate side from box x if present.
            side = self._box_side(h.get("box"))
            temp = h.get("max_temp_c")
            tt = f" ({int(temp)}°C)" if temp else ""
            candidates.append(f"High heat {side}{tt}")

        # Remembered doorway behind.
        doors_behind = [t for t in tracks if t["cls"] == "door"
                        and t.get("coasting")]
        if doors_behind and not candidates:
            candidates.append("Doorway noted behind you")

        if not candidates:
            return None
        text = candidates[0]
        now = time.time()
        if text == self._last_text and now - self._last_ts < self._min_interval * 2:
            return None
        if now - self._last_ts < self._min_interval:
            return None
        self._last_ts = now
        self._last_text = text
        self._current = text
        return text

    @staticmethod
    def _side(rel_deg: float) -> str:
        if abs(rel_deg) <= 25:
            return "ahead"
        if abs(rel_deg) >= 150:
            return "behind you"
        return "on your right" if rel_deg > 0 else "on your left"

    @staticmethod
    def _box_side(box) -> str:
        if not box:
            return "nearby"
        cx = (box[0] + box[2]) / 2.0
        # Assume a ~640 wide frame; center third = ahead.
        if cx < 640 * 0.38:
            return "on your left"
        if cx > 640 * 0.62:
            return "on your right"
        return "ahead"
