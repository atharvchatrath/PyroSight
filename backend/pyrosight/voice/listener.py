"""
Offline speech-to-text listener (Vosk small model).

Fully offline: audio never leaves the device. Runs only when both the
`vosk` + `sounddevice` packages are installed AND a model directory exists
at backend/models/vosk (see docs/DEPLOYMENT.md for the 40 MB small-model
download). Recognized phrases go through the same deterministic grammar as
typed/dashboard commands.

On the helmet unit this is the primary voice path; on dev machines it is
simply absent and the dashboard mic/text input covers testing.
"""

from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from typing import Callable, Optional

from ..config import MODELS_DIR

VOSK_MODEL_DIR = MODELS_DIR / "vosk"
SAMPLE_RATE = 16000

# Constrain recognition to our command vocabulary — dramatically improves
# accuracy over SCBA breathing noise compared to open dictation.
VOCAB = [
    "find", "exit", "locate", "victim", "person", "show", "thermal",
    "camera", "visual", "highlight", "doors", "door", "repeat", "last",
    "alert", "return", "entry", "mark", "back", "status", "report",
    "stand", "down", "clear", "way", "out",
    "hide", "labels", "label", "increase", "lower", "brightness",
    "brighter", "dimmer", "dim", "emergency", "mode", "mayday", "cancel",
    "search", "room", "guided", "[unk]",
]


class VoskListener:
    def __init__(self, on_text: Callable[[str], object]):
        self._on_text = on_text
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._model = None
        self._sd = None
        if not VOSK_MODEL_DIR.exists():
            return
        try:
            import sounddevice as sd
            import vosk
        except ImportError:
            return
        try:
            vosk.SetLogLevel(-1)
            self._model = vosk.Model(str(VOSK_MODEL_DIR))
            self._vosk = vosk
            self._sd = sd
        except Exception:  # noqa: BLE001
            self._model = None

    @property
    def available(self) -> bool:
        return self._model is not None

    def start(self) -> None:
        if not self.available:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="pyrosight-voice")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        rec = self._vosk.KaldiRecognizer(self._model, SAMPLE_RATE,
                                         json.dumps(VOCAB))
        audio_q: "queue.Queue[bytes]" = queue.Queue(maxsize=32)

        def callback(indata, frames, t, status) -> None:  # noqa: ANN001
            try:
                audio_q.put_nowait(bytes(indata))
            except queue.Full:
                pass  # drop rather than lag behind real time

        try:
            with self._sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=4000,
                                         dtype="int16", channels=1,
                                         callback=callback):
                while self._running:
                    try:
                        chunk = audio_q.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    if rec.AcceptWaveform(chunk):
                        text = json.loads(rec.Result()).get("text", "").strip()
                        if text:
                            self._on_text(text)
        except Exception:  # noqa: BLE001 - no mic / device busy: silent no-op
            return
