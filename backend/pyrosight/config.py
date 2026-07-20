"""
Central configuration for PyroSight.

Everything is a plain dataclass so the whole config can be serialized to the
dashboard, overridden from environment variables (PYROSIGHT_*), and kept
readable on a 2 AM debugging session. Platform detection lives here so every
other module can ask "am I on the Pi / Windows / macOS?" in one place.
"""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
DATA_DIR = BACKEND_ROOT / "data"
MODELS_DIR = BACKEND_ROOT / "models"


def is_raspberry_pi() -> bool:
    """True when running on Raspberry Pi hardware (checks device-tree model)."""
    model_path = Path("/proc/device-tree/model")
    try:
        return "raspberry pi" in model_path.read_text(errors="ignore").lower()
    except OSError:
        return False


def platform_name() -> str:
    if is_raspberry_pi():
        return "raspberry-pi"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("win"):
        return "windows"
    return "linux"


def _env(name: str, default: str) -> str:
    return os.environ.get(f"PYROSIGHT_{name}", default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    return _env(name, "1" if default else "0").lower() in ("1", "true", "yes", "on")


@dataclass
class SensorConfig:
    # "auto" picks real hardware when present, otherwise simulation.
    rgb_source: str = _env("RGB_SOURCE", "auto")        # auto | webcam | picamera | sim
    thermal_source: str = _env("THERMAL_SOURCE", "auto")  # auto | lepton | sim
    imu_source: str = _env("IMU_SOURCE", "auto")        # auto | bno085 | sim
    webcam_index: int = _env_int("WEBCAM_INDEX", 0)
    rgb_width: int = _env_int("RGB_WIDTH", 640)
    rgb_height: int = _env_int("RGB_HEIGHT", 480)
    # FLIR Lepton 3.5 native resolution.
    thermal_width: int = 160
    thermal_height: int = 120


@dataclass
class VisionConfig:
    # Detector chain: onnx -> ultralytics -> none. Sim mode uses ground truth.
    onnx_model: str = _env("ONNX_MODEL", str(MODELS_DIR / "yolov8n.onnx"))
    ultralytics_model: str = _env("ULTRALYTICS_MODEL", str(PROJECT_ROOT / "yolov8s-world.pt"))
    input_size: int = _env_int("DETECT_INPUT", 416)
    # Model-pass gate must sit BELOW every per-class floor in
    # vision/classes.py — the per-class floors do the real gating, and a
    # higher global gate would silently starve low-scoring classes
    # (exit signs, indoor windows) before their floors ever see them.
    conf_threshold: float = _env_float("CONF_THRESHOLD", 0.15)
    nms_iou: float = _env_float("NMS_IOU", 0.45)
    detect_every_n: int = _env_int("DETECT_EVERY_N", 2)  # tracker coasts between
    # Confidence tiers used across backend + HUD.
    confirmed_conf: float = 0.75
    likely_conf: float = 0.50
    # Thermal analysis thresholds (Celsius).
    hotspot_temp_c: float = _env_float("HOTSPOT_TEMP_C", 90.0)
    severe_temp_c: float = _env_float("SEVERE_TEMP_C", 250.0)
    critical_temp_c: float = _env_float("CRITICAL_TEMP_C", 450.0)
    body_temp_lo_c: float = 28.0
    body_temp_hi_c: float = 40.0


@dataclass
class TrackerConfig:
    iou_match: float = 0.30
    confirm_hits: int = 3
    max_misses: int = 10
    box_alpha: float = 0.45       # EMA smoothing for boxes
    conf_alpha: float = 0.25      # EMA smoothing for confidence
    dist_alpha: float = 0.30      # EMA smoothing for distance readout
    miss_conf_decay: float = 0.92 # confidence decay per coasted frame


@dataclass
class NavConfig:
    crumb_spacing_m: float = 1.0
    feet_per_meter: float = 3.28084
    # Half-angle of the "path ahead" cone used for hazard-on-route checks.
    route_cone_deg: float = 25.0
    route_hazard_range_m: float = 6.0


@dataclass
class ServerConfig:
    host: str = _env("HOST", "0.0.0.0")
    port: int = _env_int("PORT", 8000)
    telemetry_hz: float = _env_float("TELEMETRY_HZ", 15.0)
    video_hz: float = _env_float("VIDEO_HZ", 15.0)
    jpeg_quality: int = _env_int("JPEG_QUALITY", 70)
    cors_origins: str = _env("CORS_ORIGINS", "*")


@dataclass
class EngineConfig:
    target_fps: float = _env_float("TARGET_FPS", 20.0)
    record_incidents: bool = _env_bool("RECORD", True)


@dataclass
class PyroSightConfig:
    mode: str = _env("MODE", "auto")  # auto | sim | live
    sensors: SensorConfig = field(default_factory=SensorConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    tracker: TrackerConfig = field(default_factory=TrackerConfig)
    nav: NavConfig = field(default_factory=NavConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)
    platform: str = field(default_factory=platform_name)

    def resolved_mode(self) -> str:
        """auto => live on the Pi, sim everywhere else (dev laptops)."""
        if self.mode != "auto":
            return self.mode
        return "live" if self.platform == "raspberry-pi" else "sim"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["resolved_mode"] = self.resolved_mode()
        d["python"] = platform.python_version()
        return d


def load_config() -> PyroSightConfig:
    return PyroSightConfig()
