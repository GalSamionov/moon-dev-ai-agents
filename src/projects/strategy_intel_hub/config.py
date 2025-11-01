"""Configuration objects for the strategy intelligence hub."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class ResearchPipelineConfig:
    """Settings for the research/backtesting pipeline."""

    cycle_minutes: int = 90
    enable_backtests: bool = True
    idea_models: Optional[List[Dict[str, str]]] = None
    idea_retry_limit: int = 2


@dataclass
class IntelligencePipelineConfig:
    """Settings for the market intelligence monitors."""

    cycle_minutes: int = 10
    agent_cooldown_seconds: int = 5
    max_consecutive_failures: int = 3


@dataclass
class StrategyIntelHubConfig:
    """Top-level configuration for the combined project."""

    research: ResearchPipelineConfig = field(default_factory=ResearchPipelineConfig)
    intelligence: IntelligencePipelineConfig = field(default_factory=IntelligencePipelineConfig)
    log_level: int = logging.INFO
    event_log_path: Optional[Path] = None
