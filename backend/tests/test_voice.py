"""Offline voice-command grammar."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pyrosight.voice.commands import available_commands, match


def test_core_commands():
    assert match("find exit")["intent"] == "FIND_EXIT"
    assert match("locate victim")["intent"] == "LOCATE_VICTIM"
    assert match("show thermal")["intent"] == "SHOW_THERMAL"
    assert match("highlight doors")["intent"] == "HIGHLIGHT_DOORS"
    assert match("repeat last alert")["intent"] == "REPEAT_ALERT"


def test_noisy_speech():
    assert match("uh hey pyrosight find me the exit")["intent"] == "FIND_EXIT"
    assert match("where's the victim")["intent"] == "LOCATE_VICTIM"
    assert match("take me back")["intent"] == "RETURN_TO_ENTRY"
    assert match("way out")["intent"] == "FIND_EXIT"


def test_specificity_wins():
    # "mark entry" must beat plain RETURN_TO_ENTRY's ("entry",) single word.
    assert match("mark entry")["intent"] == "MARK_ENTRY"
    assert match("repeat that alert")["intent"] == "REPEAT_ALERT"


def test_unrecognized_and_catalog():
    assert match("make me a sandwich") is None
    assert match("") is None
    intents = {c["intent"] for c in available_commands()}
    assert "FIND_EXIT" in intents and len(intents) == 10
