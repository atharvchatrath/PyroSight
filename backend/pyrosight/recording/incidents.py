"""
Incident recording: every session writes an append-only JSONL event log plus
JPEG snapshots on critical alerts. Plain files, no database — trivially
extracted from a Pi after an incident, safe against power loss (each line is
flushed), and readable by any tool.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class IncidentRecorder:
    def __init__(self, data_dir: Path, enabled: bool = True):
        self.enabled = enabled
        self.session_id = time.strftime("%Y%m%d_%H%M%S")
        self.dir = data_dir / "incidents" / self.session_id
        self._lock = threading.Lock()
        self._fh = None
        if enabled:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.dir / "events.jsonl", "a", encoding="utf-8")

    def log(self, kind: str, payload: Dict[str, Any]) -> None:
        if not self.enabled or self._fh is None:
            return
        record = {"ts": time.time(), "kind": kind, **payload}
        with self._lock:
            self._fh.write(json.dumps(record) + "\n")
            self._fh.flush()

    def snapshot(self, name: str, jpeg: bytes) -> Optional[str]:
        if not self.enabled:
            return None
        fname = f"{name}_{time.strftime('%H%M%S')}.jpg"
        (self.dir / fname).write_bytes(jpeg)
        return fname

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    # ---- session queries (for the dashboard) ----

    @staticmethod
    def list_sessions(data_dir: Path) -> List[Dict[str, Any]]:
        root = data_dir / "incidents"
        if not root.exists():
            return []
        sessions = []
        for d in sorted(root.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            events_file = d / "events.jsonl"
            n_events = 0
            if events_file.exists():
                with open(events_file, "r", encoding="utf-8") as fh:
                    n_events = sum(1 for _ in fh)
            sessions.append({
                "id": d.name,
                "events": n_events,
                "snapshots": len(list(d.glob("*.jpg"))),
            })
        return sessions[:50]

    @staticmethod
    def read_events(data_dir: Path, session_id: str,
                    limit: int = 500) -> List[Dict[str, Any]]:
        safe = Path(session_id).name  # forbid path traversal
        events_file = data_dir / "incidents" / safe / "events.jsonl"
        if not events_file.exists():
            return []
        out: List[Dict[str, Any]] = []
        with open(events_file, "r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out[-limit:]
