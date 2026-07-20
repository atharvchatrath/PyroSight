"""
RGB + thermal fusion.

Takes the neural/sim detections, classical HSV fire regions, and thermal
analysis, and produces one unified detection list where each item may carry
`thermal_confirmed`. Cross-modal corroboration is the core trust mechanism:

  * person/firefighter + body-temperature blob  -> confidence boost
  * fire (neural or HSV) + hotspot              -> confidence boost, merged
  * hotspot with no visual counterpart          -> emitted as class "hotspot"
    (heat behind a wall / door is exactly what the Lepton is for)
  * fire with NO thermal support                -> confidence capped (could
    be a reflection, hi-vis jacket, or sunlight)
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .thermal_analysis import ThermalAnalyzer

PERSON_CLASSES = ("person", "firefighter")
PERSON_BOOST = 0.12
FIRE_BOOST = 0.18
UNCONFIRMED_FIRE_CAP = 0.55  # below confirmed tier: renders as uncertain


def _iou(a: List[float], b: List[float]) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = ((a[2] - a[0]) * (a[3] - a[1])
             + (b[2] - b[0]) * (b[3] - b[1]) - inter)
    return inter / union if union > 0 else 0.0


def _overlap_frac(inner: List[float], outer: List[float]) -> float:
    """Fraction of `inner` covered by `outer`."""
    ix1, iy1 = max(inner[0], outer[0]), max(inner[1], outer[1])
    ix2, iy2 = min(inner[2], outer[2]), min(inner[3], outer[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area = (inner[2] - inner[0]) * (inner[3] - inner[1])
    return inter / area if area > 0 else 0.0


def fuse(detections: List[Dict[str, Any]],
         fire_regions: List[Dict[str, Any]],
         thermal: Dict[str, Any],
         rgb_wh: Tuple[int, int],
         thermal_wh: Tuple[int, int],
         thermal_independent: bool = True) -> List[Dict[str, Any]]:
    """`thermal_independent` is False when the thermal field is *derived
    from the RGB image* (no Lepton attached). A derived field is not
    independent evidence — treating it as confirmation would let a false
    color match confirm itself in a loop. In that case: no confidence
    boosts, no hotspot promotion, and fire stays capped below the
    confirmed tier until real thermal hardware corroborates it."""
    fused: List[Dict[str, Any]] = []

    hotspot_boxes_rgb = [
        (ThermalAnalyzer.scale_box(h["box"], thermal_wh, rgb_wh), h)
        for h in thermal.get("hotspots", [])
    ]
    body_boxes_rgb = [
        ThermalAnalyzer.scale_box(b["box"], thermal_wh, rgb_wh)
        for b in thermal.get("body_regions", [])
    ]

    # --- merge HSV fire regions into the detection list (dedupe by IoU) ---
    all_dets = [dict(d) for d in detections]
    for fr in fire_regions:
        dup = next((d for d in all_dets
                    if d["cls"] == "fire" and _iou(d["box"], fr["box"]) > 0.3), None)
        if dup is not None:
            dup["conf"] = max(dup["conf"], fr["conf"])
            dup["hsv_confirmed"] = True
        else:
            all_dets.append(dict(fr))

    matched_hotspots = set()
    for det in all_dets:
        det.setdefault("thermal_confirmed", False)
        cls = det["cls"]
        if cls in PERSON_CLASSES and thermal_independent:
            for bb in body_boxes_rgb:
                if _overlap_frac(bb, det["box"]) > 0.3 or _iou(bb, det["box"]) > 0.15:
                    det["thermal_confirmed"] = True
                    det["conf"] = min(0.99, det["conf"] + PERSON_BOOST)
                    break
        elif cls == "fire":
            supported = False
            if thermal_independent:
                for i, (hb, spot) in enumerate(hotspot_boxes_rgb):
                    if _iou(hb, det["box"]) > 0.1 or _overlap_frac(hb, det["box"]) > 0.4:
                        supported = True
                        matched_hotspots.add(i)
                        det["max_temp_c"] = spot["max_temp_c"]
                        break
            if supported:
                det["thermal_confirmed"] = True
                det["conf"] = min(0.99, det["conf"] + FIRE_BOOST)
            else:
                # Without independent heat evidence, color+flicker alone
                # never reaches the confirmed tier.
                det["conf"] = min(det["conf"], UNCONFIRMED_FIRE_CAP)
        fused.append(det)

    # --- unmatched hotspots become first-class detections (measured
    # thermal only: an RGB-derived field would just re-emit the same
    # color regions under a scarier name) ---
    if thermal_independent:
        for i, (hb, spot) in enumerate(hotspot_boxes_rgb):
            if i in matched_hotspots:
                continue
            sev = spot.get("severity", "elevated")
            conf = {"critical": 0.95, "severe": 0.88}.get(sev, 0.72)
            fused.append({
                "cls": "hotspot",
                "conf": conf,
                "box": hb,
                "thermal_confirmed": True,
                "max_temp_c": spot["max_temp_c"],
                "severity": sev,
            })

    return fused
