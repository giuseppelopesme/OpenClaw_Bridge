"""Per-process context handed to every handler.

A frozen dataclass wrapping the pieces a handler needs: the
``BridgeClient`` for HTTP calls, the SQLite-backed ``State`` for
dedup + drafts, and the ``AgentConfig``. Constructed once in
``main.run`` and reused for the life of the process.
"""

from __future__ import annotations

from dataclasses import dataclass

from brains_shared import BridgeClient

from agent.config import AgentConfig
from agent.state import State


@dataclass(frozen=True)
class BrainContext:
    client: BridgeClient
    state: State
    config: AgentConfig


__all__ = ["BrainContext"]
