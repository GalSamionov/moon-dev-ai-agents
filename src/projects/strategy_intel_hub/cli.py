"""Command line interface for the Strategy & Intelligence hub."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Optional

from .config import (
    IntelligencePipelineConfig,
    ResearchPipelineConfig,
    StrategyIntelHubConfig,
)
from .hub import create_default_hub


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Moon Dev's combined research/backtesting + market intelligence workflow."
    )
    parser.add_argument(
        "--research-interval",
        type=int,
        default=90,
        help="Minutes between research/backtesting cycles (default: 90)",
    )
    parser.add_argument(
        "--intel-interval",
        type=int,
        default=10,
        help="Minutes between market intelligence sweeps (default: 10)",
    )
    parser.add_argument(
        "--agent-cooldown",
        type=int,
        default=5,
        help="Seconds to pause between individual market intelligence agents (default: 5)",
    )
    parser.add_argument(
        "--max-agent-failures",
        type=int,
        default=3,
        help="Number of consecutive failures before an agent is flagged (default: 3)",
    )
    parser.add_argument(
        "--no-backtests",
        action="store_true",
        help="Skip the RBI backtest step (useful when validating idea generation only)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Python logging level (DEBUG, INFO, WARNING, ERROR). Default: INFO",
    )
    parser.add_argument(
        "--event-log",
        type=str,
        help="Optional path to a JSONL event log for research/intelligence cycle results",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> None:
    args = _parse_args(argv)

    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    event_log_path = Path(args.event_log).expanduser() if args.event_log else None

    config = StrategyIntelHubConfig(
        research=ResearchPipelineConfig(
            cycle_minutes=args.research_interval,
            enable_backtests=not args.no_backtests,
        ),
        intelligence=IntelligencePipelineConfig(
            cycle_minutes=args.intel_interval,
            agent_cooldown_seconds=args.agent_cooldown,
            max_consecutive_failures=args.max_agent_failures,
        ),
        log_level=log_level,
        event_log_path=event_log_path,
    )

    hub = create_default_hub(config=config)

    try:
        asyncio.run(hub.run_forever())
    except KeyboardInterrupt:
        logging.getLogger("strategy_intel_hub.cli").info("Shutdown requested by user")
        hub.stop()


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
