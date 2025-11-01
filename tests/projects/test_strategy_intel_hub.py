import asyncio
import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if "termcolor" not in sys.modules:
    sys.modules["termcolor"] = types.SimpleNamespace(
        cprint=lambda *args, **kwargs: None,
        colored=lambda text, *args, **kwargs: text,
    )

if "pandas" not in sys.modules:
    sys.modules["pandas"] = types.SimpleNamespace(read_csv=lambda *args, **kwargs: None)

if "src.models" not in sys.modules:
    model_factory_module = types.ModuleType("model_factory")
    model_factory_module.get_model = lambda *args, **kwargs: None

    models_module = types.ModuleType("src.models")
    models_module.model_factory = model_factory_module

    sys.modules["src.models"] = models_module
    sys.modules["src.models.model_factory"] = model_factory_module

if "requests" not in sys.modules:
    sys.modules["requests"] = types.ModuleType("requests")

if "openai" not in sys.modules:
    sys.modules["openai"] = types.ModuleType("openai")

import pytest

from src.projects.strategy_intel_hub import (
    AgentRunner,
    IntelligencePipelineConfig,
    JsonlEventLogger,
    LiveEventBroadcaster,
    ResearchCycleResult,
    ResearchPipelineConfig,
    StrategyIntelHub,
    StrategyIntelHubConfig,
)


@pytest.fixture(autouse=True)
def stub_research_agent(monkeypatch):
    monkeypatch.setattr("src.projects.strategy_intel_hub.hub.research_agent.setup_files", lambda: None)
    monkeypatch.setattr("src.projects.strategy_intel_hub.hub.research_agent.load_existing_ideas", lambda: set())
    monkeypatch.setattr(
        "src.projects.strategy_intel_hub.hub.research_agent.log_idea",
        lambda idea, model_config: None,
    )
    monkeypatch.setattr(
        "src.projects.strategy_intel_hub.hub.research_agent.is_duplicate",
        lambda idea, existing: False,
    )
    monkeypatch.setattr("src.projects.strategy_intel_hub.hub.rbi_agent.process_trading_idea", lambda idea: None)


def test_run_research_cycle_once_records_event(tmp_path, monkeypatch):
    events_path = tmp_path / "events.jsonl"

    monkeypatch.setattr(
        "src.projects.strategy_intel_hub.hub.research_agent.generate_idea",
        lambda config: "Test idea",
    )

    config = StrategyIntelHubConfig(
        research=ResearchPipelineConfig(
            cycle_minutes=0,
            enable_backtests=False,
            idea_models=[{"type": "fake", "name": "model"}],
        ),
        intelligence=IntelligencePipelineConfig(cycle_minutes=0),
    )

    logger = JsonlEventLogger(events_path)
    hub = StrategyIntelHub(config=config, market_agents=[], event_sink=logger)

    result = asyncio.run(hub.run_research_cycle_once())

    assert result.idea == "Test idea"
    assert result.backtest_requested is False

    payload = _read_jsonl(events_path)
    assert payload["event"] == "research"
    assert payload["idea"] == "Test idea"
    assert payload["backtest_completed"] is False


def test_run_intelligence_cycle_once_records_events(tmp_path, monkeypatch):
    events_path = tmp_path / "intel_events.jsonl"

    class DummyAgent:
        def __init__(self) -> None:
            self.calls = 0

        def cycle(self):
            self.calls += 1
            return {"calls": self.calls}

    runner = AgentRunner("dummy", DummyAgent, "cycle", restart_on_failure=False)

    config = StrategyIntelHubConfig(
        research=ResearchPipelineConfig(
            cycle_minutes=0,
            enable_backtests=False,
            idea_models=[{"type": "fake", "name": "model"}],
        ),
        intelligence=IntelligencePipelineConfig(cycle_minutes=0, agent_cooldown_seconds=0),
    )

    logger = JsonlEventLogger(events_path)
    hub = StrategyIntelHub(config=config, market_agents=[runner], event_sink=logger)

    results = asyncio.run(hub.run_intelligence_cycle_once())
    assert len(results) == 1
    assert results[0].success is True
    assert results[0].result == {"calls": 1}

    payload = _read_jsonl(events_path)
    assert payload["event"] == "intelligence"
    assert payload["agent_name"] == "dummy"
    assert payload["success"] is True


def test_intelligence_failure_logged(tmp_path, monkeypatch):
    events_path = tmp_path / "intel_fail.jsonl"

    class FailingAgent:
        def cycle(self):
            raise RuntimeError("boom")

    runner = AgentRunner("failing", FailingAgent, "cycle", restart_on_failure=False)

    config = StrategyIntelHubConfig(
        research=ResearchPipelineConfig(
            cycle_minutes=0,
            enable_backtests=False,
            idea_models=[{"type": "fake", "name": "model"}],
        ),
        intelligence=IntelligencePipelineConfig(cycle_minutes=0, agent_cooldown_seconds=0, max_consecutive_failures=1),
    )

    logger = JsonlEventLogger(events_path)
    hub = StrategyIntelHub(config=config, market_agents=[runner], event_sink=logger)

    results = asyncio.run(hub.run_intelligence_cycle_once())
    assert results[0].success is False
    assert results[0].error == "boom"
    assert results[0].failure_count == 1

    payload = _read_jsonl(events_path)
    assert payload["event"] == "intelligence"
    assert payload["success"] is False
    assert payload["error"] == "boom"


def test_live_event_broadcaster_subscription():
    broadcaster = LiveEventBroadcaster(max_events=10)

    async def exercise():
        queue = await broadcaster.subscribe()
        broadcaster.record_research(ResearchCycleResult(model_name="stub", idea="alpha"))
        event = await asyncio.wait_for(queue.get(), timeout=1)
        await broadcaster.unsubscribe(queue)
        return event

    event = asyncio.run(exercise())
    assert event["event"] == "research"
    assert event["idea"] == "alpha"
    assert broadcaster.snapshot()[0]["idea"] == "alpha"


def _read_jsonl(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        line = fh.readline().strip()
    return json.loads(line)
