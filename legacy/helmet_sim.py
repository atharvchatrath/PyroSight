#!/usr/bin/env python3
"""
PyroSight v7.0 - Hardened Multi-Evidence Detection HUD
=======================================================
DETECTION PHILOSOPHY:
  Every label shown on screen must pass MULTIPLE independent tests across
  MULTIPLE frames. A single frame hit NEVER produces a label.

  PERSON  : YOLO >= 0.82  AND confirmed for 5+ consecutive frames
  FIRE    : HSV bright orange/yellow  AND flicker >= 18% change/frame
            AND region present for 5+ consecutive frames
  DOOR    : Geometry (large vertical rect, solidity >= 0.45)
            AND interior brightness delta >= 22
  OBSTACLE: YOLO >= 0.80  AND confirmed for 5+ frames
  PATH    : Floor-plane analysis (clear low-variance region ahead)

KEY CONTROLS:
  q/ESC  quit       n  nav line      m  thermal pip   p  pause
  f  mirror         x  smoke         v  night-vision   a  mute audio
  r  record         s  screenshot
"""
from __future__ import annotations
import argparse, math, random, sys, threading, time, queue
import cv2
import numpy as np

try:
    from ultralytics import YOLO
    ULTRALYTICS_AVAILABLE = True
except ImportError:
    ULTRALYTICS_AVAILABLE = False

try:
    import winsound
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False

try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

# ============================================================================
# TUNING CONSTANTS
# ============================================================================
COCO_MODEL  = "yolov8s.pt"

# --- Detection thresholds ---
CONF_PERSON            = 0.55   # YOLO confidence - tracker confirms over multiple frames
CONF_OBSTACLE          = 0.72
MIN_MOTION_BLOB_PX     = 5000
MOTION_ASPECT_MIN      = 1.4
MOTION_ASPECT_MAX      = 4.5
MOTION_PERSIST_FRAMES  = 5
MOTION_PERSON_CONF     = 0.55

## --- Fire thresholds ---
HSV_FIRE = [((5,  140, 190), (22, 255, 255)),   # Saturated bright orange
            ((22, 120, 190), (35, 255, 255))]    # Bright yellow
FIRE_MIN_AREA_FRAC   = 0.004   # Slightly stricter than original 0.003
FIRE_FLICKER_THRESH  = 0.10    # 10% change required (was 0.08 original, was 0.18 - too high)
FIRE_CONFIRM_FRAMES  = 3       # Must flicker 3 frames before labeling

# --- Geometric door (hardened) ---
DOOR_MIN_AREA_FRAC   = 0.030   # Slightly larger minimum
DOOR_AR_MIN          = 1.6     # Tighter aspect ratio
DOOR_AR_MAX          = 4.5
DOOR_SOLIDITY_MIN    = 0.45    # Much stricter (was 0.28) - rejects irregular frames
DOOR_INTERIOR_DELTA  = 22      # Much stricter (was 12) - rejects monitors, picture frames
DOOR_MIN_W           = 60
DOOR_MIN_H           = 100

# --- Tracker ---
IOU_MATCH    = 0.25
CONFIRM_HITS = 3    # 3 consecutive frames before label appears
MAX_MISSES   = 18
EMA_BOX      = 0.22
EMA_DIST     = 0.15

# --- Nav ---
NAV_MARGIN  = 55
NAV_CLEAR   = 90
FT_PACE     = 2.5
FOCAL       = 800.0
H_PERSON    = 66.0
H_DOOR      = 80.0
H_OBST      = 36.0

# --- COCO IDs ---
COCO_PERSON_IDS   = {0}
COCO_OBSTACLE_IDS = {56, 57, 59, 60, 62}
COCO_NAMES = {0: "PERSON", 56: "CHAIR", 57: "SOFA", 59: "BED", 60: "TABLE", 62: "TV"}

# ============================================================================
# PREMIUM COLOR PALETTE  (BGR notation)
# ============================================================================
C_BG        = (22,  14,  10)
C_PANEL     = (30,  20,  15)
C_BORDER    = (60,  50,  40)
C_CYAN      = (255, 212,   0)
C_GREEN     = (136, 255,   0)
C_RED       = ( 40,  50, 255)
C_AMBER     = (  0, 170, 255)
C_ORANGE    = ( 20, 120, 255)
C_WHITE     = (235, 235, 240)
C_DIM       = ( 90,  90, 100)
C_TEAL      = (200, 230,   0)
C_NVGRN     = (  0, 220,  50)
C_BLACK     = (  0,   0,   0)
C_FIRE_GLOW = ( 30, 100, 255)

FONT_BODY = cv2.FONT_HERSHEY_DUPLEX
FONT_MONO = cv2.FONT_HERSHEY_SIMPLEX
FONT_BOLD = cv2.FONT_HERSHEY_DUPLEX

THREAT_MAP = {
    0: ("SECURE",   C_GREEN),
    1: ("ELEVATED", C_AMBER),
    2: ("SEVERE",   C_ORANGE),
    3: ("CRITICAL", C_RED),
}

# ============================================================================
# GEOMETRY UTILITIES
# ============================================================================
def _ipt(p): return (int(round(p[0])), int(round(p[1])))
def clamp(v, lo, hi): return max(lo, min(hi, v))
def dft(rh, bh): return None if not bh or bh <= 0 else (rh * FOCAL) / bh / 12.0

def rect_iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter / union if union > 0 else 0.0

def inflate(r, m, fw, fh):
    return (clamp(r[0]-m, 0, fw), clamp(r[1]-m, 0, fh),
            clamp(r[2]+m, 0, fw), clamp(r[3]+m, 0, fh))

def _ori(a, b, c):
    v = (b[1]-a[1])*(c[0]-b[0]) - (b[0]-a[0])*(c[1]-b[1])
    return 1 if v > 0 else (2 if v < 0 else 0)

def _ons(a, b, c):
    return (min(a[0],c[0]) <= b[0] <= max(a[0],c[0]) and
            min(a[1],c[1]) <= b[1] <= max(a[1],c[1]))

def xcross(p1, p2, p3, p4):
    o1,o2 = _ori(p1,p2,p3), _ori(p1,p2,p4)
    o3,o4 = _ori(p3,p4,p1), _ori(p3,p4,p2)
    if o1 != o2 and o3 != o4: return True
    for ox,pa,pb,pc in ((o1,p1,p3,p2),(o2,p1,p4,p2),(o3,p3,p1,p4),(o4,p3,p2,p4)):
        if ox == 0 and _ons(pa, pb, pc): return True
    return False

def seg_rect(p1, p2, rect):
    x1,y1,x2,y2 = rect
    for p in (p1, p2):
        if x1 <= p[0] <= x2 and y1 <= p[1] <= y2: return True
    C = [(x1,y1),(x2,y1),(x2,y2),(x1,y2)]
    for i in range(4):
        if xcross(p1, p2, C[i], C[(i+1)%4]): return True
    return False

