"""
Smoke density estimation from the RGB stream (0.0 clear -> 1.0 opaque).

Physically motivated cues, cheap enough for every frame:
  * Contrast collapse — smoke scatters light, flattening the histogram.
  * Edge attenuation  — Laplacian energy drops as detail is obscured.
  * Haze brightness   — dense smoke pulls the upper image toward mid-gray.

The three cues are blended and EMA-smoothed. Output feeds the HUD visibility
indicator, detection-confidence derating, and the LOW VISIBILITY alert.
"""

from __future__ import annotations

import cv2
import numpy as np

# Reference values measured on clear indoor footage.
CLEAR_CONTRAST = 55.0
CLEAR_EDGE_ENERGY = 180.0


class SmokeEstimator:
    def __init__(self, alpha: float = 0.15, calibrate: bool = False,
                 calib_frames: int = 60):
        self._alpha = alpha
        self._density = 0.0
        # Live mode auto-baselines against the first seconds of footage
        # (assumed pre-entry / clear), so the estimator adapts to any camera
        # and lighting instead of trusting lab constants.
        self._calibrating = calibrate
        self._calib_left = calib_frames
        self._calib_contrast: list = []
        self._calib_edge: list = []
        self._ref_contrast = CLEAR_CONTRAST
        self._ref_edge = CLEAR_EDGE_ENERGY

    @property
    def density(self) -> float:
        return self._density

    @property
    def calibrating(self) -> bool:
        return self._calibrating

    def update(self, frame_bgr: np.ndarray) -> float:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (160, 120))

        contrast = float(np.std(small))
        lap = cv2.Laplacian(small, cv2.CV_32F)
        edge_energy = float(np.mean(np.abs(lap))) * 10.0

        if self._calibrating:
            self._calib_contrast.append(contrast)
            self._calib_edge.append(edge_energy)
            self._calib_left -= 1
            if self._calib_left <= 0:
                # Reference = this scene when clear, floored at half the lab
                # defaults so a dim room doesn't zero the scale.
                self._ref_contrast = max(CLEAR_CONTRAST * 0.5,
                                         float(np.median(self._calib_contrast)))
                self._ref_edge = max(CLEAR_EDGE_ENERGY * 0.5,
                                     float(np.median(self._calib_edge)))
                self._calibrating = False
            return 0.0

        contrast_cue = 1.0 - min(1.0, contrast / self._ref_contrast)
        edge_cue = 1.0 - min(1.0, edge_energy / self._ref_edge)

        top = small[: small.shape[0] // 2]
        mean_top = float(np.mean(top))
        # Haze pushes brightness toward mid-gray (neither dark nor blown out).
        haze_cue = max(0.0, 1.0 - abs(mean_top - 128.0) / 96.0)

        raw = 0.45 * contrast_cue + 0.35 * edge_cue + 0.20 * haze_cue
        self._density += self._alpha * (raw - self._density)
        return round(max(0.0, min(1.0, self._density)), 3)

    @staticmethod
    def visibility_label(density: float) -> str:
        if density < 0.25:
            return "GOOD"
        if density < 0.5:
            return "REDUCED"
        if density < 0.72:
            return "POOR"
        return "NEAR ZERO"
