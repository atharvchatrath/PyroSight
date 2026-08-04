#!/usr/bin/env python3
"""
PyroSight preflight — verify the helmet unit before an incident.

Checks every subsystem the platform depends on and prints a pass/warn/fail
report with the exact remediation for anything that is not ready. Run it on
the Pi after install, and as part of the pre-shift check:

    sudo -u pyrosight /opt/pyrosight/.venv/bin/python \
        /opt/pyrosight/backend/scripts/preflight.py

Exit status: 0 all good (warnings allowed), 1 if any hard check failed.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
results: list = []


def record(name: str, status: str, detail: str, fix: str = "") -> None:
    results.append((name, status, detail, fix))


def check_platform() -> None:
    from pyrosight.config import platform_name
    p = platform_name()
    if p == "raspberry-pi":
        record("Platform", PASS, "Raspberry Pi hardware")
    else:
        record("Platform", WARN, f"{p} (not a Pi)",
               "Sensors will run simulated; deploy on the Pi for live use.")


def check_python_deps() -> None:
    required = {"cv2": "OpenCV", "numpy": "NumPy", "fastapi": "FastAPI",
                "uvicorn": "Uvicorn", "psutil": "psutil"}
    missing = []
    for mod, label in required.items():
        try:
            __import__(mod)
        except ImportError:
            missing.append(label)
    if missing:
        record("Core dependencies", FAIL, "missing: " + ", ".join(missing),
               "pip install -r backend/requirements.txt")
    else:
        record("Core dependencies", PASS, "all present")


def check_detector() -> None:
    from pyrosight.config import load_config
    from pyrosight.vision.detector import build_detector
    cfg = load_config()
    onnx = Path(cfg.vision.onnx_model)
    det = build_detector(cfg.vision)
    if det.name == "onnx":
        sidecar = onnx.with_suffix(".classes.txt")
        classes = "unknown vocabulary"
        if sidecar.exists():
            names = [n for n in sidecar.read_text().split() if n != "_unused"]
            classes = f"{len(set(names))} classes"
        record("Neural detector", PASS,
               f"ONNX @ {det._input_size}px, {classes}")
    elif det.name == "yolo-world":
        record("Neural detector", WARN, "ultralytics YOLO-World (dev path)",
               "Export ONNX for the Pi: python backend/scripts/export_onnx.py "
               "--model yolov8s-worldv2.pt --imgsz 320")
    else:
        record("Neural detector", FAIL, "none — classical CV only",
               "python backend/scripts/export_onnx.py --model yolov8s-worldv2.pt --imgsz 320")


def check_rgb() -> None:
    from pyrosight.config import load_config
    from pyrosight.sensors.rgb import PiCameraRGB, WebcamRGB
    cfg = load_config().sensors
    cam = PiCameraRGB(cfg.rgb_width, cfg.rgb_height)
    if cam.start():
        frame = cam.read()
        cam.stop()
        if frame is not None:
            record("RGB camera", PASS,
                   f"Pi Camera 3 {frame.shape[1]}x{frame.shape[0]}")
            return
        record("RGB camera", FAIL, "Pi camera opened but produced no frames",
               "Check the CSI ribbon seating and `libcamera-hello`.")
        return
    web = WebcamRGB(cfg.webcam_index, cfg.rgb_width, cfg.rgb_height)
    if web.start():
        frame = web.read()
        web.stop()
        record("RGB camera", WARN,
               f"USB webcam {frame.shape[1]}x{frame.shape[0]}" if frame is not None
               else "USB webcam, no frames",
               "Pi Camera Module 3 not detected — using USB fallback.")
        return
    record("RGB camera", FAIL, "no camera detected",
           "Reseat the CSI ribbon; verify with `libcamera-hello`.")


def check_thermal() -> None:
    from pyrosight.sensors.thermal import LeptonThermal
    lep = LeptonThermal()
    if lep.start():
        temp = None
        for _ in range(10):          # first frames can be empty after open
            temp = lep.read()
            if temp is not None:
                break
            time.sleep(0.1)
        lep.stop()
        if temp is not None:
            record("Thermal camera", PASS,
                   f"Lepton 3.5 {temp.shape[1]}x{temp.shape[0]}, "
                   f"scene {float(temp.min()):.0f}-{float(temp.max()):.0f} C")
            return
        record("Thermal camera", FAIL, "PureThermal opened but no frames",
               "Reseat the Lepton in the socket; try another USB port.")
        return
    record("Thermal camera", FAIL, "no PureThermal/Lepton found",
           "Check USB. Without it the system falls back to an RGB-derived "
           "estimate and will NOT confirm fire or hotspots.")


def check_imu() -> None:
    from pyrosight.sensors.imu import BNO085IMU
    imu = BNO085IMU()
    if imu.start():
        reading = None
        for _ in range(10):
            reading = imu.read()
            if reading is not None:
                break
            time.sleep(0.1)
        imu.stop()
        if reading is not None:
            record("IMU", PASS, f"BNO085, heading {reading['yaw_deg']:.0f} deg")
            return
        record("IMU", FAIL, "BNO085 present but not reporting",
               "Check I2C wiring; `i2cdetect -y 1` should show 0x4a or 0x4b.")
        return
    record("IMU", FAIL, "no BNO085 on I2C",
           "Enable I2C (raspi-config), verify wiring with `i2cdetect -y 1`. "
           "Heading falls back to visual odometry (drifts).")


def check_voice() -> None:
    from pyrosight.voice.listener import VOSK_MODEL_DIR, VoskListener
    if not VOSK_MODEL_DIR.exists():
        record("Offline voice", WARN, "Vosk model not installed",
               "Re-run deploy/install-pi.sh, or download vosk-model-small-en-us "
               "to backend/models/vosk. Dashboard commands still work.")
        return
    listener = VoskListener(lambda _t: None)
    if listener.available:
        record("Offline voice", PASS, "Vosk model loaded")
    else:
        record("Offline voice", WARN, "model present but engine unavailable",
               "pip install vosk sounddevice")


def check_stereo() -> None:
    """Waveshare Dual IMX219: both CSI ports, plus whether it is calibrated.

    Uncalibrated stereo still ranges, but off datasheet geometry — the number
    on the HUD is then approximate in a way the firefighter cannot see.
    """
    from pyrosight.config import load_config
    from pyrosight.sensors.stereo import CALIB_PATH, StereoRGB
    cfg = load_config().sensors
    cam = StereoRGB(cfg.rgb_width, cfg.rgb_height)
    if not cam.start():
        record("Stereo pair", WARN, "no dual IMX219 detected",
               "Single-camera builds range monocularly (assumed object size). "
               "For measured range fit the Waveshare dual module to cam0+cam1.")
        return
    frame = cam.read()
    cam.stop()
    if frame is None:
        record("Stereo pair", FAIL, "stereo opened but produced no frames",
               "Reseat both CSI ribbons; check `rpicam-hello --camera 1`.")
        return
    if CALIB_PATH.exists():
        record("Stereo pair", PASS,
               f"dual IMX219 {frame.shape[1]}x{frame.shape[0]}, calibrated")
    else:
        record("Stereo pair", WARN,
               f"dual IMX219 {frame.shape[1]}x{frame.shape[0]}, UNCALIBRATED",
               "Run scripts/calibrate_stereo.py — until then range comes from "
               "datasheet geometry, not measurement.")


def check_peripherals() -> None:
    from pyrosight.peripherals.esp32 import Esp32Peripherals
    esp = Esp32Peripherals()
    if not esp.available:
        record("Alert peripherals", WARN, "no ESP32 serial device",
               "LEDs/buzzer/haptic unavailable. Set PYROSIGHT_ESP32_PORT if the "
               "board is on a non-standard port.")
        record("Pack telemetry", WARN, "no ESP32 — battery state unavailable",
               "A USB-C PD bank exposes no gauge to the Pi; without the ESP32 "
               "reporting it the HUD shows NO GAUGE and cannot warn on low charge.")
        return

    esp.notify_alert("info")         # visible/audible confirmation on the rig
    record("Alert peripherals", PASS,
           f"ESP32 on {getattr(esp, 'port', 'serial')} (test pulse sent)")

    # Give the firmware a moment to push a battery line before judging it.
    pack = None
    deadline = time.time() + 3.0
    while time.time() < deadline and pack is None:
        pack = esp.battery()
        time.sleep(0.2)
    esp.close()
    if pack is None:
        record("Pack telemetry", WARN, "ESP32 present but sending no battery lines",
               'Firmware should emit {"kind":"battery","percent":N} (fuel gauge) '
               'or {"kind":"battery","volts":V,"amps":A} (INA219 shunt).')
    elif "percent" in pack:
        record("Pack telemetry", PASS, f"fuel gauge {float(pack['percent']):.0f}%")
    else:
        record("Pack telemetry", PASS,
               f"shunt {pack.get('volts', '?')} V / {pack.get('amps', '?')} A "
               "(coulomb-counted, shown as approximate)")


def check_hud_display() -> None:
    """The monocular micro-OLED: attached, at its native mode, and scaled.

    A 1920x1080 panel 0.39" across renders desktop-density UI at roughly
    0.15 mm per character. The kiosk must scale it or the HUD is unreadable
    in the helmet even though it looks perfect over VNC.
    """
    scale = os.environ.get("PYROSIGHT_HUD_SCALE", "1.75")
    modes = pathlib.Path("/sys/class/drm")
    connected = []
    if modes.exists():
        for card in modes.glob("card*-*"):
            try:
                if (card / "status").read_text().strip() == "connected":
                    mode = (card / "modes").read_text().splitlines()
                    connected.append(f"{card.name.split('-', 1)[1]} "
                                     f"{mode[0] if mode else 'mode?'}")
            except OSError:
                continue
    if not connected:
        record("HUD display", WARN, "no connected display detected",
               "Plug the micro-OLED into micro-HDMI and set its native mode in "
               "/boot/firmware/config.txt.")
    else:
        record("HUD display", PASS,
               f"{', '.join(connected)} · UI scale {scale}x")


def check_storage() -> None:
    from pyrosight.config import DATA_DIR
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(DATA_DIR)
    free_gb = usage.free / 1e9
    pct = usage.used / usage.total * 100
    if free_gb < 1.0:
        record("Storage", FAIL, f"{free_gb:.1f} GB free ({pct:.0f}% used)",
               "Incident recording will fail. Free space or swap the card.")
    elif free_gb < 4.0:
        record("Storage", WARN, f"{free_gb:.1f} GB free ({pct:.0f}% used)",
               "Archive old incidents from backend/data/incidents.")
    else:
        record("Storage", PASS, f"{free_gb:.1f} GB free ({pct:.0f}% used)")


def check_thermals_and_power() -> None:
    from pyrosight.core.diagnostics import Diagnostics
    diag = Diagnostics().sample(0.0, 0.0, {}, sim_mode=False)
    temp = diag.get("cpu_temp_c")
    if temp is None:
        record("CPU temperature", WARN, "not readable on this platform")
    elif temp > 80:
        record("CPU temperature", FAIL, f"{temp:.0f} C",
               "Throttling imminent — verify the active cooler is running.")
    elif temp > 70:
        record("CPU temperature", WARN, f"{temp:.0f} C",
               "Warm; confirm airflow before a long deployment.")
    else:
        record("CPU temperature", PASS, f"{temp:.0f} C")

    batt = diag.get("battery_percent")
    if batt is None:
        record("Battery", WARN, "no battery telemetry",
               "USB-C PD packs rarely report state; monitor runtime manually.")
    elif batt < 40:
        record("Battery", WARN, f"{batt:.0f}%", "Charge before deployment.")
    else:
        record("Battery", PASS, f"{batt:.0f}%")


def main() -> int:
    print("=" * 68)
    print(" PyroSight preflight")
    print("=" * 68)
    checks = [
        check_platform, check_python_deps, check_detector, check_rgb,
        check_thermal, check_stereo, check_imu, check_voice,
        check_peripherals, check_hud_display, check_storage,
        check_thermals_and_power,
    ]
    for fn in checks:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - a broken check is a warning
            record(fn.__name__.replace("check_", "").title(), WARN,
                   f"check error: {type(exc).__name__}: {exc}")

    width = max(len(name) for name, _, _, _ in results)
    fails = warns = 0
    for name, status, detail, fix in results:
        print(f"  [{status}] {name.ljust(width)}  {detail}")
        if fix:
            print(f"         {' ' * width}  -> {fix}")
        fails += status == FAIL
        warns += status == WARN

    print("-" * 68)
    print(f" {len(results) - fails - warns} pass, {warns} warn, {fails} fail")
    if fails:
        print(" NOT READY — resolve the failures above before deployment.")
    elif warns:
        print(" OPERATIONAL WITH LIMITATIONS — review the warnings above.")
    else:
        print(" ALL SYSTEMS READY.")
    print("=" * 68)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
