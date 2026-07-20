"""
Detection taxonomy shared by every detector backend, the tracker, the HUD,
and the dashboard. One place to add a class; everything downstream keys off
this registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class DetectionClass:
    name: str
    display: str
    category: str          # person | egress | hazard | structure
    priority: int          # higher = more important on a cluttered HUD
    real_height_m: Optional[float]  # for monocular pinhole ranging
    color: str             # hex, used by both HUD and dashboard


REGISTRY: Dict[str, DetectionClass] = {c.name: c for c in [
    DetectionClass("person",      "PERSON",      "person",    10, 1.65, "#22d3ee"),
    DetectionClass("firefighter", "FIREFIGHTER", "person",     9, 1.80, "#facc15"),
    DetectionClass("door",        "DOOR",        "egress",     7, 2.00, "#4ade80"),
    DetectionClass("exit_sign",   "EXIT SIGN",   "egress",     8, 0.30, "#34d399"),
    DetectionClass("window",      "WINDOW",      "egress",     6, 1.20, "#818cf8"),
    DetectionClass("stairs",      "STAIRS",      "structure",  6, 3.00, "#a78bfa"),
    DetectionClass("hallway",     "HALLWAY",     "structure",  3, 2.60, "#94a3b8"),
    DetectionClass("fire",        "FIRE",        "hazard",    10, None, "#f87171"),
    DetectionClass("hotspot",     "HOTSPOT",     "hazard",     8, None, "#fb923c"),
]}

# Open-vocabulary prompts for YOLO-World. Several phrasings per class —
# open-vocab recall depends heavily on prompt wording, and a crawling victim
# is not matched well by the bare word "person".
WORLD_PROMPT_TO_CLASS: Dict[str, str] = {
    "person": "person",
    "person lying on the floor": "person",
    "person crawling": "person",
    "firefighter wearing helmet and gear": "firefighter",
    "door": "door",
    "open doorway": "door",
    "closed wooden door": "door",
    "exit sign": "exit_sign",
    "green exit sign": "exit_sign",
    "window": "window",
    "glass window": "window",
    "window with daylight": "window",
    "staircase": "stairs",
    "stairs": "stairs",
    "hallway corridor": "hallway",
    "fire flames": "fire",
    "burning fire": "fire",
    "flame": "fire",
}
WORLD_PROMPTS: List[str] = list(WORLD_PROMPT_TO_CLASS.keys())

# Per-class confidence floors applied after detection. Open-vocabulary scores
# are not calibrated across prompts: exit signs legitimately score lower than
# persons, and a single global threshold either floods the HUD or goes blind.
CLASS_CONF_THRESHOLDS: Dict[str, float] = {
    "person": 0.35,
    "firefighter": 0.35,
    "door": 0.25,
    "exit_sign": 0.18,
    "window": 0.22,   # indoor windows score low in open-vocab models
    "stairs": 0.28,
    "hallway": 0.40,
    "fire": 0.28,
}

# Geometry sanity gates: (min area fraction of frame, min h/w, max h/w).
# None disables a bound. Kills the classic open-vocab failure mode of a
# frame-wide "door" or a 4-pixel "person".
CLASS_GEOMETRY: Dict[str, tuple] = {
    "person": (0.0006, None, None),
    "firefighter": (0.0006, None, None),
    "door": (0.001, 1.1, None),
    "exit_sign": (0.0002, None, 1.4),
    "window": (0.001, None, None),
    "stairs": (0.002, None, None),
    "hallway": (0.02, None, None),
    "fire": (0.0008, None, None),
}

# COCO index mapping used by plain YOLOv8 ONNX exports (only classes we care
# about; a generic COCO model can still supply person detections).
COCO_TO_CLASS: Dict[int, str] = {0: "person"}


def get(name: str) -> DetectionClass:
    return REGISTRY[name]


def known(name: str) -> bool:
    return name in REGISTRY
