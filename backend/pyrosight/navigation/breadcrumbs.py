"""
Breadcrumb trail + return-to-entry.

Position source, in order of trust:
  1. External positioning (future UWB / SLAM) — supplied directly.
     In SITL the world's true pose (plus noise) stands in for this.
  2. Pedestrian dead reckoning — BNO085 step events advanced along the
     filtered heading (0.7 m stride). Drifts, but drift-tolerant guidance
     (bearing + distance to the *nearest* crumb) keeps it useful.

The trail is the firefighter's lifeline: crumbs are dropped every
`spacing` meters, the first crumb is the entry point, and the return path
walks the trail backwards so guidance follows the known-safe corridor
instead of cutting through unexplored rooms.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple

STRIDE_M = 0.7


class BreadcrumbTrail:
    def __init__(self, spacing_m: float = 1.0):
        self.spacing = spacing_m
        self.crumbs: List[Tuple[float, float, float]] = []  # (x, y, ts)
        self._pos: Optional[Tuple[float, float]] = None

    # ---- position updates ----

    def update_absolute(self, x: float, y: float) -> None:
        self._pos = (x, y)
        self._maybe_drop()

    def update_step(self, heading_deg: float) -> None:
        """Dead-reckon one stride along the current heading."""
        if self._pos is None:
            self._pos = (0.0, 0.0)
        rad = math.radians(heading_deg)
        self._pos = (self._pos[0] + STRIDE_M * math.sin(rad),
                     self._pos[1] + STRIDE_M * math.cos(rad))
        self._maybe_drop()

    def _maybe_drop(self) -> None:
        if self._pos is None:
            return
        if not self.crumbs:
            self.crumbs.append((self._pos[0], self._pos[1], time.time()))
            return
        lx, ly, _ = self.crumbs[-1]
        if math.hypot(self._pos[0] - lx, self._pos[1] - ly) >= self.spacing:
            self.crumbs.append((self._pos[0], self._pos[1], time.time()))

    # ---- queries ----

    @property
    def position(self) -> Optional[Tuple[float, float]]:
        return self._pos

    @property
    def entry(self) -> Optional[Tuple[float, float]]:
        return (self.crumbs[0][0], self.crumbs[0][1]) if self.crumbs else None

    def mark_entry_here(self) -> None:
        """Voice command 'mark entry': restart the trail at current position."""
        self.crumbs = []
        self._maybe_drop()

    def return_target(self) -> Optional[Tuple[float, float]]:
        """Next waypoint when heading back: the nearest crumb that actually
        makes progress toward the entry (skips the crumbs at our feet)."""
        if self._pos is None or len(self.crumbs) < 1:
            return None
        px, py = self._pos
        # Walk the trail from entry outward; pick the last crumb closer to
        # the entry than we are, at least 1.2 m away from us.
        entry = self.crumbs[0]
        my_d_entry = math.hypot(px - entry[0], py - entry[1])
        best: Optional[Tuple[float, float]] = None
        for (cx, cy, _) in self.crumbs:
            d_me = math.hypot(px - cx, py - cy)
            d_entry = math.hypot(cx - entry[0], cy - entry[1])
            if d_me >= 1.2 and d_entry < my_d_entry:
                best = (cx, cy)  # keep the latest qualifying = nearest to us
        return best if best is not None else (entry[0], entry[1])

    def distance_to_entry_m(self) -> Optional[float]:
        """Cumulative distance along the trail back to the entry."""
        if self._pos is None or not self.crumbs:
            return None
        total = 0.0
        px, py = self._pos
        pts = [(c[0], c[1]) for c in reversed(self.crumbs)]
        for (cx, cy) in pts:
            total += math.hypot(px - cx, py - cy)
            px, py = cx, cy
        return total

    def to_dict(self) -> Dict[str, Any]:
        return {
            "count": len(self.crumbs),
            "entry": list(self.entry) if self.entry else None,
            "position": list(self._pos) if self._pos else None,
            "trail": [[round(c[0], 2), round(c[1], 2)] for c in self.crumbs[-60:]],
        }
