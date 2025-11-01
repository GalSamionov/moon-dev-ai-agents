"""CLI entry point for launching the Strategy Intel Hub UI."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Optional

import uvicorn
from .config import (
    IntelligencePipelineConfig,
    ResearchPipelineConfig,
    StrategyIntelHubConfig,
)
from .server import create_app


def _parse_ui_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch the Strategy Intelligence Hub web UI with live event streaming.",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Interface to bind the server to (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8083, help="Port for the web UI (default: 8083)")
    parser.add_argument(
        "--uvicorn-log-level",
        default="info",
        help="Log level passed to uvicorn (default: info)",
    )
    parser.add_argument(
        "--event-log",
        type=str,
        help="Optional path to append JSONL events while streaming to the UI",
    )
    parser.add_argument(
        "--no-backtests",
        action="store_true",
        help="Disable the RBI backtest step while running the UI",
    )
    parser.add_argument(
        "--research-interval",
        type=int,
        default=90,
        help="Minutes between research cycles (default: 90)",
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
        help="Seconds between agent executions inside a sweep (default: 5)",
    )
    parser.add_argument(
        "--max-agent-failures",
        type=int,
        default=3,
        help="Consecutive failures before an agent is flagged (default: 3)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Python logging level for the hub (default: INFO)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> None:
    args = _parse_ui_args(argv)

    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.basicConfig(level=log_level, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")

    event_log = Path(args.event_log).expanduser() if args.event_log else None

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
        event_log_path=event_log,
    )

    app = create_app(config=config)

    uvicorn.run(app, host=args.host, port=args.port, log_level=args.uvicorn_log_level)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
