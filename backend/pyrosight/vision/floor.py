"""
Floor integrity: flags holes, drop-offs, and unresolvable voids in the
walkable floor band using MEASURED stereo depth only (sensors.stereo). This
never runs on assumed/estimated depth — falls through the floor are a top
cause of firefighter death, and a firefighter trusts a track with their
body weight, so a "hazard" here has to be observed, not guessed.

Detection is comparative, not absolute: with no camera-pose calibration to
lean on, the floor is instead expected to be roughly level side-to-side at
a given row. A grid cell is flagged when it disagrees with its own row:

  * DROP  — its measured depth reads meaningfully farther than its row
            neighbours (the far side of a drop-off / stairwell edge).
  * VOID  — it has almost no valid stereo match at all while neighbours in
            the same row match fine (the classic signature of a hole: the
            projected pattern has nothing to return from).

Output is shaped exactly like any other fused detection so it flows through
the normal tracker (multi-frame confirmation, honest tiers, HUD rendering)
instead of bypassing that machinery.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np

GRID_COLS = 8
GRID_ROWS = 3
FLOOR_BAND_FRAC = (0.55, 1.0)     # bottom 45% of the frame
DROP_THRESHOLD_M = 0.6
MIN_COVERAGE = 0.15
NEIGHBOR_COVERAGE_MIN = 0.5
MIN_ROW_SAMPLES = 2                # need >=2 healthy cells in a row to judge


class FloorIntegrityAnalyzer:
    def analyze(self, stereo_depth: Any,
               frame_wh: Tuple[int, int]) -> List[Dict[str, Any]]:
        dmap = stereo_depth.snapshot() if stereo_depth is not None else None
        if dmap is None:
            return []
        return self.analyze_depth(dmap, frame_wh)

    def analyze_depth(self, dmap: np.ndarray,
                      frame_wh: Tuple[int, int]) -> List[Dict[str, Any]]:
        dh, dw = dmap.shape[:2]
        y0 = int(dh * FLOOR_BAND_FRAC[0])
        band = dmap[y0:dh, :]
        bh, bw = band.shape[:2]
        if bh < GRID_ROWS or bw < GRID_COLS:
            return []
        col_w = bw / GRID_COLS
        row_h = bh / GRID_ROWS

        cells = []
        for r in range(GRID_ROWS):
            for c in range(GRID_COLS):
                cy1, cy2 = int(r * row_h), int((r + 1) * row_h)
                cx1, cx2 = int(c * col_w), int((c + 1) * col_w)
                patch = band[cy1:cy2, cx1:cx2]
                valid = patch[~np.isnan(patch)]
                coverage = valid.size / float(patch.size) if patch.size else 0.0
                median = float(np.median(valid)) if valid.size else None
                cells.append({
                    "row": r, "median": median, "coverage": coverage,
                    "box_depth": (cx1, y0 + cy1, cx2, y0 + cy2),
                })

        sx = frame_wh[0] / float(dw)
        sy = frame_wh[1] / float(dh)
        hazards: List[Dict[str, Any]] = []
        for r in range(GRID_ROWS):
            row_cells = [ce for ce in cells if ce["row"] == r]
            healthy = [ce for ce in row_cells
                      if ce["coverage"] >= NEIGHBOR_COVERAGE_MIN
                      and ce["median"] is not None]
            if len(healthy) < MIN_ROW_SAMPLES:
                continue
            baseline = float(np.median([ce["median"] for ce in healthy]))
            for ce in row_cells:
                is_drop = (ce["median"] is not None
                          and ce["coverage"] >= NEIGHBOR_COVERAGE_MIN
                          and ce["median"] - baseline >= DROP_THRESHOLD_M)
                is_void = ce["coverage"] < MIN_COVERAGE
                if not (is_drop or is_void):
                    continue
                dx1, dy1, dx2, dy2 = ce["box_depth"]
                depth_for_range = ce["median"] if ce["median"] is not None else baseline
                hint = (f"DROP {ce['median'] - baseline:.1f}M" if is_drop
                       else "VOID — POSSIBLE HOLE")
                hazards.append({
                    "cls": "floor_hazard",
                    "conf": 0.85,
                    "box": [dx1 * sx, dy1 * sy, dx2 * sx, dy2 * sy],
                    "dist_m_measured": depth_for_range,
                    "label_hint": hint,
                })
        return hazards
