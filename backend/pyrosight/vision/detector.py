"""
Object-detection backends behind one interface:

    detect(frame_bgr) -> [{"cls", "conf", "box": [x1,y1,x2,y2]}, ...]

Selection chain (build_detector):
  1. OnnxDetector        — YOLOv8 ONNX via onnxruntime. This is the Pi 5
                           production path (~15-25 FPS at 416 px with 4
                           threads). Letterbox + decode + NMS implemented
                           here, no ultralytics dependency at runtime.
  2. UltralyticsDetector — YOLO-World .pt via the ultralytics package.
                           Open-vocabulary: detects doors / exit signs /
                           windows / stairs by text prompt. Great on dev
                           machines, too heavy for the Pi.
  3. NullDetector        — no neural detection; classical CV (fire/thermal)
                           still runs. The platform degrades, never dies.

Sim mode bypasses this module: ground-truth boxes come from the SimWorld.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from ..config import VisionConfig
from . import classes as taxonomy


class BaseDetector:
    name = "base"
    available = False

    def detect(self, frame_bgr: np.ndarray) -> List[Dict[str, Any]]:
        raise NotImplementedError


def _passes_class_filters(cls_name: str, conf: float, box, frame_w: int,
                          frame_h: int) -> bool:
    """Per-class confidence floors + geometry sanity gates."""
    if conf < taxonomy.CLASS_CONF_THRESHOLDS.get(cls_name, 0.30):
        return False
    geom = taxonomy.CLASS_GEOMETRY.get(cls_name)
    if geom is None:
        return True
    min_area_frac, min_hw, max_hw = geom
    w = max(1.0, box[2] - box[0])
    h = max(1.0, box[3] - box[1])
    if (w * h) / float(frame_w * frame_h) < min_area_frac:
        return False
    ratio = h / w
    if min_hw is not None and ratio < min_hw:
        return False
    if max_hw is not None and ratio > max_hw:
        return False
    # Near-frame-filling boxes are almost always hallucinations.
    if cls_name != "hallway" and (w >= frame_w * 0.95 and h >= frame_h * 0.95):
        return False
    return True


class NullDetector(BaseDetector):
    name = "none"
    available = True

    def detect(self, frame_bgr: np.ndarray) -> List[Dict[str, Any]]:
        return []


def _letterbox(img: np.ndarray, size: int):
    h, w = img.shape[:2]
    scale = size / max(h, w)
    nh, nw = int(round(h * scale)), int(round(w * scale))
    resized = cv2.resize(img, (nw, nh))
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    top, left = (size - nh) // 2, (size - nw) // 2
    canvas[top:top + nh, left:left + nw] = resized
    return canvas, scale, left, top


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_thr: float) -> List[int]:
    idxs = scores.argsort()[::-1]
    keep: List[int] = []
    while idxs.size > 0:
        i = idxs[0]
        keep.append(int(i))
        if idxs.size == 1:
            break
        rest = idxs[1:]
        xx1 = np.maximum(boxes[i, 0], boxes[rest, 0])
        yy1 = np.maximum(boxes[i, 1], boxes[rest, 1])
        xx2 = np.minimum(boxes[i, 2], boxes[rest, 2])
        yy2 = np.minimum(boxes[i, 3], boxes[rest, 3])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        area_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
        area_r = (boxes[rest, 2] - boxes[rest, 0]) * (boxes[rest, 3] - boxes[rest, 1])
        union = area_i + area_r - inter
        iou = np.where(union > 0, inter / union, 0.0)
        idxs = rest[iou <= iou_thr]
    return keep


class OnnxDetector(BaseDetector):
    name = "onnx"

    def __init__(self, cfg: VisionConfig):
        self.cfg = cfg
        self.session = None
        self.class_map: Dict[int, str] = {}
        model_path = Path(cfg.onnx_model)
        if not model_path.exists():
            return
        try:
            import onnxruntime as ort
        except ImportError:
            return
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 4  # Pi 5 has 4 Cortex-A76 cores
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        try:
            self.session = ort.InferenceSession(
                str(model_path), sess_options=opts,
                providers=["CPUExecutionProvider"])
        except Exception:  # noqa: BLE001 - fall through the chain
            self.session = None
            return
        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        # Respect the graph's own input size (exports are usually fixed-
        # shape); silently feeding a different size would fail every frame.
        self._input_size = (int(inp.shape[2])
                            if isinstance(inp.shape[2], int) else cfg.input_size)
        # Class mapping: a sidecar lists one name per model class index —
        # either taxonomy names (custom fire-service model) or YOLO-World
        # prompts (vocabulary-baked export); a stock COCO model maps person.
        sidecar = model_path.with_suffix(".classes.txt")
        if sidecar.exists():
            names = [ln.strip() for ln in sidecar.read_text().splitlines() if ln.strip()]
            self.class_map = {}
            for i, n in enumerate(names):
                if taxonomy.known(n):
                    self.class_map[i] = n
                elif n.lower() in taxonomy.WORLD_PROMPT_TO_CLASS:
                    self.class_map[i] = taxonomy.WORLD_PROMPT_TO_CLASS[n.lower()]
        else:
            self.class_map = dict(taxonomy.COCO_TO_CLASS)
        self.available = True

    def detect(self, frame_bgr: np.ndarray) -> List[Dict[str, Any]]:
        if self.session is None:
            return []
        size = self._input_size
        img, scale, pad_x, pad_y = _letterbox(frame_bgr, size)
        blob = img[:, :, ::-1].astype(np.float32) / 255.0  # BGR -> RGB
        blob = blob.transpose(2, 0, 1)[None]
        out = self.session.run(None, {self.input_name: blob})[0]
        # YOLOv8 output: (1, 4+nc, N) -> (N, 4+nc)
        preds = out[0].T if out.shape[1] < out.shape[2] else out[0]
        boxes_xywh = preds[:, :4]
        scores_all = preds[:, 4:]
        cls_ids = scores_all.argmax(axis=1)
        confs = scores_all[np.arange(len(cls_ids)), cls_ids]
        mask = confs >= self.cfg.conf_threshold
        if not mask.any():
            return []
        boxes_xywh, cls_ids, confs = boxes_xywh[mask], cls_ids[mask], confs[mask]
        boxes = np.empty_like(boxes_xywh)
        boxes[:, 0] = boxes_xywh[:, 0] - boxes_xywh[:, 2] / 2
        boxes[:, 1] = boxes_xywh[:, 1] - boxes_xywh[:, 3] / 2
        boxes[:, 2] = boxes_xywh[:, 0] + boxes_xywh[:, 2] / 2
        boxes[:, 3] = boxes_xywh[:, 1] + boxes_xywh[:, 3] / 2
        # NMS per mapped taxonomy class: multiple prompts for one class
        # (e.g. "window" / "glass window") dedupe against each other, while
        # a person standing in a doorway never suppresses the door.
        keep: List[int] = []
        mapped = np.array([taxonomy.REGISTRY.get(
            self.class_map.get(int(c), ""), None) is not None
            for c in cls_ids])
        cls_keys = np.array([self.class_map.get(int(c), "?") for c in cls_ids])
        for key in set(cls_keys[mapped]):
            idx = np.where(cls_keys == key)[0]
            for j in _nms(boxes[idx], confs[idx], self.cfg.nms_iou):
                keep.append(int(idx[j]))
        h, w = frame_bgr.shape[:2]
        results = []
        for i in keep:
            cls_name = self.class_map.get(int(cls_ids[i]))
            if cls_name is None:
                continue
            x1 = (boxes[i, 0] - pad_x) / scale
            y1 = (boxes[i, 1] - pad_y) / scale
            x2 = (boxes[i, 2] - pad_x) / scale
            y2 = (boxes[i, 3] - pad_y) / scale
            box = [float(max(0, x1)), float(max(0, y1)),
                   float(min(w, x2)), float(min(h, y2))]
            if not _passes_class_filters(cls_name, float(confs[i]), box, w, h):
                continue
            results.append({"cls": cls_name, "conf": float(confs[i]), "box": box})
        return results


class UltralyticsDetector(BaseDetector):
    name = "yolo-world"

    def __init__(self, cfg: VisionConfig):
        self.cfg = cfg
        self.model = None
        self._device: Any = None  # None = ultralytics default (CPU)
        model_path = Path(cfg.ultralytics_model)
        if not model_path.exists():
            return
        try:
            from ultralytics import YOLO
        except ImportError:
            return
        try:
            self.model = YOLO(str(model_path))
            if hasattr(self.model, "set_classes"):
                self.model.set_classes(taxonomy.WORLD_PROMPTS)
            self.available = True
        except Exception:  # noqa: BLE001
            self.model = None
            return
        # Apple-Silicon GPU when available; first failed inference falls back.
        try:
            import torch
            if torch.backends.mps.is_available():
                self._device = "mps"
        except Exception:  # noqa: BLE001
            self._device = None

    def _predict(self, frame_bgr: np.ndarray):
        kwargs = dict(conf=self.cfg.conf_threshold, imgsz=self.cfg.input_size,
                      verbose=False)
        if self._device is not None:
            try:
                return self.model.predict(frame_bgr, device=self._device, **kwargs)
            except Exception:  # noqa: BLE001 - MPS op gap: fall back to CPU
                self._device = None
        return self.model.predict(frame_bgr, **kwargs)

    def detect(self, frame_bgr: np.ndarray) -> List[Dict[str, Any]]:
        if self.model is None:
            return []
        h, w = frame_bgr.shape[:2]
        results = self._predict(frame_bgr)
        merged: Dict[str, List[Dict[str, Any]]] = {}
        for r in results:
            if r.boxes is None:
                continue
            names = r.names or {}
            for box in r.boxes:
                prompt = str(names.get(int(box.cls[0]), "")).lower()
                cls_name = taxonomy.WORLD_PROMPT_TO_CLASS.get(prompt)
                if cls_name is None:
                    continue
                x1, y1, x2, y2 = (float(v) for v in box.xyxy[0])
                conf = float(box.conf[0])
                if not _passes_class_filters(cls_name, conf, (x1, y1, x2, y2), w, h):
                    continue
                merged.setdefault(cls_name, []).append(
                    {"cls": cls_name, "conf": conf, "box": [x1, y1, x2, y2]})
        # Cross-prompt NMS: "person" and "person crawling" both fire on the
        # same body — keep the strongest box per overlapping cluster.
        out: List[Dict[str, Any]] = []
        for dets in merged.values():
            dets.sort(key=lambda d: -d["conf"])
            kept: List[Dict[str, Any]] = []
            for d in dets:
                if all(_box_iou(d["box"], k["box"]) < 0.55 for k in kept):
                    kept.append(d)
            out.extend(kept)
        return out


def _box_iou(a, b) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = ((a[2] - a[0]) * (a[3] - a[1])
             + (b[2] - b[0]) * (b[3] - b[1]) - inter)
    return inter / union if union > 0 else 0.0


def build_detector(cfg: VisionConfig) -> BaseDetector:
    onnx = OnnxDetector(cfg)
    if onnx.available:
        return onnx
    world = UltralyticsDetector(cfg)
    if world.available:
        return world
    return NullDetector()
