"""REST API. The WebSocket channels in ws.py carry the real-time traffic;
these routes serve configuration, history, and one-shot queries."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import DATA_DIR
from ..recording.incidents import IncidentRecorder
from ..voice import commands as voice_grammar


class CommandRequest(BaseModel):
    text: str


def build_router(engine, hub) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/health")
    def health() -> Dict[str, Any]:
        state = hub.get_state()
        return {
            "status": "ok" if state else "starting",
            "mode": engine.config.resolved_mode(),
            "detector": engine.detector.name,
            "fps": state.get("fps"),
        }

    @router.get("/state")
    def get_state() -> Dict[str, Any]:
        return hub.get_state()

    @router.get("/config")
    def get_config() -> Dict[str, Any]:
        return engine.config.to_dict()

    @router.get("/commands")
    def list_commands():
        return voice_grammar.available_commands()

    @router.post("/command")
    def post_command(req: CommandRequest) -> Dict[str, Any]:
        return engine.submit_command(req.text)

    @router.get("/events")
    def recent_events(limit: int = 100):
        return hub.recent_events(limit)

    @router.get("/alerts")
    def alert_history(limit: int = 100):
        return [e for e in hub.recent_events(500) if e["kind"] == "alert"][-limit:]

    @router.get("/incidents")
    def incidents():
        return IncidentRecorder.list_sessions(DATA_DIR)

    @router.get("/incidents/{session_id}")
    def incident_events(session_id: str, limit: int = 500):
        events = IncidentRecorder.read_events(DATA_DIR, session_id, limit)
        if not events:
            raise HTTPException(status_code=404, detail="no such session")
        return events

    return router
