"""
Detection taxonomy shared by every detector backend, the tracker, the HUD,
and the dashboard. One place to add a class; everything downstream keys off
this registry.

Naming is operational, not academic. A firefighter is not looking for a
"person" instance — they are looking for a HUMAN, a DOOR, a WINDOW they can
go out of, or a FIRE. The display strings say exactly that, and the evidence
policy below exists so the system can say them without hedging when the
evidence is actually there.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional, Tuple


@dataclass(frozen=True)
class DetectionClass:
    name: str
    display: str
    category: str          # person | egress | hazard | structure
    priority: int          # higher = more important on a cluttered HUD
    real_height_m: Optional[float]  # for monocular pinhole ranging
    color: str             # hex, used by both HUD and dashboard


# Palette is the warm ramp defined in frontend/lib/design.ts: a human is the
# brightest mark on the display, hazards run red-orange, egress runs amber.
REGISTRY: Dict[str, DetectionClass] = {c.name: c for c in [
    DetectionClass("person",      "HUMAN",       "person",    10, 1.65, "#ffffff"),
    DetectionClass("firefighter", "FIREFIGHTER", "person",     9, 1.80, "#ffd9a8"),
    DetectionClass("door",        "DOOR",        "egress",     7, 2.00, "#ff8a1f"),
    DetectionClass("exit_sign",   "EXIT SIGN",   "egress",     8, 0.30, "#ffc24b"),
    # A window is an exit. Fire service practice treats it as secondary
    # egress, guidance already routes to it (navigation/guidance.py), and the
    # label says so rather than making the operator make that leap at 2am in
    # zero visibility.
    DetectionClass("window",      "WINDOW EXIT", "egress",     7, 1.20, "#ffc24b"),
    DetectionClass("stairs",      "STAIRS",      "structure",  6, 3.00, "#e08a3c"),
    DetectionClass("hallway",     "HALLWAY",     "structure",  3, 2.60, "#9a7358"),
    DetectionClass("fire",        "FIRE",        "hazard",    10, None, "#ff3b0f"),
    DetectionClass("hotspot",     "HOTSPOT",     "hazard",     8, None, "#ff6a00"),
    DetectionClass("floor_hazard","FLOOR HAZARD","hazard",     9, None, "#ff9e1b"),
]}

# Sentinel class for open-vocabulary decoys — see DECOY_PROMPTS. Never enters
# the registry, so nothing downstream can render or track it.
DECOY = "_decoy"

# ------------------------------------------------------- custom training
#
# The classes a custom RGB model is trained on, IN MODEL INDEX ORDER.
#
# This tuple is the contract between three files that must never disagree:
# the dataset's data.yaml (written from it), the exported model's class
# indices, and the .classes.txt sidecar the ONNX detector reads to map those
# indices back to taxonomy names. If the order drifts between any two of
# them, the detector silently relabels everything — doors become people —
# and nothing raises an error. So all three are generated from here, and
# test_training_pipeline.py asserts they agree.
#
# hotspot and floor_hazard are deliberately absent: they are derived from
# thermal and depth, not from RGB pixels, so there is nothing to label.
TRAINABLE_CLASSES: Tuple[str, ...] = (
    "person",
    "firefighter",
    "door",
    "exit_sign",
    "window",
    "stairs",
    "hallway",
    "fire",
)

# Open-vocabulary prompts for YOLO-World. Several phrasings per class —
# open-vocab recall depends heavily on prompt wording, and a crawling victim
# is not matched well by the bare word "person".
WORLD_PROMPT_TO_CLASS: Dict[str, str] = {
    "person": "person",
    "person lying on the floor": "person",
    "person crawling": "person",
    "person sitting slumped against a wall": "person",
    "human body": "person",
    "firefighter wearing helmet and gear": "firefighter",
    "door": "door",
    "open doorway": "door",
    "closed wooden door": "door",
    "door with handle": "door",
    "exit sign": "exit_sign",
    "green exit sign": "exit_sign",
    "illuminated emergency exit sign": "exit_sign",
    "window": "window",
    "glass window": "window",
    "window with daylight": "window",
    "staircase": "stairs",
    "stairs": "stairs",
    "hallway corridor": "hallway",
    "fire flames": "fire",
    "burning fire": "fire",
    "flame": "fire",
    "open flame burning": "fire",
}

# Decoy prompts: the things an open-vocabulary model mistakes for a human or
# a flame. Giving the model a BETTER-FITTING label for them is far more
# effective than raising the person threshold — the score moves off "person"
# onto the decoy, and the decoy is discarded. Raising a threshold only trades
# those false positives for missed real victims.
#
# This complements vision/spoof.py, which catches the framed-picture case
# geometrically. Between them: the model declines to call it a person, and if
# it does anyway, the frame test rejects it.
DECOY_PROMPTS: Dict[str, str] = {
    "photograph of a person": DECOY,
    "poster of a person": DECOY,
    "painting of a person": DECOY,
    "mannequin": DECOY,
    "statue of a person": DECOY,
    "television screen showing people": DECOY,
    "computer monitor": DECOY,
    "reflection in a mirror": DECOY,
    "orange traffic cone": DECOY,
    "high visibility safety jacket": DECOY,
    "warm ceiling light": DECOY,
}

WORLD_PROMPT_TO_CLASS.update(DECOY_PROMPTS)
WORLD_PROMPTS: List[str] = list(WORLD_PROMPT_TO_CLASS.keys())

# Per-class confidence floors applied after detection. Open-vocabulary scores
# are not calibrated across prompts: exit signs legitimately score lower than
# persons, and a single global threshold either floods the HUD or goes blind.
CLASS_CONF_THRESHOLDS: Dict[str, float] = {
    # Persons carry the highest bar in the taxonomy. A weak "person" is the
    # most expensive false positive the platform can make — it sends a crew
    # to a poster — and the classes that matter for finding a real victim
    # (body heat, motion, persistence) are corroborated downstream in
    # fusion.py and spoof.py rather than by lowering this floor.
    "person": 0.60,
    "firefighter": 0.55,
    "door": 0.25,
    "exit_sign": 0.18,
    "window": 0.22,   # indoor windows score low in open-vocab models
    "stairs": 0.28,
    "hallway": 0.40,
    "fire": 0.28,
}

# ---------------------------------------------------------------- hysteresis
#
# The floors above are the bar to START believing in something. They are NOT
# the bar to KEEP believing in it, and using one number for both is what makes
# a detector flicker.
#
# Confidence on a real object is noisy: a person at moderate range through a
# webcam wanders across roughly 0.50-0.70 frame to frame. With a single 0.60
# gate, every dip below it deletes the detection outright — before the tracker
# ever sees it — and the label blinks in and out several times a second on an
# object that never moved. Raising the gate loses distant victims; lowering it
# floods the HUD. Neither fixes the flicker, because the flicker is not caused
# by the threshold's height. It is caused by there being only one of them.
#
# So: a detection must clear the full floor to OPEN a track, and only this
# lower fraction of it to SUSTAIN one that is already open. Evidence good
# enough to have convinced us a moment ago stays good enough while it decays.
# Same principle as a Schmitt trigger, and as track maintenance in radar.
#
# The asymmetry is also the safe direction. It is harder to invent a victim
# (full bar, every time) and easier to keep one you already found (reduced
# bar) — which is the behaviour you want from something whose job is to not
# lose people.
KEEP_RATIO = 0.62


def enter_threshold(cls_name: str) -> float:
    """Confidence needed to open a NEW track for this class."""
    return CLASS_CONF_THRESHOLDS.get(cls_name, 0.30)


def keep_threshold(cls_name: str) -> float:
    """Confidence needed to sustain a track that already exists."""
    return enter_threshold(cls_name) * KEEP_RATIO


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

# ----------------------------------------------------------------- conflicts
#
# Two boxes on the same pixels cannot both be right when their classes are
# mutually exclusive. One rectangle in a wall is a door OR a window OR an exit
# sign — never two of them — and a shape is a human OR a decoy. Per-class NMS
# cannot see this (it only ever compares like with like), so a wall opening
# routinely reached the HUD as a stacked "DOOR 46% / WINDOW 41%" pair, which
# is precisely the ambiguity an operator cannot act on.
#
# Groups are mutually exclusive sets. Members of the same group competing for
# the same pixels are resolved to one winner; classes in different groups
# (a human standing in a doorway, fire seen through a window) never compete.
CONFLICT_GROUPS: Tuple[FrozenSet[str], ...] = (
    frozenset({"door", "window", "exit_sign", "hallway"}),
    frozenset({"person", "firefighter"}),
    frozenset({"fire", "hotspot"}),
)

# Tie-break weight when two conflicting classes score alike. This encodes
# consequence, not likelihood: calling a door a window costs a firefighter a
# wasted approach, calling a human anything else can cost a life.
CLASS_PRIOR: Dict[str, float] = {
    "person": 1.30,
    "firefighter": 1.20,
    "fire": 1.25,
    "exit_sign": 1.15,   # an engineered, unambiguous target
    "door": 1.05,
    "window": 1.00,
    "stairs": 1.00,
    "hotspot": 1.00,
    "floor_hazard": 1.10,
    "hallway": 0.70,     # the weakest claim in the taxonomy; loses most ties
}


def conflict_group(name: str) -> Optional[FrozenSet[str]]:
    """The mutually-exclusive set `name` belongs to, if any."""
    for group in CONFLICT_GROUPS:
        if name in group:
            return group
    return None


def conflicts(a: str, b: str) -> bool:
    """True when two classes cannot both describe the same pixels."""
    if a == b:
        return False
    group = conflict_group(a)
    return group is not None and b in group


# COCO index mapping used by plain YOLOv8 ONNX exports (only classes we care
# about; a generic COCO model can still supply person detections).
COCO_TO_CLASS: Dict[int, str] = {0: "person"}


def get(name: str) -> DetectionClass:
    return REGISTRY[name]


def known(name: str) -> bool:
    return name in REGISTRY
