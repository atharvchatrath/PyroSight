"""
Mesh position sharing: lightweight UDP broadcast so every helmet on the same
local network knows where the rest of the crew is, indoors, where GPS does
not work. This is a software stand-in for a future UWB/BLE mesh radio — same
sim<->hardware swap point as every sensor in pyrosight.sensors, just built on
a transport that exists today.

Each unit periodically broadcasts its own pose; `teammates()` returns
everyone heard from recently, pruned after `timeout_s` of silence so a unit
that drops off the network does not linger on the map as a ghost.
"""

from __future__ import annotations

import json
import math
import socket
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from ..config import MeshConfig

FEET_PER_METER = 3.28084


class MeshLink:
    def __init__(self, cfg: MeshConfig):
        self.cfg = cfg
        self.unit_id = cfg.unit_id or f"unit-{uuid.uuid4().hex[:6]}"
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()
        self._peers: Dict[str, Dict[str, Any]] = {}
        self._last_publish = 0.0

    @property
    def available(self) -> bool:
        return self._sock is not None

    def start(self) -> bool:
        if not self.cfg.enabled:
            return False
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError:
                    pass
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("", self.cfg.port))
            sock.settimeout(0.5)
        except OSError:
            self._sock = None
            return False
        self._sock = sock
        self._running = True
        self._thread = threading.Thread(target=self._listen, daemon=True,
                                        name="pyrosight-mesh")
        self._thread.start()
        return True

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def _listen(self) -> None:
        while self._running and self._sock is not None:
            try:
                data, _addr = self._sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                msg = json.loads(data.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            uid = msg.get("id")
            if not uid or uid == self.unit_id:
                continue
            with self._lock:
                self._peers[uid] = {**msg, "heard_at": time.time()}

    def publish(self, position: Optional[Tuple[float, float]],
               heading_deg: float, emergency: bool = False,
               battery_percent: Optional[float] = None) -> None:
        if self._sock is None:
            return
        now = time.time()
        if now - self._last_publish < (1.0 / max(0.1, self.cfg.broadcast_hz)):
            return
        self._last_publish = now
        payload = {
            "id": self.unit_id,
            "x": position[0] if position else None,
            "y": position[1] if position else None,
            "heading_deg": round(heading_deg, 1),
            "emergency": bool(emergency),
            "battery_percent": battery_percent,
            "ts": now,
        }
        try:
            self._sock.sendto(json.dumps(payload).encode("utf-8"),
                              (self.cfg.broadcast_addr, self.cfg.port))
        except OSError:
            pass

    def teammates(self) -> List[Dict[str, Any]]:
        """Recently-heard peers; entries older than timeout_s are pruned."""
        now = time.time()
        with self._lock:
            self._peers = {uid: p for uid, p in self._peers.items()
                           if now - p["heard_at"] <= self.cfg.timeout_s}
            return [dict(p, id=uid) for uid, p in self._peers.items()]


def buddy_bearings(own_pos: Optional[Tuple[float, float]], heading_deg: float,
                   teammates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Relative bearing/distance to each teammate, nearest first. Mirrors
    the HUD-facing shape guidance.py already uses for exit/victim targets."""
    if own_pos is None:
        return []
    now = time.time()
    out: List[Dict[str, Any]] = []
    for tm in teammates:
        if tm.get("x") is None or tm.get("y") is None:
            continue
        dx, dy = tm["x"] - own_pos[0], tm["y"] - own_pos[1]
        dist_m = math.hypot(dx, dy)
        abs_bearing = math.degrees(math.atan2(dx, dy)) % 360.0
        rel = (abs_bearing - heading_deg + 180.0) % 360.0 - 180.0
        out.append({
            "id": tm["id"],
            "rel_bearing_deg": round(rel, 1),
            "dist_ft": round(dist_m * FEET_PER_METER, 1),
            "emergency": bool(tm.get("emergency")),
            "age_s": round(now - tm.get("heard_at", now), 1),
        })
    out.sort(key=lambda b: b["dist_ft"])
    return out
