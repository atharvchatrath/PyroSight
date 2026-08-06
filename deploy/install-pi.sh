#!/usr/bin/env bash
# PyroSight — Raspberry Pi 5 production install.
#
#   sudo bash deploy/install-pi.sh
#
# Installs to /opt/pyrosight, creates the service user, installs Python and
# Node dependencies and exports the ONNX detector.
# model, builds the UI, and enables auto-start units for the backend, the
# frontend, and the helmet HUD kiosk. Finishes by verifying the services
# actually answer — an installer that exits 0 on a dead system is worthless.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo: sudo bash deploy/install-pi.sh" >&2
    exit 1
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST=/opt/pyrosight
UI_PORT=3100
API_PORT=8000

# Guard: this script configures Pi-specific hardware (I2C, libcamera) and
# systemd units. Running it on a dev laptop would be destructive.
if ! grep -qi "raspberry pi" /proc/device-tree/model 2>/dev/null; then
    echo "WARNING: this does not look like Raspberry Pi hardware." >&2
    echo "         For laptop testing use scripts/run-sim.sh instead." >&2
    read -r -p "Continue anyway? [y/N] " reply
    [[ "$reply" == "y" || "$reply" == "Y" ]] || exit 1
fi

echo "== [1/8] System packages =="
apt-get update -qq
# rsync + curl + unzip are used by this script itself; python3-opencv and
# libatlas come from apt so pip does not spend 40 minutes building them.
apt-get install -y -qq \
    python3-venv python3-pip python3-opencv python3-picamera2 \
    nodejs npm rsync curl unzip i2c-tools libatlas-base-dev libcamera-dev
# Chromium package name differs by release; install whichever exists.
apt-get install -y -qq chromium || apt-get install -y -qq chromium-browser || \
    echo "WARN: no Chromium package found — HUD kiosk will not start."

echo "== [2/8] Service user + files =="
id -u pyrosight &>/dev/null || useradd -r -m -G video,i2c,audio,render pyrosight
mkdir -p "$DEST"
rsync -a --delete \
    --exclude .venv --exclude node_modules --exclude .next \
    --exclude backend/data --exclude .git \
    "$SRC_DIR/" "$DEST/"
chmod +x "$DEST"/deploy/hud-kiosk.sh

echo "== [3/8] Python environment =="
cd "$DEST"
# --system-site-packages exposes the apt-installed picamera2 and cv2.
[[ -d .venv ]] || python3 -m venv .venv --system-site-packages
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q --prefer-binary -r backend/requirements.txt
# Hardware extras (best-effort: the platform degrades without them).
.venv/bin/pip install -q --prefer-binary \
    adafruit-circuitpython-bno08x pyserial || \
    echo "WARN: some optional extras failed (IMU/ESP32 may be unavailable)."

echo "== [4/8] ONNX detector export (full vocabulary preferred) =="
if [[ ! -f backend/models/yolov8n.onnx ]]; then
    .venv/bin/pip install -q --prefer-binary ultralytics onnx onnxslim
    # Full PyroSight vocabulary via YOLO-World v2 at 320 px (v2 is the
    # export-capable variant). Falls back to person-only COCO yolov8n.
    .venv/bin/python backend/scripts/export_onnx.py --model yolov8s-worldv2.pt --imgsz 320 \
        || .venv/bin/python backend/scripts/export_onnx.py \
        || echo "WARN: ONNX export failed — classical CV only until a model is provided."
fi


echo "== [6/8] Frontend production build =="
cd "$DEST/frontend"
npm install --no-audit --no-fund
npm run build

echo "== [7/8] Hardware interfaces + services =="
mkdir -p "$DEST/backend/data"
chown -R pyrosight:pyrosight "$DEST"
# Enable I2C for the BNO085 IMU (idempotent).
raspi-config nonint do_i2c 0 || echo "WARN: could not enable I2C automatically."
install -m 644 "$DEST"/deploy/pyrosight-backend.service /etc/systemd/system/
install -m 644 "$DEST"/deploy/pyrosight-frontend.service /etc/systemd/system/
install -m 644 "$DEST"/deploy/pyrosight-hud.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now pyrosight-backend pyrosight-frontend
systemctl enable pyrosight-hud || true   # starts with the graphical session

echo "== [8/8] Verifying services =="
ok=1
for _ in $(seq 1 45); do
    if curl -fsS -m 2 "http://localhost:${API_PORT}/api/health" >/dev/null 2>&1; then
        break
    fi
    sleep 2
done
if curl -fsS -m 3 "http://localhost:${API_PORT}/api/health" 2>/dev/null | grep -q '"status"'; then
    echo "  backend  OK  $(curl -fsS -m 3 http://localhost:${API_PORT}/api/health)"
else
    echo "  backend  FAILED — journalctl -u pyrosight-backend -n 40" >&2
    ok=0
fi
for _ in $(seq 1 30); do
    curl -fsS -m 2 "http://localhost:${UI_PORT}" >/dev/null 2>&1 && break
    sleep 2
done
if curl -fsS -m 3 "http://localhost:${UI_PORT}" >/dev/null 2>&1; then
    echo "  frontend OK  http://localhost:${UI_PORT}"
else
    echo "  frontend FAILED — journalctl -u pyrosight-frontend -n 40" >&2
    ok=0
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo ""
if [[ $ok -eq 1 ]]; then
    echo "PyroSight installed and running."
else
    echo "PyroSight installed, but a service did not come up (see errors above)." >&2
fi
echo "  Helmet HUD      http://${IP:-<pi-ip>}:${UI_PORT}/hud   (kiosk auto-starts on the OLED)"
echo "  Command dash    http://${IP:-<pi-ip>}:${UI_PORT}/dashboard"
echo "  API             http://${IP:-<pi-ip>}:${API_PORT}/api/health"
echo ""
echo "Verify the sensor build:  sudo -u pyrosight $DEST/.venv/bin/python $DEST/backend/scripts/preflight.py"
[[ $ok -eq 1 ]] || exit 1
