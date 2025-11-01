import asyncio
import json
import types

import pytest

pytest.importorskip("fastapi", reason="FastAPI is required for UI integration tests")
from fastapi.testclient import TestClient

from src.projects.strategy_intel_hub import (
    IntelligenceCycleResult,
    IntelligencePipelineConfig,
    ResearchCycleResult,
    ResearchPipelineConfig,
    StrategyIntelHubConfig,
    create_app,
)


class StubHub:
    def __init__(self, *, market_agents=None):
        self.market_agents = market_agents or []
        self._stop_event = asyncio.Event()

    async def run_forever(self):  # pragma: no cover - not executed with start_background=False
        await self._stop_event.wait()

    def stop(self):
        self._stop_event.set()


@pytest.fixture
def stub_hub_factory():
    def _factory(config, event_sink):
        agents = [types.SimpleNamespace(name="whale", description="Tracks whale wallets")]
        return StubHub(market_agents=agents)

    return _factory


def _build_app(stub_hub_factory):
    config = StrategyIntelHubConfig(
        research=ResearchPipelineConfig(cycle_minutes=30, enable_backtests=False, idea_retry_limit=1),
        intelligence=IntelligencePipelineConfig(
            cycle_minutes=5,
            agent_cooldown_seconds=1,
            max_consecutive_failures=2,
        ),
    )
    return create_app(config=config, hub_factory=stub_hub_factory, start_background=False)


def test_status_endpoint_returns_configuration(stub_hub_factory):
    app = _build_app(stub_hub_factory)

    with TestClient(app) as client:
        response = client.get("/api/status")
        payload = response.json()

    assert response.status_code == 200
    assert payload["research"]["cycle_minutes"] == 30
    assert payload["research"]["enable_backtests"] is False
    assert payload["intelligence"]["agent_cooldown_seconds"] == 1
    assert payload["market_agents"][0]["name"] == "whale"


def test_events_endpoint_reflects_recorded_results(stub_hub_factory):
    app = _build_app(stub_hub_factory)

    with TestClient(app) as client:
        sink = client.app.state.event_sink
        sink.record_research(ResearchCycleResult(model_name="test", idea="Alpha"))

        response = client.get("/api/events")
        data = response.json()

    assert response.status_code == 200
    assert data["events"][0]["event"] == "research"
    assert data["events"][0]["idea"] == "Alpha"


def test_stream_endpoint_emits_new_events(stub_hub_factory):
    app = _build_app(stub_hub_factory)

    with TestClient(app) as client:
        sink = client.app.state.event_sink

        with client.stream("GET", "/api/events/stream") as stream:
            sink.record_intelligence(
                IntelligenceCycleResult(
                    agent_name="sentiment",
                    success=True,
                    duration_seconds=0.5,
                    result={"bias": "bullish"},
                    failure_count=0,
                )
            )

            for line in stream.iter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    payload = json.loads(line[len("data: ") :])
                    assert payload["event"] == "intelligence"
                    assert payload["agent_name"] == "sentiment"
                    assert payload["result"] == {"bias": "bullish"}
                    break
            else:
                pytest.fail("Stream produced no events")
