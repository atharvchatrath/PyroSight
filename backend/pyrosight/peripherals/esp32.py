"""
ESP32 peripheral bridge — LEDs, buzzer, haptic motor, and pack telemetry.

The helmet BOM includes an ESP32 as a secondary microcontroller driving
the physical alert channel: a warning must reach the firefighter even if
the OLED fails or is unreadable in dense smoke. The Pi sends one JSON line
per event over USB serial; the ESP32 firmware maps severity to a pattern:

    {"kind": "alert", "severity": "critical"}   -> red LED + buzzer + strong haptic
    {"kind": "alert", "severity": "warning"}    -> amber LED + short haptic
    {"kind": "alert", "severity": "info"}       -> single green blink
    {"kind": "heartbeat"}                       -> slow green breathing (system alive)

The link is bidirectional. A 20,000 mAh USB-C PD power bank presents no
battery gauge to the Pi — `psutil.sensors_battery()` returns None on Pi OS —
so "how long do I have left" has no answer from the host alone. The ESP32
sits on the 5 V rail and can measure it, so any line it sends upstream is
consumed here:

    {"kind": "battery", "percent": 63}                 -> gauge IC (MAX17048…)
    {"kind": "battery", "volts": 5.03, "amps": 1.82}   -> INA219 shunt
    {"kind": "button", "id": "ack"}                    -> glove-friendly input

Percent is used directly when the firmware has a real gauge. With only
volts/amps, `Diagnostics` coulomb-counts against the configured pack
capacity and labels the result COUNTED, never MEASURED — see
core/diagnostics.py. Absent either, the HUD says NO GAUGE rather than
inventing a number.

Fully optional: without pyserial or with no device attached this is a
silent no-op, and a device unplugged mid-run degrades gracefully.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

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
        self._telemetry: Dict[str, Any] = {}
        self._telemetry_ts = 0.0
        self._reader: Optional[threading.Thread] = None
        self._buttons: List[str] = []
        port = _find_port()
        if port is None:
            return
        try:
            import serial
            self._serial = serial.Serial(port, BAUD, timeout=0.1,
                                         write_timeout=0.2)
            self.port = port
            self._reader = threading.Thread(target=self._read_loop, daemon=True)
            self._reader.start()
        except Exception:  # noqa: BLE001 - device busy/absent: no-op
            self._serial = None

    @property
    def available(self) -> bool:
        return self._serial is not None

    # ------------------------------------------------------------- inbound

    def _read_loop(self) -> None:
        """Consume upstream JSON lines. Never raises into the engine: a noisy
        or half-connected UART must degrade to 'no telemetry', not a crash."""
        while self._serial is not None:
            try:
                raw = self._serial.readline()
            except Exception:  # noqa: BLE001 - unplugged mid-run
                return
            if not raw:
                continue
            try:
                msg = json.loads(raw.decode("utf-8", "ignore").strip())
            except (ValueError, UnicodeDecodeError):
                continue  # partial line or firmware debug print
            if not isinstance(msg, dict):
                continue
            kind = msg.get("kind")
            if kind == "battery":
                self._telemetry = {
                    k: msg[k] for k in ("percent", "volts", "amps", "source")
                    if k in msg
                }
                self._telemetry_ts = time.time()
            elif kind == "button":
                bid = str(msg.get("id", ""))
                if bid:
                    self._buttons.append(bid)
                    del self._buttons[:-8]  # bounded: only recent presses matter

    def battery(self, max_age_s: float = 15.0) -> Optional[Dict[str, Any]]:
        """Latest pack telemetry, or None if stale/absent. Stale data on a
        life-safety readout is worse than no data, so it expires."""
        if not self._telemetry:
            return None
        if time.time() - self._telemetry_ts > max_age_s:
            return None
        return dict(self._telemetry)

    def take_buttons(self) -> List[str]:
        """Drain pending button presses (glove-friendly physical input)."""
        pending, self._buttons = self._buttons, []
        return pending

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
