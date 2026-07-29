"""
Stereo RGB sensor — Waveshare Dual IMX219 on the Raspberry Pi 5.

Why this matters for accuracy: every other RGB path estimates range with a
monocular pinhole model, which assumes the object is a standard size and is
fully visible. A crouching victim, a partially occluded doorway, or a child
all break that assumption, and the error is silent. A stereo pair *measures*
range from disparity, so the distance on the HUD is observed rather than
assumed.

The Pi 5 exposes two CSI connectors (cam0/cam1). Both IMX219 sensors are
opened through Picamera2; the left image feeds the perception pipeline
unchanged, and a StereoSGBM disparity map provides depth for any bounding
box. Depth is computed on a downscaled pair to stay inside the frame budget.

Calibration: `backend/data/stereo_calib.json` (written by
scripts/calibrate_stereo.py) supplies fx and baseline. Absent that, the file
falls back to the datasheet geometry for the Waveshare 83-degree module,
which is close enough for hazard-distance decisions but should be calibrated
before relying on the numbers.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np

from ..config import DATA_DIR
from .base import Sensor, SensorHealth

CALIB_PATH = DATA_DIR / "stereo_calib.json"

# Waveshare IMX219-83 stereo module defaults (uncalibrated fallback).
DEFAULT_BASELINE_M = 0.06        # 60 mm between optical centres
DEFAULT_FX_AT_640 = 500.0        # ~83 deg HFOV at 640 px
DEPTH_W, DEPTH_H = 320, 240      # disparity resolution (speed/quality balance)


class StereoDepth:
    """StereoSGBM disparity -> metric depth lookups."""

    def __init__(self, fx_at_640: float, baseline_m: float):
        self.baseline_m = baseline_m
        self.fx_depth = fx_at_640 * (DEPTH_W / 640.0)
        # SGBM is markedly better than BM on low-texture interior walls.
        self._matcher = cv2.StereoSGBM_create(
            minDisparity=0,
            numDisparities=64,       # multiple of 16
            blockSize=7,
            P1=8 * 3 * 7 ** 2,
            P2=32 * 3 * 7 ** 2,
            disp12MaxDiff=1,
            uniquenessRatio=10,
            speckleWindowSize=100,
            speckleRange=2,
            mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY,
        )
        self._lock = threading.Lock()
        self._depth: Optional[np.ndarray] = None   # metres, DEPTH_H x DEPTH_W
        self._ts = 0.0

    def compute(self, left_bgr: np.ndarray, right_bgr: np.ndarray) -> None:
        left = cv2.cvtColor(cv2.resize(left_bgr, (DEPTH_W, DEPTH_H)),
                            cv2.COLOR_BGR2GRAY)
        right = cv2.cvtColor(cv2.resize(right_bgr, (DEPTH_W, DEPTH_H)),
                             cv2.COLOR_BGR2GRAY)
        # SGBM returns fixed-point disparity scaled by 16.
        disp = self._matcher.compute(left, right).astype(np.float32) / 16.0
        with np.errstate(divide="ignore", invalid="ignore"):
            depth = (self.fx_depth * self.baseline_m) / disp
        # Invalid / out-of-range disparities become NaN so they are excluded
        # from medians rather than poisoning them with zeros or infinities.
        depth[disp <= 0.5] = np.nan
        depth[(depth < 0.3) | (depth > 40.0)] = np.nan
        with self._lock:
            self._depth = depth
            self._ts = time.time()

    def distance_for_box(self, box, frame_wh: Tuple[int, int]) -> Optional[float]:
        """Median depth over the central region of a detection box, in metres.

        The centre region is sampled rather than the whole box because box
        edges usually straddle the background, which would bias the estimate
        toward whatever is behind the object.
        """
        with self._lock:
            depth = None if self._depth is None else self._depth
            if depth is None:
                return None
            sx = DEPTH_W / float(frame_wh[0])
            sy = DEPTH_H / float(frame_wh[1])
            x1, y1, x2, y2 = box
            cx1, cy1 = x1 + (x2 - x1) * 0.25, y1 + (y2 - y1) * 0.25
            cx2, cy2 = x1 + (x2 - x1) * 0.75, y1 + (y2 - y1) * 0.75
            ix1 = max(0, min(DEPTH_W - 1, int(cx1 * sx)))
            iy1 = max(0, min(DEPTH_H - 1, int(cy1 * sy)))
            ix2 = max(ix1 + 1, min(DEPTH_W, int(cx2 * sx)))
            iy2 = max(iy1 + 1, min(DEPTH_H, int(cy2 * sy)))
            patch = depth[iy1:iy2, ix1:ix2]
        valid = patch[~np.isnan(patch)]
        if valid.size < 12:          # too few matches to trust
            return None
        return float(np.median(valid))

    def coverage(self) -> float:
        """Fraction of the depth map with a valid match (match quality)."""
        with self._lock:
            if self._depth is None:
                return 0.0
            return float(np.count_nonzero(~np.isnan(self._depth))
                         / self._depth.size)


def load_calibration() -> Dict[str, float]:
    if CALIB_PATH.exists():
        try:
            data = json.loads(CALIB_PATH.read_text())
            return {"fx_at_640": float(data["fx_at_640"]),
                    "baseline_m": float(data["baseline_m"]),
                    "calibrated": True}
        except (ValueError, KeyError, OSError):
            pass
    return {"fx_at_640": DEFAULT_FX_AT_640,
            "baseline_m": DEFAULT_BASELINE_M,
            "calibrated": False}


class StereoRGB(Sensor):
    """Dual IMX219 stereo pair. read() returns the LEFT frame so the rest of
    the pipeline is unchanged; depth is exposed separately via `depth`."""

    name = "rgb_stereo_imx219"
    kind = "rgb"

    def __init__(self, width: int, height: int,
                 left_index: int = 0, right_index: int = 1):
        super().__init__()
        self._size = (width, height)
        self._left_index = left_index
        self._right_index = right_index
        self._cams: list = []
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._thread: Optional[threading.Thread] = None
        calib = load_calibration()
        self.calibrated = calib["calibrated"]
        self.depth = StereoDepth(calib["fx_at_640"], calib["baseline_m"])
        self._depth_every = 2       # disparity every Nth frame
        self._count = 0

    def start(self) -> bool:
        try:
            from picamera2 import Picamera2  # type: ignore
        except ImportError:
            self._health = SensorHealth.OFFLINE
            self._detail = "picamera2 not installed"
            return False
        try:
            available = Picamera2.global_camera_info()
        except Exception as exc:  # noqa: BLE001
            self._health = SensorHealth.OFFLINE
            self._detail = f"camera enumeration failed: {exc}"
            return False
        if len(available) < 2:
            self._health = SensorHealth.OFFLINE
            self._detail = f"stereo needs 2 CSI cameras, found {len(available)}"
            return False
        try:
            for idx in (self._left_index, self._right_index):
                cam = Picamera2(idx)
                cam.configure(cam.create_video_configuration(
                    main={"size": self._size, "format": "RGB888"}))
                cam.start()
                self._cams.append(cam)
        except Exception as exc:  # noqa: BLE001
            for cam in self._cams:
                try:
                    cam.stop()
                except Exception:  # noqa: BLE001
                    pass
            self._cams = []
            self._health = SensorHealth.OFFLINE
            self._detail = f"stereo start failed: {exc}"
            return False

        self._started = True
        self._health = SensorHealth.OK
        self._detail = (f"Dual IMX219 {self._size[0]}x{self._size[1]}, "
                        + ("calibrated" if self.calibrated
                           else "UNCALIBRATED (datasheet geometry)"))
        self._thread = threading.Thread(target=self._reader, daemon=True,
                                        name="pyrosight-stereo")
        self._thread.start()
        return True

    def _reader(self) -> None:
        while self._started and len(self._cams) == 2:
            try:
                left = cv2.cvtColor(self._cams[0].capture_array(),
                                    cv2.COLOR_RGB2BGR)
                right = cv2.cvtColor(self._cams[1].capture_array(),
                                     cv2.COLOR_RGB2BGR)
            except Exception:  # noqa: BLE001 - transient capture error
                time.sleep(0.02)
                continue
            with self._lock:
                self._frame = left
            self._count += 1
            if self._count % self._depth_every == 0:
                try:
                    self.depth.compute(left, right)
                except cv2.error:
                    pass

    def read(self) -> Optional[np.ndarray]:
        with self._lock:
            frame = None if self._frame is None else self._frame.copy()
        if frame is not None:
            self._mark_read()
        return frame

    def health(self) -> Dict[str, Any]:
        info = super().health()
        cov = self.depth.coverage()
        info["detail"] = f"{self._detail}, depth match {cov * 100:.0f}%"
        return info

    def stop(self) -> None:
        super().stop()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        for cam in self._cams:
            try:
                cam.stop()
            except Exception:  # noqa: BLE001
                pass
        self._cams = []
