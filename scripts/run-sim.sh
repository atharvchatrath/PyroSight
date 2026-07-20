#!/usr/bin/env bash
# PyroSight — simulation (SITL) demo: synthetic burning building, no hardware.
#   bash scripts/run-sim.sh
set -euo pipefail
cd "$(dirname "$0")/.."

pkill -f "backend/run.py" 2>/dev/null || true
sleep 1

PY=.venv/bin/python
[[ -x "$PY" ]] || PY=python3

PYROSIGHT_MODE=sim "$PY" backend/run.py &
BACKEND_PID=$!
cleanup() { kill "$BACKEND_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

if ! curl -s -m 1 http://localhost:3100 >/dev/null 2>&1; then
    (cd frontend && npm run dev) &
    FRONTEND_PID=$!
    trap 'kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true' EXIT INT TERM
fi

until curl -s -m 2 http://localhost:8000/api/health 2>/dev/null | grep -q '"status":"ok"'; do
    sleep 1
done
echo "PyroSight (sim) is up: http://localhost:3100"
command -v open >/dev/null && open "http://localhost:3100" || true
wait
