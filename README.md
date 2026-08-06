# PyroSight

**AI-powered wearable firefighter assistance platform.** Real-time thermal +
RGB perception, temporal AI detection with honest confidence, breadcrumb
navigation, and a monocular helmet HUD — on an $800 Raspberry Pi 5 hardware
stack, fully offline.

```
        RGB (Pi Camera 3) ─┐                       ┌─ Helmet HUD  (monocular OLED)
   Thermal (Lepton 3.5)  ──┼─▶ Perception Engine ──┼─ Command Dashboard (browser)
        IMU (BNO085)     ──┘   detect · fuse ·     └─ Incident recorder (JSONL)
                               track · navigate
```

## What it does

| Capability | How |
|---|---|
| Human / firefighter / door / exit-sign / window / stairs / fire detection | YOLOv8 ONNX (Pi) or YOLO-World open-vocabulary (dev), async worker so the HUD never stalls |
| One object, one answer | Mutually-exclusive classes never both claim the same pixels. A wall opening resolves to *either* door or window — decided on corroborated evidence, weighted by the cost of being wrong, at both frame and track level |
| Decoy suppression | Open-vocab prompts for the things that get mistaken for victims — posters, mannequins, screens, hi-vis jackets. The score moves onto the decoy and the decoy is discarded, instead of raising the person threshold and losing real victims with it |
| Hotspot detection + relative heat map | FLIR Lepton 3.5 radiometric analysis (°C), percentile-normalized ironbow view |
| RGB + thermal fusion | Body-heat corroboration of person detections; hotspot corroboration of fire; unmatched hotspots surfaced as first-class "heat behind obstruction" |
| Fire verification | HSV color + temporal flicker analysis + thermal cross-check — a hi-vis jacket stays "possible", a real flame confirms |
| Smoke density estimation | Contrast collapse + edge attenuation + haze cues, auto-calibrated per camera |
| Temporal confidence | Every detection tracked over frames; labels degrade honestly: `HUMAN 92%` → `POSSIBLE HUMAN 38%`. Corroboration by a second modality (body heat, flicker, classical egress match) promotes a call — persistence alone never does |
| Navigation | Compass, breadcrumb trail, return-to-entry, exit guidance (live sighting → remembered bearing), hazard-on-route warnings, top-right position mini-map |
| Autonomous operation | No command surface at all — nothing to press, say, or configure mid-incident. The platform reports what it sees; mission mode, emergency escalation and route status are derived from conditions and clear themselves when the conditions do |
| Fail-safe degradation | No Lepton → RGB-derived thermal *estimate* (labeled). No IMU → visual heading from camera motion (labeled). No model → classical CV only. Sensors stalling are watchdogged and reopened. |

## Quickstart (any laptop — macOS / Windows / Linux)

No hardware needed: the platform ships with a software-in-the-loop simulation
of a smoke-filled corridor (fire, victim, doors, exit) and runs the *real*
perception algorithms against it.

**macOS / Linux**

```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd frontend && npm install && cd ..
bash scripts/run-sim.sh          # simulation demo
bash scripts/run-live-macos.sh   # LIVE: your webcam + real AI detection
```

