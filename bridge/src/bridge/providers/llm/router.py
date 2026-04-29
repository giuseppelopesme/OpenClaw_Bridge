"""Per-task_class provider routing per `docs/api-contract.md` § LLM.

Routing logic v1:

- `provider_hint=auto` →
    - `triage`/`classify` prefer the local provider if available, else openrouter.
    - `reason`/`draft`/`summarise` always go to openrouter.
- `provider_hint=local` → local provider if available, else `DependencyUnavailable`.
- `provider_hint=openrouter` → openrouter directly.

The local provider is intentionally absent in Session 3 — the slot is
wired so when Session 4+ adds one, the routing logic does not change.
The `local` branch always falls through to OpenRouter under `auto` and
raises `DependencyUnavailable` under explicit `local`. TODO comment marks
the swap point.
"""

from __future__ import annotations

import logging
from typing import Final

from bridge.errors import DependencyUnavailable
from bridge.providers.llm.base import LLMProvider, LLMRequest, LLMResponse, ProviderHint

logger = logging.getLogger("bridge.llm.router")

_LOCAL_PREFERRING_TASKS: Final[frozenset[str]] = frozenset({"triage", "classify"})


class LLMRouter:
    """Picks one provider per request and delegates `complete()`."""

    def __init__(
        self,
        *,
        openrouter: LLMProvider,
        local: LLMProvider | None = None,
    ) -> None:
        self._openrouter = openrouter
        # TODO(session-4+): wire a real local provider (Llama 3.2 / Qwen 2.5
        # per the telemetry plan, depending on which trigger fires).
        self._local = local

    async def complete(self, request: LLMRequest) -> LLMResponse:
        provider = self._select(request.provider_hint, request.task_class)
        return await provider.complete(request)

    def _select(self, hint: ProviderHint, task_class: str) -> LLMProvider:
        if hint == "openrouter":
            return self._openrouter
        if hint == "local":
            if self._local is None:
                raise DependencyUnavailable(
                    "Local LLM provider is not configured.",
                    details={"hint": "local"},
                )
            return self._local
        # auto
        if task_class in _LOCAL_PREFERRING_TASKS and self._local is not None:
            return self._local
        return self._openrouter
