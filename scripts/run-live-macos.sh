#!/usr/bin/env bash
# PyroSight — one-command LIVE demo on macOS/Linux laptops:
# real webcam + YOLO-World AI detection + RGB-derived thermal estimate.
#
#   bash scripts/run-live-macos.sh
#
# First run: macOS will ask for Camera permission — click OK, then restart
# the script. Ctrl-C stops everything.
set -euo pipefail
cd "$(dirname "$0")/.."

# Take over from any previous backend instance.
pkill -f "backend/run.py" 2>/dev/null || true
sleep 1

PY=.venv/bin/python
[[ -x "$PY" ]] || PY=python3

echo "== PyroSight LIVE mode: webcam + neural detector =="
PYROSIGHT_MODE=live PYROSIGHT_RGB_SOURCE=webcam "$PY" backend/run.py &
BACKEND_PID=$!

cleanup() { kill "$BACKEND_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# Frontend (reuse if already running on :3000).
if ! curl -s -m 1 http://localhost:3100 >/dev/null 2>&1; then
    (cd frontend && npm run dev) &
    FRONTEND_PID=$!
    trap 'kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true' EXIT INT TERM
fi

echo "Waiting for backend (first run loads the AI model, ~30 s)..."
until curl -s -m 2 http://localhost:8000/api/health 2>/dev/null | grep -q '"status":"ok"'; do
    sleep 2
done

URL="http://localhost:3100"
echo "PyroSight is up: $URL"
command -v open >/dev/null && open "$URL" || true
wait
