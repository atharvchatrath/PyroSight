"""
RGB camera sensors.

  * WebcamRGB    — cross-platform OpenCV capture (Windows: DirectShow,
                   macOS: AVFoundation, Linux: V4L2/any) on a daemon thread
                   so the perception loop always reads the freshest frame.
  * PiCameraRGB  — Raspberry Pi Camera Module 3 via Picamera2 (Pi only).
  * SimulatedRGB — renders the SITL corridor world.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Optional

import cv2
import numpy as np

from ..sim.render import render_rgb
from ..sim.world import SimWorld
from .base import Sensor, SensorHealth


def _capture_backend() -> int:
    if sys.platform == "darwin":
        return cv2.CAP_AVFOUNDATION
    if sys.platform.startswith("win"):
        return cv2.CAP_DSHOW  # avoids the multi-second MSMF probe on Windows
    return cv2.CAP_ANY


class WebcamRGB(Sensor):
    name = "rgb_webcam"
    kind = "rgb"

    def __init__(self, index: int, width: int, height: int):
        super().__init__()
        self._index = index
        self._req = (width, height)
        self._cap: Optional[cv2.VideoCapture] = None
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        self._cap = cv2.VideoCapture(self._index, _capture_backend())
        if not self._cap.isOpened():
            self._cap = cv2.VideoCapture(self._index)
        if not self._cap.isOpened():
            self._health = SensorHealth.OFFLINE
            self._detail = f"cannot open camera index {self._index}"
            return False
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._req[0])
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._req[1])
        deadline = time.time() + 5.0
        while time.time() < deadline:
            ok, frame = self._cap.read()
            if ok:
                self._frame = frame
                self._started = True
                self._health = SensorHealth.OK
                self._detail = f"index {self._index} @ {frame.shape[1]}x{frame.shape[0]}"
                self._thread = threading.Thread(target=self._reader, daemon=True)
                self._thread.start()
                return True
            time.sleep(0.05)
        self._health = SensorHealth.OFFLINE
        self._detail = "camera opened but produced no frames"
        return False

    def _reader(self) -> None:
        last_ok = time.time()
        while self._started and self._cap is not None:
            ok, frame = self._cap.read()
            if not ok:
                # Watchdog: a camera that stalls >3 s (USB glitch, driver
                # hiccup) gets reopened instead of silently freezing the HUD.
                if time.time() - last_ok > 3.0:
                    self._health = SensorHealth.DEGRADED
                    self._detail = "stream stalled — reopening"
                    try:
                        self._cap.release()
                        self._cap = cv2.VideoCapture(self._index, _capture_backend())
                        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._req[0])
                        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._req[1])
                    except cv2.error:
                        pass
                    last_ok = time.time()
                time.sleep(0.02)
                continue
            last_ok = time.time()
            if self._health != SensorHealth.OK:
                self._health = SensorHealth.OK
                self._detail = f"index {self._index} recovered"
            with self._lock:
                self._frame = frame

    def read(self) -> Optional[np.ndarray]:
        with self._lock:
            frame = None if self._frame is None else self._frame.copy()
        if frame is not None:
            self._mark_read()
        return frame

    def stop(self) -> None:
        super().stop()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self._cap is not None:
            self._cap.release()


class PiCameraRGB(Sensor):
    """Raspberry Pi Camera Module 3 via Picamera2. Import is deferred so this
    file loads fine on dev machines without libcamera."""

    name = "rgb_picamera3"
    kind = "rgb"

    def __init__(self, width: int, height: int):
        super().__init__()
        self._size = (width, height)
        self._picam = None

    def start(self) -> bool:
        try:
            from picamera2 import Picamera2  # type: ignore
        except ImportError:
            self._health = SensorHealth.OFFLINE
            self._detail = "picamera2 not installed"
            return False
        try:
            self._picam = Picamera2()
            config = self._picam.create_video_configuration(
                main={"size": self._size, "format": "RGB888"})
            self._picam.configure(config)
            self._picam.start()
            self._started = True
            self._health = SensorHealth.OK
            self._detail = f"Camera Module 3 @ {self._size[0]}x{self._size[1]}"
            return True
        except Exception as exc:  # noqa: BLE001 - report, degrade to sim
            self._health = SensorHealth.OFFLINE
            self._detail = f"picamera2 failed: {exc}"
            return False

    def read(self) -> Optional[np.ndarray]:
        if self._picam is None:
            return None
        frame = self._picam.capture_array()
        self._mark_read()
        return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

    def stop(self) -> None:
        super().stop()
        if self._picam is not None:
            self._picam.stop()


class BrowserRGB(Sensor):
    """RGB frames pushed from a browser over /ws/ingest (getUserMedia ->
    JPEG). Lets any laptop/phone camera drive the real pipeline without OS
    driver or permission plumbing on the backend host — the browser owns the
    camera permission. Used for live testing on dev machines."""

    name = "rgb_browser"
    kind = "rgb"

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None

    def start(self) -> bool:
        self._started = True
        self._health = SensorHealth.DEGRADED
        self._detail = "waiting for browser camera frames"
        return True

    def push(self, jpeg: bytes) -> bool:
        arr = np.frombuffer(jpeg, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            return False
        with self._lock:
            self._frame = frame
        if self._health != SensorHealth.OK:
            self._health = SensorHealth.OK
            self._detail = f"browser feed {frame.shape[1]}x{frame.shape[0]}"
        self._mark_read()
        return True

    def read(self) -> Optional[np.ndarray]:
        with self._lock:
            frame = None if self._frame is None else self._frame.copy()
        # Stale feed (tab closed) degrades via base-class staleness check.
        if self._started and (time.time() - self._last_read_ts) > 2.0:
            self._health = SensorHealth.DEGRADED
            self._detail = "browser feed stalled"
        return frame


class SimulatedRGB(Sensor):
    name = "rgb_sim"
    kind = "rgb"

    def __init__(self, world: SimWorld, width: int, height: int):
        super().__init__()
        self._world = world
        self._size = (width, height)

    def start(self) -> bool:
        self._started = True
        self._health = SensorHealth.SIMULATED
        self._detail = "SITL corridor world"
        return True

    def read(self) -> Optional[np.ndarray]:
        self._mark_read()
        return render_rgb(self._world, self._size[0], self._size[1])
