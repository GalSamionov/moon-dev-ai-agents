"""Structured events and logging helpers for the strategy intel hub."""

from __future__ import annotations

import json
import asyncio
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Deque, Iterable, List, Optional, Protocol, Sequence


@dataclass
class ResearchCycleResult:
    """Outcome of a single research/backtesting iteration."""

    model_name: str
    attempts: int = 0
    idea: Optional[str] = None
    duplicates_skipped: int = 0
    backtest_requested: bool = False
    backtest_completed: bool = False
    error: Optional[str] = None
    duration_seconds: float = 0.0


@dataclass
class IntelligenceCycleResult:
    """Outcome of running one market intelligence agent."""

    agent_name: str
    success: bool
    duration_seconds: float
    result: Any = None
    error: Optional[str] = None
    failure_count: int = 0
    description: Optional[str] = None


class EventSink(Protocol):
    """Protocol for objects that capture hub events."""

    def record_research(self, result: ResearchCycleResult) -> None:  # pragma: no cover - interface definition
        """Persist details about a research cycle."""

    def record_intelligence(self, result: IntelligenceCycleResult) -> None:  # pragma: no cover - interface definition
        """Persist details about a market intelligence cycle."""


def _default_json_serializer(value: Any) -> Any:
    """Fallback serializer that stringifies unknown objects."""

    if isinstance(value, (datetime, Path)):
        return str(value)
    return repr(value)


def _build_event_payload(kind: str, result: Any) -> dict[str, Any]:
    """Serialize a dataclass result into a JSON-friendly payload."""

    payload = asdict(result)
    payload.update({"event": kind, "timestamp": datetime.utcnow().isoformat()})
    return payload


@dataclass
class JsonlEventLogger:
    """Append-only JSONL writer for hub events."""

    path: Path
    _lock: Lock = field(init=False, repr=False, default_factory=Lock)

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record_research(self, result: ResearchCycleResult) -> None:
        self._write(_build_event_payload("research", result))

    def record_intelligence(self, result: IntelligenceCycleResult) -> None:
        self._write(_build_event_payload("intelligence", result))

    def _write(self, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, default=_default_json_serializer)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")


class CompositeEventSink:
    """Dispatch events to multiple sinks."""

    def __init__(self, sinks: Sequence[EventSink]) -> None:
        self._sinks: tuple[EventSink, ...] = tuple(sinks)

    def record_research(self, result: ResearchCycleResult) -> None:
        for sink in self._sinks:
            sink.record_research(result)

    def record_intelligence(self, result: IntelligenceCycleResult) -> None:
        for sink in self._sinks:
            sink.record_intelligence(result)


class LiveEventBroadcaster:
    """In-memory event sink with async subscriptions for UI clients."""

    def __init__(self, *, max_events: int = 200) -> None:
        self.max_events = max_events
        self._events: Deque[dict[str, Any]] = deque(maxlen=max_events)
        self._listeners: List[asyncio.Queue] = []
        self._lock = Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def record_research(self, result: ResearchCycleResult) -> None:
        self._store_and_dispatch(_build_event_payload("research", result))

    def record_intelligence(self, result: IntelligenceCycleResult) -> None:
        self._store_and_dispatch(_build_event_payload("intelligence", result))

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)

    async def subscribe(self) -> asyncio.Queue:
        """Register a listener queue and replay the backlog."""

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        with self._lock:
            self._listeners.append(queue)
            backlog = list(self._events)
            self._loop = loop

        for event in backlog:
            queue.put_nowait(event)

        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            if queue in self._listeners:
                self._listeners.remove(queue)
            if not self._listeners:
                self._loop = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _store_and_dispatch(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._events.append(event)
            listeners = tuple(self._listeners)
            loop = self._loop

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is not None and loop is None:
            loop = running_loop
            self._loop = loop

        if not listeners:
            return

        if loop is None:
            for queue in listeners:
                queue.put_nowait(event)
            return

        if running_loop is loop:
            for queue in listeners:
                queue.put_nowait(event)
        else:
            loop.call_soon_threadsafe(self._fan_out, listeners, event)

    @staticmethod
    def _fan_out(listeners: Iterable[asyncio.Queue], event: dict[str, Any]) -> None:
        for queue in listeners:
            queue.put_nowait(event)
