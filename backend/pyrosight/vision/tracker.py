"""
Temporal multi-object tracker with confidence dynamics.

Single detections are never trusted directly. Each track accumulates
evidence over frames:

  * greedy per-class IoU association, EMA-smoothed boxes and distance
  * temporal confidence = EMA of detection confidence, with a persistence
    bonus as hits accumulate and exponential decay while coasting
  * display tier derived from temporal confidence:
        confirmed  (>= 0.75)  ->  "PERSON 92%"
        likely     (>= 0.50)  ->  "PERSON 61%"
        possible   (<  0.50)  ->  "POSSIBLE PERSON 38%"
    Communicating uncertainty is a hard product requirement: a low-evidence
    track must *look* uncertain on the HUD, never certain.

Monocular ranging: pinhole model using per-class real-world heights from the
taxonomy. fx scales with frame width (calibrated for the Camera Module 3
wide-ish FOV at 640 px).
"""

from __future__ import annotations

import itertools
import math
from typing import Any, Dict, List, Optional, Tuple

from ..config import TrackerConfig, VisionConfig
from . import classes as taxonomy

RGB_FX_AT_640 = 522.0
FEET_PER_METER = 3.28084


def _iou(a, b) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = ((a[2] - a[0]) * (a[3] - a[1])
             + (b[2] - b[0]) * (b[3] - b[1]) - inter)
    return inter / union if union > 0 else 0.0


def estimate_distance_m(cls_name: str, box, frame_w: int) -> Optional[float]:
    dc = taxonomy.REGISTRY.get(cls_name)
    if dc is None or dc.real_height_m is None:
        return None
    box_h = box[3] - box[1]
    if box_h <= 1:
        return None
    fx = RGB_FX_AT_640 * (frame_w / 640.0)
    return dc.real_height_m * fx / box_h


class Track:
    _ids = itertools.count(1)

    def __init__(self, det: Dict[str, Any], cfg: TrackerConfig, frame_w: int):
        self.id = next(Track._ids)
        self.cls = det["cls"]
        self.cfg = cfg
        self.box = list(det["box"])
        self.conf = float(det["conf"])
        self.hits = 1
        self.misses = 0
        self.age = 1
        self.thermal_confirmed = bool(det.get("thermal_confirmed"))
        self.max_temp_c = det.get("max_temp_c")
        self.severity = det.get("severity")
        self.label_hint = det.get("label_hint", "")
        self.dist_m = estimate_distance_m(self.cls, self.box, frame_w)
        self.vel = [0.0, 0.0, 0.0, 0.0]  # per-frame box-corner velocity
        self._evidence = float(det["conf"])  # decaying max of raw det conf

    def update(self, det: Dict[str, Any], frame_w: int) -> None:
        a = self.cfg.box_alpha
        for i in range(4):
            step = a * (det["box"][i] - self.box[i])
            self.box[i] += step
            # Velocity EMA feeds motion prediction while coasting.
            self.vel[i] = 0.7 * self.vel[i] + 0.3 * step
        self.conf += self.cfg.conf_alpha * (det["conf"] - self.conf)
        # Persistence bonus — but HARD-CEILINGED by the evidence actually
        # seen: track confidence may never exceed the (decaying) best raw
        # detection confidence by more than a whisker. Without this ceiling
        # a sustained 0.38 "possible" would compound its way into a
        # confident alarm, defeating the entire uncertainty design.
        self._evidence = max(float(det["conf"]), self._evidence * 0.92)
        self.conf = min(0.99, self.conf + min(0.10, 0.01 * self.hits))
        self.conf = min(self.conf, self._evidence + 0.08)
        self.hits += 1
        self.age += 1
        self.misses = 0
        if det.get("thermal_confirmed"):
            self.thermal_confirmed = True
        if det.get("max_temp_c") is not None:
            self.max_temp_c = det["max_temp_c"]
        if det.get("severity"):
            self.severity = det["severity"]
        if det.get("label_hint"):
            self.label_hint = det["label_hint"]
        d = estimate_distance_m(self.cls, self.box, frame_w)
        if d is not None:
            if self.dist_m is None:
                self.dist_m = d
            else:
                self.dist_m += self.cfg.dist_alpha * (d - self.dist_m)

    def coast(self) -> None:
        self.misses += 1
        self.age += 1
        self.conf *= self.cfg.miss_conf_decay
        # Constant-velocity prediction (damped): a track on a panning camera
        # keeps sliding toward where the object actually is, so the next
        # detection still associates instead of spawning a duplicate id.
        damp = max(0.0, 1.0 - 0.15 * self.misses)
        for i in range(4):
            self.box[i] += self.vel[i] * damp

    @property
    def confirmed_track(self) -> bool:
        return self.hits >= self.cfg.confirm_hits

    def tier(self, vis: VisionConfig) -> str:
        if self.conf >= vis.confirmed_conf:
            return "confirmed"
        if self.conf >= vis.likely_conf:
            return "likely"
        return "possible"

    def to_dict(self, vis: VisionConfig) -> Dict[str, Any]:
        dc = taxonomy.get(self.cls)
        tier = self.tier(vis)
        display = dc.display if tier != "possible" else f"POSSIBLE {dc.display}"
        return {
            "id": self.id,
            "cls": self.cls,
            "display": display,
            "category": dc.category,
            "priority": dc.priority,
            "color": dc.color,
            "box": [round(v, 1) for v in self.box],
            "conf": round(self.conf, 3),
            "tier": tier,
            "thermal_confirmed": self.thermal_confirmed,
            "max_temp_c": self.max_temp_c,
            "severity": self.severity,
            "dist_ft": round(self.dist_m * FEET_PER_METER, 1)
            if self.dist_m is not None else None,
            "age": self.age,
            "coasting": self.misses > 0,
            "label_hint": self.label_hint,
        }


class TemporalTracker:
    def __init__(self, cfg: TrackerConfig, vis: VisionConfig):
        self.cfg = cfg
        self.vis = vis
        self.tracks: List[Track] = []

    def update(self, detections: List[Dict[str, Any]],
               frame_wh: Tuple[int, int]) -> List[Dict[str, Any]]:
        frame_w = frame_wh[0]
        unmatched = list(range(len(detections)))
        for tr in self.tracks:
            best_iou, best_j = 0.0, -1
            for j in unmatched:
                if detections[j]["cls"] != tr.cls:
                    continue
                iou = _iou(tr.box, detections[j]["box"])
                if iou > best_iou:
                    best_iou, best_j = iou, j
            if best_j >= 0 and best_iou >= self.cfg.iou_match:
                tr.update(detections[best_j], frame_w)
                unmatched.remove(best_j)
            else:
                tr.coast()

        for j in unmatched:
            self.tracks.append(Track(detections[j], self.cfg, frame_w))

        self.tracks = [t for t in self.tracks
                       if t.misses <= self.cfg.max_misses and t.conf > 0.10]

        visible = [t.to_dict(self.vis) for t in self.tracks if t.confirmed_track]
        visible.sort(key=lambda d: (-d["priority"], -d["conf"]))
        return visible

    def count(self, cls_name: str) -> int:
        return sum(1 for t in self.tracks
                   if t.cls == cls_name and t.confirmed_track)
