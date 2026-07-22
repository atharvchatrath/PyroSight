"""
Search Mode coverage tracking.

Guided room search needs to answer one question under stress: "have I
covered this space, or is there a corner I skipped?" We maintain a coarse
occupancy grid in world meters around the entry. Cells the firefighter has
been near (within sensor reach) are marked EXPLORED; cells seen only
briefly or at the edge of range are PARTIAL and flagged for another pass.

Coarse on purpose (0.75 m cells): a firefighter cannot act on a fine map
while moving, and dead-reckoned position is not that precise anyway.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple

CELL_M = 0.75
GRID_RADIUS_CELLS = 24     # +/- 18 m around entry
REACH_M = 2.2              # cells this close to the operator become explored
PARTIAL_M = 4.5            # seen-at-range -> partial


class SearchCoverage:
    def __init__(self):
        # (cx, cy) -> {"level": 1 partial | 2 explored, "ts": last update}
        self.cells: Dict[Tuple[int, int], Dict[str, float]] = {}
        self.active = False
        self._origin: Optional[Tuple[float, float]] = None

    def start(self, position: Optional[Tuple[float, float]]) -> None:
        self.active = True
        self.cells.clear()
        self._origin = position or (0.0, 0.0)

    def stop(self) -> None:
        self.active = False

    def update(self, position: Optional[Tuple[float, float]],
               heading_deg: float) -> None:
        if not self.active or position is None:
            return
        if self._origin is None:
            self._origin = position
        px, py = position
        # Mark cells in a forward-biased disc around the operator.
        r = int(math.ceil(PARTIAL_M / CELL_M))
        base_cx = int(round((px - self._origin[0]) / CELL_M))
        base_cy = int(round((py - self._origin[1]) / CELL_M))
        for dcx in range(-r, r + 1):
            for dcy in range(-r, r + 1):
                cx, cy = base_cx + dcx, base_cy + dcy
                if abs(cx) > GRID_RADIUS_CELLS or abs(cy) > GRID_RADIUS_CELLS:
                    continue
                wx = dcx * CELL_M
                wy = dcy * CELL_M
                dist = math.hypot(wx, wy)
                if dist <= REACH_M:
                    level = 2
                elif dist <= PARTIAL_M:
                    level = 1
                else:
                    continue
                cur = self.cells.get((cx, cy))
                if cur is None or level > cur["level"]:
                    self.cells[(cx, cy)] = {"level": level, "ts": time.time()}
                elif cur["level"] == level:
                    cur["ts"] = time.time()

    def stats(self) -> Dict[str, Any]:
        explored = sum(1 for c in self.cells.values() if c["level"] == 2)
        partial = sum(1 for c in self.cells.values() if c["level"] == 1)
        total = explored + partial
        return {
            "active": self.active,
            "explored_cells": explored,
            "partial_cells": partial,
            "coverage_pct": round(100.0 * explored / total) if total else 0,
            "needs_pass": partial,
        }

    def to_dict(self) -> Dict[str, Any]:
        out = self.stats()
        if self.active:
            out["cell_m"] = CELL_M
            out["cells"] = [
                {"x": k[0], "y": k[1], "level": v["level"]}
                for k, v in list(self.cells.items())[:400]
            ]
        else:
            out["cells"] = []
        return out
