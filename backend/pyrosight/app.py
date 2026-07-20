"""
FastAPI application factory. Wires config -> engine -> REST + WebSocket
routes, with the engine running for the app's whole lifespan.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api.routes import build_router
from .api.ws import build_ws_router
from .config import load_config
from .core.events import FrameStore, TelemetryHub
from .pipeline.engine import PerceptionEngine


def create_app() -> FastAPI:
    config = load_config()
    hub = TelemetryHub()
    frames = FrameStore()
    engine = PerceptionEngine(config, hub, frames)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine.start()
        try:
            yield
        finally:
            engine.stop()

    app = FastAPI(title="PyroSight", version=__version__, lifespan=lifespan)

    origins = config.server.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if origins == "*" else [o.strip() for o in origins.split(",")],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(build_router(engine, hub))
    app.include_router(build_ws_router(engine, hub, frames))

    # Expose for tests / debugging.
    app.state.engine = engine
    app.state.hub = hub
    return app
