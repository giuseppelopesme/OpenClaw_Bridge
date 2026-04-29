"""Provider-agnostic LLM types and the `LLMProvider` Protocol.

Shapes mirror `docs/api-contract.md` so the route handler can pass these
straight to the provider without translation. Providers (OpenRouter,
local-in-future) implement `LLMProvider.complete`; the router picks one
per `task_class` + `provider_hint`.

Errors raised by providers should be `bridge.errors.BridgeError` subclasses
(typically `DependencyUnavailable`) so the existing exception handler
renders the spec envelope. Timeouts fold into `DependencyUnavailable` with
`details.timeout=true` per the Session 3 decision (see SESSION-NOTES).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

TaskClass = Literal["triage", "classify", "reason", "draft", "summarise"]
ProviderHint = Literal["auto", "local", "openrouter"]
ResponseFormat = Literal["text", "json"]
Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class LLMMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class LLMRequest:
    """Inputs to a provider call. Mirrors `POST /v1/llm/complete` request body."""

    task_class: TaskClass
    messages: Sequence[LLMMessage]
    provider_hint: ProviderHint = "auto"
    model_hint: str | None = None
    max_tokens: int = 1024
    temperature: float = 0.2
    response_format: ResponseFormat = "text"


@dataclass(frozen=True)
class LLMUsage:
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


@dataclass(frozen=True)
class LLMResponse:
    """Outputs from a provider call. Mirrors `POST /v1/llm/complete` response body."""

    provider: str
    model: str
    content: str
    usage: LLMUsage
    latency_ms: int
    extras: dict[str, object] = field(default_factory=dict)


class LLMProvider(Protocol):
    """One method that does the actual work. Async — providers do real I/O."""

    name: str
    """Stable identifier written to telemetry (`provider` column)."""

    async def complete(self, request: LLMRequest) -> LLMResponse: ...

    async def healthcheck(self) -> Literal["ok", "degraded", "down"]:
        """Cheap probe used by `/v1/health`. Should not raise."""
        ...
