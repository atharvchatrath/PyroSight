# PyroSight Deployment

## 1. Laptop testing (macOS / Windows / Linux)

### Browser camera (recommended — real AI on your webcam, zero driver setup)

```bash
# terminal 1 — backend in live mode with browser ingest
PYROSIGHT_MODE=live PYROSIGHT_RGB_SOURCE=browser python backend/run.py
# terminal 2 — frontend
cd frontend && npm run dev
```

Open **http://localhost:3100/live** → **START CAMERA** → approve the browser
permission prompt. Your camera streams to the backend over WebSocket and the
full pipeline (YOLO-World detection, fire flicker analysis, smoke density,
RGB-derived thermal estimate, fusion, temporal tracking) runs on the real
feed. The HUD (`/hud`) and dashboard (`/dashboard`) run off the same live
state simultaneously.

Windows: `scripts\setup.ps1` once, then `scripts\run-backend.ps1` +
`scripts\run-frontend.ps1` (or `scripts\start-windows.bat` for one click).

### Native webcam (backend opens the camera itself)

```bash
PYROSIGHT_MODE=live PYROSIGHT_RGB_SOURCE=webcam python backend/run.py
```

macOS will prompt for camera access for your terminal the first time —
approve and rerun. On Windows the DirectShow backend is selected
automatically.

### Simulation (no camera at all)

```bash
python backend/run.py        # sim on laptops by default
```

## 2. Raspberry Pi 5 helmet unit (production)

```bash
sudo bash deploy/install-pi.sh
```

The installer, in order: installs OS packages (including whichever Chromium
package the release provides) → creates the `pyrosight` service user →
rsyncs to `/opt/pyrosight` → builds the venv against the apt-installed
Picamera2/OpenCV → installs BNO085, Vosk and ESP32 extras → exports the
full-vocabulary ONNX detector → downloads the offline voice model → builds
the frontend → enables I²C → installs and starts three systemd units →
**verifies the services actually answer** and exits non-zero if not.

| Unit | Purpose |
|---|---|
| `pyrosight-backend` | perception engine + API on :8000, auto-restart, CPU priority |
| `pyrosight-frontend` | Next.js production server on :3100 |
| `pyrosight-hud` | Chromium kiosk on the monocular OLED (`/hud`) |

Everything starts at boot: power the battery pack and the helmet is live in
~25 s with zero interaction — a requirement, since a firefighter cannot
debug a login prompt.

The HUD kiosk runs through `deploy/hud-kiosk.sh`, which resolves the Chromium
binary name (Bookworm ships `chromium`, Bullseye `chromium-browser`) and waits
for the UI to answer before opening, so the helmet never shows an error page.

### Preflight — verify the build before an incident

```bash
sudo -u pyrosight /opt/pyrosight/.venv/bin/python \
    /opt/pyrosight/backend/scripts/preflight.py
```

Checks the detector, RGB camera, Lepton, IMU, voice model, ESP32 alert
channel, storage headroom, CPU temperature and battery — printing the exact
remediation for anything not ready, and exiting non-zero on hard failures.
Run it after install and as the pre-shift check.

### Mission demonstration

```bash
/opt/pyrosight/.venv/bin/python /opt/pyrosight/scripts/demo-mission.py
```

Drives the platform through a full incident (size-up → primary search →
victim location → hazard encounter → emergency egress → return-to-entry →
after-action record) using the real command API and live telemetry. Useful
for acceptance testing, training, and demonstrations.

**Voice**: with the Vosk model installed the backend listens on the default
microphone, fully offline, constrained to the command vocabulary for noise
robustness. Without it, voice still works through the dashboard.

**Custom detection model**: the installer bakes the PyroSight vocabulary
(person, firefighter, door, exit sign, window, stairs, hallway, fire) into a
YOLO-World ONNX export. To use a model fine-tuned on fire-service imagery:

```bash
python backend/scripts/export_onnx.py --model your-model.pt --imgsz 320
# + write backend/models/yolov8n.classes.txt (one class name per line)
```

**Field checklist**
- [ ] `preflight.py` reports ALL SYSTEMS READY (or only accepted warnings)
- [ ] `systemctl status pyrosight-backend` — active, FPS ≥ 15 in dashboard
- [ ] Thermal: sensor panel shows `thermal ok (PureThermal UVC …)`, not "estimated"
- [ ] IMU: compass tracks head rotation, `imu ok`
- [ ] Voice: say "status" → command ack event appears
- [ ] Battery: HUD BAT % present (USB-C PD pack reporting)
- [ ] Incident recording: new session dir under `backend/data/incidents/`
- [ ] HUD kiosk fills the OLED with no clipping (run the Calibration Wizard)

## 3. Ports & environment

| Var | Default | Meaning |
|---|---|---|
| `PYROSIGHT_MODE` | auto | `sim` / `live` (auto: live on Pi, sim elsewhere) |
| `PYROSIGHT_RGB_SOURCE` | auto | `picamera` / `webcam` / `browser` / `sim` |
| `PYROSIGHT_THERMAL_SOURCE` | auto | `lepton` / `sim` |
| `PYROSIGHT_IMU_SOURCE` | auto | `bno085` / `sim` |
| `PYROSIGHT_PORT` | 8000 | backend API/WebSocket port |
| `PYROSIGHT_TARGET_FPS` | 20 | engine loop rate |
| `PYROSIGHT_DETECT_INPUT` | 416 | detector input resolution |
| `PYROSIGHT_DETECT_EVERY_N` | 2 | frames between detector submissions |
| `PYROSIGHT_JPEG_QUALITY` | 70 | stream encode quality |
| `PYROSIGHT_RECORD` | 1 | incident recording on/off |
