"""
IMU sensors. read() returns a dict:
  {"yaw_deg", "pitch_deg", "roll_deg", "accel": [ax, ay, az], "step": bool}

  * BNO085IMU    — Bosch BNO085 over I2C via adafruit-circuitpython-bno08x.
                   The chip runs its own sensor-fusion firmware; we consume
                   the rotation vector directly.
  * SimulatedIMU — SITL heading + gyro noise + gait accelerations, with a
                   deliberately drifting bias so the heading filter has real
                   work to do.
"""

from __future__ import annotations

import math
import random
import time
from typing import Any, Dict, Optional

from ..sim.world import SimWorld
from .base import Sensor, SensorHealth


class BNO085IMU(Sensor):
    name = "imu_bno085"
    kind = "imu"

    def __init__(self):
        super().__init__()
        self._bno = None

    def start(self) -> bool:
        try:
            import board  # type: ignore
            import busio  # type: ignore
            from adafruit_bno08x import (  # type: ignore
                BNO_REPORT_ACCELEROMETER, BNO_REPORT_ROTATION_VECTOR)
            from adafruit_bno08x.i2c import BNO08X_I2C  # type: ignore
        except ImportError:
            self._health = SensorHealth.OFFLINE
            self._detail = "adafruit-circuitpython-bno08x not installed"
            return False
        try:
            i2c = busio.I2C(board.SCL, board.SDA, frequency=400_000)
            self._bno = BNO08X_I2C(i2c)
            self._bno.enable_feature(BNO_REPORT_ROTATION_VECTOR)
            self._bno.enable_feature(BNO_REPORT_ACCELEROMETER)
            self._started = True
            self._health = SensorHealth.OK
            self._detail = "BNO085 on I2C"
            return True
        except Exception as exc:  # noqa: BLE001
            self._health = SensorHealth.OFFLINE
            self._detail = f"BNO085 init failed: {exc}"
            return False

    def read(self) -> Optional[Dict[str, Any]]:
        if self._bno is None:
            return None
        try:
            qi, qj, qk, qr = self._bno.quaternion
            ax, ay, az = self._bno.acceleration
        except Exception:  # noqa: BLE001 - transient I2C hiccup
            return None
        self._mark_read()
        yaw = math.degrees(math.atan2(2 * (qr * qk + qi * qj),
                                      1 - 2 * (qj * qj + qk * qk)))
        pitch = math.degrees(math.asin(max(-1.0, min(1.0, 2 * (qr * qj - qk * qi)))))
        roll = math.degrees(math.atan2(2 * (qr * qi + qj * qk),
                                       1 - 2 * (qi * qi + qj * qj)))
        return {"yaw_deg": yaw % 360.0, "pitch_deg": pitch, "roll_deg": roll,
                "accel": [ax, ay, az], "step": False}


class StaticIMU(Sensor):
    """Live mode without a BNO085 (laptop testing / failed IMU). Yields no
    yaw of its own — the engine derives heading from camera motion instead
    (vision.visual_odometry) — and reports itself as estimated."""

    name = "imu_none"
    kind = "imu"

    def start(self) -> bool:
        self._started = True
        self._health = SensorHealth.ESTIMATED
        self._detail = "no BNO085 — heading from camera motion"
        return True

    def read(self) -> Optional[Dict[str, Any]]:
        self._mark_read()
        return {"yaw_deg": None, "pitch_deg": 0.0, "roll_deg": 0.0,
                "accel": [0.0, 0.0, 9.81], "step": False}


class SimulatedIMU(Sensor):
    name = "imu_sim"
    kind = "imu"

    def __init__(self, world: SimWorld):
        super().__init__()
        self._world = world
        self._rng = random.Random(11)
        self._bias = 0.0
        self._last_pos = None
        self._step_phase = 0.0

    def start(self) -> bool:
        self._started = True
        self._health = SensorHealth.SIMULATED
        self._detail = "SITL pose + gyro noise/drift"
        return True

    def read(self) -> Optional[Dict[str, Any]]:
        self._mark_read()
        x, y, yaw = self._world.camera_pose()
        # Slowly wandering bias models magnetometer disturbance near steel.
        self._bias += self._rng.uniform(-0.02, 0.02)
        self._bias = max(-4.0, min(4.0, self._bias))
        noisy_yaw = (yaw + self._bias + self._rng.uniform(-0.8, 0.8)) % 360.0

        moving = False
        if self._last_pos is not None:
            moving = math.hypot(x - self._last_pos[0], y - self._last_pos[1]) > 1e-4
        self._last_pos = (x, y)

        step = False
        if moving:
            self._step_phase += 0.09
            if self._step_phase >= 1.0:  # ~one stride per ~0.7 s at loop rate
                self._step_phase -= 1.0
                step = True
        gait = math.sin(time.time() * 11.0) * (1.2 if moving else 0.05)
        return {
            "yaw_deg": noisy_yaw,
            "pitch_deg": self._rng.uniform(-2.0, 2.0),
            "roll_deg": self._rng.uniform(-1.5, 1.5),
            "accel": [self._rng.uniform(-0.2, 0.2),
                      self._rng.uniform(-0.2, 0.2),
                      9.81 + gait],
            "step": step,
        }
