"""
Offline voice-command grammar.

Speech-to-text is pluggable (Vosk small-model on the Pi; the HUD/dashboard
can also submit typed or browser-transcribed text). This module is the
grammar layer both paths share: fuzzy token matching against a fixed intent
set — no network, no LLM, deterministic under stress.

    match("uh find the exit")   -> intent FIND_EXIT
    match("where's the victim") -> intent LOCATE_VICTIM
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

FILLER = {"uh", "um", "the", "a", "an", "please", "hey", "pyrosight",
          "to", "me", "my", "for", "of", "on", "in", "is", "wheres", "where"}

# intent -> list of keyword sets; a phrase matches if any set is fully
# covered by the spoken tokens (after filler removal + light stemming).
GRAMMAR: Dict[str, List[Tuple[str, ...]]] = {
    "FIND_EXIT": [("find", "exit"), ("exit",), ("egress",), ("way", "out"),
                  ("get", "out")],
    "LOCATE_VICTIM": [("locate", "victim"), ("victim",), ("find", "person"),
                      ("survivor",), ("casualty",)],
    "RETURN_TO_ENTRY": [("return", "entry"), ("go", "back"), ("retreat",),
                        ("take", "back"), ("entry",)],
    "MARK_ENTRY": [("mark", "entry"), ("mark", "point")],
    "SHOW_THERMAL": [("show", "thermal"), ("thermal",), ("heat", "view")],
    "SHOW_RGB": [("show", "camera"), ("normal", "view"), ("rgb",),
                 ("visual",)],
    "HIGHLIGHT_DOORS": [("highlight", "door"), ("door",), ("show", "door")],
    "REPEAT_ALERT": [("repeat", "alert"), ("repeat",), ("last", "alert"),
                     ("say", "again")],
    "CLEAR_OBJECTIVE": [("clear",), ("cancel",), ("stand", "down"),
                        ("explore",)],
    "STATUS": [("status",), ("report",), ("sitrep",)],
}

ACKS: Dict[str, str] = {
    "FIND_EXIT": "OBJECTIVE: FIND EXIT",
    "LOCATE_VICTIM": "OBJECTIVE: LOCATE VICTIM",
    "RETURN_TO_ENTRY": "OBJECTIVE: RETURN TO ENTRY",
    "MARK_ENTRY": "ENTRY POINT MARKED",
    "SHOW_THERMAL": "THERMAL VIEW ON",
    "SHOW_RGB": "VISUAL VIEW ON",
    "HIGHLIGHT_DOORS": "DOOR HIGHLIGHT ON",
    "REPEAT_ALERT": "REPEATING LAST ALERT",
    "CLEAR_OBJECTIVE": "OBJECTIVE CLEARED",
    "STATUS": "STATUS REPORT",
}


def _stem(token: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)]
    return token


def _tokens(text: str) -> List[str]:
    words = re.findall(r"[a-z]+", text.lower())
    return [_stem(w) for w in words if w not in FILLER]


def match(text: str) -> Optional[Dict[str, Any]]:
    spoken = set(_tokens(text))
    if not spoken:
        return None
    best: Optional[Tuple[int, str]] = None  # (specificity, intent)
    for intent, phrase_sets in GRAMMAR.items():
        for phrase in phrase_sets:
            needed = {_stem(w) for w in phrase}
            if needed.issubset(spoken):
                key = (len(needed), intent)
                if best is None or key[0] > best[0]:
                    best = key
    if best is None:
        return None
    intent = best[1]
    return {"intent": intent, "ack": ACKS[intent], "transcript": text}


def available_commands() -> List[Dict[str, str]]:
    examples = {
        "FIND_EXIT": "find exit",
        "LOCATE_VICTIM": "locate victim",
        "RETURN_TO_ENTRY": "return to entry",
        "MARK_ENTRY": "mark entry",
        "SHOW_THERMAL": "show thermal",
        "SHOW_RGB": "show camera",
        "HIGHLIGHT_DOORS": "highlight doors",
        "REPEAT_ALERT": "repeat last alert",
        "CLEAR_OBJECTIVE": "stand down",
        "STATUS": "status",
    }
    return [{"intent": k, "example": v} for k, v in examples.items()]
