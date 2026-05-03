"""task_class shortcuts over `POST /v1/llm/complete`.

The five v1 task classes (per `docs/api-contract.md`) are shipped as
top-level functions: ``triage``, ``classify``, ``reason``, ``draft``,
``summarise``. Each pre-fills `task_class` and forwards the rest of
the kwargs to the generated client.

Brains write::

    from brains_shared import llm
    response = await llm.triage(client, messages=[
        {"role": "user", "content": "should I respond to …?"}
    ])

The result is the generated ``LLMCompleteResponse`` — same shape as
the API contract response, with `provider`, `model`, `content`,
`usage`, `latency_ms`.
"""

from __future__ import annotations

import json
from typing import Literal

from brains_shared._generated.api.llm import llm_complete_v1_llm_complete_post
from brains_shared._generated.models.llm_complete_request import LLMCompleteRequest
from brains_shared._generated.models.llm_complete_request_provider_hint import (
    LLMCompleteRequestProviderHint,
)
from brains_shared._generated.models.llm_complete_request_response_format import (
    LLMCompleteRequestResponseFormat,
)
from brains_shared._generated.models.llm_complete_request_task_class import (
    LLMCompleteRequestTaskClass,
)
from brains_shared._generated.models.llm_complete_response import LLMCompleteResponse
from brains_shared._generated.models.message import Message
from brains_shared._generated.models.message_role import MessageRole
from brains_shared._generated.types import UNSET
from brains_shared.client import BridgeClient

ProviderHint = Literal["auto", "local", "openrouter"]
ResponseFormat = Literal["text", "json"]
MessageRoleStr = Literal["system", "user", "assistant"]
TaskClass = Literal["triage", "classify", "reason", "draft", "summarise"]

_PROVIDER_HINTS: dict[str, LLMCompleteRequestProviderHint] = {
    "auto": LLMCompleteRequestProviderHint.AUTO,
    "local": LLMCompleteRequestProviderHint.LOCAL,
    "openrouter": LLMCompleteRequestProviderHint.OPENROUTER,
}
_RESPONSE_FORMATS: dict[str, LLMCompleteRequestResponseFormat] = {
    "text": LLMCompleteRequestResponseFormat.TEXT,
    "json": LLMCompleteRequestResponseFormat.JSON,
}
_MESSAGE_ROLES: dict[str, MessageRole] = {
    "system": MessageRole.SYSTEM,
    "user": MessageRole.USER,
    "assistant": MessageRole.ASSISTANT,
}
_TASK_CLASSES: dict[str, LLMCompleteRequestTaskClass] = {
    "triage": LLMCompleteRequestTaskClass.TRIAGE,
    "classify": LLMCompleteRequestTaskClass.CLASSIFY,
    "reason": LLMCompleteRequestTaskClass.REASON,
    "draft": LLMCompleteRequestTaskClass.DRAFT,
    "summarise": LLMCompleteRequestTaskClass.SUMMARISE,
}


