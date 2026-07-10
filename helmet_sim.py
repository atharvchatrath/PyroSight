#!/usr/bin/env python3
"""
==============================================================================
 PyroSight v5.0 — AI-Assisted Situational Awareness HUD (SITL Prototype)
==============================================================================
 Software-in-the-Loop engine for a firefighter helmet display.

 SUBSYSTEMS
 ----------
   1. CAPTURE     : Threaded, platform-aware webcam ingest (low latency).
   2. AI VISION   : YOLO-World open-vocabulary detection of
                    ["person", "door", "doorway", "exit"] @ conf 0.15,
                    stabilized by an IoU tracker with EMA smoothing so the
                    low-recall threshold does not cause HUD flicker.
   3. RANGING     : Pinhole-camera monocular distance estimation.
                      distance_ft = (REAL_H_IN * FOCAL_LENGTH) / bbox_h_px / 12
   4. HAZARD SIM  : Independent HSV color mask (bright orange/yellow) with
                    morphological cleanup, contour extraction, and a
                    per-hazard thermal random-walk simulator (600-1100 F).
   5. NAVIGATION  : AR egress line from the operator's feet (bottom-center of
                    screen) to the locked exit. True segment-vs-rectangle
                    collision testing against inflated hazard boxes; if the
                    direct path is compromised, a scored left/right waypoint
                    detour is planned and drawn as two connected lines.
   6. HUD         : Tactical heads-up display — corner-bracket target boxes,
                    telemetry sidebar, threat ladder, bearing-to-exit,
                    flashing alert banner, center reticle, mask PiP.

 CONTROLS
 --------
   q / ESC  quit          n  toggle nav line       m  toggle hazard-mask PiP
   p        pause         f  toggle mirror         s  save screenshot

 REQUIREMENTS
 ------------
   pip install opencv-python ultralytics numpy
   (If ultralytics is missing, PyroSight degrades gracefully to
    hazard-detection-only mode instead of crashing.)

 ENGINEERING NOTES
 -----------------
   * Every cv2 drawing call receives strictly integer coordinates — enforced
     centrally by the _ipt() helper.
   * All division sites (bbox height, FPS dt, IoU union, path normalization,
     chevron spacing) carry explicit zero-division failsafes.
==============================================================================
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import threading
import time

import cv2
import numpy as np

# Graceful degradation: the hazard/nav/HUD stack must survive without YOLO.
try:
    from ultralytics import YOLO
    ULTRALYTICS_AVAILABLE = True
except ImportError:
    ULTRALYTICS_AVAILABLE = False


# ============================================================================
# CONFIGURATION
# ============================================================================

YOLO_MODEL_PATH = "yolov8s-world.pt"
YOLO_CLASSES = ["person", "door", "doorway", "exit"]
DOOR_CLASSES = {"door", "doorway", "exit"}
DEFAULT_CONFIDENCE = 0.15          # High recall for partially visible doorways

# --- Pinhole ranging model ---
FOCAL_LENGTH = 800.0               # Effective focal length in pixels
PERSON_HEIGHT_INCHES = 66.0        # Standardized human height
DOOR_HEIGHT_INCHES = 80.0          # Standardized door / exit height

# --- Hazard (HSV) subsystem ---
# Bright orange -> yellow bands. Hue is 0-179 in OpenCV.
HSV_FIRE_RANGES = [
    ((5, 130, 170), (22, 255, 255)),    # saturated orange (flame core)
    ((22, 100, 190), (35, 255, 255)),   # bright yellow (flame tips)
]
HAZARD_MIN_AREA_FRAC = 0.004       # Contour must cover >=0.4% of the frame
TEMP_MIN_F, TEMP_MAX_F = 600.0, 1100.0

# --- Navigation planner ---
HAZARD_SAFETY_MARGIN = 45          # px inflation applied to hazard boxes
WAYPOINT_CLEARANCE = 70            # px lateral offset past the hazard edge
FEET_PER_PACE = 2.5                # For the "paces to exit" readout

# --- Tracker stabilization ---
TRACK_IOU_MATCH = 0.30             # Min IoU to associate detection -> track
TRACK_CONFIRM_HITS = 3             # Frames before a track is HUD-visible
TRACK_MAX_MISSES = 8               # Frames a lost track coasts before purge
EMA_BOX_ALPHA = 0.45               # Box position smoothing factor
EMA_DIST_ALPHA = 0.30              # Distance readout smoothing factor

# --- HUD palette (BGR) ---
CYAN = (255, 255, 0)               # Humans / primary HUD chrome
GREEN = (0, 255, 0)                # Egress route + exits
RED = (0, 0, 255)                  # Hazards
AMBER = (0, 190, 255)              # Warnings
WHITE = (240, 240, 240)
BLACK = (0, 0, 0)
DIM_GREEN = (0, 90, 0)
FONT = cv2.FONT_HERSHEY_SIMPLEX

THREAT_LADDER = {                  # level -> (label, color)
    0: ("SECURE", GREEN),
    1: ("ELEVATED", AMBER),
    2: ("SEVERE", (0, 100, 255)),
    3: ("CRITICAL", RED),
}


# ============================================================================
# GEOMETRY & MATH UTILITIES
# ============================================================================

def _ipt(p):
    """Coerce any point-like into a strict (int, int) tuple for cv2 calls."""
    return (int(round(p[0])), int(round(p[1])))


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def estimate_distance_ft(real_height_inches, bbox_height_pixels):
    """Pinhole camera ranging. Returns None on degenerate (<=0 px) boxes."""
    if bbox_height_pixels is None or bbox_height_pixels <= 0:
        return None  # Division-by-zero failsafe
    return (real_height_inches * FOCAL_LENGTH) / bbox_height_pixels / 12.0


def rect_iou(a, b):
    """IoU of two (x1, y1, x2, y2) rects, with a zero-union failsafe."""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    union = ((a[2] - a[0]) * (a[3] - a[1])
             + (b[2] - b[0]) * (b[3] - b[1]) - inter)
    if union <= 0:
        return 0.0
    return inter / union


def inflate_rect(rect, margin, frame_w, frame_h):
    """Grow (x1, y1, x2, y2) by margin px, clamped to the frame."""
    x1, y1, x2, y2 = rect
    return (clamp(x1 - margin, 0, frame_w), clamp(y1 - margin, 0, frame_h),
            clamp(x2 + margin, 0, frame_w), clamp(y2 + margin, 0, frame_h))


def _segments_intersect(p1, p2, p3, p4):
    """True segment-segment intersection via signed-area orientations."""
    def orient(a, b, c):
        val = (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1])
        if val > 0:
            return 1
        if val < 0:
            return 2
        return 0

    def on_seg(a, b, c):
        return (min(a[0], c[0]) <= b[0] <= max(a[0], c[0])
                and min(a[1], c[1]) <= b[1] <= max(a[1], c[1]))

    o1, o2 = orient(p1, p2, p3), orient(p1, p2, p4)
    o3, o4 = orient(p3, p4, p1), orient(p3, p4, p2)
    if o1 != o2 and o3 != o4:
        return True
    # Collinear edge cases
    if o1 == 0 and on_seg(p1, p3, p2):
        return True
    if o2 == 0 and on_seg(p1, p4, p2):
        return True
    if o3 == 0 and on_seg(p3, p1, p4):
        return True
    if o4 == 0 and on_seg(p3, p2, p4):
        return True
    return False


def segment_intersects_rect(p1, p2, rect):
    """
    TRUE segment-vs-axis-aligned-rect test (endpoint containment OR crossing
    any of the four edges). Replaces the old AABB-overlap approximation that
    produced false positives on diagonal paths.
    """
    x1, y1, x2, y2 = rect
    for p in (p1, p2):
        if x1 <= p[0] <= x2 and y1 <= p[1] <= y2:
            return True
    corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    for i in range(4):
        if _segments_intersect(p1, p2, corners[i], corners[(i + 1) % 4]):
            return True
    return False


# ============================================================================
# SUBSYSTEM 1: THREADED CAPTURE
# ============================================================================

class ThreadedCamera:
    """
    Grabs frames on a daemon thread so the AI/render loop always consumes the
    most recent frame (no driver-buffer lag). Picks the correct capture
    backend per platform — the old build hardcoded CAP_DSHOW, which is a
    Windows-only backend and fails silently on macOS/Linux.
    """

    def __init__(self, index, req_width, req_height):
        if sys.platform == "darwin":
            backend = cv2.CAP_AVFOUNDATION
        elif sys.platform.startswith("win"):
            backend = cv2.CAP_DSHOW
        else:
            backend = cv2.CAP_ANY
        self.cap = cv2.VideoCapture(index, backend)
        if not self.cap.isOpened():           # Fallback: let OpenCV choose
            self.cap = cv2.VideoCapture(index)
        if self.cap.isOpened():
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, req_width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, req_height)
        self._lock = threading.Lock()
        self._frame = None
        self._running = False
        self._thread = None

    def start(self):
        # Block for the first frame so main() never renders a null image.
        # AVFoundation may take a moment to deliver frames after the capture
        # session opens, so retry briefly instead of failing on one empty read.
        deadline = time.time() + 5.0
        while time.time() < deadline:
            ok, frame = self.cap.read()
            if ok:
                self._frame = frame
                self._running = True
                self._thread = threading.Thread(target=self._reader, daemon=True)
                self._thread.start()
                return True
            time.sleep(0.05)
        return False

    def _reader(self):
        while self._running:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.02)
                continue
            with self._lock:
                self._frame = frame

    def read(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def release(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self.cap.release()


# ============================================================================
# SUBSYSTEM 2: DETECTION TRACKER (flicker suppression for conf=0.15)
# ============================================================================

class Track:
    """One smoothed, persistent detection."""

    _next_id = 1

    def __init__(self, kind, box, dist):
        self.id = Track._next_id
        Track._next_id += 1
        self.kind = kind                      # 'person' | 'door'
        self.box = list(box)                  # EMA-smoothed [x1, y1, x2, y2]
        self.dist = dist                      # EMA-smoothed feet (or None)
        self.hits = 1
        self.misses = 0

    @property
    def confirmed(self):
        return self.hits >= TRACK_CONFIRM_HITS

    def update(self, box, dist):
        for i in range(4):
            self.box[i] += EMA_BOX_ALPHA * (box[i] - self.box[i])
        if dist is not None:
            if self.dist is None:
                self.dist = dist
            else:
                self.dist += EMA_DIST_ALPHA * (dist - self.dist)
        self.hits += 1
        self.misses = 0


class DetectionTracker:
    """
    Greedy IoU association of raw YOLO boxes to persistent tracks. Running
    at conf=0.15 (required for partial-doorway recall) produces jittery,
    intermittent boxes; requiring TRACK_CONFIRM_HITS before display and
    coasting TRACK_MAX_MISSES after loss yields a stable tactical picture.
    """

    def __init__(self):
        self.tracks = []

    def update(self, detections):
        """detections: list of (kind, box, dist). Returns confirmed tracks."""
        unmatched = list(range(len(detections)))
        for tr in self.tracks:
            best_iou, best_j = 0.0, -1
            for j in unmatched:
                kind, box, _ = detections[j]
                if kind != tr.kind:
                    continue
                iou = rect_iou(tr.box, box)
                if iou > best_iou:
                    best_iou, best_j = iou, j
            if best_j >= 0 and best_iou >= TRACK_IOU_MATCH:
                _, box, dist = detections[best_j]
                tr.update(box, dist)
                unmatched.remove(best_j)
            else:
                tr.misses += 1
        for j in unmatched:
            kind, box, dist = detections[j]
            self.tracks.append(Track(kind, box, dist))
        self.tracks = [t for t in self.tracks if t.misses <= TRACK_MAX_MISSES]
        return [t for t in self.tracks if t.confirmed]


# ============================================================================
# SUBSYSTEM 3: HSV HAZARD DETECTION + THERMAL SIMULATION
# ============================================================================

class HazardDetector:
    """
    Fully independent of the neural detector: isolates bright orange/yellow
    regions in HSV space, cleans the mask morphologically, and extracts
    large contours as hazard boxes. Each hazard carries a simulated core
    temperature driven by a bounded random walk, matched frame-to-frame by
    IoU so the readout is coherent instead of white noise.
    """

    def __init__(self):
        self._kernel_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        self._kernel_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
        self._thermal = {}                    # track_id -> temperature F
        self._prev = []                       # [(track_id, box), ...]
        self._next_id = 1

    def detect(self, frame):
        """Returns (hazards, mask). hazards: list of dicts with box + temp."""
        h, w = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        mask = np.zeros((h, w), dtype=np.uint8)
        for lo, hi in HSV_FIRE_RANGES:
            mask = cv2.bitwise_or(mask, cv2.inRange(hsv, np.array(lo), np.array(hi)))

        # Despeckle, then fuse flame fragments into solid blobs.
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self._kernel_open)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self._kernel_close)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        min_area = max(1.0, HAZARD_MIN_AREA_FRAC * w * h)

        boxes = []
        for c in contours:
            if cv2.contourArea(c) < min_area:
                continue
            x, y, bw, bh = cv2.boundingRect(c)
            boxes.append((x, y, x + bw, y + bh))

        hazards = self._simulate_thermals(boxes)
        return hazards, mask

    def _simulate_thermals(self, boxes):
        """Persist per-hazard temperatures across frames via IoU matching."""
        matched, used_prev = [], set()
        for box in boxes:
            best_iou, best_id = 0.0, None
            for pid, pbox in self._prev:
                if pid in used_prev:
                    continue
                iou = rect_iou(box, pbox)
                if iou > best_iou:
                    best_iou, best_id = iou, pid
            if best_id is not None and best_iou >= 0.15:
                used_prev.add(best_id)
                tid = best_id
                # Bounded random walk with a slight upward (growth) bias.
                self._thermal[tid] = clamp(
                    self._thermal[tid] + random.uniform(-16.0, 22.0),
                    TEMP_MIN_F, TEMP_MAX_F)
            else:
                tid = self._next_id
                self._next_id += 1
                self._thermal[tid] = random.uniform(680.0, 950.0)
            matched.append({"id": tid, "box": box, "temp": self._thermal[tid]})

        live_ids = {m["id"] for m in matched}
        self._thermal = {k: v for k, v in self._thermal.items() if k in live_ids}
        self._prev = [(m["id"], m["box"]) for m in matched]
        return matched


# ============================================================================
# SUBSYSTEM 4: NAVIGATION PLANNER (waypoint routing around hazards)
# ============================================================================

class NavigationPlanner:
    """
    Plans the egress polyline from the operator's feet to the locked exit.
      DIRECT   : straight shot, no hazard on path.
      REROUTED : one intermediate waypoint clears all inflated hazard boxes;
                 the candidate (left vs right of the blocker) is chosen by
                 collision count first, then smallest lateral detour.
      BLOCKED  : no clean detour exists — the least-bad path is still drawn
                 so the operator sees geometry, but the HUD flags CRITICAL.
    """

    def plan(self, start, target, hazard_boxes, frame_w, frame_h):
        inflated = [inflate_rect(b, HAZARD_SAFETY_MARGIN, frame_w, frame_h)
                    for b in hazard_boxes]
        blockers = [r for r in inflated
                    if segment_intersects_rect(start, target, r)]
        if not blockers:
            return [start, target], "DIRECT"

        # Route around the blocking hazard nearest to the operator.
        def dist_to_start(r):
            cx, cy = (r[0] + r[2]) / 2.0, (r[1] + r[3]) / 2.0
            return (cx - start[0]) ** 2 + (cy - start[1]) ** 2

        blk = min(blockers, key=dist_to_start)
        wy = int(clamp((blk[1] + blk[3]) / 2.0, 0, frame_h - 1))
        candidates = [
            (int(blk[0] - WAYPOINT_CLEARANCE), wy),   # swing LEFT of hazard
            (int(blk[2] + WAYPOINT_CLEARANCE), wy),   # swing RIGHT of hazard
        ]

        best_path, best_key = None, None
        for wp in candidates:
            if not (0 <= wp[0] < frame_w):            # off-screen: unusable
                continue
            legs = [(start, wp), (wp, target)]
            collisions = sum(1 for a, b in legs for r in inflated
                             if segment_intersects_rect(a, b, r))
            detour = abs(wp[0] - (start[0] + target[0]) / 2.0)
            key = (collisions, detour)
            if best_key is None or key < best_key:
                best_key, best_path = key, [start, wp, target]

        if best_path is None:                          # both waypoints off-frame
            return [start, target], "BLOCKED"
        status = "REROUTED" if best_key[0] == 0 else "BLOCKED"
        return best_path, status


# ============================================================================
# SUBSYSTEM 5: TACTICAL HUD RENDERER
# ============================================================================

class HUDRenderer:
    """
    All drawing funnels through here. Translucent geometry is painted onto an
    overlay and alpha-blended once per frame; crisp chrome (text, brackets,
    reticle) is drawn after the blend so it stays razor sharp.
    """

    def __init__(self):
        self.t0 = time.time()

    # ---------- translucent layer ----------

    def draw_nav_path(self, overlay, path, status, frame_h):
        color = GREEN if status != "BLOCKED" else AMBER
        # Thick under-glow, then core line, then direction chevrons.
        for a, b in zip(path[:-1], path[1:]):
            cv2.line(overlay, _ipt(a), _ipt(b), DIM_GREEN, 22, cv2.LINE_AA)
            cv2.line(overlay, _ipt(a), _ipt(b), color, 9, cv2.LINE_AA)
        self._draw_chevrons(overlay, path, color)
        # Diamond marker on the detour waypoint, if any.
        if len(path) == 3:
            wx, wy = _ipt(path[1])
            pts = np.array([(wx, wy - 14), (wx + 14, wy),
                            (wx, wy + 14), (wx - 14, wy)], np.int32)
            cv2.fillPoly(overlay, [pts.reshape((-1, 1, 2))], AMBER)

    def _draw_chevrons(self, overlay, path, color):
        """Perspective-scaled direction arrows marching along the route."""
        pts = []
        for a, b in zip(path[:-1], path[1:]):
            seg_len = math.hypot(b[0] - a[0], b[1] - a[1])
            n = max(2, int(seg_len / 55.0))            # one chevron per ~55 px
            for i in range(n):
                t = i / float(n)                       # n >= 2, never div-by-0
                pts.append((a[0] + (b[0] - a[0]) * t,
                            a[1] + (b[1] - a[1]) * t,
                            math.atan2(b[1] - a[1], b[0] - a[0])))
        for (x, y, theta) in pts:
            size = clamp(int(y / 22.0), 7, 26)         # smaller when "farther"
            tip = (x + math.cos(theta) * size, y + math.sin(theta) * size)
            spread = math.pi / 4.0
            l = (tip[0] + math.cos(theta - spread + math.pi) * size * 1.5,
                 tip[1] + math.sin(theta - spread + math.pi) * size * 1.5)
            r = (tip[0] + math.cos(theta + spread + math.pi) * size * 1.5,
                 tip[1] + math.sin(theta + spread + math.pi) * size * 1.5)
            arrow = np.array([_ipt(l), _ipt(tip), _ipt(r)], np.int32)
            arrow = arrow.reshape((-1, 1, 2))
            cv2.polylines(overlay, [arrow], False, BLACK,
                          max(1, size // 2 + 3), cv2.LINE_AA)
            cv2.polylines(overlay, [arrow], False, color,
                          max(1, size // 2), cv2.LINE_AA)

    def draw_hazard_fills(self, overlay, hazards):
        for hz in hazards:
            x1, y1, x2, y2 = (int(v) for v in hz["box"])
            cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 0, 120), -1)

    def draw_top_bar(self, overlay, w):
        cv2.rectangle(overlay, (0, 0), (int(w), 52), (25, 25, 25), -1)

    def draw_sidebar(self, overlay, h):
        cv2.rectangle(overlay, (0, 60), (250, int(h) - 12), (20, 20, 20), -1)

    # ---------- crisp layer ----------

    def draw_bracket_box(self, frame, box, color, label, sub=None, thickness=2):
        """Corner-bracket target box with label plate (and optional subtext)."""
        x1, y1, x2, y2 = (int(v) for v in box)
        arm = max(8, int(min(x2 - x1, y2 - y1) * 0.22))
        for (cx, cy, dx, dy) in ((x1, y1, 1, 1), (x2, y1, -1, 1),
                                 (x1, y2, 1, -1), (x2, y2, -1, -1)):
            cv2.line(frame, (cx, cy), (cx + dx * arm, cy), color, thickness)
            cv2.line(frame, (cx, cy), (cx, cy + dy * arm), color, thickness)
        (tw, th), _ = cv2.getTextSize(label, FONT, 0.55, 2)
        ly = max(th + 8, y1)                           # keep plate on-screen
        cv2.rectangle(frame, (x1, ly - th - 8), (x1 + tw + 10, ly), color, -1)
        cv2.putText(frame, label, (x1 + 5, ly - 5), FONT, 0.55, BLACK, 2)
        if sub:
            cv2.putText(frame, sub, (x1 + 2, y2 + 20), FONT, 0.5, color, 2)

    def draw_hazard_box(self, frame, hz, blink_on):
        x1, y1, x2, y2 = (int(v) for v in hz["box"])
        cv2.rectangle(frame, (x1, y1), (x2, y2), RED, 4)
        label = "HAZARD - BLOCKED"
        temp = f"{hz['temp']:.0f} F"
        (tw, th), _ = cv2.getTextSize(label, FONT, 0.6, 2)
        ly = max(th + 10, y1)
        cv2.rectangle(frame, (x1, ly - th - 10), (x1 + tw + 12, ly), RED, -1)
        cv2.putText(frame, label, (x1 + 6, ly - 6), FONT, 0.6, WHITE, 2)
        if blink_on:                                   # flashing thermal readout
            cv2.putText(frame, temp, (x1 + 4, min(y2 + 24, frame.shape[0] - 6)),
                        FONT, 0.65, AMBER, 2)

    def draw_reticle(self, frame, w, h):
        cx, cy = int(w // 2), int(h // 2)
        cv2.line(frame, (cx - 18, cy), (cx - 6, cy), CYAN, 1)
        cv2.line(frame, (cx + 6, cy), (cx + 18, cy), CYAN, 1)
        cv2.line(frame, (cx, cy - 18), (cx, cy - 6), CYAN, 1)
        cv2.line(frame, (cx, cy + 6), (cx, cy + 18), CYAN, 1)
        cv2.circle(frame, (cx, cy), 2, CYAN, -1)

    def draw_status(self, frame, w, h, fps, threat, exit_info, counts, ai_online):
        # --- top bar ---
        cv2.putText(frame, "PYROSIGHT v5.0", (12, 34), FONT, 0.8, CYAN, 2)
        elapsed = int(time.time() - self.t0)
        clock = f"T+{elapsed // 60:02d}:{elapsed % 60:02d}"
        cv2.putText(frame, clock, (int(w) - 320, 34), FONT, 0.7, WHITE, 2)
        cv2.putText(frame, f"{fps:4.1f} FPS", (int(w) - 150, 34), FONT, 0.7, WHITE, 2)
        t_label, t_color = THREAT_LADDER[threat]
        cv2.putText(frame, f"THREAT: {t_label}", (270, 34), FONT, 0.7, t_color, 2)

        # --- telemetry sidebar ---
        rows = [
            ("MODE", "AI SENSOR LOCK" if ai_online else "HAZARD-ONLY", CYAN),
            ("PERSONS", str(counts["persons"]), CYAN),
            ("HAZARDS", str(counts["hazards"]), RED if counts["hazards"] else WHITE),
            ("EGRESS", counts["egress"], GREEN if counts["egress"] == "LOCKED" else AMBER),
        ]
        if exit_info is not None:
            dist, bearing = exit_info
            if dist is not None:
                paces = max(1, int(math.ceil(dist / FEET_PER_PACE)))
                rows.append(("RANGE", f"{dist:5.1f} FT / {paces} PACES", GREEN))
            side = "RIGHT" if bearing >= 0 else "LEFT"
            rows.append(("BEARING", f"{abs(bearing):4.1f} DEG {side}", GREEN))
        y = 92
        for name, val, color in rows:
            cv2.putText(frame, name, (14, int(y)), FONT, 0.5, (150, 150, 150), 1)
            cv2.putText(frame, val, (110, int(y)), FONT, 0.5, color, 2)
            y += 30

    def draw_alert_banner(self, frame, w, text, blink_on):
        if not blink_on:
            return
        (tw, th), _ = cv2.getTextSize(text, FONT, 0.9, 2)
        x = int((w - tw) // 2)
        cv2.rectangle(frame, (x - 14, 66), (x + tw + 14, 66 + th + 20), RED, -1)
        cv2.putText(frame, text, (x, 66 + th + 8), FONT, 0.9, WHITE, 2)

    def draw_mask_pip(self, frame, mask, w):
        """Picture-in-picture thermal-mask view, top-right corner."""
        pip_w = int(w // 4)
        if mask.shape[1] <= 0 or pip_w <= 0:
            return
        scale = pip_w / float(mask.shape[1])           # width>0 guaranteed above
        pip_h = max(1, int(mask.shape[0] * scale))
        pip = cv2.resize(mask, (pip_w, pip_h))
        pip = cv2.applyColorMap(pip, cv2.COLORMAP_HOT)
        x0, y0 = int(w - pip_w - 10), 62
        frame[y0:y0 + pip_h, x0:x0 + pip_w] = pip
        cv2.rectangle(frame, (x0, y0), (x0 + pip_w, y0 + pip_h), RED, 1)
        cv2.putText(frame, "THERMAL MASK", (x0 + 4, y0 + 16), FONT, 0.45, RED, 1)


# ============================================================================
# THREAT ASSESSMENT
# ============================================================================

def assess_threat(hazards, nav_status, frame_area):
    """Fuse hazard coverage + routing state into a 0-3 threat level."""
    if frame_area <= 0:
        return 0, None
    coverage = sum((h["box"][2] - h["box"][0]) * (h["box"][3] - h["box"][1])
                   for h in hazards) / float(frame_area)
    if nav_status == "BLOCKED":
        return 3, "ALL ROUTES COMPROMISED - FALL BACK"
    if coverage > 0.18:
        return 3, "FLASHOVER RISK - EVACUATE"
    if nav_status == "REROUTED":
        return 2, "HAZARD ON PATH - REROUTING"
    if coverage > 0.06:
        return 2, "MAJOR THERMAL EVENT"
    if hazards:
        return 1, None
    return 0, None


# ============================================================================
# MAIN ENGINE LOOP
# ============================================================================

def build_arg_parser():
    p = argparse.ArgumentParser(description="PyroSight v5.0 SITL engine")
    p.add_argument("--camera", type=int, default=0, help="webcam index")
    p.add_argument("--width", type=int, default=1280, help="requested capture width")
    p.add_argument("--height", type=int, default=720, help="requested capture height")
    p.add_argument("--conf", type=float, default=DEFAULT_CONFIDENCE,
                   help="YOLO confidence threshold (default 0.15 for recall)")
    p.add_argument("--detect-every", type=int, default=1,
                   help="run YOLO every N frames (tracker coasts in between)")
    p.add_argument("--no-yolo", action="store_true",
                   help="skip neural detection (hazard/nav subsystems only)")
    p.add_argument("--mirror", action="store_true",
                   help="mirror the feed (selfie testing; off = true helmet POV)")
    return p


def load_model(args):
    """Load YOLO-World with the tactical vocabulary; None on any failure."""
    if args.no_yolo:
        print("[INIT] Neural detection disabled by --no-yolo.", flush=True)
        return None
    if not ULTRALYTICS_AVAILABLE:
        print("[WARN] ultralytics not installed - running hazard-only mode.\n"
              "       Fix with: pip install ultralytics", flush=True)
        return None
    print("[INIT] Loading YOLO-World model (first run downloads weights)...", flush=True)
    try:
        model = YOLO(YOLO_MODEL_PATH)
        model.set_classes(YOLO_CLASSES)
        print(f"[INIT] Vocabulary locked: {YOLO_CLASSES}", flush=True)
        return model
    except Exception as exc:  # noqa: BLE001 - degrade instead of crash
        print(f"[WARN] Model load failed ({exc}) - hazard-only mode.", flush=True)
        return None


def run_inference(model, frame, conf):
    """Raw YOLO pass -> list of (kind, box, distance_ft) tuples."""
    detections = []
    results = model.predict(frame, conf=conf, verbose=False)
    for r in results:
        names = r.names if r.names else {}
        if r.boxes is None:
            continue
        for box in r.boxes:
            cls_name = str(names.get(int(box.cls[0]), "")).lower()
            x1, y1, x2, y2 = (float(v) for v in box.xyxy[0])
            bbox_h = y2 - y1
            if cls_name == "person":
                dist = estimate_distance_ft(PERSON_HEIGHT_INCHES, bbox_h)
                detections.append(("person", (x1, y1, x2, y2), dist))
            elif cls_name in DOOR_CLASSES:
                dist = estimate_distance_ft(DOOR_HEIGHT_INCHES, bbox_h)
                detections.append(("door", (x1, y1, x2, y2), dist))
    return detections


def main():
    args = build_arg_parser().parse_args()

    model = load_model(args)
    tracker = DetectionTracker()
    hazard_detector = HazardDetector()
    planner = NavigationPlanner()
    hud = HUDRenderer()

    print(f"[INIT] Opening webcam index {args.camera}...", flush=True)
    camera = ThreadedCamera(args.camera, args.width, args.height)
    if not camera.start():
        print(f"[FATAL] Could not open webcam at index {args.camera}. "
              "Check camera permissions (System Settings > Privacy > Camera) "
              "or try --camera 1.", flush=True)
        return 1
    print("[READY] Feed live. q=quit  n=nav  m=mask  p=pause  f=mirror  s=snap",
          flush=True)

    show_nav, show_mask_pip, mirror, paused = True, False, args.mirror, False
    fps, last_t = 0.0, time.time()
    frame_count = 0
    detections = []          # persists across throttled inference frames
    frame = None
    hazards, fire_mask = [], None

    while True:
        if not paused:
            grabbed = camera.read()
            if grabbed is None:
                print("[FATAL] Camera stream ended.", flush=True)
                break
            frame = grabbed
            if mirror:
                frame = cv2.flip(frame, 1)
        elif frame is None:
            break
        display = frame.copy()

        frame_count += 1
        h_frame, w_frame = display.shape[:2]
        blink_on = (frame_count % 24) < 14             # shared blink phase

        # ---- FPS (EMA, zero-dt failsafe) ----
        now = time.time()
        dt = now - last_t
        last_t = now
        if dt > 0:
            fps = fps * 0.9 + (1.0 / dt) * 0.1 if fps > 0 else 1.0 / dt

        if not paused:
            # ---- SUBSYSTEM: neural detection (throttleable) + tracking ----
            if model is not None and frame_count % max(1, args.detect_every) == 0:
                detections = run_inference(model, display, args.conf)
            tracks = tracker.update(detections if model is not None else [])

            # ---- SUBSYSTEM: independent HSV hazard scan ----
            hazards, fire_mask = hazard_detector.detect(display)
        else:
            # Paused: freeze the tactical picture (tracks, hazards, thermals).
            tracks = [t for t in tracker.tracks if t.confirmed]
        if fire_mask is None:
            fire_mask = np.zeros((h_frame, w_frame), dtype=np.uint8)

        persons = [t for t in tracks if t.kind == "person"]
        doors = [t for t in tracks if t.kind == "door"]

        # ---- SUBSYSTEM: navigation ----
        nav_path, nav_status, exit_info = None, "NONE", None
        target_door = None
        if doors:
            # Lock the largest door (nearest / most confident egress).
            target_door = max(doors, key=lambda t: (t.box[2] - t.box[0])
                              * (t.box[3] - t.box[1]))
            start_pt = (int(w_frame / 2), int(h_frame))          # operator feet
            end_pt = (int((target_door.box[0] + target_door.box[2]) / 2),
                      int(target_door.box[3]))                   # door threshold
            nav_path, nav_status = planner.plan(
                start_pt, end_pt, [tuple(hz["box"]) for hz in hazards],
                w_frame, h_frame)
            bearing = math.degrees(math.atan2(end_pt[0] - w_frame / 2.0,
                                              FOCAL_LENGTH))
            exit_info = (target_door.dist, bearing)

        threat, alert = assess_threat(hazards, nav_status, w_frame * h_frame)
        if alert is None and any(p.dist is not None and p.dist < 8.0
                                 for p in persons):
            alert = "VICTIM PROXIMATE - RENDER AID"

        # ================= RENDER: translucent layer =================
        overlay = display.copy()
        hud.draw_top_bar(overlay, w_frame)
        hud.draw_sidebar(overlay, h_frame)
        hud.draw_hazard_fills(overlay, hazards)
        if show_nav and nav_path is not None:
            hud.draw_nav_path(overlay, nav_path, nav_status, h_frame)
        display = cv2.addWeighted(overlay, 0.55, display, 0.45, 0)

        # ================= RENDER: crisp layer =================
        for p in persons:
            sub = f"{p.dist:.1f} FT" if p.dist is not None else "RANGE N/A"
            hud.draw_bracket_box(display, p.box, CYAN, f"PERSON #{p.id}", sub)
        for d in doors:
            is_target = target_door is not None and d.id == target_door.id
            label = "EXIT [LOCKED]" if is_target else "EXIT"
            sub = f"{d.dist:.1f} FT" if d.dist is not None else None
            hud.draw_bracket_box(display, d.box, GREEN, label, sub,
                                 thickness=3 if is_target else 2)
        for hz in hazards:
            hud.draw_hazard_box(display, hz, blink_on)

        hud.draw_reticle(display, w_frame, h_frame)
        counts = {
            "persons": len(persons),
            "hazards": len(hazards),
            "egress": "LOCKED" if doors else "SEARCHING",
        }
        hud.draw_status(display, w_frame, h_frame, fps, threat, exit_info,
                        counts, ai_online=model is not None)
        if alert:
            hud.draw_alert_banner(display, w_frame, alert, blink_on)
        if show_mask_pip:
            hud.draw_mask_pip(display, fire_mask, w_frame)
        if paused:
            cv2.putText(display, "[ PAUSED ]",
                        (int(w_frame / 2) - 90, int(h_frame / 2) - 40),
                        FONT, 1.0, AMBER, 2)

        cv2.imshow("PyroSight v5.0 - Tactical HUD", display)

        # ---- input handling ----
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        elif key == ord("n"):
            show_nav = not show_nav
        elif key == ord("m"):
            show_mask_pip = not show_mask_pip
        elif key == ord("p"):
            paused = not paused
        elif key == ord("f"):
            mirror = not mirror
        elif key == ord("s"):
            name = time.strftime("pyrosight_%Y%m%d_%H%M%S.png")
            cv2.imwrite(name, display)
            print(f"[SNAP] Saved {name}", flush=True)

    camera.release()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