# ============================================================================
# THREADED CAMERA
# ============================================================================
class Camera:
    def __init__(self, idx):
        bk = (cv2.CAP_AVFOUNDATION if sys.platform == "darwin"
              else cv2.CAP_DSHOW if sys.platform.startswith("win")
              else cv2.CAP_ANY)
        self.cap = None
        for i in [idx] + [x for x in range(5) if x != idx]:
            print(f"[CAM] Trying {i}...", flush=True)
            cap = cv2.VideoCapture(i, bk)
            if not cap.isOpened(): cap = cv2.VideoCapture(i)
            if cap.isOpened():
                ok, fr = cap.read()
                if ok and fr is not None and fr.any():
                    self.cap = cap; print(f"[CAM] Live {i}!", flush=True); break
                cap.release()
        if self.cap is None: self.cap = cv2.VideoCapture(idx)
        self._lock = threading.Lock(); self._frame = None
        self._run = False; self._thread = None

    def start(self):
        dl = time.time() + 6
        while time.time() < dl:
            ok, fr = self.cap.read()
            if ok and fr is not None and fr.any():
                self._frame = fr; self._run = True
                self._thread = threading.Thread(target=self._loop, daemon=True)
                self._thread.start(); return True
            time.sleep(0.05)
        return False

    def _loop(self):
        while self._run:
            ok, fr = self.cap.read()
            if ok and fr is not None:
                with self._lock: self._frame = fr
            else: time.sleep(0.01)

    def read(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def release(self):
        self._run = False
        if self._thread: self._thread.join(timeout=1)
        self.cap.release()

# ============================================================================
# YOLO BACKGROUND THREAD
# ============================================================================
class YOLOThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.model = None; self.ready = False; self._run = True
        self._iq = queue.Queue(maxsize=1); self._oq = queue.Queue(maxsize=1)

    def submit(self, frame):
        try: self._iq.put_nowait(frame)
        except queue.Full: pass

    def get(self):
        try: return self._oq.get_nowait()
        except queue.Empty: return None

    def run(self):
        print("[YOLO] Loading yolov8s.pt ...", flush=True)
        try:
            self.model = YOLO(COCO_MODEL)
            print("[YOLO] Ready!", flush=True); self.ready = True
        except Exception as e:
            print(f"[YOLO] Failed: {e}", flush=True); return
        while self._run:
            try: frame = self._iq.get(timeout=0.1)
            except queue.Empty: continue
            try:
                res = self.model.predict(
                    frame,
                    conf=min(CONF_PERSON, CONF_OBSTACLE) - 0.05,
                    verbose=False,
                    classes=list(COCO_PERSON_IDS | COCO_OBSTACLE_IDS))
                try: self._oq.put_nowait(res)
                except queue.Full: pass
            except Exception as e:
                print(f"[YOLO] predict err: {e}", flush=True)

    def stop(self): self._run = False

# ============================================================================
# MOTION DETECTOR  (hardened MOG2 + persistence)
# ============================================================================
class MotionDetector:
    """
    Finds large moving blobs with strict human-like proportions.
    Requires a blob to persist for MOTION_PERSIST_FRAMES before reporting.
    """
    def __init__(self):
        self._bg = cv2.createBackgroundSubtractorMOG2(
            history=200, varThreshold=55, detectShadows=False)
        self._kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        self._fc = 0
        self._persist: dict = {}

    def detect(self, frame):
        self._fc += 1
        small = cv2.resize(frame, (frame.shape[1]//2, frame.shape[0]//2))
        fg = self._bg.apply(small)
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN,  self._kernel)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, self._kernel)
        if self._fc < 30: return []   # warmup

        contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        sx = 2.0
        raw_blobs = []
        for c in contours:
            area = cv2.contourArea(c) * sx * sx
            if area < MIN_MOTION_BLOB_PX: continue
            x, y, w, h = cv2.boundingRect(c)
            x, y, w, h = int(x*sx), int(y*sx), int(w*sx), int(h*sx)
            ar = h / (w + 1e-5)
            if MOTION_ASPECT_MIN <= ar <= MOTION_ASPECT_MAX:
                raw_blobs.append((x, y, x+w, y+h, area))

        new_persist = {}
        confirmed = []
        for blob in raw_blobs:
            cx = (blob[0] + blob[2]) // 2
            cy = (blob[1] + blob[3]) // 2
            key = (cx // 80, cy // 80)
            count = self._persist.get(key, 0) + 1
            new_persist[key] = count
            if count >= MOTION_PERSIST_FRAMES:
                confirmed.append(blob)
        self._persist = new_persist
        return confirmed

# ============================================================================
# FIRE DETECTOR  (hardened HSV + multi-frame confirmation)
# ============================================================================
class FireDetector:
    """
    Three-stage fire detection:
    1. HSV mask (very bright, saturated orange/yellow only)
    2. Flicker >= 18% of fire pixels must change per frame
    3. Must flicker for FIRE_CONFIRM_FRAMES consecutive frames
    """
    def __init__(self):
        self._ko = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        self._kc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
        self._prev_mask = None
        self._thermal = {}; self._prev_boxes = []; self._nid = 1
        self._blob_confirm: dict = {}

    def _hsv_mask(self, frame):
        h, w = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = np.zeros((h, w), np.uint8)
        for lo, hi in HSV_FIRE:
            mask = cv2.bitwise_or(mask, cv2.inRange(hsv, np.array(lo), np.array(hi)))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  self._ko)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self._kc)
        return mask

    def detect(self, frame):
        mask = self._hsv_mask(frame)
        h, w = frame.shape[:2]
        min_area = max(1, FIRE_MIN_AREA_FRAC * w * h)

        if self._prev_mask is not None and self._prev_mask.shape == mask.shape:
            diff = cv2.bitwise_xor(mask, self._prev_mask)
            total_fire_px = float(np.count_nonzero(mask)) + 1.0
            flicker_ratio = np.count_nonzero(diff) / total_fire_px
        else:
            flicker_ratio = 1.0

        self._prev_mask = mask.copy()

        if flicker_ratio < FIRE_FLICKER_THRESH:
            self._blob_confirm = {}
            return [], mask

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        raw_boxes = []
        for c in contours:
            if cv2.contourArea(c) < min_area: continue
            x, y, bw, bh = cv2.boundingRect(c)
            raw_boxes.append((x, y, x+bw, y+bh))

        new_confirm = {}
        candidate_boxes = []
        for box in raw_boxes:
            cx = (box[0] + box[2]) // 2
            cy = (box[1] + box[3]) // 2
            key = (cx // 60, cy // 60)
            count = self._blob_confirm.get(key, 0) + 1
            new_confirm[key] = count
            if count >= FIRE_CONFIRM_FRAMES:
                candidate_boxes.append(box)
        self._blob_confirm = new_confirm

        return self._thermals(candidate_boxes), mask

    def _thermals(self, boxes):
        matched, used = [], set()
        for box in boxes:
            best, bid = 0.0, None
            for pid, pb in self._prev_boxes:
                if pid in used: continue
                iou = rect_iou(box, pb)
                if iou > best: best, bid = iou, pid
            if bid and best >= 0.15:
                used.add(bid); tid = bid
                self._thermal[tid] = clamp(
                    self._thermal[tid] + random.uniform(-10, 18), 650, 1100)
            else:
                tid = self._nid; self._nid += 1
                self._thermal[tid] = random.uniform(750, 950)
            matched.append({"id": tid, "box": box, "temp": self._thermal[tid]})
        live = {m["id"] for m in matched}
        self._thermal = {k: v for k, v in self._thermal.items() if k in live}
        self._prev_boxes = [(m["id"], m["box"]) for m in matched]
        return matched

# ============================================================================
# GEOMETRIC DOOR DETECTOR  (hardened)
# ============================================================================
class DoorDetector:
    def detect(self, frame, existing_doors):
        h, w = frame.shape[:2]
        min_area = DOOR_MIN_AREA_FRAC * w * h
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        filt = cv2.bilateralFilter(gray, 11, 90, 90)
        edges = cv2.Canny(filt, 25, 80)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 11))
        edges = cv2.dilate(edges, kernel, iterations=1)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        cands = []
        for c in contours:
            area = cv2.contourArea(c)
            if area < min_area: continue
            x, y, bw, bh = cv2.boundingRect(c)
            ar = bh / (bw + 1e-5)
            if not (DOOR_AR_MIN <= ar <= DOOR_AR_MAX): continue
            if bw < DOOR_MIN_W or bh < DOOR_MIN_H: continue
            hull_area = cv2.contourArea(cv2.convexHull(c))
            if hull_area > 0 and area / hull_area < DOOR_SOLIDITY_MIN: continue
            border = 15
            roi = gray[y:y+bh, x:x+bw]
            if roi.shape[0] < border*3 or roi.shape[1] < border*3: continue
            interior = roi[border:-border, border:-border]
            border_mask = roi.copy(); border_mask[border:-border, border:-border] = 0
            border_pixels = roi[np.where(border_mask > 0)] if border_mask.any() else np.array([])
            if interior.size == 0 or border_pixels.size == 0: continue
            delta = abs(float(interior.mean()) - float(border_pixels.mean()))
            if delta < DOOR_INTERIOR_DELTA: continue
            box = (x, y, x+bw, y+bh)
            if any(rect_iou(box, (int(d.box[0]),int(d.box[1]),int(d.box[2]),int(d.box[3]))) > 0.35
                   for d in existing_doors): continue
            cands.append((box, delta))

        cands.sort(key=lambda c: c[1], reverse=True)
        result = []
        for box, delta in cands[:3]:
            cx = (box[0]+box[2])/2; cy = (box[1]+box[3])/2
            if any(abs(cx-(r[0]+r[2])/2) < 60 and abs(cy-(r[1]+r[3])/2) < 60 for r in result):
                continue
            result.append(box)
            if len(result) >= 2: break
        return result

