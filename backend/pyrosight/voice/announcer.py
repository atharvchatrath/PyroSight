"""
Audio-first fallback: in zero-visibility smoke, a HUD is useless — the
firefighter cannot see it and should not be staring at a screen instead of
the room. When active, guidance switches from "read the arrow" to "listen to
the instruction": the current nav instruction is spoken on an interval, and
any new critical alert interrupts immediately. Offline TTS only, consistent
with the platform's no-cloud-calls design principle — same optional-import,
degrade-to-silent pattern as winsound/pyserial elsewhere in the codebase.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List

from ..config import AudioConfig

try:
    import pyttsx3  # type: ignore
    _PYTTSX3_AVAILABLE = True
except ImportError:
    _PYTTSX3_AVAILABLE = False


class AudioAnnouncer:
    def __init__(self, cfg: AudioConfig):
        self.cfg = cfg
        self._engine = None
        self._speak_lock = threading.Lock()
        self._last_instruction_ts = 0.0
        self._last_instruction_text = ""
        self._last_alert_ts: Dict[str, float] = {}
        self.available = False
        if cfg.enabled and _PYTTSX3_AVAILABLE:
            try:
                self._engine = pyttsx3.init()
                self.available = True
            except Exception:  # noqa: BLE001 - no TTS backend on this OS
                self._engine = None

    def _speak_async(self, text: str) -> None:
        if self._engine is None:
            return

        def _run() -> None:
            with self._speak_lock:
                try:
                    self._engine.say(text)
                    self._engine.runAndWait()
                except Exception:  # noqa: BLE001 - TTS backend hiccup
                    pass

        threading.Thread(target=_run, daemon=True).start()

    def update(self, active: bool, instruction: str,
              alerts: List[Dict[str, Any]]) -> None:
        """Call once per engine tick. `active` is the audio-first condition
        (near-zero visibility or emergency)."""
        if not active or not self.available:
            return
        now = time.time()
        for alert in alerts:
            if alert.get("severity") != "critical":
                continue
            rule = alert.get("rule", "")
            if now - self._last_alert_ts.get(rule, 0.0) < self.cfg.alert_cooldown_s:
                continue
            self._last_alert_ts[rule] = now
            self._speak_async(alert["text"])
            self._last_instruction_ts = now  # don't immediately double-speak
            return
        if (now - self._last_instruction_ts >= self.cfg.instruction_interval_s
                and instruction and instruction != self._last_instruction_text):
            self._last_instruction_ts = now
            self._last_instruction_text = instruction
            self._speak_async(instruction)
