#!/usr/bin/env bash
# PyroSight helmet HUD kiosk launcher.
#
# Run by pyrosight-hud.service on the monocular OLED display. Exists as a
# script rather than a bare ExecStart because the Chromium binary name is not
# stable across Raspberry Pi OS releases: Bullseye ships `chromium-browser`,
# Bookworm ships `chromium`. Hard-coding either one silently breaks the
# helmet display on half the fleet.
set -euo pipefail

PORT="${PYROSIGHT_UI_PORT:-3100}"
URL="http://localhost:${PORT}/hud"

# Find whichever Chromium this OS release provides.
CHROMIUM=""
for candidate in chromium chromium-browser /usr/bin/chromium /usr/bin/chromium-browser; do
    if command -v "$candidate" >/dev/null 2>&1; then
        CHROMIUM="$(command -v "$candidate")"
        break
    fi
done
if [[ -z "$CHROMIUM" ]]; then
    echo "FATAL: no Chromium found (tried chromium, chromium-browser)." >&2
    exit 1
fi

# Wait for the UI to answer before opening the kiosk, otherwise the
# firefighter sees a Chromium error page at boot.
for _ in $(seq 1 60); do
    if curl -fsS -m 2 "http://localhost:${PORT}" >/dev/null 2>&1; then
        break
    fi
    sleep 2
done

exec "$CHROMIUM" \
    --kiosk \
    --app="$URL" \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-features=TranslateUI \
    --no-first-run \
    --force-dark-mode \
    --autoplay-policy=no-user-gesture-required \
    --check-for-update-interval=31536000