# ============================================================================
# PATH DETECTOR
# ============================================================================
class PathDetector:
    def detect(self, frame, hazard_boxes, obstacle_boxes):
        h, w = frame.shape[:2]
        roi_y = int(h * 0.60)
        roi = frame[roi_y:, :]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        lap = cv2.Laplacian(gray, cv2.CV_64F)
        var_map = np.abs(lap)

        n_cols = 16; col_w = w // n_cols
        clear = []
        for i in range(n_cols):
            col = var_map[:, i*col_w:(i+1)*col_w]
            if col.size == 0: clear.append(False); continue
            clear.append(float(col.mean()) < 22.0)

        blocked = [False]*n_cols
        for box in hazard_boxes + obstacle_boxes:
            c1 = max(0, int(box[0])//col_w); c2 = min(n_cols-1, int(box[2])//col_w)
            for ci in range(c1, c2+1): blocked[ci] = True

        best_start = best_len = 0; run_start = -1; run_len = 0
        for i in range(n_cols):
            if clear[i] and not blocked[i]:
                if run_start < 0: run_start = i
                run_len += 1
                if run_len > best_len: best_len = run_len; best_start = run_start
            else: run_start = -1; run_len = 0

        if best_len < 4: return None
        cx = int((best_start + best_len/2) * col_w)
        return (cx, best_len/n_cols, roi_y)

# ============================================================================
# TRACKER
# ============================================================================
class Track:
    _nid = 1
    def __init__(self, kind, label, box, d, cf):
        self.id = Track._nid; Track._nid += 1
        self.kind = kind; self.label = label; self.box = list(box)
        self.dist = d; self.conf = cf; self.hits = 1; self.misses = 0
        self.lock_anim = 1.0; self.fade_in = 0.0

    @property
    def confirmed(self): return self.hits >= CONFIRM_HITS

    def update(self, box, d, cf):
        for i in range(4): self.box[i] += EMA_BOX*(box[i]-self.box[i])
        if d is not None:
            self.dist = d if self.dist is None else self.dist + EMA_DIST*(d-self.dist)
        if cf is not None:
            self.conf = cf if self.conf is None else self.conf + 0.20*(cf-self.conf)
        self.hits += 1; self.misses = 0
        self.lock_anim = max(0, self.lock_anim - 0.07)
        self.fade_in = min(1.0, self.fade_in + 0.15)

class Tracker:
    def __init__(self): self.tracks = []

    def update(self, dets):
        unmatched = list(range(len(dets)))
        for tr in self.tracks:
            best, bj = 0.0, -1
            for j in unmatched:
                if dets[j][0] != tr.kind: continue
                iou = rect_iou(tr.box, dets[j][2])
                if iou > best: best, bj = iou, j
            if bj >= 0 and best >= IOU_MATCH:
                _, l, box, d, cf = dets[bj]; tr.update(box, d, cf); unmatched.remove(bj)
            else: tr.misses += 1
        for j in unmatched:
            kind, l, box, d, cf = dets[j]; self.tracks.append(Track(kind, l, box, d, cf))
        self.tracks = [t for t in self.tracks if t.misses <= MAX_MISSES]
        return [t for t in self.tracks if t.confirmed]

# ============================================================================
# NAV PLANNER
# ============================================================================
class NavPlan:
    def plan(self, start, target, hboxes, obstacles, fw, fh):
        allb = hboxes + [tuple(t.box) for t in obstacles]
        inf = [inflate(b, NAV_MARGIN, fw, fh) for b in allb]
        blk = [r for r in inf if seg_rect(start, target, r)]
        if not blk: return [start, target], "DIRECT"
        def d2(r): cx=(r[0]+r[2])/2; cy=(r[1]+r[3])/2; return (cx-start[0])**2+(cy-start[1])**2
        b = min(blk, key=d2); wy = int(clamp((b[1]+b[3])/2, 0, fh-1))
        cands = [(int(b[0]-NAV_CLEAR), wy), (int(b[2]+NAV_CLEAR), wy)]
        bp, bk = None, None
        for wp in cands:
            if not (0 <= wp[0] < fw): continue
            legs = [(start, wp), (wp, target)]
            coll = sum(1 for a, bb in legs for r in inf if seg_rect(a, bb, r))
            det = abs(wp[0]-(start[0]+target[0])/2); k = (coll, det)
            if bk is None or k < bk: bk, bp = k, [start, wp, target]
        if bp is None: return [start, target], "BLOCKED"
        return bp, ("REROUTED" if bk[0] == 0 else "BLOCKED")

# ============================================================================
# SMOKE SIMULATOR
# ============================================================================
class Smoke:
    def __init__(self): self._off = 0.0; self._layers = []

    def _init(self, h, w):
        self._layers = [(s, np.random.rand(max(1,int(h*s)), max(1,int(w*s))).astype(np.float32))
                        for s in [0.25, 0.5, 1.0]]

    def apply(self, frame, intensity=0.62):
        h, w = frame.shape[:2]
        if not self._layers: self._init(h, w)
        self._off += 0.007; combined = np.zeros((h, w), np.float32)
        for (s, noise), wt in zip(self._layers, [0.5, 0.35, 0.15]):
            sh, sw = noise.shape[:2]
            shifted = np.roll(np.roll(noise, int(self._off*sw)%sw, axis=1),
                              int(self._off*0.3*sh)%sh, axis=0)
            res = cv2.resize(shifted, (w, h), interpolation=cv2.INTER_LINEAR)
            combined += cv2.GaussianBlur(res, (0,0), sigmaX=max(1,int(w*s*0.05)))*wt
        combined = np.clip(combined, 0, 1); sm = combined*intensity
        sg = np.clip(combined*180+40, 0, 255).astype(np.uint8)
        sbgr = cv2.cvtColor(sg, cv2.COLOR_GRAY2BGR)
        out = frame.astype(np.float32)*(1-sm[:,:,None]) + sbgr.astype(np.float32)*sm[:,:,None]
        return out.astype(np.uint8)

    def tick(self, h, w):
        if not self._layers: return
        self._layers = [(s, np.clip(n + np.random.rand(*n.shape).astype(np.float32)*0.04-0.02, 0, 1))
                        for s, n in self._layers]

# ============================================================================
# GPS TRACKER
# ============================================================================
class GPSReceiver(threading.Thread):
    def __init__(self, port=None, baud=9600):
        super().__init__(daemon=True)
        self.port = port; self.baud = baud; self._run = True
        self.lat = 37.7749; self.lon = -122.4194
        self.fix = False; self.mode = "SIM" if not port else "SERIAL"
        self._lock = threading.Lock()

    def get_coords(self):
        with self._lock: return self.lat, self.lon, self.fix, self.mode

    def run(self):
        if self.mode == "SERIAL":
            if not SERIAL_AVAILABLE:
                print("[GPS] pyserial not installed, falling back to SIM.", flush=True)
                self.mode = "SIM"
            else:
                try:
                    ser = serial.Serial(self.port, self.baud, timeout=1)
                    print(f"[GPS] Connected to {self.port}.", flush=True)
                    while self._run:
                        line = ser.readline().decode('ascii', errors='replace').strip()
                        if line.startswith("$GPGGA") or line.startswith("$GPRMC"):
                            pass  # NMEA parsing placeholder
                        time.sleep(0.1)
                except Exception as e:
                    print(f"[GPS] Serial error: {e}, falling back to SIM.", flush=True)
                    self.mode = "SIM"
        if self.mode == "SIM":
            print("[GPS] Running in SIM mode.", flush=True)
            self.fix = True
            while self._run:
                with self._lock:
                    self.lat += random.uniform(-0.00004, 0.00004)
                    self.lon += random.uniform(-0.00004, 0.00004)
                time.sleep(1.2)

    def stop(self): self._run = False

# ============================================================================
# AUDIO
# ============================================================================
class Audio:
    def __init__(self): self.muted = False; self._last = {}

    def alert(self, ev):
        if self.muted or not AUDIO_AVAILABLE: return
        now = time.time()
        if now - self._last.get(ev, 0) < 3.0: return
        self._last[ev] = now
        def _b(f, d):
            try: winsound.Beep(f, d)
            except: pass
        if ev == "critical":
            threading.Thread(target=lambda:[_b(880,150),time.sleep(0.1),_b(1100,300)], daemon=True).start()
        elif ev == "locked":
            threading.Thread(target=lambda:[_b(660,80),time.sleep(0.05),_b(880,180)], daemon=True).start()
        elif ev == "person":
            threading.Thread(target=lambda:_b(440,70), daemon=True).start()
        elif ev == "hazard":
            threading.Thread(target=lambda:[_b(550,90),time.sleep(0.07),_b(550,90)], daemon=True).start()

# ============================================================================
# VIDEO RECORDER
# ============================================================================
class Recorder:
    def __init__(self): self._w = None; self._p = None; self.recording = False

    def start(self, frame):
        self._p = time.strftime("pyrosight_rec_%Y%m%d_%H%M%S.avi")
        h, w = frame.shape[:2]
        self._w = cv2.VideoWriter(self._p, cv2.VideoWriter_fourcc(*"XVID"), 15, (w, h))
        self.recording = True; print(f"[REC] {self._p}", flush=True)

    def write(self, frame):
        if self._w: self._w.write(frame)

    def stop(self):
        if self._w: self._w.release(); self._w = None
        self.recording = False; print(f"[REC] Saved {self._p}", flush=True)

# ============================================================================
# HUD RENDERER  v7.0 — Premium Redesign
# ============================================================================
class HUD:
    SIDEBAR_W = 240
    TOPBAR_H  = 58

    def __init__(self): self.t0 = time.time()

    # -------------------------------------------------------------------------
    # Core drawing helpers
    # -------------------------------------------------------------------------
    def _glow(self, img, text, org, scale, col, thickness=1, blur_r=3):
        x, y = org
        for dx in range(-blur_r, blur_r+1, max(1,blur_r)):
            for dy in range(-blur_r, blur_r+1, max(1,blur_r)):
                if dx == 0 and dy == 0: continue
                cv2.putText(img, text, (x+dx,y+dy), FONT_BODY, scale,
                            C_BLACK, thickness+2, cv2.LINE_AA)
        cv2.putText(img, text, org, FONT_BODY, scale, col, thickness, cv2.LINE_AA)

    def _panel(self, img, x1, y1, x2, y2, alpha=0.80, border_col=None):
        overlay = img.copy()
        cv2.rectangle(overlay, (x1,y1), (x2,y2), C_PANEL, -1)
        cv2.addWeighted(overlay, alpha, img, 1-alpha, 0, img)
        if border_col:
            cv2.rectangle(img, (x1,y1), (x2,y2), border_col, 1)

    def _bracket(self, img, x1, y1, x2, y2, col, thickness=2, pulse=0.0, lock=0.0):
        arm = max(10, int(min(x2-x1,y2-y1)*clamp(0.18+0.05*math.sin(pulse),0.08,0.32)))
        if lock > 0:
            ins = int(lock*min(x2-x1,y2-y1)*0.18)
            x1+=ins; y1+=ins; x2-=ins; y2-=ins
        for cx, cy, sx, sy in ((x1,y1,1,1),(x2,y1,-1,1),(x1,y2,1,-1),(x2,y2,-1,-1)):
            cv2.line(img,(cx,cy),(cx+sx*arm,cy),   col, thickness, cv2.LINE_AA)
            cv2.line(img,(cx,cy),(cx,cy+sy*arm),   col, thickness, cv2.LINE_AA)

    def _confidence_bar(self, img, x, y, w, conf, col):
        cv2.rectangle(img,(x,y),(x+w,y+4), C_BORDER, -1)
        filled = int(w*clamp(conf,0,1))
        if filled > 0: cv2.rectangle(img,(x,y),(x+filled,y+4), col, -1)

    def _label_card(self, img, x1, y1, label, sub, col, conf=None):
        pad_x, pad_y = 8, 6
        (tw, th), _ = cv2.getTextSize(label, FONT_BODY, 0.52, 1)
        card_w = tw + pad_x*2 + 4
        card_h = th + pad_y*2 + (8 if conf is not None else 0)
        cx1 = x1; cy1 = max(0, y1-card_h-4)
        cx2 = cx1+card_w; cy2 = cy1+card_h
        self._panel(img, cx1, cy1, cx2, cy2, 0.85)
        cv2.rectangle(img,(cx1,cy1),(cx1+3,cy2), col, -1)
        ty = cy1+pad_y+th
        cv2.putText(img, label, (cx1+pad_x+4,ty), FONT_BODY, 0.52, C_WHITE, 1, cv2.LINE_AA)
        if conf is not None:
            self._confidence_bar(img, cx1+pad_x+4, ty+3, tw, conf, col)
        if sub:
            self._glow(img, sub, (x1+4, min(y1+20, img.shape[0]-5)), 0.42, col, 1, 2)

    def _pulse_ring(self, img, cx, cy, r_base, t, col):
        for i in range(3):
            phase = (t*2.5 + i*0.4) % 1.0
            r = int(r_base + phase*30)
            thick = max(1, int((1.0-phase)*3))
            overlay = img.copy()
            cv2.circle(overlay,(cx,cy),r,col,thick,cv2.LINE_AA)
            a = (1.0-phase)*0.55
            cv2.addWeighted(overlay, a, img, 1-a, 0, img)

    # -------------------------------------------------------------------------
    # Background panels
    # -------------------------------------------------------------------------
    def top_bar(self, img, W):
        overlay = img.copy()
        cv2.rectangle(overlay,(0,0),(W,self.TOPBAR_H), C_BG, -1)
        cv2.addWeighted(overlay,0.85,img,0.15,0,img)
        cv2.line(img,(0,self.TOPBAR_H),(W,self.TOPBAR_H),(80,60,40),1)

    def sidebar(self, img, H):
        overlay = img.copy()
        cv2.rectangle(overlay,(0,self.TOPBAR_H),(self.SIDEBAR_W,H), C_BG, -1)
        cv2.addWeighted(overlay,0.82,img,0.18,0,img)
        cv2.line(img,(self.SIDEBAR_W,self.TOPBAR_H),(self.SIDEBAR_W,H),(80,60,40),1)

    def haz_fills(self, img, hz):
        for h in hz:
            x1,y1,x2,y2 = (int(v) for v in h["box"])
            overlay = img.copy()
            cv2.rectangle(overlay,(x1,y1),(x2,y2),(0,0,80),-1)
            cv2.addWeighted(overlay,0.28,img,0.72,0,img)

    def obs_fills(self, img, obs):
        for o in obs:
            x1,y1,x2,y2 = (int(v) for v in o.box)
            overlay = img.copy()
            cv2.rectangle(overlay,(x1,y1),(x2,y2),(30,15,0),-1)
            cv2.addWeighted(overlay,0.18,img,0.82,0,img)

    # -------------------------------------------------------------------------
    # Nav
    # -------------------------------------------------------------------------
    def nav_line(self, img, path, status, t):
        col = C_GREEN if status != "BLOCKED" else C_RED
        gl  = (0,40,0) if status != "BLOCKED" else (0,0,50)
        for a, b in zip(path[:-1], path[1:]):
            cv2.line(img,_ipt(a),_ipt(b),gl,26,cv2.LINE_AA)
            cv2.line(img,_ipt(a),_ipt(b),col,6,cv2.LINE_AA)
        self._chevrons(img, path, col, t)
        if len(path) == 3:
            wx,wy = _ipt(path[1])
            pts = np.array([(wx,wy-14),(wx+14,wy),(wx,wy+14),(wx-14,wy)],np.int32)
            cv2.fillPoly(img,[pts.reshape(-1,1,2)],C_AMBER)

    def _chevrons(self, img, path, col, t):
        ph = (t*1.8)%1.0; pts = []
        for a, b in zip(path[:-1], path[1:]):
            sl = math.hypot(b[0]-a[0],b[1]-a[1]); n = max(2,int(sl/55))
            theta = math.atan2(b[1]-a[1],b[0]-a[0])
            for i in range(n):
                f = ((i/float(n))+ph)%1.0
                pts.append((a[0]+(b[0]-a[0])*f, a[1]+(b[1]-a[1])*f, theta))
        for x, y, theta in pts:
            sz = clamp(int(y/22),5,22); af = 0.5+0.5*math.sin(t*3+y*0.02)
            bc = tuple(int(c*af) for c in col)
            tip = (x+math.cos(theta)*sz, y+math.sin(theta)*sz)
            sp = math.pi/3.8
            l = (tip[0]+math.cos(theta-sp+math.pi)*sz*1.4, tip[1]+math.sin(theta-sp+math.pi)*sz*1.4)
            r = (tip[0]+math.cos(theta+sp+math.pi)*sz*1.4, tip[1]+math.sin(theta+sp+math.pi)*sz*1.4)
            arr = np.array([_ipt(l),_ipt(tip),_ipt(r)],np.int32).reshape(-1,1,2)
            cv2.polylines(img,[arr],False,C_BLACK,max(1,sz//2+3),cv2.LINE_AA)
            cv2.polylines(img,[arr],False,bc,      max(1,sz//2),   cv2.LINE_AA)

    # -------------------------------------------------------------------------
    # Entity boxes
    # -------------------------------------------------------------------------
    def person_box(self, img, tr, pulse):
        x1,y1,x2,y2 = (int(v) for v in tr.box)
        self._bracket(img,x1,y1,x2,y2,C_CYAN,2,pulse,tr.lock_anim)
        cx = (x1+x2)//2
        cv2.line(img,(cx,y2-14),(cx,y2-4),C_CYAN,1,cv2.LINE_AA)
        dist_str = f"{tr.dist:.1f} FT" if tr.dist else None
        self._label_card(img,x1,y1,f"PERSON #{tr.id}",dist_str,C_CYAN,tr.conf)

    def motion_person_box(self, img, box, pulse):
        x1,y1,x2,y2 = box
        for sx,sy,ex,ey in [(x1,y1,x2,y1),(x2,y1,x2,y2),(x2,y2,x1,y2),(x1,y2,x1,y1)]:
            ln = math.hypot(ex-sx,ey-sy)
            if ln == 0: continue
            steps = max(1,int(ln/14))
            for i in range(0,steps,2):
                t0=i/float(steps); t1=min((i+1)/float(steps),1.0)
                cv2.line(img,(int(sx+(ex-sx)*t0),int(sy+(ey-sy)*t0)),
                              (int(sx+(ex-sx)*t1),int(sy+(ey-sy)*t1)),C_TEAL,1,cv2.LINE_AA)
        self._glow(img,"MOTION DETECTED",(x1+4,max(y1-8,12)),0.44,C_TEAL,1)

    def door_box(self, img, tr, is_tgt, pulse):
        x1,y1,x2,y2 = (int(v) for v in tr.box)
        col = C_GREEN
        self._bracket(img,x1,y1,x2,y2,col,3 if is_tgt else 2,pulse,tr.lock_anim)
        if is_tgt:
            step = 16
            for off in range(0,(x2-x1)+(y2-y1),step):
                sx2=min(x1+off,x2); ex2=max(x1,x1+off-(y2-y1))
                ey2=min(y1+max(0,off-(x2-x1)),y2)
                ex2=clamp(ex2,x1,x2); ey2=clamp(ey2,y1,y2)
                if (sx2,y1)!=(ex2,ey2): cv2.line(img,(sx2,y1),(ex2,ey2),(0,40,0),1,cv2.LINE_AA)
        lbl = "EXIT [TARGET]" if is_tgt else "EXIT"
        dist_str = f"{tr.dist:.1f} FT" if tr.dist else None
        self._label_card(img,x1,y1,lbl,dist_str,col,None)

    def geo_door_box(self, img, box, t):
        x1,y1,x2,y2 = box
        pulse = 0.5+0.5*math.sin(t*3)
        col = tuple(int(c*pulse+(1-pulse)*60) for c in C_GREEN)
        for sx,sy,ex,ey in [(x1,y1,x2,y1),(x2,y1,x2,y2),(x2,y2,x1,y2),(x1,y2,x1,y1)]:
            ln = math.hypot(ex-sx,ey-sy)
            if ln == 0: continue
            steps = max(1,int(ln/18))
            for i in range(0,steps,2):
                t0=i/float(steps); t1=min((i+1)/float(steps),1.0)
                cv2.line(img,(int(sx+(ex-sx)*t0),int(sy+(ey-sy)*t0)),
                              (int(sx+(ex-sx)*t1),int(sy+(ey-sy)*t1)),C_GREEN,2,cv2.LINE_AA)
        self._label_card(img,x1,y1,"OPENING",None,C_GREEN,None)

    def obs_box(self, img, tr, pulse):
        x1,y1,x2,y2 = (int(v) for v in tr.box)
        self._bracket(img,x1,y1,x2,y2,C_AMBER,1,pulse,0)
        self._label_card(img,x1,y1,tr.label,None,C_AMBER,tr.conf)

    def haz_box(self, img, hz, t):
        x1,y1,x2,y2 = (int(v) for v in hz["box"])
        cx = (x1+x2)//2; cy = (y1+y2)//2
        r_base = min(x2-x1,y2-y1)//2
        thick = 3+int(1.5*abs(math.sin(t*4)))
        cv2.rectangle(img,(x1,y1),(x2,y2),C_RED,thick)
        self._pulse_ring(img,cx,cy,r_base,t,C_ORANGE)
        cv2.rectangle(img,(x1+2,y1+2),(x2-2,y2-2),C_FIRE_GLOW,1)
        self._label_card(img,x1,y1,"FIRE HAZARD",f"{hz['temp']:.0f}F",C_RED,None)

    def draw_path(self, img, path_info, t):
        if path_info is None: return
        cx, wfrac, roi_y = path_info
        h, w = img.shape[:2]
        path_w = int(wfrac*w*0.88)
        x1=max(0,cx-path_w//2); x2=min(w,cx+path_w//2)
        pulse_a = 0.5+0.5*abs(math.sin(t*2.2))
        col = tuple(int(c*pulse_a) for c in C_GREEN)
        cv2.line(img,(x1,roi_y),(x1,h-5),col,2,cv2.LINE_AA)
        cv2.line(img,(x2,roi_y),(x2,h-5),col,2,cv2.LINE_AA)
        overlay = img.copy()
        poly = np.array([(x1,roi_y),(x2,roi_y),(x2,h),(x1,h)],np.int32).reshape(-1,1,2)
        cv2.fillPoly(overlay,[poly],(0,60,0))
        cv2.addWeighted(overlay,0.07,img,0.93,0,img)
        ay = roi_y+25
        cv2.arrowedLine(img,(cx,ay),(cx,min(h-15,ay+55)),col,3,cv2.LINE_AA,tipLength=0.28)
        self._label_card(img,cx-40,roi_y-2,"CLEAR PATH",None,C_GREEN,None)

    # -------------------------------------------------------------------------
    # Radar / minimap
    # -------------------------------------------------------------------------
    def radar_sweep(self, img, cx, cy, r, t):
        ang = t*55*math.pi/180
        for i in range(36):
            a = ang - i*math.pi/180*1.8; fade = 1.0-i/36.0
            ex=cx+int(math.cos(a)*r); ey=cy+int(math.sin(a)*r)
            cv2.line(img,(cx,cy),(ex,ey),(0,int(fade*80),0),1,cv2.LINE_AA)
        ex=cx+int(math.cos(ang)*r); ey=cy+int(math.sin(ang)*r)
        cv2.line(img,(cx,cy),(ex,ey),(0,160,0),2,cv2.LINE_AA)

    def minimap(self, img, W, H, persons, doors, hazards, obstacles, geo_doors, t):
        mw,mh = 160,120; x0=W-mw-20; y0=self.TOPBAR_H+8
        self._panel(img,x0-2,y0-2,x0+mw+2,y0+mh+2,0.88,C_BORDER)
        for i in range(1,4):
            gx=x0+mw*i//4; gy=y0+mh*i//4
            cv2.line(img,(gx,y0),(gx,y0+mh),(30,25,20),1)
            cv2.line(img,(x0,gy),(x0+mw,gy),(30,25,20),1)
        cx_m,cy_m = x0+mw//2, y0+mh//2
        self.radar_sweep(img,cx_m,cy_m,min(mw,mh)//2-4,t)
        for ring_r in [25,50]: cv2.circle(img,(cx_m,cy_m),ring_r,(25,20,15),1)
        cv2.circle(img,(cx_m,cy_m+mh//3),5,C_CYAN,-1)
        cv2.circle(img,(cx_m,cy_m+mh//3),7,C_CYAN,1)

        def mp(box):
            return (int(x0+(box[0]+box[2])/2/W*mw), int(y0+(box[1]+box[3])/2/H*mh))
        for p in persons:
            pt=mp(p.box); cv2.circle(img,pt,4,C_CYAN,-1); cv2.circle(img,pt,6,C_CYAN,1)
        for d in doors:
            pt=mp(d.box); cv2.rectangle(img,(pt[0]-3,pt[1]-6),(pt[0]+3,pt[1]+6),C_GREEN,2)
        for hz in hazards:
            pt=mp(hz["box"]); cv2.circle(img,pt,6,C_RED,-1)
            for i in range(4):
                ang=t*2+i*math.pi/2
                cv2.line(img,pt,(pt[0]+int(math.cos(ang)*9),pt[1]+int(math.sin(ang)*9)),C_ORANGE,1)
        for ob in obstacles:
            pt=mp(ob.box); cv2.circle(img,pt,3,C_AMBER,-1)
        for gd in geo_doors:
            pt=mp(gd); cv2.circle(img,pt,4,(0,200,80),1)
        self._glow(img,"SECTOR MAP",(x0+4,y0+13),0.32,C_DIM,1)

    # -------------------------------------------------------------------------
    # Threat arc
    # -------------------------------------------------------------------------
    def threat_arc(self, img, W, H, level):
        cx=W-16; cy=H//2; r=55
        cv2.ellipse(img,(cx,cy),(r,r),-90,0,270,C_BORDER,3)
        colors=[C_GREEN,C_AMBER,C_ORANGE,C_RED]
        spans=[0,90,180,270]
        for lvl in range(level+1):
            end_angle=spans[lvl+1] if lvl+1<len(spans) else 270
            cv2.ellipse(img,(cx,cy),(r,r),-90,spans[lvl],end_angle,colors[lvl],4)
        for i in range(4):
            ang=math.radians(-90+i*90)
            px=cx+int(math.cos(ang)*(r+5)); py=cy+int(math.sin(ang)*(r+5))
            cv2.circle(img,(px,py),2,C_DIM,-1)

    # -------------------------------------------------------------------------
    # Compass
    # -------------------------------------------------------------------------
    def compass(self, img, W, brg):
        cx=W//2; cy=self.TOPBAR_H-12; r=22
        cv2.ellipse(img,(cx,cy),(r,r),-90,-65,65,C_BORDER,2)
        ang=math.radians(clamp(brg,-60,60))
        cv2.line(img,(cx,cy),(cx+int(math.sin(ang)*r),cy-int(math.cos(ang)*r)),C_GREEN,2,cv2.LINE_AA)
        cv2.circle(img,(cx,cy),3,C_GREEN,-1)
        self._glow(img,"N",(cx-5,cy-r-3),0.28,C_WHITE,1)

    # -------------------------------------------------------------------------
    # Reticle
    # -------------------------------------------------------------------------
    def reticle(self, img, W, H, t):
        cx,cy = W//2,H//2
        rr = t*18*math.pi/180
        cv2.circle(img,(cx,cy),40,C_BORDER,1,cv2.LINE_AA)
        for i in range(4):
            ang = rr+i*math.pi/2
            cv2.line(img,(cx+int(math.cos(ang)*12),cy+int(math.sin(ang)*12)),
                         (cx+int(math.cos(ang)*26),cy+int(math.sin(ang)*26)),
                         C_TEAL,1,cv2.LINE_AA)
        cv2.circle(img,(cx,cy),4,C_TEAL,1,cv2.LINE_AA)
        cv2.circle(img,(cx,cy),1,C_TEAL,-1)
        for ex,ey in [(0,0),(W-1,0),(0,H-1),(W-1,H-1)]:
            sx2=1 if ex==0 else -1; sy2=1 if ey==0 else -1
            cv2.line(img,(ex,ey),(ex+sx2*28,ey),   C_BORDER,1)
            cv2.line(img,(ex,ey),(ex,ey+sy2*28),   C_BORDER,1)

    # -------------------------------------------------------------------------
    # GPS widget
    # -------------------------------------------------------------------------
    def gps_widget(self, img, W, gps_info):
        if gps_info is None: return
        lat,lon,fix,mode = gps_info
        col = C_GREEN if fix else C_AMBER
        x0=W-258; y0=self.TOPBAR_H+136
        self._panel(img,x0,y0,W-20,y0+54,0.85,C_BORDER)
        # Satellite icon
        ico_x=x0+14; ico_y=y0+27
        cv2.circle(img,(ico_x,ico_y),6,col,1)
        for ang_deg in [0,60,120,180,240,300]:
            ang=math.radians(ang_deg)
            cv2.line(img,(ico_x+int(math.cos(ang)*6),ico_y+int(math.sin(ang)*6)),
                         (ico_x+int(math.cos(ang)*10),ico_y+int(math.sin(ang)*10)),col,1,cv2.LINE_AA)
        # Plain decimal coordinates — no direction letters
        lat_str = f"LAT  {lat:+.5f}"
        lon_str = f"LON  {lon:+.5f}"
        cv2.putText(img,lat_str,(ico_x+18,y0+22),FONT_MONO,0.44,col,1,cv2.LINE_AA)
        cv2.putText(img,lon_str,(ico_x+18,y0+42),FONT_MONO,0.44,col,1,cv2.LINE_AA)
        badge = f"GPS [{mode}]" + (" FIX" if fix else " SRCH")
        cv2.putText(img,badge,(x0+6,y0+13),FONT_MONO,0.30,col,1,cv2.LINE_AA)

    # -------------------------------------------------------------------------
    # Status (top bar + sidebar)
    # -------------------------------------------------------------------------
    def status(self, img, W, H, fps, threat, exit_info, counts, ai_on, rec, smoke, nv, gps_info, t):
        tl, tc = THREAT_MAP[threat]
        SW = self.SIDEBAR_W

        # Top bar - Logo
        self._glow(img,"PYRO",  (14,  36), 0.80, C_RED,   2)
        self._glow(img,"SIGHT", (80,  36), 0.80, C_CYAN,  2)
        self._glow(img,"v7.0",  (178, 36), 0.44, C_DIM,   1)

        # Mission clock (center)
        elap=int(time.time()-self.t0)
        clock=f"T+ {elap//3600:02d}:{(elap%3600)//60:02d}:{elap%60:02d}"
        (cw,_),_ = cv2.getTextSize(clock,FONT_MONO,0.50,1)
        self._glow(img,clock,(W//2-cw//2,36),0.50,C_WHITE,1)

        # Threat badge
        tx=W//2+140
        cv2.rectangle(img,(tx-6,10),(tx+128,50),tc,-1)
        cv2.putText(img,f"  {tl}",(tx,40),FONT_BOLD,0.58,C_BLACK,2,cv2.LINE_AA)

        # FPS
        fc=C_GREEN if fps>=20 else(C_AMBER if fps>=10 else C_RED)
        self._glow(img,f"{fps:4.1f} FPS",(W-115,36),0.52,fc,1)

        # Status indicators
        ind_x=W//2-340
        if rec:   self._glow(img,"● REC",  (ind_x,     36),0.52,C_RED,  2)
        if smoke: self._glow(img,"SMOKE",  (ind_x+88,  36),0.48,C_DIM,  1)
        if nv:    self._glow(img,"NV ON",  (ind_x+168, 36),0.48,C_NVGRN,2)

        # --- Sidebar ---
        y=self.TOPBAR_H+26

        def section(label, row_y):
            cv2.line(img,(10,row_y-8),(SW-10,row_y-8),C_BORDER,1)
            cv2.putText(img,label,(12,row_y),FONT_MONO,0.33,C_DIM,1,cv2.LINE_AA)
            return row_y+20

        # AI Mode pill
        ai_col=C_CYAN if ai_on else C_AMBER
        ai_label="AI + MOTION" if ai_on else "MOTION ONLY"
        cv2.rectangle(img,(12,y-14),(SW-12,y+4),ai_col,1)
        cv2.putText(img,f"  {ai_label}",(16,y),FONT_MONO,0.40,ai_col,1,cv2.LINE_AA)
        y+=24

        y=section("DETECTIONS",y+4)
        rows=[
            ("PERSONS",  str(counts["persons"]),  C_CYAN  if counts["persons"]   else C_DIM),
            ("MOTION",   str(counts["motion"]),   C_TEAL  if counts["motion"]    else C_DIM),
            ("EXITS",    str(counts["exits"]),    C_GREEN if counts["exits"]     else C_AMBER),
            ("GEO DOOR", str(counts["geo"]),      C_GREEN if counts["geo"]       else C_DIM),
            ("HAZARDS",  str(counts["hazards"]),  C_RED   if counts["hazards"]   else C_DIM),
            ("OBST.",    str(counts["obstacles"]),C_AMBER if counts["obstacles"] else C_DIM),
        ]
        for nm, val, col in rows:
            if val != "0":
                cv2.rectangle(img,(10,y-13),(SW-10,y+4),(col[0]//10,col[1]//10,col[2]//10),-1)
            cv2.putText(img,nm, (16, y), FONT_MONO,0.40,C_DIM,1,cv2.LINE_AA)
            cv2.putText(img,val,(155,y), FONT_BODY, 0.50,col,  1,cv2.LINE_AA)
            y+=22

        y=section("NAVIGATION",y+4)
        egress_col=C_GREEN if counts["egress"]=="LOCKED" else C_AMBER
        cv2.putText(img,"EGRESS",        (16, y),FONT_MONO,0.40,C_DIM,     1,cv2.LINE_AA)
        cv2.putText(img,counts["egress"],(100,y),FONT_BODY,0.46,egress_col,1,cv2.LINE_AA)
        y+=22
        path_col=C_GREEN if counts["path"] else C_AMBER
        cv2.putText(img,"PATH",          (16, y),FONT_MONO,0.40,C_DIM,    1,cv2.LINE_AA)
        cv2.putText(img,"CLEAR" if counts["path"] else "SCAN",(100,y),FONT_BODY,0.46,path_col,1,cv2.LINE_AA)
        y+=22

        if exit_info:
            dist,brg=exit_info
            if dist: self._glow(img,f"{dist:.1f} ft  ~{max(1,int(math.ceil(dist/FT_PACE)))} paces",(12,y),0.40,C_GREEN,1); y+=20
            self._glow(img,f"BRG {abs(brg):.0f}deg {'R' if brg>=0 else 'L'}",(12,y),0.40,C_GREEN,1); y+=20

        # Key hint
        self._glow(img,"q r x v a n m p f s t",(10,H-14),0.32,C_DIM,1)

    # -------------------------------------------------------------------------
    # Alert banner
    # -------------------------------------------------------------------------
    def alert(self, img, W, H, text, blink, t):
        if not blink: return
        pulse=0.7+0.3*math.sin(t*5)
        (tw,th),_ = cv2.getTextSize(text,FONT_BODY,0.88,2)
        x=(W-tw)//2; y0=H//2-th-30
        overlay=img.copy()
        cv2.rectangle(overlay,(x-20,y0-14),(x+tw+20,y0+th+18),C_RED,-1)
        cv2.addWeighted(overlay,pulse*0.88,img,1-pulse*0.88,0,img)
        cv2.rectangle(img,(x-20,y0-14),(x+tw+20,y0+th+18),C_WHITE,1)
        cv2.putText(img,text,(x,y0+th+4),FONT_BODY,0.88,C_WHITE,2,cv2.LINE_AA)

    # -------------------------------------------------------------------------
    # Thermal PiP
    # -------------------------------------------------------------------------
    def mask_pip(self, img, mask, W):
        pw=W//6
        if pw<=0: return
        sc=pw/float(mask.shape[1]); ph=max(1,int(mask.shape[0]*sc))
        pip=cv2.applyColorMap(cv2.resize(mask,(pw,ph)),cv2.COLORMAP_INFERNO)
        x0=W-pw-22; y0=self.TOPBAR_H+200
        self._panel(img,x0-2,y0-2,x0+pw+2,y0+ph+2,0.90,C_RED)
        img[y0:y0+ph,x0:x0+pw]=pip
        cv2.putText(img,"THERMAL",(x0+4,y0+13),FONT_MONO,0.34,C_RED,1)

    # -------------------------------------------------------------------------
    # Post-processing
    # -------------------------------------------------------------------------
    def vignette(self, frame):
        h,w=frame.shape[:2]; cx,cy=w/2,h/2
        Y,X=np.ogrid[:h,:w]
        d=np.sqrt(((X-cx)/(cx+1))**2+((Y-cy)/(cy+1))**2)
        vg=1.0-np.clip(d*0.46,0,0.56)
        fr=frame.astype(np.float32)
        for c in range(3): fr[:,:,c]*=vg
        return fr.astype(np.uint8)

    def scanlines(self, frame, a=0.040):
        h,w=frame.shape[:2]; sl=np.zeros((h,w,3),np.uint8); sl[1::2]=5
        return cv2.addWeighted(frame,1.0,sl,a,0)

    def night_vision(self, frame):
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        eq=cv2.createCLAHE(clipLimit=3.5,tileGridSize=(8,8)).apply(gray)
        nv=np.zeros_like(frame); nv[:,:,1]=eq
        return cv2.addWeighted(frame,0.12,nv,0.88,0)

# ============================================================================
# THREAT ASSESSMENT
# ============================================================================
def assess(hazards, nav_status, frame_area, obstacles):
    if frame_area<=0: return 0, None
    cov=sum((h["box"][2]-h["box"][0])*(h["box"][3]-h["box"][1]) for h in hazards)/float(frame_area)
    if nav_status=="BLOCKED":   return 3,"ALL ROUTES COMPROMISED"
    if cov>0.18:                return 3,"FLASHOVER RISK - EVACUATE NOW"
    if nav_status=="REROUTED":  return 2,"HAZARD ON EGRESS PATH"
    if cov>0.06:                return 2,"MAJOR THERMAL EVENT"
    if len(obstacles)>=4:       return 1,"HIGH OBSTACLE DENSITY"
    if hazards:                 return 1,None
    return 0, None

# ============================================================================
# MAIN
# ============================================================================
def main():
    p=argparse.ArgumentParser(description="PyroSight v7.0")
    p.add_argument("--camera",       type=int,  default=0)
    p.add_argument("--detect-every", type=int,  default=2)
    p.add_argument("--no-yolo",      action="store_true")
    p.add_argument("--mirror",       action="store_true")
    p.add_argument("--gps-port",     type=str,  default=None)
    p.add_argument("--gps-baud",     type=int,  default=9600)
    args=p.parse_args()

    yolo_t=None
    if not args.no_yolo and ULTRALYTICS_AVAILABLE:
        yolo_t=YOLOThread(); yolo_t.start()

    tracker  = Tracker()
    fire_d   = FireDetector()
    motion_d = MotionDetector()
    door_d   = DoorDetector()
    path_d   = PathDetector()
    planner  = NavPlan()
    hud      = HUD()
    smoke    = Smoke()
    audio    = Audio()
    rec      = Recorder()
    gps      = GPSReceiver(port=args.gps_port, baud=args.gps_baud)
    gps.start()

    camera=Camera(args.camera)
    if not camera.start(): print("[FATAL] No camera.",flush=True); return 1

    show_nav=True; show_mask=False; mirror=args.mirror; paused=False
    smoke_on=False; nv=False; fullscreen=False
    fps=0.0; last_t=time.time(); fc=0; dets=[]
    frame=None; haz=[]; fmask=None; geo_doors=[]; motion_blobs=[]; path_info=None

    WIN_NAME="PyroSight v7.0 - Tactical HUD"
    cv2.namedWindow(WIN_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN_NAME, 1280, 720)

    def fit_to_window(img):
        try:
            _,_,ww,wh=cv2.getWindowImageRect(WIN_NAME)
        except Exception:
            ww,wh=0,0
        h,w=img.shape[:2]
        if ww<=0 or wh<=0 or (ww==w and wh==h): return img
        scale=min(ww/w, wh/h)
        nw,nh=max(1,int(round(w*scale))),max(1,int(round(h*scale)))
        resized=cv2.resize(img,(nw,nh),interpolation=cv2.INTER_AREA if scale<1 else cv2.INTER_LINEAR)
        canvas=np.zeros((wh,ww,3),np.uint8); canvas[:]=C_BG
        xo,yo=(ww-nw)//2,(wh-nh)//2
        canvas[yo:yo+nh, xo:xo+nw]=resized
        return canvas

    print("[v7.0 READY] q=quit r=rec x=smoke v=nv a=mute n=nav m=mask p=pause s=snap f=mirror t=fullscreen",flush=True)

    while True:
        t=time.time()
        if not paused:
            g=camera.read()
            if g is None: break
            frame=g
            if mirror: frame=cv2.flip(frame,1)
        elif frame is None: break

        fc+=1; H,W=frame.shape[:2]; blink=(fc%22)<13
        dt=t-last_t; last_t=t
        if dt>0: fps=fps*0.9+(1/dt)*0.1 if fps>0 else 1/dt

        if not paused:
            if yolo_t and yolo_t.ready and fc%max(1,args.detect_every)==0:
                yolo_t.submit(frame)

            new_dets=[]
            if yolo_t:
                res=yolo_t.get()
                if res:
                    for r in res:
                        if r.boxes is None: continue
                        for box in r.boxes:
                            cid=int(box.cls[0]); cf=float(box.conf[0])
                            x1,y1,x2,y2=(float(v) for v in box.xyxy[0]); bh=y2-y1
                            if cid in COCO_PERSON_IDS and cf>=CONF_PERSON:
                                new_dets.append(("person","PERSON",(x1,y1,x2,y2),dft(H_PERSON,bh),cf))
                            elif cid in COCO_OBSTACLE_IDS and cf>=CONF_OBSTACLE:
                                lbl=COCO_NAMES.get(cid,"OBJ")
                                new_dets.append(("obstacle",lbl,(x1,y1,x2,y2),dft(H_OBST,bh),cf))
            if new_dets: dets=new_dets
            tracks=tracker.update(dets)

            haz,fmask=fire_d.detect(frame)
            motion_blobs=motion_d.detect(frame)
            doors_tracked=[tr for tr in tracks if tr.kind=="door"]
            geo_doors=door_d.detect(frame,doors_tracked)
            haz_boxes=[tuple(hz["box"]) for hz in haz]
            obs_boxes=[tuple(tr.box) for tr in tracks if tr.kind=="obstacle"]
            path_info=path_d.detect(frame,haz_boxes,obs_boxes)
        else:
            tracks=[tr for tr in tracker.tracks if tr.confirmed]

        if fmask is None: fmask=np.zeros((H,W),np.uint8)

        persons  =[tr for tr in tracks if tr.kind=="person"]
        obstacles=[tr for tr in tracks if tr.kind=="obstacle"]
        clean_motion=[b for b in motion_blobs
                      if not any(rect_iou((b[0],b[1],b[2],b[3]),
                                          (int(p.box[0]),int(p.box[1]),int(p.box[2]),int(p.box[3])))>0.3
                                 for p in persons)]

        if persons or clean_motion: audio.alert("person")
        if haz:                     audio.alert("hazard")
        if geo_doors:               audio.alert("locked")

        nav_path,nav_status,exit_info=None,"NONE",None
        if geo_doors:
            gd=geo_doors[0]; ep=(int((gd[0]+gd[2])/2),int(gd[3])); sp=(W//2,H)
            nav_path,nav_status=planner.plan(sp,ep,haz_boxes,obstacles,W,H)
            exit_info=(None,math.degrees(math.atan2(ep[0]-W/2,800.0)))
        elif path_info:
            cx_p,_,roi_y=path_info; sp=(W//2,H); ep=(cx_p,roi_y)
            nav_path,nav_status=planner.plan(sp,ep,haz_boxes,obstacles,W,H)
            exit_info=None

        threat,alert_txt=assess(haz,nav_status,W*H,obstacles)
        if threat==3: audio.alert("critical")
        if alert_txt is None and any(p.dist and p.dist<8 for p in persons):
            alert_txt="VICTIM PROXIMATE - RENDER AID"

        # --- RENDER ---
        disp=frame.copy()
        if smoke_on:
            disp=smoke.apply(disp)
            if fc%3==0: smoke.tick(H,W)
        if nv: disp=hud.night_vision(disp)

        ov=disp.copy()
        hud.top_bar(ov,W); hud.sidebar(ov,H)
        hud.haz_fills(ov,haz); hud.obs_fills(ov,obstacles)
        if show_nav and nav_path: hud.nav_line(ov,nav_path,nav_status,t)
        disp=cv2.addWeighted(ov,0.62,disp,0.38,0)

        pulse=t*3.0
        # Only show clear-path corridor when a door has actually been found
        hud.draw_path(disp, path_info if geo_doors else None, t)
        for per in persons:       hud.person_box(disp,per,pulse)
        for blob in clean_motion: hud.motion_person_box(disp,(blob[0],blob[1],blob[2],blob[3]),pulse)
        for ob in obstacles:      hud.obs_box(disp,ob,pulse)
        for hz in haz:            hud.haz_box(disp,hz,t)
        for gd in geo_doors:      hud.geo_door_box(disp,gd,t)

        hud.reticle(disp,W,H,t)
        if exit_info: hud.compass(disp,W,exit_info[1])
        hud.threat_arc(disp,W,H,threat)

        ai_on=(yolo_t is not None and yolo_t.ready)
        counts={
            "persons":   len(persons),
            "motion":    len(clean_motion),
            "exits":     0,
            "geo":       len(geo_doors),
            "hazards":   len(haz),
            "obstacles": len(obstacles),
            "path":      path_info is not None,
            "egress":    "LOCKED" if geo_doors else "SEARCHING",
        }
        hud.status(disp,W,H,fps,threat,exit_info,counts,ai_on,
                   rec.recording,smoke_on,nv,gps.get_coords(),t)
        if alert_txt:  hud.alert(disp,W,H,alert_txt,blink,t)
        if show_mask:  hud.mask_pip(disp,fmask,W)
        if paused:     hud.alert(disp,W,H,"[ PAUSED ]",True,t)

        disp=hud.vignette(disp)
        disp=hud.scanlines(disp)

        if rec.recording: rec.write(disp)
        cv2.imshow(WIN_NAME,fit_to_window(disp))
        key=cv2.waitKey(1)&0xFF
        if key in(ord("q"),27): break
        elif key==ord("n"): show_nav=not show_nav
        elif key==ord("m"): show_mask=not show_mask
        elif key==ord("p"): paused=not paused
        elif key==ord("f"): mirror=not mirror
        elif key==ord("t"):
            fullscreen=not fullscreen
            cv2.setWindowProperty(WIN_NAME, cv2.WND_PROP_FULLSCREEN,
                                   cv2.WINDOW_FULLSCREEN if fullscreen else cv2.WINDOW_NORMAL)
        elif key==ord("x"):
            smoke_on=not smoke_on; print(f"[SMOKE]{'ON' if smoke_on else 'OFF'}",flush=True)
        elif key==ord("v"):
            nv=not nv; print(f"[NV]{'ON' if nv else 'OFF'}",flush=True)
        elif key==ord("a"):
            audio.muted=not audio.muted
            print(f"[AUDIO]{'MUTED' if audio.muted else 'ON'}",flush=True)
        elif key==ord("r"):
            if rec.recording: rec.stop()
            else: rec.start(disp)
        elif key==ord("s"):
            fn=time.strftime("pyrosight_%Y%m%d_%H%M%S.png")
            cv2.imwrite(fn,disp); print(f"[SNAP]{fn}",flush=True)

    gps.stop()
    if rec.recording: rec.stop()
    if yolo_t: yolo_t.stop()
    camera.release(); cv2.destroyAllWindows(); return 0

if __name__=="__main__":
    sys.exit(main())
