# PyroSight

**AI-powered wearable firefighter assistance platform.** Real-time thermal +
RGB perception, temporal AI detection with honest confidence, breadcrumb
navigation, and a monocular helmet HUD — on an $800 Raspberry Pi 5 hardware
stack, fully offline.

```
        RGB (Pi Camera 3) ─┐                       ┌─ Helmet HUD  (monocular OLED)
   Thermal (Lepton 3.5)  ──┼─▶ Perception Engine ──┼─ Command Dashboard (browser)
        IMU (BNO085)     ──┘   detect · fuse ·     └─ Incident recorder (JSONL)
        Voice (offline)  ──▶   track · navigate
```

## What it does

| Capability | How |
|---|---|
| Human / firefighter / door / exit-sign / window / stairs / fire detection | YOLOv8 ONNX (Pi) or YOLO-World open-vocabulary (dev), async worker so the HUD never stalls |
| Hotspot detection + relative heat map | FLIR Lepton 3.5 radiometric analysis (°C), percentile-normalized ironbow view |
| RGB + thermal fusion | Body-heat corroboration of person detections; hotspot corroboration of fire; unmatched hotspots surfaced as first-class "heat behind obstruction" |
| Fire verification | HSV color + temporal flicker analysis + thermal cross-check — a hi-vis jacket stays "possible", a real flame confirms |
| Smoke density estimation | Contrast collapse + edge attenuation + haze cues, auto-calibrated per camera |
| Temporal confidence | Every detection tracked over frames; labels degrade honestly: `PERSON 92%` → `POSSIBLE PERSON 38%` |
| Navigation | Compass, breadcrumb trail, return-to-entry, exit guidance (live sighting → remembered bearing), hazard-on-route warnings, top-right position mini-map |
| Voice commands | Offline grammar (Vosk on the Pi): *find exit, locate victim, show thermal, highlight doors, repeat last alert…* |
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
    voice/             offline command grammar + Vosk listener
    recording/         incident JSONL logs + snapshots
    api/               REST + WebSocket (telemetry / video)
frontend/              Next.js 14 + TypeScript + Tailwind (HUD + dashboard)
scripts/               cross-platform launchers (sh / ps1 / bat)
deploy/                Raspberry Pi 5 install + systemd units
docs/                  ARCHITECTURE · HARDWARE · DEPLOYMENT
legacy/                v5 single-file OpenCV prototype
```

## Target hardware (~$800)

Raspberry Pi 5 8GB · FLIR Lepton 3.5 + PureThermal · Pi Camera Module 3 ·
Bosch BNO085 IMU · monocular OLED display · USB-C battery pack.
See [docs/HARDWARE.md](docs/HARDWARE.md) for the build and
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the one-command Pi install
(`sudo bash deploy/install-pi.sh` — auto-start on boot, HUD kiosk, offline
voice model, ONNX export).

## Design principles

1. **Uncertainty is a first-class output.** Single frames are never trusted;
   temporal tracks carry calibrated-ish confidence, and anything below the
   bar renders as *POSSIBLE* — visually distinct, dashed, never authoritative.
2. **Degrade, never die.** Every subsystem has a fallback chain and says so
   on the HUD (`estimated`, `simulated`, `degraded` states).
3. **The HUD is glanceable.** One instruction, one arrow, one confidence
   number. Maps and history live on the command dashboard, not in the eye.
4. **Offline always.** No cloud calls anywhere in the loop.
```
