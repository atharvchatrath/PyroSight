"""
Thermal camera sensors. read() returns a float32 array of temperatures in
deg C (Lepton 3.5 radiometric convention), NOT a colorized image — all
color-mapping happens downstream so analysis code sees physical units.

  * LeptonThermal    — FLIR Lepton 3.5 on a PureThermal board. The board
                       enumerates as a UVC device delivering Y16 frames where
                       raw = centikelvin (TLinear mode).
  * SimulatedThermal — renders the SITL world's heat field.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Optional

import cv2
import numpy as np

from ..sim.render import render_thermal
from ..sim.world import SimWorld
from .base import Sensor, SensorHealth

LEPTON_W, LEPTON_H = 160, 120


class LeptonThermal(Sensor):
    name = "thermal_lepton35"
    kind = "thermal"

    def __init__(self, index: Optional[int] = None):
        super().__init__()
        self._index = index
        self._cap: Optional[cv2.VideoCapture] = None
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._thread: Optional[threading.Thread] = None

    def _try_open(self, idx: int) -> Optional[cv2.VideoCapture]:
        backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY
        cap = cv2.VideoCapture(idx, backend)
        if not cap.isOpened():
            return None
        # PureThermal delivers Y16; disable RGB conversion to keep raw counts.
        cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
        ok, frame = cap.read()
        if ok and frame is not None:
            h, w = frame.shape[:2]
            if (w, h) in ((LEPTON_W, LEPTON_H), (LEPTON_W, LEPTON_H + 2)):
                return cap
        cap.release()
        return None

    def start(self) -> bool:
        indices = [self._index] if self._index is not None else list(range(4))
        for idx in indices:
            cap = self._try_open(idx)
            if cap is not None:
                self._cap = cap
                self._started = True
                self._health = SensorHealth.OK
                self._detail = f"PureThermal UVC on index {idx}"
                self._thread = threading.Thread(target=self._reader, daemon=True)
                self._thread.start()
                return True
        self._health = SensorHealth.OFFLINE
        self._detail = "no PureThermal / Lepton device found"
        return False

    def _reader(self) -> None:
        while self._started and self._cap is not None:
            ok, frame = self._cap.read()
            if not ok or frame is None:
                time.sleep(0.02)
                continue
            with self._lock:
                self._frame = frame

    def read(self) -> Optional[np.ndarray]:
        with self._lock:
            raw = None if self._frame is None else self._frame.copy()
        if raw is None:
            return None
        self._mark_read()
        raw = raw[:LEPTON_H]  # strip telemetry rows if present
        if raw.dtype != np.uint16:
            raw = raw.view(np.uint16).reshape(LEPTON_H, LEPTON_W)
        # TLinear: raw counts are centikelvin.
        return raw.astype(np.float32) / 100.0 - 273.15

    def stop(self) -> None:
        super().stop()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self._cap is not None:
            self._cap.release()


class SimulatedThermal(Sensor):
    name = "thermal_sim"
    kind = "thermal"

    def __init__(self, world: SimWorld, width: int = LEPTON_W, height: int = LEPTON_H):
        super().__init__()
        self._world = world
        self._size = (width, height)

    def start(self) -> bool:
        self._started = True
        self._health = SensorHealth.SIMULATED
        self._detail = "SITL heat field (Lepton 3.5 geometry)"
        return True

    def read(self) -> Optional[np.ndarray]:
        self._mark_read()
        return render_thermal(self._world, self._size[0], self._size[1])
