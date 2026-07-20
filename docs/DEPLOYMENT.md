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

The installer: installs OS packages → creates the `pyrosight` service user →
sets up the venv (with system Picamera2) → installs BNO085 + Vosk extras →
exports the YOLOv8n ONNX model → downloads the offline voice model →
builds the frontend → enables I²C → installs and starts three systemd units:

| Unit | Purpose |
|---|---|
| `pyrosight-backend` | perception engine + API, auto-restart, CPU priority |
| `pyrosight-frontend` | Next.js production server on :3000 |
| `pyrosight-hud` | Chromium kiosk on the monocular OLED (`/hud`) |

Everything starts at boot: power the battery pack and the helmet is live in
~25 s with zero interaction — a requirement, since a firefighter cannot
debug a login prompt.

**Voice**: with the Vosk model installed the backend listens on the default
microphone, fully offline, constrained to the command vocabulary for noise
robustness. Without it, voice still works through the dashboard.

**Custom detection model**: the stock export gives person detection (COCO).
For the full taxonomy (doors, exit signs, windows, stairs, fire), fine-tune
YOLOv8n on a fire-service dataset, then:

```bash
python backend/scripts/export_onnx.py --model your-model.pt
# + write backend/models/yolov8n.classes.txt (one class name per line)
```

**Field checklist**
- [ ] `systemctl status pyrosight-backend` — active, FPS ≥ 15 in dashboard
- [ ] Thermal: sensor panel shows `thermal ok (PureThermal UVC …)`, not "estimated"
- [ ] IMU: compass tracks head rotation, `imu ok`
- [ ] Voice: say "status" → command ack event appears
- [ ] Battery: HUD BAT % present (USB-C PD pack reporting)
- [ ] Incident recording: new session dir under `backend/data/incidents/`

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
