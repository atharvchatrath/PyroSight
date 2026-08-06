# Training a custom PyroSight detector

The shipped dev detector is **YOLO-World**, an open-vocabulary model: it
matches text prompts like *"illuminated emergency exit sign"* against pixels.
That it works at all is remarkable, and it is the right default — it needs no
data and detects eight classes out of the box.

It is also the accuracy ceiling. It has never seen a fire-service door, an
exit sign through smoke, or a firefighter in full PPE. No amount of threshold
tuning fixes that, because the limit is the model, not the gates in front of
it. A YOLOv8 fine-tuned on a few thousand labelled fireground frames beats it
decisively **and** runs several times faster on the Pi.

Everything below assumes `pip install ultralytics` (already installed if you
ran the live demo).

---

## 1. Scaffold

```bash
python backend/scripts/train.py --init
```

Creates `dataset/` and writes `data.yaml`. Class ids:

| id | class | id | class |
|---|---|---|---|
| 0 | `person` | 4 | `window` |
| 1 | `firefighter` | 5 | `stairs` |
| 2 | `door` | 6 | `hallway` |
| 3 | `exit_sign` | 7 | `fire` |

`hotspot` and `floor_hazard` are absent on purpose — they come from the
Lepton and from stereo depth, not from RGB pixels. There is nothing to label,
and training on appearance would teach the model to hallucinate them.

> **Never hand-edit the class list in `data.yaml`.** It is regenerated from
> `vision/classes.TRAINABLE_CLASSES` on every run, and that same list writes
> the model's `.classes.txt` sidecar. If the two orders ever disagree the
> model still loads, still runs fast, still reports high confidence — and
> calls every door a person, with no error anywhere.
> `test_training_pipeline.py` asserts the round trip.

## 2. Collect

Aim for **500–2000 images**, ~80/20 train/val. Fine-tuning from COCO weights
needs far less than training from scratch, but a class with a handful of
examples yields a detector that is *confidently wrong* about it — worse than
the open-vocabulary model it replaces. The trainer refuses under 200 images
and warns per class under 50 instances.

What actually moves accuracy, in order:

1. **Smoke.** The single biggest distribution gap. Frames with visible smoke
   layers are worth several times a clean one. Training-tower burns and live-
   fire evolutions are the gold standard.
2. **Bad light.** Dark rooms, backlit doorways, a torch as the only source.
3. **PPE.** `firefighter` is the class open-vocab handles worst, because
   people in SCBA and turnout gear look nothing like COCO's "person".
4. **Real exit signage** in your jurisdiction. Fittings vary by country and
   this is a small, high-value class.
5. **Victim poses.** Prone, crawling, slumped, partly under furniture — this
   is what a search actually finds, and it is what "person" is worst at.
6. **Hard negatives.** Rooms with *no* victim, posters, mannequins, TVs.
   Images with an empty label file are valid training data and are the
   cheapest way to cut false positives.

Public sets worth starting from: **FireNet** and **D-Fire** (fire/smoke),
**FLAME** (aerial fire). None cover interior search — that part has to be
yours, which is also why it is defensible.

## 3. Label

Any tool that exports YOLO format works — Roboflow, Label Studio, CVAT. One
`.txt` per image, same basename, one line per object, normalised 0–1:

```
<class_id> <x_center> <y_center> <width> <height>
2 0.481 0.532 0.140 0.610
```

Two conventions that matter:

- **Label what is visible, not what you know is there.** A victim 80%
  occluded gets a box around the visible 20%. Boxing the whole imagined body
  teaches the model to guess extent, and extent is what the range estimate is
  computed from.
- **A door is the opening, not the leaf.** Guidance routes to the gap you
  walk through.

## 4. Train

```bash
python backend/scripts/train.py --epochs 100            # auto device
python backend/scripts/train.py --epochs 100 --device mps   # Apple GPU
python backend/scripts/train.py --epochs 100 --device 0     # CUDA
```

Augmentation is already tuned for this domain — heavy value/saturation jitter
(dark and smoky), mild rotation, no vertical flip. A victim is a victim
upside down; a victim at half brightness through smoke is what the model will
actually meet.

Keep `--imgsz 416` unless you also change `VisionConfig.input_size`.

## 5. Read the result honestly

The trainer prints **per-class mAP50-95**, not just the overall number. The
summary figure hides the class you care about: 0.72 overall with `person` at
0.31 is a bad detector for a search, and it is exactly what happens when
`hallway` (easy, common) drowns out `person` (hard, rare).

Rough reading for this domain:

| mAP50-95 | verdict |
|---|---|
| > 0.60 | strong |
| 0.40–0.60 | usable; deployable for `person` and `fire` |
| 0.25–0.40 | thin — collect more of that class |
| < 0.25 | worse than YOLO-World; do not ship it |

## 6. Deploy

The export is automatic. It writes `backend/models/yolov8n.onnx` plus the
sidecar — the exact path `VisionConfig.onnx_model` already points at — so
deployment is a restart and nothing else.

```bash
curl -s localhost:8000/api/health     # expect "detector": "onnx"
```

The detector chain is **onnx → ultralytics → none**, so the trained model
takes priority over YOLO-World automatically, on the Pi and on a laptop.

Then measure it against reality rather than against the val split:

```bash
.venv/bin/python scripts/camera-test.py
```

That runs the live pipeline on real cameras and reports throughput, false
positives in an empty scene, per-class recall and range error. It refuses to
run against simulated imagery, because certifying accuracy on fake input is
worthless.

---

## Retraining cadence

Every new dataset should be *added* to the old one, not replace it. The
failure mode is a model that gets better at last month's building and worse
at everything else. Keep `dataset/` under version control externally (it is
gitignored here) and keep the val split fixed between runs — otherwise the
mAP numbers are not comparable and you cannot tell whether a change helped.
