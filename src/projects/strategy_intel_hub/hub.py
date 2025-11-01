"""Async orchestration that fuses research/backtesting with live intel feeds."""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from typing import Iterable, List, Optional

from .agent_wrappers import AgentRunner
from .config import StrategyIntelHubConfig
from .events import EventSink, IntelligenceCycleResult, JsonlEventLogger, ResearchCycleResult

# Import heavy agents lazily to avoid expensive work when the package is only
# inspected. Individual functions are invoked inside helper methods.
from src.agents import research_agent
from src.agents import rbi_agent

LOGGER_NAME = "strategy_intel_hub"


def build_default_agent_runners() -> List[AgentRunner]:
    """Create wrappers for the default observational agents."""

    runners: List[AgentRunner] = []
    log = logging.getLogger(LOGGER_NAME)

    def register(name: str, factory, method: str, description: Optional[str] = None) -> None:
        runners.append(AgentRunner(name=name, factory=factory, run_method=method, description=description))
        log.debug("Registered market intelligence agent: %s", name)

    try:
        from src.agents.whale_agent import WhaleAgent

        register(
            "whale",
            WhaleAgent,
            "run_monitoring_cycle",
            "Tracks open-interest surges that often precede large moves.",
        )
    except Exception as exc:  # pragma: no cover - dependent on optional deps
        log.warning("Skipping whale agent: %s", exc)

    try:
        from src.agents.sentiment_agent import SentimentAgent

        register(
            "sentiment",
            SentimentAgent,
            "run",
            "Aggregates social sentiment and produces bias summaries.",
        )
    except Exception as exc:  # pragma: no cover - dependent on optional deps
        log.warning("Skipping sentiment agent: %s", exc)

    try:
        from src.agents.funding_agent import FundingAgent

        register(
            "funding",
            FundingAgent,
            "run_monitoring_cycle",
            "Monitors perp funding dislocations across venues.",
        )
    except Exception as exc:  # pragma: no cover - dependent on optional deps
        log.warning("Skipping funding agent: %s", exc)

    try:
        from src.agents.liquidation_agent import LiquidationAgent

        register(
            "liquidation",
            LiquidationAgent,
            "run_monitoring_cycle",
            "Surfaces liquidation clusters that hint at squeeze risk.",
        )
    except Exception as exc:  # pragma: no cover - dependent on optional deps
        log.warning("Skipping liquidation agent: %s", exc)

    try:
        from src.agents.listingarb_agent import ListingArbAgent

        register(
            "listing",
            ListingArbAgent,
            "run_analysis_cycle",
            "Scans new listings for potential arbitrage dislocations.",
        )
    except Exception as exc:  # pragma: no cover - dependent on optional deps
        log.warning("Skipping listing arb agent: %s", exc)

    return runners