**Windows (PowerShell)**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
scripts\run-backend.ps1          # sim mode   (add -Webcam for live camera)
scripts\run-frontend.ps1         # second terminal
# or double-click scripts\start-windows.bat for everything at once
```

Open **http://localhost:3100** → choose **HELMET HUD** or **COMMAND DASHBOARD**.

### Validate accuracy on your own hardware

The camera test runs the live pipeline against your real cameras and reports
**measured** accuracy — throughput, false positives in an empty scene,
detection recall for each class, range error against a tape measure, and a
thermal plausibility check. It refuses to run against simulated imagery,
because certifying accuracy on fake input is worthless.

```bash
# Pi (real cameras):   sudo systemctl start pyrosight-backend
# Laptop (browser cam): PYROSIGHT_MODE=live PYROSIGHT_RGB_SOURCE=browser \
#                       .venv/bin/python backend/run.py   # then open /live
.venv/bin/python scripts/camera-test.py
```

Results are written to `backend/data/camera_test_<timestamp>.json` so runs can
be compared after any pipeline change. On the Pi, check the build first with
`backend/scripts/preflight.py`.

### Train a detector on your own imagery

The shipped dev detector is open-vocabulary — it matches text prompts against
pixels, and that is its accuracy ceiling. Fine-tuning YOLOv8 on labelled
fireground frames beats it decisively and runs faster on the Pi:

```bash
python backend/scripts/train.py --init      # scaffold dataset/
# label images, then
python backend/scripts/train.py --epochs 100
```

Exports ONNX + class sidecar straight to the path the backend already reads,
so deployment is a restart. See [docs/TRAINING.md](docs/TRAINING.md) for what
data actually moves accuracy and how to read the per-class numbers.

> Live camera mode on macOS: the first run triggers the system camera
> permission prompt — approve it and rerun. Live mode without a Lepton/IMU
> attached runs with clearly-labeled estimated thermal + visual heading.

## Repository layout

```
backend/               FastAPI + perception engine (Python 3.9+)
  pyrosight/
    sensors/           Pi Camera 3 / Lepton 3.5 / BNO085 + simulated twins
    sim/               SITL world: geometry, heat field, ground-truth boxes
    vision/            detector chain, thermal analysis, fusion, tracker,
                       fire/smoke estimators, visual odometry
    navigation/        heading filter, breadcrumbs, guidance engine
    pipeline/          engine loop + async detection worker
    recording/         incident JSONL logs + snapshots
    api/               REST + WebSocket (telemetry / video)
frontend/              Next.js 14 + TypeScript + Tailwind (HUD + dashboard)
scripts/               cross-platform launchers (sh / ps1 / bat)
deploy/                Raspberry Pi 5 install + systemd units
docs/                  ARCHITECTURE · HARDWARE · DEPLOYMENT · TRAINING
helmet_sim.py          v7 standalone OpenCV HUD (runs independently of the platform)
```

## Target hardware (~$800)

Raspberry Pi 5 8GB · FLIR Lepton 3.5 + PureThermal · Pi Camera Module 3 ·
Bosch BNO085 IMU · monocular OLED display · USB-C battery pack.
See [docs/HARDWARE.md](docs/HARDWARE.md) for the build and
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the one-command Pi install
(`sudo bash deploy/install-pi.sh` — auto-start on boot, HUD kiosk,
ONNX export).

## Design principles

1. **Uncertainty is a first-class output — and so is certainty.** Single
   frames are never trusted; temporal tracks carry calibrated-ish confidence,
   and anything genuinely unresolved renders as *POSSIBLE* — dashed, never
   authoritative. The converse matters just as much: a call the system *is*
   sure of gets made plainly. Hedging everything is not caution, it teaches
   the operator that *POSSIBLE* carries no information, and then the real
   warnings stop being read too.
2. **One word, one meaning.** *POSSIBLE* means we don't know **what** it is.
   Losing sight of a known object is a different fact and gets a different
   channel — dimmed, dashed, tagged `OCCLUDED`. Colour and wording say what a
   thing is; weight and opacity say how sure we are we can still see it.
3. **Degrade, never die.** Every subsystem has a fallback chain and says so
   on the HUD (`estimated`, `simulated`, `degraded` states).
4. **The HUD is glanceable.** One instruction, one arrow, one confidence
   number. Maps and history live on the command dashboard, not in the eye.
5. **Warm on black, and luminance carries the hierarchy.** Cool hues are the
   first to disappear through a sooted visor and an eye adapted to flame, so
   the palette is orange on true black — also the cheapest thing an OLED can
   draw, and lit pixels are battery. Brightness, not hue, encodes priority:
   white is a human, amber is a way out, deep red is fire. That ordering
   survives colourblindness and a monochrome panel.
6. **Offline always.** No cloud calls anywhere in the loop.
