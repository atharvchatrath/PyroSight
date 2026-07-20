"""
WebSocket channels.

  /ws/telemetry — JSON. Server pushes {type:"state"} at telemetry_hz plus
                  {type:"event"} for everything new since the client's last
                  delivery (alerts, detections, command acks). Clients may
                  send {type:"command", text:"find exit"}.
  /ws/video     — binary JPEG frames for ?feed=rgb|thermal|fused at
                  video_hz, skipping resends when the frame hasn't changed.

Both endpoints tolerate slow clients: they always transmit the *latest*
state/frame, never a growing backlog.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


def build_ws_router(engine, hub, frames) -> APIRouter:
    router = APIRouter()
    telemetry_dt = 1.0 / max(1.0, engine.config.server.telemetry_hz)
    video_dt = 1.0 / max(1.0, engine.config.server.video_hz)

    @router.websocket("/ws/telemetry")
    async def telemetry(ws: WebSocket) -> None:
        await ws.accept()
        await ws.send_text(json.dumps({
            "type": "hello",
            "config": engine.config.to_dict(),
            "history": hub.recent_events(50),
        }))
        last_event_seq = 0
        history = hub.recent_events(1)
        if history:
            last_event_seq = history[-1]["seq"]

        async def receiver() -> None:
            while True:
                raw = await ws.receive_text()
                try:
                    msg: Dict[str, Any] = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") == "command" and isinstance(msg.get("text"), str):
                    engine.submit_command(msg["text"][:200])

        recv_task = asyncio.create_task(receiver())
        try:
            while True:
                state = hub.get_state()
                if state:
                    await ws.send_text(json.dumps({"type": "state", "state": state}))
                for event in hub.events_since(last_event_seq):
                    last_event_seq = event["seq"]
                    await ws.send_text(json.dumps({"type": "event", "event": event}))
                await asyncio.sleep(telemetry_dt)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            recv_task.cancel()

    @router.websocket("/ws/ingest")
    async def ingest(ws: WebSocket) -> None:
        """Browser camera -> backend: binary JPEG frames in, pipeline output
        observable on the normal telemetry/video channels."""
        await ws.accept()
        try:
            while True:
                data = await ws.receive_bytes()
                if len(data) < 100 or len(data) > 2_000_000:
                    continue  # garbage or absurd frame: drop
                engine.ingest_frame(data)
        except (WebSocketDisconnect, RuntimeError, KeyError):
            pass

    @router.websocket("/ws/video")
    async def video(ws: WebSocket) -> None:
        await ws.accept()
        feed = ws.query_params.get("feed", "fused")
        if feed not in ("rgb", "thermal", "fused"):
            feed = "fused"
        last_id = -1
        try:
            while True:
                item = frames.get(feed)
                if item is not None and item[0] != last_id:
                    last_id = item[0]
                    await ws.send_bytes(item[1])
                await asyncio.sleep(video_dt)
        except (WebSocketDisconnect, RuntimeError):
            pass

    return router
