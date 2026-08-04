"""
Classical fire detection on the RGB stream.

A real flame — from a lighter up to a room fire — has a characteristic
signature that skin, wood, and hi-vis fabric do not:

  * a WHITE-HOT CORE: near-saturated brightness with LOW color saturation
    (the sensor blows out), fringed by
  * a COLORED RING of saturated orange/yellow, and
  * temporal FLICKER: the mask shimmers frame to frame, and
  * a HUE GRADIENT across the region (white -> yellow -> orange -> red).

The detector builds two masks — colored flame and white-hot — and only
accepts white-hot pixels adjacent to colored flame (a bare white blob is a
lamp; a bare orange blob might be a jacket).

The dominant false positive in live testing is human skin: a face lit warm
sits inside the orange hue band, and the specular highlight on a nose or a
forehead is a bright, low-saturation blob directly adjacent to it — which is
structurally identical to "white core inside colored ring". Three independent
gates reject it:

  * SKIN CHROMA — a YCrCb skin-chroma test (the standard Cr/Cb box). A region
    that is mostly skin-chroma is never fire, whatever its brightness.
  * HUE SPREAD — flame runs a gradient from a blown-out core through yellow
    to deep orange; skin is chromatically flat.
  * PERSISTENCE — a flame stays in roughly one place across frames while
    flickering. A single-frame highlight from a head turn does not.

Confidence is assembled from the evidence actually present, and fusion caps
anything without independent thermal corroboration below the confirmed tier.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import cv2
import numpy as np

# Colored-flame bands (OpenCV hue 0-179).
ORANGE_LO, ORANGE_HI = (5, 140, 180), (22, 255, 255)
YELLOW_LO, YELLOW_HI = (22, 100, 200), (35, 255, 255)
# White-hot core: blown out, not merely bright. A specular highlight on skin
# sits around V 235-245; a flame core pins the sensor.
WHITE_HOT_V_MIN = 248
WHITE_HOT_S_MAX = 90

MIN_AREA_FRAC = 0.0003     # ~90 px at 640x480: a small lighter flame
MAX_AREA_FRAC = 0.45       # larger = white balance / lighting, not flame
REGION_MIN_V = 190.0       # region must be emissive-bright ...
REGION_OVER_SCENE_V = 20.0  # ... and clearly brighter than the scene
WHITE_CORE_MIN_PX = 6      # glint-sized specks don't count as a core

# Skin chroma box in YCrCb (Chai & Ngan). Wide enough to cover every skin
# tone under warm indoor light, which is exactly what we want to exclude.
SKIN_CR = (133, 177)
SKIN_CB = (77, 127)
SKIN_REJECT_FRAC = 0.30    # region is skin, not fire
SKIN_SUSPECT_FRAC = 0.12   # some skin present: demand harder evidence

HUE_SPREAD_MIN = 3.0       # flame runs a colour gradient; skin does not
PERSIST_RADIUS_FRAC = 0.06  # same flame, frame to frame
PERSIST_FRAMES = 4          # history depth used for the persistence test

# Kept for external callers (pseudo-thermal shares the exact same model of
# what "fire-colored" means so the two never disagree).
HSV_FIRE_RANGES = [(ORANGE_LO, ORANGE_HI), (YELLOW_LO, YELLOW_HI)]

_K3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
_K7 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
_K9 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))


def build_fire_mask(frame_bgr: np.ndarray,
                    hsv: np.ndarray = None,
                    exclude_skin: bool = True) -> Tuple[np.ndarray, np.ndarray]:
    """Returns (fire_mask, white_core_mask). White-hot pixels only count
    when adjacent to colored flame — that adjacency is what separates a
    flame core from a lamp or a specular glint.

    Skin is removed from the colored mask *before* the adjacency test, not
    after: a highlight on a nose is white-hot and touches skin-coloured
    pixels, so leaving skin in the ring would qualify it as a flame core."""
    if hsv is None:
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    colored = (cv2.inRange(hsv, np.array(ORANGE_LO), np.array(ORANGE_HI))
               | cv2.inRange(hsv, np.array(YELLOW_LO), np.array(YELLOW_HI)))
    if exclude_skin:
        colored = cv2.bitwise_and(colored, cv2.bitwise_not(skin_mask(frame_bgr)))
    white = cv2.inRange(hsv, np.array((0, 0, WHITE_HOT_V_MIN)),
                        np.array((179, WHITE_HOT_S_MAX, 255)))
    ring = cv2.dilate(colored, _K9)
    white_core = cv2.bitwise_and(white, ring)
    return cv2.bitwise_or(colored, white_core), white_core


def skin_mask(frame_bgr: np.ndarray) -> np.ndarray:
    """Standard YCrCb skin-chroma test. Deliberately generous: this mask is
    used to *reject* fire candidates, so over-covering skin is the safe
    direction and a genuine flame never lands inside the chroma box."""
    ycrcb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2YCrCb)
    return cv2.inRange(
        ycrcb,
        np.array((0, SKIN_CR[0], SKIN_CB[0]), dtype=np.uint8),
        np.array((255, SKIN_CR[1], SKIN_CB[1]), dtype=np.uint8),
    )


class FireDetector:
    def __init__(self):
        self._prev_mask: np.ndarray = None  # type: ignore[assignment]
        # Recent accepted centroids, newest last: [[(cx, cy), ...], ...]
        self._history: List[List[Tuple[float, float]]] = []

    def _persisted(self, cx: float, cy: float, radius: float) -> int:
        """How many of the recent frames held a candidate at this spot."""
        hits = 0
        for frame in self._history:
            for px, py in frame:
                if (px - cx) ** 2 + (py - cy) ** 2 <= radius * radius:
                    hits += 1
                    break
        return hits

    def detect(self, frame_bgr: np.ndarray) -> List[Dict[str, Any]]:
        h, w = frame_bgr.shape[:2]
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        v_chan = hsv[..., 2].astype(np.float32)
        hue_chan = hsv[..., 0].astype(np.float32)
        scene_v = float(np.mean(v_chan))
        skin = skin_mask(frame_bgr) > 0

        mask, white_core = build_fire_mask(frame_bgr, hsv)
        # Gentle cleanup only — a 5x5 opening would erase a lighter flame.
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, _K3)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, _K7)

        flicker = None
        if self._prev_mask is not None and self._prev_mask.shape == mask.shape:
            flicker = cv2.bitwise_xor(mask, self._prev_mask)
        self._prev_mask = mask

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        min_area = max(1.0, MIN_AREA_FRAC * w * h)
        max_area = MAX_AREA_FRAC * w * h
        out: List[Dict[str, Any]] = []
        for c in contours:
            area = cv2.contourArea(c)
            if area < min_area or area > max_area:
                continue
            x, y, bw, bh = cv2.boundingRect(c)

            region_mask = mask[y:y + bh, x:x + bw] > 0
            if not region_mask.any():
                continue

            # --- gate 1: skin chroma -------------------------------------
            # A face lit warm is orange, bright, and adjacent to a specular
            # highlight. Chroma is what separates it from combustion.
            skin_frac = float(
                np.count_nonzero(skin[y:y + bh, x:x + bw][region_mask])
            ) / float(max(1, np.count_nonzero(region_mask)))
            if skin_frac >= SKIN_REJECT_FRAC:
                continue

            white_px = int(np.count_nonzero(white_core[y:y + bh, x:x + bw]))
            has_core = white_px >= WHITE_CORE_MIN_PX

            # Emissive-brightness gate (a white core is itself proof of
            # emission, so core-bearing regions pass automatically).
            region_v = float(np.mean(v_chan[y:y + bh, x:x + bw][region_mask]))
            if not has_core and (region_v < REGION_MIN_V
                                 or region_v < scene_v + REGION_OVER_SCENE_V):
                continue

            # --- gate 2: hue gradient ------------------------------------
            # Flame is a colour ramp; skin, hi-vis fabric and painted wood are
            # chromatically flat. Hue wraps at 180, but every pixel here is
            # already inside the 5-35 flame band, so a plain std is valid.
            hue_spread = float(
                np.std(hue_chan[y:y + bh, x:x + bw][region_mask])
            )

            flicker_ratio = 0.0
            if flicker is not None:
                region = flicker[y:y + bh, x:x + bw]
                flicker_ratio = (float(np.count_nonzero(region))
                                 / float(max(1, bw * bh)))

            # --- gate 3: persistence -------------------------------------
            cx = x + bw / 2.0
            cy = y + bh / 2.0
            persist = self._persisted(cx, cy, PERSIST_RADIUS_FRAC * max(w, h))

            # Evidence-assembled confidence. Every term is something the
            # sensor actually measured; nothing is assumed.
            conf = 0.32
            if has_core:
                conf += 0.12
            conf += min(0.15, (area / (w * h)) * 3.0)
            if hue_spread >= HUE_SPREAD_MIN:
                conf += 0.06
            else:
                conf = min(conf, 0.30)   # flat colour: not combustion
            if flicker_ratio < 0.02:
                conf = min(conf, 0.30)   # rock-steady: a lamp or a jacket
            elif flicker_ratio > 0.05:
                conf = min(0.80, conf + 0.15)
            if persist == 0:
                conf = min(conf, 0.34)   # first sighting is never a claim
            elif persist >= 2:
                conf = min(0.85, conf + 0.08)
            if skin_frac >= SKIN_SUSPECT_FRAC and not (
                has_core and flicker_ratio > 0.05
            ):
                # Skin present at the edges: only a blown-out, flickering core
                # is allowed to overrule it.
                conf = min(conf, 0.28)

            out.append({"cls": "fire", "conf": round(conf, 3),
                        "box": [float(x), float(y), float(x + bw), float(y + bh)],
                        "source": "hsv",
                        "flicker": round(flicker_ratio, 3),
                        "hue_spread": round(hue_spread, 2),
                        "skin_frac": round(skin_frac, 3),
                        "persist": persist,
                        "white_core_px": white_px})

        self._history.append([( (d["box"][0] + d["box"][2]) / 2.0,
                                (d["box"][1] + d["box"][3]) / 2.0 )
                              for d in out])
        if len(self._history) > PERSIST_FRAMES:
            self._history.pop(0)
        return out
