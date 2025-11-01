# AI Strategy & Market Intelligence Hub

The repository now ships with a runnable project that merges Moon Dev's research/backtesting stack and its real-time market intelligence agents. It handles idea generation, optional RBI backtesting, and scheduled observational sweeps inside a single asyncio orchestrator.

## Included Modules

| Path | Purpose |
| --- | --- |
| `src/projects/strategy_intel_hub/config.py` | Dataclasses that describe research and intelligence scheduling knobs. |
| `src/projects/strategy_intel_hub/agent_wrappers.py` | Lazy wrappers that make individual agents behave like single-cycle callables. |
| `src/projects/strategy_intel_hub/events.py` | Structured dataclasses, JSONL logging, and a live broadcaster that powers dashboards. |
| `src/projects/strategy_intel_hub/hub.py` | Core orchestrator coordinating idea generation, RBI processing, and market intel loops. |
| `src/projects/strategy_intel_hub/cli.py` | Command line entry point for running the end-to-end workflow. |
| `src/projects/strategy_intel_hub/server.py` | FastAPI factory that streams hub events to browser clients. |
| `src/projects/strategy_intel_hub/web_cli.py` | Convenience launcher that wraps `uvicorn` for the realtime UI. |
| `src/projects/strategy_intel_hub/static/index.html` | Tailwind-inspired dashboard showing status cards and the rolling event feed. |

## Running the Hub

```bash
python -m src.projects.strategy_intel_hub.cli --help

# Example: 60 minute research cadence, 8 minute intel sweep, skip backtests
python -m src.projects.strategy_intel_hub.cli \
  --research-interval 60 \
  --intel-interval 8 \
  --no-backtests \
  --event-log data/strategy_intel_hub/events.jsonl
```

The CLI wires up logging, instantiates `StrategyIntelHub`, and blocks until interrupted (`Ctrl+C`). Configuration flags mirror the dataclasses so the workflow can be tuned without editing code.

## Launching the Web UI

```bash
python -m src.projects.strategy_intel_hub.web_cli --port 8083 --event-log data/strategy_intel_hub/ui_events.jsonl

# or, using uvicorn directly
uvicorn src.projects.strategy_intel_hub.server:create_app --factory --port 8083
```

The UI wraps the same orchestration config as the CLI, streams events over Server-Sent Events (SSE), and renders them in the bundled `static/index.html` dashboard. Existing JSONL logging continues to work alongside the live feed when `--event-log` is supplied.

## Pipeline Overview

1. **Research Cycle**
   - Rotates through `research_agent.MODELS` (or custom overrides) to call `generate_idea`.
   - Deduplicates ideas using the shared CSV/`ideas.txt` store and persists new concepts automatically.
   - Optionally forwards each idea into `rbi_agent.process_trading_idea` for full research → backtest execution.

2. **Market Intelligence Loop**
   - Wraps the Whale, Sentiment, Funding, Liquidation, and Listing Arbitrage agents in `AgentRunner` helpers.
   - Executes each agent in sequence with a configurable cooldown and failure threshold.
   - Logs structured status messages so downstream systems (or future dashboards) can subscribe to actionable output.

3. **Graceful Coordination**
   - Both loops share a cancellation event so `Ctrl+C` or programmatic `hub.stop()` requests exit cleanly.
   - Blocking agent code runs inside `asyncio.to_thread`, preventing slow external APIs from freezing the orchestrator.
   - Optional JSONL event logging (`events.JsonlEventLogger`) captures the outcome of every research/backtesting and market intelligence pass for downstream analytics.

4. **Testable Building Blocks**
   - `StrategyIntelHub.run_research_cycle_once()` and `run_intelligence_cycle_once()` expose single-pass helpers that make unit testing and scripted automation straightforward.
   - `tests/projects/test_strategy_intel_hub.py` demonstrates how to stub heavy agents and assert on the recorded event payloads.

## Customising the Roster

Developers can supply their own `AgentRunner` list when instantiating `StrategyIntelHub` to add or remove monitors:

```python
from src.projects.strategy_intel_hub import StrategyIntelHub, StrategyIntelHubConfig
from src.projects.strategy_intel_hub.agent_wrappers import AgentRunner
from src.agents.chartanalysis_agent import ChartAnalysisAgent

hub = StrategyIntelHub(
    config=StrategyIntelHubConfig(),
    market_agents=[
        AgentRunner("chart", ChartAnalysisAgent, "run"),
    ],
)
```

Any agent method that performs a single analytical pass (e.g., `run_monitoring_cycle`) can be wrapped this way.

## Extending Beyond Crypto

- **Equities & Futures**: Swap data adapters in generated RBI strategies for Polygon/Quandl/IBKR connectors, or point sentiment/whale prompts at equities data sources.
- **Alert Delivery**: Layer Telegram/Slack/httpx notifiers on top of the log messages or agent return payloads.
- **Dashboards**: Use the bundled FastAPI UI or extend it with additional charts that subscribe to the live SSE feed.
- **Event Replay**: Point analytics notebooks at the JSONL event log to review success/failure rates, latency, and model utilisation.

This project-level scaffold lets teams explore, validate, and monitor strategies continuously while reusing Moon Dev's large library of specialised agents.
