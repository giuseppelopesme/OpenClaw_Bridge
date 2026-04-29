"""POST /v1/llm/complete — scope `llm:call`.

Routes to a provider via `LLMRouter`, records one row in
`telemetry.db.llm_calls` after the response goes out, and returns the
response shape from `docs/api-contract.md`.

Idempotency: not enforced. LLM calls are typically non-idempotent (output
is non-deterministic across providers and even across calls to the same
model). Revisit in v1.1 if a use case emerges.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, Field

from bridge.auth import AuthContext, require_scope
from bridge.errors import BridgeError
from bridge.providers.llm.base import LLMMessage, LLMRequest
from bridge.providers.llm.router import LLMRouter
from bridge.ratelimit import require_rate
from bridge.telemetry import LLMCallRecord, write_llm_call

logger = logging.getLogger("bridge.llm.route")

router = APIRouter(tags=["llm"])


class _Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMCompleteRequest(BaseModel):
    task_class: Literal["triage", "classify", "reason", "draft", "summarise"]
    messages: list[_Message] = Field(min_length=1)
    provider_hint: Literal["auto", "local", "openrouter"] = "auto"
    model_hint: str | None = None
    max_tokens: int = Field(default=1024, ge=1, le=32_000)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    response_format: Literal["text", "json"] = "text"


class _UsageOut(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


class LLMCompleteResponse(BaseModel):
    provider: str
    model: str
    content: str
    usage: _UsageOut
    latency_ms: int


def _llm_router(request: Request) -> LLMRouter:
    return request.app.state.llm_router  # type: ignore[no-any-return]


@router.post("/v1/llm/complete", response_model=LLMCompleteResponse)
async def llm_complete(
    request: Request,
    body: LLMCompleteRequest,
    background_tasks: BackgroundTasks,
    auth: Annotated[AuthContext, Depends(require_scope("llm:call"))],
    _rate: Annotated[AuthContext, Depends(require_rate("llm:call"))],
) -> LLMCompleteResponse:
    request_id = getattr(request.state, "request_id", "") or ""
    llm_req = LLMRequest(
        task_class=body.task_class,
        provider_hint=body.provider_hint,
        model_hint=body.model_hint,
        messages=[LLMMessage(role=m.role, content=m.content) for m in body.messages],
        max_tokens=body.max_tokens,
        temperature=body.temperature,
        response_format=body.response_format,
    )
    conn = request.app.state.telemetry_conn
    try:
        llm_resp = await _llm_router(request).complete(llm_req)
    except BridgeError as exc:
        # Provider failure: record telemetry inline before re-raising. Starlette
        # does not run BackgroundTasks attached to an exception path, so we
        # write synchronously here. SQLite insert is fast; the response is
        # already destined for an exception handler.
        details: dict[str, Any] = exc.details if isinstance(exc.details, dict) else {}
        timeout = bool(details.get("timeout", False))
        status = "timeout" if timeout else "error"
        latency_ms = int(details.get("latency_ms", 0) or 0)
        model = str(details.get("model") or body.model_hint or "unknown")
        provider = "openrouter" if body.provider_hint != "local" else "local"
        write_llm_call(
            conn,
            LLMCallRecord(
                actor=auth.actor,
                task_class=body.task_class,
                provider=provider,
                model=model,
                prompt_tokens=0,
                completion_tokens=0,
                cost_usd=0.0,
                latency_ms=latency_ms,
                status=status,
                error_code=exc.code,
                request_id=request_id,
            ),
        )
        raise

    background_tasks.add_task(
        write_llm_call,
        conn,
        LLMCallRecord(
            actor=auth.actor,
            task_class=body.task_class,
            provider=llm_resp.provider,
            model=llm_resp.model,
            prompt_tokens=llm_resp.usage.prompt_tokens,
            completion_tokens=llm_resp.usage.completion_tokens,
            cost_usd=llm_resp.usage.cost_usd,
            latency_ms=llm_resp.latency_ms,
            status="success",
            error_code=None,
            request_id=request_id,
        ),
    )

    return LLMCompleteResponse(
        provider=llm_resp.provider,
        model=llm_resp.model,
        content=llm_resp.content,
        usage=_UsageOut(
            prompt_tokens=llm_resp.usage.prompt_tokens,
            completion_tokens=llm_resp.usage.completion_tokens,
            cost_usd=llm_resp.usage.cost_usd,
        ),
        latency_ms=llm_resp.latency_ms,
    )
