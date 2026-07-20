"""
ESP32 peripheral bridge — LEDs, buzzer, haptic motor.

The helmet BOM includes an ESP32 as a secondary microcontroller driving
the physical alert channel: a warning must reach the firefighter even if
the OLED fails or is unreadable in dense smoke. The Pi sends one JSON line
per event over USB serial; the ESP32 firmware maps severity to a pattern:

    {"kind": "alert", "severity": "critical"}   -> red LED + buzzer + strong haptic
    {"kind": "alert", "severity": "warning"}    -> amber LED + short haptic
    {"kind": "alert", "severity": "info"}       -> single green blink
    {"kind": "heartbeat"}                       -> slow green breathing (system alive)

Fully optional: without pyserial or with no device attached this is a
silent no-op, and a device unplugged mid-run degrades gracefully.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, Optional

BAUD = 115200
HEARTBEAT_S = 2.0


def _find_port() -> Optional[str]:
    """PYROSIGHT_ESP32_PORT wins; otherwise scan for a likely USB-UART."""
    env = os.environ.get("PYROSIGHT_ESP32_PORT")
    if env:
        return env
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    for p in list_ports.comports():
        desc = f"{p.description} {p.manufacturer or ''}".lower()
        if any(tag in desc for tag in ("cp210", "ch340", "esp32", "usb serial",
                                       "silicon labs", "uart")):
            return p.device
    return None


class Esp32Peripherals:
    def __init__(self):
        self._serial = None
        self._lock = threading.Lock()
        self._last_heartbeat = 0.0
        port = _find_port()
        if port is None:
            return
        try:
            import serial
            self._serial = serial.Serial(port, BAUD, timeout=0.1,
                                         write_timeout=0.2)
            self.port = port
        except Exception:  # noqa: BLE001 - device busy/absent: no-op
            self._serial = None

    @property
    def available(self) -> bool:
        return self._serial is not None

    def _send(self, payload: Dict[str, Any]) -> None:
        if self._serial is None:
            return
        line = (json.dumps(payload) + "\n").encode()
        with self._lock:
            try:
                self._serial.write(line)
            except Exception:  # noqa: BLE001 - unplugged mid-run
                try:
                    self._serial.close()
                finally:
                    self._serial = None

    def notify_alert(self, severity: str) -> None:
        self._send({"kind": "alert", "severity": severity})

    def heartbeat(self) -> None:
        now = time.time()
        if now - self._last_heartbeat >= HEARTBEAT_S:
            self._last_heartbeat = now
            self._send({"kind": "heartbeat"})

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            finally:
                self._serial = None
