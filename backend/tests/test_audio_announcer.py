"""Audio-first fallback: gating logic for offline TTS guidance.

Runs without a real TTS backend by exercising the announcer's timing/
cooldown logic directly and capturing what _speak_async would have said,
since pyttsx3 (and a working audio device) are not guaranteed to be present
in a test environment.
"""

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pyrosight.config import AudioConfig
from pyrosight.voice.announcer import AudioAnnouncer


def _wired_announcer(cfg=None):
    ann = AudioAnnouncer(cfg or AudioConfig(instruction_interval_s=1000.0,
                                            alert_cooldown_s=1000.0))
    ann.available = True  # force-enable regardless of pyttsx3 availability
    said = []
    ann._speak_async = said.append  # type: ignore[method-assign]
    return ann, said


def test_inactive_never_speaks():
    ann, said = _wired_announcer()
    ann.update(active=False, instruction="EXIT: AHEAD 10 FT", alerts=[])
    assert said == []


def test_unavailable_never_speaks():
    ann, said = _wired_announcer()
    ann.available = False
    ann.update(active=True, instruction="EXIT: AHEAD 10 FT", alerts=[])
    assert said == []


def test_active_speaks_instruction_first_time():
    ann, said = _wired_announcer()
    ann.update(active=True, instruction="EXIT: AHEAD 10 FT", alerts=[])
    assert said == ["EXIT: AHEAD 10 FT"]


def test_repeated_identical_instruction_not_spammed():
    ann, said = _wired_announcer()
    ann.update(active=True, instruction="EXIT: AHEAD 10 FT", alerts=[])
    ann.update(active=True, instruction="EXIT: AHEAD 10 FT", alerts=[])
    assert said == ["EXIT: AHEAD 10 FT"]


def test_critical_alert_preempts_instruction():
    ann, said = _wired_announcer()
    alert = {"rule": "fire_detected", "severity": "critical", "text": "FIRE 90%"}
    ann.update(active=True, instruction="EXIT: AHEAD 10 FT", alerts=[alert])
    assert said == ["FIRE 90%"]


def test_non_critical_alert_does_not_preempt():
    ann, said = _wired_announcer()
    alert = {"rule": "victim_detected", "severity": "info", "text": "VICTIM DETECTED"}
    ann.update(active=True, instruction="EXIT: AHEAD 10 FT", alerts=[alert])
    assert said == ["EXIT: AHEAD 10 FT"]


def test_instruction_repeats_after_interval_elapses():
    cfg = AudioConfig(instruction_interval_s=0.05, alert_cooldown_s=1000.0)
    ann, said = _wired_announcer(cfg)
    ann.update(active=True, instruction="EXIT: AHEAD 10 FT", alerts=[])
    time.sleep(0.08)
    ann.update(active=True, instruction="EXIT: AHEAD 5 FT", alerts=[])
    assert said == ["EXIT: AHEAD 10 FT", "EXIT: AHEAD 5 FT"]
