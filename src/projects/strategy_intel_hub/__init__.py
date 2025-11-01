"""Unified research and market intelligence orchestration."""

from .config import (
    StrategyIntelHubConfig,
    ResearchPipelineConfig,
    IntelligencePipelineConfig,
)
from .agent_wrappers import AgentRunner
from .events import (
    CompositeEventSink,
    IntelligenceCycleResult,
    JsonlEventLogger,
    LiveEventBroadcaster,
    ResearchCycleResult,
)
from .hub import StrategyIntelHub, create_default_hub

try:  # pragma: no cover - optional dependency for the web UI
    from .server import create_app
except ModuleNotFoundError:  # fastapi not installed in minimal environments
    create_app = None  # type: ignore[assignment]

__all__ = [
    "StrategyIntelHub",
    "create_default_hub",
    "StrategyIntelHubConfig",
    "ResearchPipelineConfig",
    "IntelligencePipelineConfig",
    "AgentRunner",
    "JsonlEventLogger",
    "CompositeEventSink",
    "LiveEventBroadcaster",
    "ResearchCycleResult",
    "IntelligenceCycleResult",
]

if create_app is not None:  # pragma: no cover - depends on optional fastapi
    __all__.append("create_app")
