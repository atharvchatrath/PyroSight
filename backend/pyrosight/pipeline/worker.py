"""
Asynchronous detection worker.

Neural inference (50-400 ms depending on hardware) must never block the
capture/HUD loop — a firefighter's video feed freezing during inference is
unacceptable. The engine submits the newest frame; the worker runs inference
on its own thread and publishes the latest results + measured latency. The
temporal tracker coasts between updates, so detection running at 3-8 Hz
still yields a smooth 15-20 FPS tactical picture.

Frames are conflated: if inference is busy, older pending frames are
replaced by newer ones. Detection always runs on the freshest image.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

import numpy as np


class DetectionWorker:
    def __init__(self, detector=None, factory=None):
        # Either a ready detector, or a factory built lazily ON THE WORKER
        # THREAD — model loading takes seconds and must not stall the engine
        # (used by the runtime sim -> live camera switch).
        self.detector = detector
        self._factory = factory
        self._cond = threading.Condition()
        self._pending: Optional[np.ndarray] = None
        self._latest: List[Dict[str, Any]] = []
        self._latest_ts: float = 0.0
        self._infer_ms: float = 0.0
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="pyrosight-detector")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        with self._cond:
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def submit(self, frame_bgr: np.ndarray) -> None:
        with self._cond:
            self._pending = frame_bgr
            self._cond.notify()

    def latest(self) -> List[Dict[str, Any]]:
        with self._cond:
            return list(self._latest)

    @property
    def infer_ms(self) -> float:
        return self._infer_ms

    @property
    def age_s(self) -> float:
        return time.time() - self._latest_ts if self._latest_ts else float("inf")

    @property
    def detector_name(self) -> str:
        return self.detector.name if self.detector is not None else "loading"

    def _loop(self) -> None:
        if self.detector is None and self._factory is not None:
            try:
                self.detector = self._factory()
            except Exception:  # noqa: BLE001
                from ..vision.detector import NullDetector
                self.detector = NullDetector()
        while self._running:
            with self._cond:
                while self._pending is None and self._running:
                    self._cond.wait(timeout=0.5)
                frame = self._pending
                self._pending = None
            if frame is None or not self._running:
                continue
            t0 = time.time()
            try:
                results = self.detector.detect(frame)
            except Exception:  # noqa: BLE001 - a bad frame must not kill the worker
                results = []
            with self._cond:
                self._latest = results
                self._latest_ts = time.time()
                self._infer_ms = (time.time() - t0) * 1000.0
