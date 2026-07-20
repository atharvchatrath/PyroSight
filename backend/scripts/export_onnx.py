#!/usr/bin/env python3
"""
Export a detection model to ONNX for the Raspberry Pi 5 production path.

Preferred: bake the FULL PyroSight vocabulary (person, firefighter, door,
exit sign, window, stairs, hallway, fire) into a YOLO-World export — the
text prompts are embedded at export time, producing a fixed-vocabulary
detector that runs under plain onnxruntime with no CLIP at runtime:

    pip install ultralytics onnx
    python backend/scripts/export_onnx.py --model yolov8s-world.pt --imgsz 320

Fallback (person-only, COCO):

    python backend/scripts/export_onnx.py            # yolov8n @ 416

Both write backend/models/<name>.onnx plus a .classes.txt sidecar mapping
model class indices to PyroSight taxonomy names; the backend picks up both
automatically.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
MODELS_DIR = BACKEND / "models"
sys.path.insert(0, str(BACKEND))

from pyrosight.vision import classes as taxonomy  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="yolov8n.pt",
                        help=".pt weights; a *-world model gets the PyroSight "
                             "vocabulary baked in")
    parser.add_argument("--imgsz", type=int, default=416,
                        help="input size (320 recommended for world models on Pi 5)")
    args = parser.parse_args()

    from ultralytics import YOLO

    MODELS_DIR.mkdir(exist_ok=True)
    is_world = "world" in Path(args.model).stem.lower()
    model = YOLO(args.model)

    if is_world:
        if not hasattr(model, "set_classes"):
            print("[ERR] this ultralytics version cannot set world classes")
            return 1
        model.set_classes(taxonomy.WORLD_PROMPTS)
        class_lines = [taxonomy.WORLD_PROMPT_TO_CLASS[p]
                       for p in taxonomy.WORLD_PROMPTS]
    else:
        # Stock COCO model: person only (index 0).
        class_lines = ["person"] + ["_unused"] * 79

    try:
        # opset pinned for broad onnxruntime compatibility (Pi wheels lag).
        out = model.export(format="onnx", imgsz=args.imgsz, simplify=True,
                           opset=19)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERR] export failed: {exc}")
        if is_world:
            print("      (v1 world models may not export; try yolov8s-worldv2.pt)")
        return 1

    out_path = Path(out)
    target = MODELS_DIR / "yolov8n.onnx"  # canonical name the backend expects
    target.write_bytes(out_path.read_bytes())
    target.with_suffix(".classes.txt").write_text("\n".join(class_lines) + "\n")
    print(f"[OK] {target}  ({target.stat().st_size / 1e6:.1f} MB)")
    print(f"[OK] {target.with_suffix('.classes.txt')} "
          f"({'full vocabulary' if is_world else 'person-only COCO'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
