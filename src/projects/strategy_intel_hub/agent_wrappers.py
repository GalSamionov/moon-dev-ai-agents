"""Utility wrappers that adapt standalone agents into reusable tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class AgentRunner:
    """Lazily instantiate an agent and expose a single-cycle callable."""

    name: str
    factory: Callable[[], Any]
    run_method: str
    restart_on_failure: bool = True
    description: Optional[str] = None
    _instance: Any = field(init=False, default=None, repr=False)

    def ensure_instance(self) -> Any:
        """Return an agent instance, creating it on first use."""

        if self._instance is None:
            self._instance = self.factory()
        return self._instance

    def reset(self) -> None:
        """Forget the cached instance so it will be recreated next call."""

        self._instance = None

    def run_cycle(self) -> Any:
        """Execute a single monitoring cycle for the wrapped agent."""

        agent = self.ensure_instance()
        handler = getattr(agent, self.run_method)
        return handler()
