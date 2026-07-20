"""
SensorSuite: builds the sensor set from config, auto-detecting hardware and
falling back to simulation so the platform always comes up. The suite is the
single place the engine talks to; adding a future sensor (LiDAR, UWB, gas)
means adding a slot here and a Sensor subclass.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..config import PyroSightConfig
from ..sim.world import SimWorld
from .base import Sensor
from .imu import BNO085IMU, SimulatedIMU, StaticIMU
from .rgb import BrowserRGB, PiCameraRGB, SimulatedRGB, WebcamRGB
from .thermal import LeptonThermal, SimulatedThermal


class SensorSuite:
    def __init__(self, config: PyroSightConfig, world: SimWorld):
        self.config = config
        self.world = world
        self.rgb: Optional[Sensor] = None
        self.thermal: Optional[Sensor] = None
        self.imu: Optional[Sensor] = None
        self.rgb_is_sim = False

    def start(self) -> None:
        s = self.config.sensors
        sim_mode = self.config.resolved_mode() == "sim"

        self.rgb = self._start_rgb(s.rgb_source, sim_mode)
        self.thermal = self._start_thermal(s.thermal_source, sim_mode)
        self.imu = self._start_imu(s.imu_source, sim_mode)

    def _start_rgb(self, source: str, sim_mode: bool) -> Sensor:
        s = self.config.sensors
        candidates = []
        if source == "sim" or (source == "auto" and sim_mode):
            candidates = []
        elif source == "webcam":
            candidates = [WebcamRGB(s.webcam_index, s.rgb_width, s.rgb_height)]
        elif source == "browser":
            candidates = [BrowserRGB()]
        elif source == "picamera":
            candidates = [PiCameraRGB(s.rgb_width, s.rgb_height)]
        elif source == "auto":
            candidates = [PiCameraRGB(s.rgb_width, s.rgb_height),
                          WebcamRGB(s.webcam_index, s.rgb_width, s.rgb_height)]
        for cand in candidates:
            if cand.start():
                self.rgb_is_sim = False
                return cand
        sim = SimulatedRGB(self.world, s.rgb_width, s.rgb_height)
        sim.start()
        self.rgb_is_sim = True
        return sim

    def _start_thermal(self, source: str, sim_mode: bool) -> Optional[Sensor]:
        if source in ("lepton",) or (source == "auto" and not sim_mode):
            lepton = LeptonThermal()
            if lepton.start():
                return lepton
        if sim_mode:
            sim = SimulatedThermal(self.world)
            sim.start()
            return sim
        # Live mode without a Lepton: no thermal sensor. The engine derives
        # an RGB-based estimate so fusion stays coherent with the real scene
        # (fusing sim-world heat against a live webcam would be nonsense).
        return None

    def _start_imu(self, source: str, sim_mode: bool) -> Sensor:
        if source in ("bno085",) or (source == "auto" and not sim_mode):
            bno = BNO085IMU()
            if bno.start():
                return bno
        if sim_mode:
            sim = SimulatedIMU(self.world)
            sim.start()
            return sim
        # Live mode without a BNO085: heading comes from camera motion.
        static = StaticIMU()
        static.start()
        return static

    def health(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for sensor in (self.rgb, self.thermal, self.imu):
            if sensor is not None:
                out[sensor.kind] = sensor.health()
        return out

    def stop(self) -> None:
        for sensor in (self.rgb, self.thermal, self.imu):
            if sensor is not None:
                sensor.stop()