class LLMError(RuntimeError):
    """Raised when the bridge returns a non-200 from `/v1/llm/complete`."""

    def __init__(self, *, status: int, code: str, message: str) -> None:
        super().__init__(f"llm error {status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message

    @classmethod
    def from_response(cls, status: int, content: bytes) -> LLMError:
        try:
            envelope = json.loads(content.decode("utf-8")).get("error", {})
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            envelope = {}
        return cls(
            status=status,
            code=str(envelope.get("code", "unknown")),
            message=str(envelope.get("message", "")),
        )


async def complete(
    client: BridgeClient,
    *,
    task_class: TaskClass,
    messages: list[dict[str, str]],
    provider_hint: ProviderHint = "auto",
    model_hint: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    response_format: ResponseFormat = "text",
) -> LLMCompleteResponse:
    """Generic complete — the five named shortcuts below all delegate here."""
    body = LLMCompleteRequest(
        messages=[_to_message(m) for m in messages],
        task_class=_TASK_CLASSES[task_class],
        max_tokens=max_tokens,
        model_hint=model_hint if model_hint is not None else UNSET,
        provider_hint=_PROVIDER_HINTS[provider_hint],
        response_format=_RESPONSE_FORMATS[response_format],
        temperature=temperature,
    )
    resp = await llm_complete_v1_llm_complete_post.asyncio_detailed(
        client=client.get_inner(),
        body=body,
    )
    if resp.status_code != 200 or not isinstance(resp.parsed, LLMCompleteResponse):
        raise LLMError.from_response(int(resp.status_code), resp.content)
    return resp.parsed


def _to_message(raw: dict[str, str]) -> Message:
    role_str = raw.get("role", "user")
    if role_str not in _MESSAGE_ROLES:
        raise ValueError(f"Unknown message role: {role_str!r}")
    return Message(content=raw["content"], role=_MESSAGE_ROLES[role_str])


# --- task_class shortcuts ---------------------------------------------
#
# Each shortcut has explicit kwargs (rather than `**kwargs: object`) so
# mypy --strict can verify the call chain. The signatures mirror
# `complete()` minus `task_class`.


async def triage(
    client: BridgeClient,
    *,
    messages: list[dict[str, str]],
    provider_hint: ProviderHint = "auto",
    model_hint: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    response_format: ResponseFormat = "text",
) -> LLMCompleteResponse:
    return await complete(
        client,
        task_class="triage",
        messages=messages,
        provider_hint=provider_hint,
        model_hint=model_hint,
        max_tokens=max_tokens,
        temperature=temperature,
        response_format=response_format,
    )


async def classify(
    client: BridgeClient,
    *,
    messages: list[dict[str, str]],
    provider_hint: ProviderHint = "auto",
    model_hint: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    response_format: ResponseFormat = "text",
) -> LLMCompleteResponse:
    return await complete(
        client,
        task_class="classify",
        messages=messages,
        provider_hint=provider_hint,
        model_hint=model_hint,
        max_tokens=max_tokens,
        temperature=temperature,
        response_format=response_format,
    )


async def reason(
    client: BridgeClient,
    *,
    messages: list[dict[str, str]],
    provider_hint: ProviderHint = "auto",
    model_hint: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    response_format: ResponseFormat = "text",
) -> LLMCompleteResponse:
    return await complete(
        client,
        task_class="reason",
        messages=messages,
        provider_hint=provider_hint,
        model_hint=model_hint,
        max_tokens=max_tokens,
        temperature=temperature,
        response_format=response_format,
    )


async def draft(
    client: BridgeClient,
    *,
    messages: list[dict[str, str]],
    provider_hint: ProviderHint = "auto",
    model_hint: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    response_format: ResponseFormat = "text",
) -> LLMCompleteResponse:
    return await complete(
        client,
        task_class="draft",
        messages=messages,
        provider_hint=provider_hint,
        model_hint=model_hint,
        max_tokens=max_tokens,
        temperature=temperature,
        response_format=response_format,
    )


async def summarise(
    client: BridgeClient,
    *,
    messages: list[dict[str, str]],
    provider_hint: ProviderHint = "auto",
    model_hint: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    response_format: ResponseFormat = "text",
) -> LLMCompleteResponse:
    return await complete(
        client,
        task_class="summarise",
        messages=messages,
        provider_hint=provider_hint,
        model_hint=model_hint,
        max_tokens=max_tokens,
        temperature=temperature,
        response_format=response_format,
    )


# Public aliases for callers that prefer the lower-case generic names.
LLMResponse = LLMCompleteResponse


__all__ = [
    "LLMError",
    "LLMResponse",
    "MessageRoleStr",
    "ProviderHint",
    "ResponseFormat",
    "TaskClass",
    "classify",
    "complete",
    "draft",
    "reason",
    "summarise",
    "triage",
]
