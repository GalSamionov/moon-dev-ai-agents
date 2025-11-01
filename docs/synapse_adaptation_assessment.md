# Synapse AI Compatibility Assessment

This document compares the Synapse AI Trading Decision-Support System PRD against the existing Moon Dev AI Agents repository to gauge reusability and customization effort.

## Repository Snapshot
- **Core Orchestration:** `src/main.py` provides a sequential loop that runs selected agents one after another with configurable sleep intervals, but it does not expose a FastAPI surface or background scheduler like Synapse requires. 【F:src/main.py†L1-L78】
- **Flagship Agent:** `trading_agent.py` already supports single-model or six-model "swarm" consensus decisions with exchange routing logic for Aster, HyperLiquid, and Solana. 【F:src/agents/trading_agent.py†L1-L117】
- **Risk Controls:** `risk_agent.py` wraps portfolio-value checks and override prompts around Anthropic/OpenAI tooling, but it still relies on ad-hoc prompts rather than deterministic policy constraints or quantitative metrics. 【F:src/agents/risk_agent.py†L1-L117】
- **Consensus Utility:** `swarm_agent.py` includes a reusable multi-model consensus helper that could underpin Synapse-style consensus scoring. 【F:src/agents/swarm_agent.py†L1-L94】

## Requirement Mapping

| Synapse PRD Capability | Repository Status | Notes |
| --- | --- | --- |
| **FastAPI server with REST + SSE dashboard** | ❌ Not present by default | Only specialized FastAPI scripts exist for backtest dashboards; no unified API or SSE endpoints in production paths. 【F:src/main.py†L1-L78】【F:src/scripts/backtestdashboard.py†L1-L120】 |
| **Multi-agent concurrent analysis via asyncio** | ⚠️ Partial | Agents execute sequentially inside `run_agents()`; adding `asyncio.gather` and per-agent futures would require significant refactor. 【F:src/main.py†L24-L74】 |
| **Consensus scoring (base/confidence/volatility bonuses)** | ⚠️ Partial | Swarm voting exists, but there is no scoring function or volatility bonus logic. Custom scoring must be implemented on top of `SwarmAgent` outputs. 【F:src/agents/trading_agent.py†L1-L117】【F:src/agents/swarm_agent.py†L39-L94】 |
| **Multi-timeframe (4h/1h/15m) ATR storage in SQLite** | ❌ Missing | Project lacks SQLite persistence layers for indicator history; only generated strategy artifacts store results on disk. No SQLite references for ATR caching. 【F:src/agents/trading_agent.py†L96-L117】 |
| **Scheduler with Israel trading session filtering** | ❌ Missing | No calendar-aware scheduler; `main.py` simply sleeps between loops without timezone checks. 【F:src/main.py†L52-L74】 |
| **Telegram alert pipeline** | ❌ Missing | Repository has no Telegram integrations (`rg "Telegram"` returns none). 【a94c7f†L1-L2】 |
| **Per-agent SQLite history and feedback prompts** | ❌ Missing | Agents do not persist outputs in individual databases; prompts lack historical context injection. 【F:src/agents/trading_agent.py†L1-L117】 |
| **Portfolio exposure & risk dashboards** | ⚠️ Partial | Risk agent can compute balances and enforce soft limits, but there's no aggregated dashboard or Prometheus metrics. 【F:src/agents/risk_agent.py†L56-L117】 |
| **Binance market data ingestion for multiple timeframes** | ⚠️ Partial | Existing code focuses on exchange APIs (Aster/HyperLiquid/Solana) rather than Binance OHLCV; integration would require new adapters. 【F:src/agents/trading_agent.py†L60-L117】 |
| **Automated tests with 100% coverage** | ❌ Missing | pytest suite currently fails to collect because pandas/termcolor dependencies are absent; coverage is unreported. 【7d27aa†L1-L88】 |

## Migration Considerations
1. **API & Scheduler Layer:** Build a FastAPI service that wraps the existing agent calls, introduce APScheduler or asyncio loops for 10-minute cycles, and implement Israel-time filtering. Leverage `swarm_agent.py` as a service module instead of direct CLI execution.
2. **Data Persistence:** Add a database module (SQLite via SQLAlchemy) to track ATR histories, per-agent signal logs, veto counters, and percentile calculations demanded by the PRD.
3. **Notification & Monitoring:** Implement Telegram messaging, Prometheus metrics endpoints, and structured logging to match Synapse’s operational telemetry.
4. **Backtesting & Risk Alignment:** Extend `risk_agent.py` to read/write persistent risk metrics and align prompts with deterministic guardrails. Integrate Binance data collectors or reuse existing OHLCV collectors after adapting them to Binance’s API.
5. **Testing & Tooling:** Update `requirements.txt` with the missing scientific stack, ensure pytest fixtures provide mock data, and target the PRD’s 100% test coverage benchmark.

## Conclusion
The Moon Dev AI Agents repository offers valuable building blocks—most notably the configurable trading agent and swarm consensus helper—but large portions of the Synapse specification (API services, multi-timeframe volatility database, scheduling, telemetry, and Telegram alerts) would need to be implemented from scratch. Treat this codebase as a library of agent implementations rather than a drop-in platform for Synapse’s production workflow.