class StrategyIntelHub:
    """Coordinate idea generation/backtesting with live intelligence feeds."""

    def __init__(
        self,
        *,
        config: Optional[StrategyIntelHubConfig] = None,
        market_agents: Optional[Iterable[AgentRunner]] = None,
        event_sink: Optional[EventSink] = None,
    ) -> None:
        self.config = config or StrategyIntelHubConfig()

        self.logger = logging.getLogger(LOGGER_NAME)
        self.logger.setLevel(self.config.log_level)

        self.market_agents: List[AgentRunner] = list(market_agents) if market_agents else build_default_agent_runners()
        self._agent_failures = {runner.name: 0 for runner in self.market_agents}

        if event_sink is not None:
            self.event_sink: Optional[EventSink] = event_sink
        elif self.config.event_log_path:
            self.event_sink = JsonlEventLogger(self.config.event_log_path)
        else:
            self.event_sink = None

        self._shutdown = asyncio.Event()

        # Prepare research pipeline assets up-front
        research_agent.setup_files()
        self._existing_ideas = research_agent.load_existing_ideas()

        models = self.config.research.idea_models or list(getattr(research_agent, "MODELS", []))
        if not models:
            raise ValueError("No models configured for research idea generation")
        self._model_cycle = itertools.cycle(models)

        self.logger.debug(
            "StrategyIntelHub initialized with %d market agents", len(self.market_agents)
        )

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------
    async def run_forever(self) -> None:
        """Start both pipelines and block until stopped."""

        tasks = []
        if self.config.research.cycle_minutes > 0:
            tasks.append(asyncio.create_task(self._run_research_loop(), name="research"))
        if self.market_agents and self.config.intelligence.cycle_minutes > 0:
            tasks.append(asyncio.create_task(self._run_intelligence_loop(), name="intelligence"))

        if not tasks:
            self.logger.warning("No tasks scheduled. Adjust configuration to enable pipelines.")
            await self._shutdown.wait()
            return

        try:
            await asyncio.gather(*tasks)
        finally:
            self._shutdown.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def stop(self) -> None:
        """Signal running tasks to stop at the next opportunity."""

        self._shutdown.set()

    # ------------------------------------------------------------------
    # Research pipeline
    # ------------------------------------------------------------------
    async def run_research_cycle_once(self) -> ResearchCycleResult:
        """Execute a single research loop including optional RBI handoff."""

        started = time.perf_counter()
        try:
            result = await asyncio.to_thread(self._run_research_cycle_blocking)
        except Exception as exc:  # pragma: no cover - relies on external services
            duration = time.perf_counter() - started
            failure = ResearchCycleResult(
                model_name="unknown",
                attempts=0,
                error=str(exc),
                duration_seconds=duration,
            )
            if self.event_sink:
                self.event_sink.record_research(failure)
            raise

        result.duration_seconds = time.perf_counter() - started

        if result.idea and self.config.research.enable_backtests:
            result.backtest_requested = True
            try:
                await asyncio.to_thread(self._run_backtest_blocking, result.idea)
            except Exception as exc:  # pragma: no cover - relies on external services
                result.error = str(exc)
                if self.event_sink:
                    self.event_sink.record_research(result)
                raise
            else:
                result.backtest_completed = True

        if self.event_sink:
            self.event_sink.record_research(result)

        return result

    async def _run_research_loop(self) -> None:
        interval = max(1, self.config.research.cycle_minutes) * 60
        self.logger.info("Research pipeline running every %s minutes", self.config.research.cycle_minutes)

        while not self._shutdown.is_set():
            started = time.perf_counter()
            try:
                result = await self.run_research_cycle_once()
            except Exception:  # pragma: no cover - relies on external services
                self.logger.exception("Unexpected error during research cycle")
            else:
                if result.idea:
                    self.logger.info("Generated idea with %s: %s", result.model_name, result.idea)
                else:
                    self.logger.warning(
                        "Research cycle completed without a new idea (attempts=%s)",
                        result.attempts,
                    )

            if await self._sleep_until_next_cycle(started, interval):
                break

    def _run_research_cycle_blocking(self) -> ResearchCycleResult:
        """Generate and log an idea synchronously, handling duplicates."""

        max_attempts = max(1, self.config.research.idea_retry_limit + 1)
        result = ResearchCycleResult(model_name="unknown")

        for _ in range(max_attempts):
            model_config = next(self._model_cycle)
            result.model_name = f"{model_config.get('type')}:{model_config.get('name')}"
            result.attempts += 1

            idea = research_agent.generate_idea(model_config)
            if not idea:
                continue

            if research_agent.is_duplicate(idea, self._existing_ideas):
                result.duplicates_skipped += 1
                self.logger.info("Skipping duplicate idea from %s", result.model_name)
                continue

            research_agent.log_idea(idea, model_config)
            self._existing_ideas.add(idea.lower())
            result.idea = idea
            break

        if not result.idea and result.duplicates_skipped:
            result.error = "duplicate_idea"

        return result

    def _run_backtest_blocking(self, idea: str) -> None:
        """Execute the RBI pipeline for a single idea."""

        self.logger.info("Submitting idea to RBI backtester")
        rbi_agent.process_trading_idea(idea)

    # ------------------------------------------------------------------
    # Market intelligence pipeline
    # ------------------------------------------------------------------
    async def run_intelligence_cycle_once(self) -> List[IntelligenceCycleResult]:
        """Execute a single pass across all configured intelligence agents."""

        results: List[IntelligenceCycleResult] = []
        cooldown = max(0, self.config.intelligence.agent_cooldown_seconds)

        for runner in self.market_agents:
            if self._shutdown.is_set():
                break
            cycle_result = await self._execute_agent_runner(runner)
            results.append(cycle_result)

            if cooldown and not self._shutdown.is_set():
                if await self._wait_or_stop(cooldown):
                    break

        return results

    async def _run_intelligence_loop(self) -> None:
        interval = max(1, self.config.intelligence.cycle_minutes) * 60
        self.logger.info(
            "Market intelligence pipeline running every %s minutes", self.config.intelligence.cycle_minutes
        )

        while not self._shutdown.is_set():
            started = time.perf_counter()

            results = await self.run_intelligence_cycle_once()
            for cycle in results:
                if cycle.success and cycle.result is not None:
                    self.logger.debug("Agent '%s' returned %s", cycle.agent_name, cycle.result)

            if await self._sleep_until_next_cycle(started, interval):
                break

    async def _execute_agent_runner(self, runner: AgentRunner) -> IntelligenceCycleResult:
        started = time.perf_counter()
        try:
            payload = await asyncio.to_thread(runner.run_cycle)
        except Exception as exc:  # pragma: no cover - relies on external services
            self._agent_failures[runner.name] += 1
            self.logger.exception("Agent '%s' cycle failed", runner.name)
            if runner.restart_on_failure:
                runner.reset()

            failure = IntelligenceCycleResult(
                agent_name=runner.name,
                success=False,
                duration_seconds=time.perf_counter() - started,
                result=None,
                error=str(exc),
                failure_count=self._agent_failures[runner.name],
                description=runner.description,
            )

            if self._agent_failures[runner.name] >= self.config.intelligence.max_consecutive_failures:
                self.logger.error(
                    "Agent '%s' exceeded failure threshold (%s).",
                    runner.name,
                    self.config.intelligence.max_consecutive_failures,
                )

            if self.event_sink:
                self.event_sink.record_intelligence(failure)
            return failure

        self._agent_failures[runner.name] = 0
        success = IntelligenceCycleResult(
            agent_name=runner.name,
            success=True,
            duration_seconds=time.perf_counter() - started,
            result=payload,
            failure_count=0,
            description=runner.description,
        )

        if self.event_sink:
            self.event_sink.record_intelligence(success)

        return success

    # ------------------------------------------------------------------
    # Timing helpers
    # ------------------------------------------------------------------
    async def _sleep_until_next_cycle(self, started: float, interval: float) -> bool:
        """Sleep for the remainder of the interval. Return True if stopping."""

        elapsed = time.perf_counter() - started
        remaining = max(0.0, interval - elapsed)
        if remaining <= 0:
            return False
        return await self._wait_or_stop(remaining)

    async def _wait_or_stop(self, seconds: float) -> bool:
        try:
            await asyncio.wait_for(self._shutdown.wait(), timeout=seconds)
            return True
        except asyncio.TimeoutError:
            return False


def create_default_hub(
    config: Optional[StrategyIntelHubConfig] = None,
    *,
    event_sink: Optional[EventSink] = None,
) -> StrategyIntelHub:
    """Factory for a hub with the default market intelligence roster."""

    return StrategyIntelHub(config=config, event_sink=event_sink)
