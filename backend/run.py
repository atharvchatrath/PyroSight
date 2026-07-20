#!/usr/bin/env python3
"""
PyroSight backend launcher.

    python run.py                 # auto mode: sim on laptops, live on the Pi
    PYROSIGHT_MODE=live python run.py
    PYROSIGHT_RGB_SOURCE=webcam python run.py   # real webcam + real detector

Works identically on macOS, Windows, Linux, and Raspberry Pi OS.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Runnable from any working directory: `python backend/run.py` from the repo
# root keeps model caches (e.g. CLIP weights for YOLO-World) shared at root.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn

from pyrosight.app import create_app
from pyrosight.config import load_config

app = create_app()


def main() -> None:
    config = load_config()
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
        log_level="info",
        # ws_max_size default is fine; JPEG frames are ~30-80 KB.
    )


if __name__ == "__main__":
    main()
