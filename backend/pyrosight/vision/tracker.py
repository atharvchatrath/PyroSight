"""
Temporal multi-object tracker with confidence dynamics.

Single detections are never trusted directly. Each track accumulates
evidence over frames:

  * greedy per-class IoU association, EMA-smoothed boxes and distance
  * temporal confidence = EMA of detection confidence, with a persistence
    bonus as hits accumulate and exponential decay while coasting
  * display tier derived from temporal confidence:
        confirmed  (>= 0.75)  ->  "HUMAN 92%"
        likely     (>= 0.50)  ->  "HUMAN 61%"
        possible   (<  0.50)  ->  "POSSIBLE HUMAN 38%"
    Communicating uncertainty is a hard product requirement: a low-evidence
    track must *look* uncertain on the HUD, never certain.

Monocular ranging: pinhole model using per-class real-world heights from the
taxonomy. fx scales with frame width (calibrated for the Camera Module 3
wide-ish FOV at 640 px).
"""

from __future__ import annotations

import itertools
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


def _containment(inner, outer) -> float:
    """Fraction of `inner`'s area inside `outer`."""
    ix1, iy1 = max(inner[0], outer[0]), max(inner[1], outer[1])
    ix2, iy2 = min(inner[2], outer[2]), min(inner[3], outer[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area = (inner[2] - inner[0]) * (inner[3] - inner[1])
    return inter / area if area > 0 else 0.0


# A detection mostly inside an existing track's box (or vice versa) is the
# same object with a re-cropped box, not a new one.
NEST_MATCH = 0.70

# Certainty bonuses — see Track.certainty(). Both are gated on independent
# corroboration; neither applies without it.
CORROBORATION_BONUS = 0.12
PERSISTENCE_BONUS = 0.08

# Cross-class track competition (see TemporalTracker._resolve_conflicts).
# Looser than same-class association: two classes fighting over one object
# agree on roughly where it is, rarely on exactly where its edges are.
CONFLICT_IOU = 0.40
CONFLICT_CONTAINMENT = 0.72

# Consecutive missed associations before a track is *stale* — genuinely
# unseen rather than merely between detector passes.
#
# `coasting` (misses > 0) is not that signal and must not be used as one. The
# detector runs every Nth frame by design (vision.detect_every_n), so at the
# default cadence a perfectly healthy track is coasting roughly half the time.
# Treating that as doubt made confirmed detections strobe between "DOOR" and
# "POSSIBLE DOOR" at several hertz — which reads as a system that cannot make
# up its mind, on a display whose entire job is to be decided.
#
# Three misses is about a third of a second of an object not being where the
# tracker predicted it. That is a real occlusion, and worth saying.
STALE_MISSES = 3


# Monocular pinhole ranging is only meaningful over a limited band. A
# partially-visible or occluded object yields a small box, which the model
# turns into a huge distance — reporting "193 FT" inside a corridor is
# fiction dressed as precision. Outside this band we report None (unknown),
# which the HUD renders as "RANGE UNKNOWN" instead of a false number.
MIN_RANGE_M = 0.4
MAX_RANGE_M = 30.0     # ~100 ft: beyond any interior sightline in smoke
MIN_BOX_PX = 12        # smaller than this, box height is mostly noise


def estimate_distance_m(cls_name: str, box, frame_w: int) -> Optional[float]:
    dc = taxonomy.REGISTRY.get(cls_name)
    if dc is None or dc.real_height_m is None:
        return None
    box_h = box[3] - box[1]
    if box_h < MIN_BOX_PX:
        return None
    fx = RGB_FX_AT_640 * (frame_w / 640.0)
    dist = dc.real_height_m * fx / box_h
    if dist < MIN_RANGE_M or dist > MAX_RANGE_M:
        return None
    return dist


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
        self.rgb_corroborated = bool(det.get("rgb_corroborated"))
        self.max_temp_c = det.get("max_temp_c")
        self.severity = det.get("severity")
        self.label_hint = det.get("label_hint", "")
        # Measured stereo depth beats the monocular size assumption whenever
        # it is available (`dist_m_measured` is injected by the engine).
        self.range_measured = det.get("dist_m_measured") is not None
        self.dist_m = (det.get("dist_m_measured")
                       or estimate_distance_m(self.cls, self.box, frame_w))
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
        if det.get("rgb_corroborated"):
            self.rgb_corroborated = True
        if det.get("max_temp_c") is not None:
            self.max_temp_c = det["max_temp_c"]
        if det.get("severity"):
            self.severity = det["severity"]
        if det.get("label_hint"):
            self.label_hint = det["label_hint"]
        measured = det.get("dist_m_measured")
        if measured is not None:
            self.range_measured = True
        d = measured if measured is not None else estimate_distance_m(
            self.cls, self.box, frame_w)
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

    @property
    def corroborated(self) -> bool:
        """A second, independent witness agreed about this object."""
        return self.thermal_confirmed or self.rgb_corroborated

    def certainty(self) -> float:
        """Belief that the CLASS CALL is correct — the operator-facing number.

        `self.conf` is what the detector thinks of this frame's pixels,
        smoothed. It is not the same question. A body at the far end of a
        smoke-filled corridor scores badly on pixels and is still, beyond
        reasonable doubt, a human — because the thermal sensor independently
        found a 34°C mass in the same place and has agreed for two seconds.

        So certainty adds what pixel confidence structurally cannot see:

          * corroboration — a second modality (Lepton body heat, flicker
            analysis, classical egress detection) that can fail in ways the
            detector cannot, agreeing anyway
          * persistence — an unbroken track across a moving camera, which a
            transient artefact does not survive

        The load-bearing rule is the guard clause: with NO independent
        witness, certainty IS conf. Uncorroborated evidence never gets
        promoted no matter how long it persists, which is what stops a
        sustained hallucination from compounding into a confident alarm.
        That property is enforced by test_tracker.py.
        """
        if not self.corroborated:
            return self.conf
        bonus = CORROBORATION_BONUS
        if self.misses < STALE_MISSES:
            mature = (self.hits - 2 * self.cfg.confirm_hits) / 12.0
            bonus += PERSISTENCE_BONUS * max(0.0, min(1.0, mature))
        return min(0.99, self.conf + bonus)

    def tier(self, vis: VisionConfig) -> str:
        certainty = self.certainty()
        if certainty >= vis.confirmed_conf:
            return "confirmed"
        if certainty >= vis.likely_conf:
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
            # The published figure is certainty: it is the one the HUD prints
            # next to the label, and the label must mean what the number says.
            # The detector's own smoothed score stays available as raw_conf
            # for diagnostics and the training overlay.
            "conf": round(self.certainty(), 3),
            "raw_conf": round(self.conf, 3),
            "tier": tier,
            "thermal_confirmed": self.thermal_confirmed,
            "corroborated": self.thermal_confirmed or self.rgb_corroborated,
            "max_temp_c": self.max_temp_c,
            "severity": self.severity,
            "dist_ft": round(self.dist_m * FEET_PER_METER, 1)
            if self.dist_m is not None else None,
            # "stereo" = measured from disparity; "mono" = inferred from
            # assumed object height. The HUD marks the difference so nobody
            # mistakes an assumption for a measurement.
            "range_source": "stereo" if self.range_measured else "mono",
            "age": self.age,
            # `coasting` drives the HUD's motion extrapolation — it wants to
            # know about a single missed frame. `stale` drives what the HUD
            # SAYS, and it must not fire on the detector's normal cadence.
            "coasting": self.misses > 0,
            "stale": self.misses >= STALE_MISSES,
            "misses": self.misses,
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

        # Association is scored across every pair, then assigned best-first.
        # Walking the track list in order let an older track claim a detection
        # that belonged to a nearer one — two victims swap identities, and
        # their labels and distances appear to jump between bodies.
        #
        # Containment sits alongside IoU because a detector routinely tightens
        # from full body to torso between frames: IoU falls under the match
        # threshold, the real track coasts, and a duplicate track opens on the
        # same human.
        pairs = []
        for ti, tr in enumerate(self.tracks):
            for j, det in enumerate(detections):
                if det["cls"] != tr.cls:
                    continue
                iou = _iou(tr.box, det["box"])
                nest = max(_containment(det["box"], tr.box),
                           _containment(tr.box, det["box"]))
                score = max(iou, nest * 0.9 if nest >= NEST_MATCH else 0.0)
                if score >= self.cfg.iou_match:
                    pairs.append((score, ti, j))
        pairs.sort(key=lambda p: -p[0])

        taken_tracks = set()
        taken_dets = set()
        for _score, ti, j in pairs:
            if ti in taken_tracks or j in taken_dets:
                continue
            taken_tracks.add(ti)
            taken_dets.add(j)
            self.tracks[ti].update(detections[j], frame_w)

        for ti, tr in enumerate(self.tracks):
            if ti not in taken_tracks:
                tr.coast()

        # The second half of the hysteresis (see classes.KEEP_RATIO). Every
        # detection that reached here was good enough to SUSTAIN a track, and
        # the loop above has already used them to do exactly that. Opening a
        # NEW track is the stronger claim, so it needs the full floor: a
        # detection flagged `weak` may keep a victim on the display, but it
        # may not invent one.
        for j in range(len(detections)):
            if j in taken_dets or detections[j].get("weak"):
                continue
            self.tracks.append(Track(detections[j], self.cfg, frame_w))

        self.tracks = [t for t in self.tracks
                       if t.misses <= self.cfg.max_misses and t.conf > 0.10]

        visible = [t.to_dict(self.vis) for t in self.tracks if t.confirmed_track]
        visible = self._resolve_conflicts(visible)
        visible.sort(key=lambda d: (-d["priority"], -d["conf"]))
        return visible

    @staticmethod
    def _resolve_conflicts(visible: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """One object, one answer — decided on accumulated evidence.

        detector.resolve_class_conflicts settles this within a single frame,
        but two competing tracks can still both establish themselves over
        time: the detector calls a wall opening a door on odd frames and a
        window on even ones, each wins its own frame, and both tracks mature.
        The HUD then shows a stacked pair and the operator is the one asked to
        decide — which is the whole failure this pass exists to prevent.

        Here the judgement uses temporal evidence rather than one frame's
        pixels, so it is the more reliable of the two passes: whichever track
        has accumulated the stronger corroborated certainty keeps the object.
        Only classes the taxonomy declares mutually exclusive compete.
        """
        ordered = sorted(
            visible,
            key=lambda d: -d["conf"] * taxonomy.CLASS_PRIOR.get(d["cls"], 1.0))
        kept: List[Dict[str, Any]] = []
        for d in ordered:
            beaten = False
            for k in kept:
                if not taxonomy.conflicts(d["cls"], k["cls"]):
                    continue
                if (_iou(d["box"], k["box"]) >= CONFLICT_IOU
                        or _containment(d["box"], k["box"]) >= CONFLICT_CONTAINMENT
                        or _containment(k["box"], d["box"]) >= CONFLICT_CONTAINMENT):
                    beaten = True
                    break
            if not beaten:
                kept.append(d)
        return kept

    def count(self, cls_name: str) -> int:
        return sum(1 for t in self.tracks
                   if t.cls == cls_name and t.confirmed_track)
