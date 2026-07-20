#!/usr/bin/env bash
# PyroSight — Raspberry Pi 5 production install.
#
#   sudo bash deploy/install-pi.sh
#
# Installs to /opt/pyrosight, creates the service user, installs Python and
# Node dependencies, exports the ONNX detector, downloads the offline voice
# model, and enables auto-start units for backend + frontend + HUD kiosk.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo: sudo bash deploy/install-pi.sh" >&2
    exit 1
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST=/opt/pyrosight

echo "== [1/7] System packages =="
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip nodejs npm chromium-browser \
    libatlas-base-dev libcamera-dev python3-picamera2 i2c-tools unzip

echo "== [2/7] Service user + files =="
id -u pyrosight &>/dev/null || useradd -r -m -G video,i2c,audio pyrosight
mkdir -p "$DEST"
rsync -a --exclude .venv --exclude node_modules --exclude .next \
    --exclude backend/data "$SRC_DIR/" "$DEST/"

echo "== [3/7] Python environment =="
cd "$DEST"
[[ -d .venv ]] || python3 -m venv .venv --system-site-packages  # picamera2 from apt
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r backend/requirements.txt
.venv/bin/pip install -q adafruit-circuitpython-bno08x vosk sounddevice || true

echo "== [4/7] ONNX detector export (full vocabulary preferred) =="
if [[ ! -f backend/models/yolov8n.onnx ]]; then
    .venv/bin/pip install -q ultralytics onnx
    # Full PyroSight vocabulary via YOLO-World v2 at 320 px (v2 is the
    # export-capable variant; auto-downloads ~50 MB). Falls back to
    # person-only COCO yolov8n if that fails.
    .venv/bin/python backend/scripts/export_onnx.py --model yolov8s-worldv2.pt --imgsz 320 \
        || .venv/bin/python backend/scripts/export_onnx.py \
        || echo "WARN: ONNX export failed — classical CV only until a model is provided."
fi

echo "== [5/7] Offline voice model (Vosk small-en, ~40 MB) =="
if [[ ! -d backend/models/vosk ]]; then
    mkdir -p backend/models
    curl -fsSL -o /tmp/vosk.zip \
        https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip \
        && unzip -q /tmp/vosk.zip -d backend/models \
        && mv backend/models/vosk-model-small-en-us-0.15 backend/models/vosk \
        || echo "WARN: Vosk model download failed — voice commands via dashboard only."
fi

echo "== [6/7] Frontend production build =="
cd "$DEST/frontend"
npm install --no-audit --no-fund
npm run build

echo "== [7/7] Services =="
chown -R pyrosight:pyrosight "$DEST"
# Enable I2C for the BNO085 (idempotent).
raspi-config nonint do_i2c 0 || true
cp "$DEST"/deploy/pyrosight-backend.service /etc/systemd/system/
cp "$DEST"/deploy/pyrosight-frontend.service /etc/systemd/system/
cp "$DEST"/deploy/pyrosight-hud.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now pyrosight-backend pyrosight-frontend
systemctl enable pyrosight-hud || true   # starts with the graphical session

echo ""
echo "PyroSight installed. Backend: http://<pi-ip>:8000  Dashboard: http://<pi-ip>:3000"
echo "The HUD kiosk starts on the helmet display at boot."
