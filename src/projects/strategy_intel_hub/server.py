"""FastAPI server that visualizes Strategy Intel Hub events in real time."""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import Callable, Iterable, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import StrategyIntelHubConfig
from .events import CompositeEventSink, JsonlEventLogger, LiveEventBroadcaster
from .hub import StrategyIntelHub, create_default_hub

DEFAULT_STATIC_DIR = Path(__file__).with_name("static")
INDEX_PATH = DEFAULT_STATIC_DIR / "index.html"


def _build_event_sink(
    broadcaster: LiveEventBroadcaster,
    config: StrategyIntelHubConfig,
) -> CompositeEventSink | LiveEventBroadcaster:
    sinks: list = [broadcaster]
    if config.event_log_path:
        sinks.append(JsonlEventLogger(config.event_log_path))
    if len(sinks) == 1:
        return broadcaster
    return CompositeEventSink(tuple(sinks))


def _serialize_agents(agents: Iterable) -> list[dict[str, Optional[str]]]:
    summary: list[dict[str, Optional[str]]] = []
    for runner in agents:
        summary.append(
            {
                "name": getattr(runner, "name", "unknown"),
                "description": getattr(runner, "description", None),
            }
        )
    return summary


def create_app(
    config: Optional[StrategyIntelHubConfig] = None,
    *,
    hub_factory: Callable[[StrategyIntelHubConfig, LiveEventBroadcaster | CompositeEventSink], StrategyIntelHub]
    = create_default_hub,
    start_background: bool = True,
) -> FastAPI:
    """Instantiate a FastAPI application backed by the strategy intel hub."""

    config = config or StrategyIntelHubConfig()
    broadcaster = LiveEventBroadcaster()
    event_sink = _build_event_sink(broadcaster, config)

    hub = hub_factory(config=config, event_sink=event_sink)

    app = FastAPI(title="Strategy Intelligence Hub", version="0.1.0")
    app.state.config = config
    app.state.hub = hub
    app.state.broadcaster = broadcaster
    app.state.event_sink = event_sink
    app.state.start_background = start_background

    if DEFAULT_STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=DEFAULT_STATIC_DIR), name="static")

    if start_background:
        @app.on_event("startup")
        async def _startup() -> None:  # pragma: no cover - exercised in integration tests
            app.state.hub_task = asyncio.create_task(hub.run_forever())

        @app.on_event("shutdown")
        async def _shutdown() -> None:  # pragma: no cover - exercised in integration tests
            hub.stop()
            task = getattr(app.state, "hub_task", None)
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
    else:
        @app.on_event("shutdown")
        async def _shutdown_noop() -> None:
            hub.stop()

    @app.get("/")
    async def index() -> FileResponse:
        if not INDEX_PATH.exists():
            raise HTTPException(status_code=404, detail="UI assets missing")
        return FileResponse(INDEX_PATH)

    @app.get("/api/status")
    async def status() -> JSONResponse:
        cfg = app.state.config
        research_cfg = cfg.research
        intel_cfg = cfg.intelligence
        hub_agents = getattr(app.state.hub, "market_agents", [])
        payload = {
            "research": {
                "cycle_minutes": research_cfg.cycle_minutes,
                "enable_backtests": research_cfg.enable_backtests,
                "idea_retry_limit": research_cfg.idea_retry_limit,
            },
            "intelligence": {
                "cycle_minutes": intel_cfg.cycle_minutes,
                "agent_cooldown_seconds": intel_cfg.agent_cooldown_seconds,
                "max_consecutive_failures": intel_cfg.max_consecutive_failures,
            },
            "market_agents": _serialize_agents(hub_agents),
        }
        return JSONResponse(payload)

    @app.get("/api/events")
    async def list_events() -> JSONResponse:
        return JSONResponse({"events": broadcaster.snapshot()})

    @app.get("/api/events/stream")
    async def stream_events() -> StreamingResponse:
        queue = await broadcaster.subscribe()

        async def event_generator():
            try:
                while True:
                    event = await queue.get()
                    yield f"data: {json.dumps(event, default=str)}\n\n"
            finally:
                await broadcaster.unsubscribe(queue)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    return app


__all__ = [
    "create_app",
]
