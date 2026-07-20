"""
Thread-safe state + event plumbing between the perception engine (a plain
thread, so it can never be starved by the event loop) and the async API layer.

Design:
  * TelemetryHub.set_state()  — engine publishes the latest full snapshot;
    WS handlers poll it at their own rate. Readers never block the engine.
  * TelemetryHub.push_event() — monotonic-sequence ring buffer of discrete
    events (alerts, detections entering/leaving, command acks). WS handlers
    drain "events since seq N" so nothing is lost between polls.
  * FrameStore              — latest encoded JPEG per feed with a frame id,
    so video sockets skip resends when nothing new arrived.
"""

from __future__ import annotations

import itertools
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple


class TelemetryHub:
    def __init__(self, event_capacity: int = 500):
        self._lock = threading.Lock()
        self._state: Dict[str, Any] = {}
        self._state_seq = 0
        self._events: deque = deque(maxlen=event_capacity)
        self._event_seq = itertools.count(1)

    # ---- state snapshots ----

    def set_state(self, state: Dict[str, Any]) -> None:
        with self._lock:
            self._state_seq += 1
            state["seq"] = self._state_seq
            self._state = state

    def get_state(self) -> Dict[str, Any]:
        with self._lock:
            return self._state

    # ---- discrete events ----

    def push_event(self, kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        event = {
            "seq": next(self._event_seq),
            "ts": time.time(),
            "kind": kind,
            **payload,
        }
        with self._lock:
            self._events.append(event)
        return event

    def events_since(self, seq: int, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            return [e for e in self._events if e["seq"] > seq][:limit]

    def recent_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._events)[-limit:]


class FrameStore:
    """Latest JPEG bytes per feed name ('rgb' | 'thermal' | 'fused')."""

    def __init__(self):
        self._lock = threading.Lock()
        self._frames: Dict[str, Tuple[int, bytes]] = {}
        self._counter = itertools.count(1)

    def put(self, feed: str, jpeg: bytes) -> None:
        with self._lock:
            self._frames[feed] = (next(self._counter), jpeg)

    def get(self, feed: str) -> Optional[Tuple[int, bytes]]:
        with self._lock:
            return self._frames.get(feed)

    def feeds(self) -> List[str]:
        with self._lock:
            return list(self._frames.keys())
