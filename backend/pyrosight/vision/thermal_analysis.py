"""
Thermal analysis on the raw temperature field (deg C, float32).

Outputs:
  * hotspots       — connected regions above the hotspot threshold, each with
    a bbox (in thermal pixel coords), max/mean temp, and a severity tier.
  * body_regions   — regions inside the human body-temperature band, used by
    the fusion stage to corroborate person detections through smoke.
  * stats          — min / max / mean, hottest-point location.
  * colorize()     — ironbow-style visualization with relative normalization
    (percentile-clipped so one flame doesn't crush the rest of the scene).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from ..config import VisionConfig


class ThermalAnalyzer:
    def __init__(self, cfg: VisionConfig):
        self.cfg = cfg

    def analyze(self, temp_c: np.ndarray) -> Dict[str, Any]:
        h, w = temp_c.shape[:2]
        t_min = float(np.min(temp_c))
        t_max = float(np.max(temp_c))
        t_mean = float(np.mean(temp_c))
        hot_idx = np.unravel_index(int(np.argmax(temp_c)), temp_c.shape)

        hotspots = self._regions(temp_c, self.cfg.hotspot_temp_c, min_area=6)
        for spot in hotspots:
            if spot["max_temp_c"] >= self.cfg.critical_temp_c:
                spot["severity"] = "critical"
            elif spot["max_temp_c"] >= self.cfg.severe_temp_c:
                spot["severity"] = "severe"
            else:
                spot["severity"] = "elevated"

        body_mask = ((temp_c >= self.cfg.body_temp_lo_c)
                     & (temp_c <= self.cfg.body_temp_hi_c)).astype(np.uint8)
        body_regions = self._mask_regions(body_mask, temp_c, min_area=8)

        return {
            "stats": {
                "min_c": round(t_min, 1),
                "max_c": round(t_max, 1),
                "mean_c": round(t_mean, 1),
                "hottest_px": [int(hot_idx[1]), int(hot_idx[0])],
                "width": w,
                "height": h,
            },
            "hotspots": hotspots,
            "body_regions": body_regions,
        }

    def _regions(self, temp_c: np.ndarray, threshold: float,
                 min_area: int) -> List[Dict[str, Any]]:
        mask = (temp_c >= threshold).astype(np.uint8)
        return self._mask_regions(mask, temp_c, min_area)

    @staticmethod
    def _mask_regions(mask: np.ndarray, temp_c: np.ndarray,
                      min_area: int) -> List[Dict[str, Any]]:
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        regions: List[Dict[str, Any]] = []
        for c in contours:
            if cv2.contourArea(c) < min_area:
                continue
            x, y, w, h = cv2.boundingRect(c)
            patch = temp_c[y:y + h, x:x + w]
            regions.append({
                "box": [int(x), int(y), int(x + w), int(y + h)],
                "max_temp_c": round(float(np.max(patch)), 1),
                "mean_temp_c": round(float(np.mean(patch)), 1),
                "area_px": int(cv2.contourArea(c)),
            })
        regions.sort(key=lambda r: -r["max_temp_c"])
        return regions

    @staticmethod
    def colorize(temp_c: np.ndarray,
                 clip: Tuple[float, float] = (1.0, 99.5)) -> np.ndarray:
        """Relative heat map: percentile normalization + ironbow-ish LUT."""
        lo = float(np.percentile(temp_c, clip[0]))
        hi = float(np.percentile(temp_c, clip[1]))
        if hi - lo < 1e-3:
            hi = lo + 1e-3
        norm = np.clip((temp_c - lo) / (hi - lo), 0.0, 1.0)
        u8 = (norm * 255).astype(np.uint8)
        return cv2.applyColorMap(u8, cv2.COLORMAP_INFERNO)

    @staticmethod
    def scale_box(box: List[int], from_wh: Tuple[int, int],
                  to_wh: Tuple[int, int]) -> List[float]:
        """Map a thermal-space box into RGB frame coordinates (aligned-FOV
        assumption; a calibration offset can be layered in config later)."""
        sx = to_wh[0] / float(from_wh[0])
        sy = to_wh[1] / float(from_wh[1])
        return [box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy]
