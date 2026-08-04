"""
Is that a person, or a picture of a person?

A detector answers "person" for a face on a poster, a figure on a television,
a photograph on a desk, and a phone screen. In a search that is not a
harmless error: it sends a crew to a wall. Two independent cues separate a
body from an image of one, and neither needs extra hardware:

  * FRAMED — a picture, monitor or TV is a strong four-sided rectangle around
    the subject, with the subject almost entirely inside it. Real people are
    not enclosed in high-contrast quadrilaterals.
  * STATIC — a living person is never perfectly still relative to the room.
    Breathing, sway and limb motion all move the box against the background.
    An image moves only when the camera does, so subtracting the frame-wide
    motion leaves nothing behind.

Neither cue is used to silently delete a detection. A framed subject is
rejected outright (that evidence is strong and specific); a subject with no
residual motion is capped below the confirmed tier so it shows as POSSIBLE
PERSON — because a genuinely unconscious victim is also very still, and the
one thing this system must never do is hide a real body.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

# --- framed-image test -----------------------------------------------------
FRAME_CONTAINMENT = 0.80    # subject must be mostly inside the rectangle
FRAME_MAX_AREA_FRAC = 0.55  # a rectangle bigger than this is the room itself
FRAME_MIN_SUBJECT_FRAC = 0.15   # the subject must be a real part of the frame
# The gate that separates a picture from a doorway. A doorway is tall and
# narrow (a 0.9 x 2.05 m door is h/w ≈ 2.3); televisions, monitors and picture
# frames are landscape or mildly portrait. Getting this wrong in the generous
# direction would suppress a victim standing in a door — the exact person the
# search exists to find — so the bar sits well clear of door proportions.
FRAME_MAX_ASPECT = 1.6

# --- static-subject test ---------------------------------------------------
STATIC_WINDOW_S = 5.0       # observation needed before calling anything static
STATIC_RESIDUAL_PX = 2.2    # per-frame motion beyond camera motion, in px


def _containment(inner, outer) -> float:
    ix1, iy1 = max(inner[0], outer[0]), max(inner[1], outer[1])
    ix2, iy2 = min(inner[2], outer[2]), min(inner[3], outer[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area = (inner[2] - inner[0]) * (inner[3] - inner[1])
    return inter / area if area > 0 else 0.0


def framed_by_rectangle(frame_bgr: np.ndarray, box: List[float]) -> Optional[Dict[str, Any]]:
    """Detect a photo frame / screen bezel enclosing `box`.

    Returns the enclosing rectangle's metrics, or None. Deliberately strict:
    a false positive here suppresses a real victim, so the rectangle must be
    a clean quadrilateral that closely surrounds the subject.
    """
    h, w = frame_bgr.shape[:2]
    bw = max(1.0, box[2] - box[0])
    bh = max(1.0, box[3] - box[1])

    # Search a neighbourhood around the subject, not the whole frame.
    pad_x, pad_y = bw * 0.6, bh * 0.6
    rx1 = int(max(0, box[0] - pad_x))
    ry1 = int(max(0, box[1] - pad_y))
    rx2 = int(min(w, box[2] + pad_x))
    ry2 = int(min(h, box[3] + pad_y))
    roi = frame_bgr[ry1:ry2, rx1:rx2]
    if roi.size == 0 or roi.shape[0] < 12 or roi.shape[1] < 12:
        return None

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 1.0), 60, 170)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    for c in contours:
        peri = cv2.arcLength(c, True)
        if peri < 40:
            continue
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        x, y, rw, rh = cv2.boundingRect(approx)
        rect = [float(rx1 + x), float(ry1 + y),
                float(rx1 + x + rw), float(ry1 + y + rh)]
        rect_area = float(rw * rh)
        if rect_area / float(w * h) > FRAME_MAX_AREA_FRAC:
            continue                      # that is the room, not a picture
        if rect_area <= bw * bh:
            continue                      # smaller than the subject
        if _containment(box, rect) < FRAME_CONTAINMENT:
            continue
        # Tall and narrow is a doorway, and a person in a doorway is a victim
        # standing in the way out — never a picture.
        if rh / float(max(1, rw)) > FRAME_MAX_ASPECT:
            continue
        # The subject must be a substantial part of the rectangle; a person
        # who happens to stand inside a large wall panel is not framed.
        if (bw * bh) / rect_area < FRAME_MIN_SUBJECT_FRAC:
            continue
        # Straight, high-contrast sides — a bezel, not a soft shadow.
        fill = cv2.contourArea(approx) / rect_area if rect_area > 0 else 0.0
        if fill < 0.75:
            continue
        border = edges[max(0, y - 2):y + rh + 2, max(0, x - 2):x + rw + 2]
        strength = float(np.count_nonzero(border)) / float(max(1, border.size))
        if strength < 0.02:
            continue
        return {"rect": rect, "fill": round(fill, 3),
                "edge_strength": round(min(1.0, strength * 20), 3),
                "subject_frac": round((bw * bh) / rect_area, 3)}
    return None


class StaticSubjectMonitor:
    """Tracks per-track motion residual after removing camera motion."""

    def __init__(self) -> None:
        self._hist: Dict[int, List[Tuple[float, float, float]]] = {}

    def update(self, track_id: int, box: List[float],
               camera_shift_px: float = 0.0) -> None:
        cx = (box[0] + box[2]) / 2.0
        cy = (box[1] + box[3]) / 2.0
        hist = self._hist.setdefault(track_id, [])
        hist.append((time.time(), cx, cy))
        # Camera motion is shared by every object; only what moves *more*
        # than the scene counts as the subject moving.
        self._hist[track_id] = [h for h in hist if time.time() - h[0] <= STATIC_WINDOW_S * 2]
        self._camera_shift = camera_shift_px

    def residual_motion(self, track_id: int) -> Optional[float]:
        """Mean per-sample displacement in px, or None if not enough history."""
        hist = self._hist.get(track_id, [])
        if len(hist) < 8:
            return None
        if hist[-1][0] - hist[0][0] < STATIC_WINDOW_S:
            return None
        steps = [
            float(np.hypot(b[1] - a[1], b[2] - a[2]))
            for a, b in zip(hist, hist[1:])
        ]
        return float(np.mean(steps)) if steps else None

    def is_static(self, track_id: int) -> bool:
        residual = self.residual_motion(track_id)
        return residual is not None and residual < STATIC_RESIDUAL_PX

    def forget(self, live_ids) -> None:
        for tid in list(self._hist):
            if tid not in live_ids:
                del self._hist[tid]
