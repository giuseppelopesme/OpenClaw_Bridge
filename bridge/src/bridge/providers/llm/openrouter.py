"""OpenRouter LLM provider — wraps `https://openrouter.ai/api/v1`.

The API key lives in macOS Keychain under service
`com.giuseppelopesme.openclaw.bridge`, account `provider.openrouter`. We
reuse `keychain.set_credential`'s schema dual-purpose: the API key goes in
the `token` field, `scopes` is the empty list, rotation fields are
unused. Documented in `bridge.keychain` so future readers see why a
provider secret shares a store with actor tokens. To install:

    scripts/mint-token.py --actor provider.openrouter --scopes ""
    # or with explicit set_credential:
    python -c 'from bridge import keychain; keychain.set_credential(
        "provider.openrouter", "<key>", [])'

Errors and timeouts surface as `DependencyUnavailable` (502) per the
Session 3 decision. Timeouts set `details.timeout=true`; HTTP error
responses set `details.upstream_status` to the response code.
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
from typing import Any, Final, Literal

import httpx

from bridge import keychain
from bridge.errors import DependencyUnavailable
from bridge.providers.llm.base import LLMRequest, LLMResponse, LLMUsage
from bridge.providers.llm.pricing import compute_cost_usd

logger = logging.getLogger("bridge.llm.openrouter")

OPENROUTER_API_BASE: Final[str] = "https://openrouter.ai/api/v1"
OPENROUTER_KEYCHAIN_ACTOR: Final[str] = "provider.openrouter"

# Default models per task_class. The telemetry plan calls out triage/classify
# as the candidates for a future local model; for now everything goes to
# OpenRouter and we record what each task_class actually costs.
_DEFAULT_MODEL_BY_TASK: Final[dict[str, str]] = {
    "triage": "anthropic/claude-haiku-4.5",
    "classify": "anthropic/claude-haiku-4.5",
    "summarise": "anthropic/claude-sonnet-4.5",
    "draft": "anthropic/claude-sonnet-4.5",
    "reason": "anthropic/claude-sonnet-4.5",
}


def default_model(task_class: str) -> str:
    return _DEFAULT_MODEL_BY_TASK.get(task_class, "anthropic/claude-sonnet-4.5")


class OpenRouterProvider:
    """Single shared `httpx.AsyncClient` per app, lifecycled by `main.create_app`."""

    name: str = "openrouter"

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        api_base: str = OPENROUTER_API_BASE,
        request_timeout_s: float = 30.0,
    ) -> None:
        self._client = client
        self._api_base = api_base.rstrip("/")
        self._timeout_s = request_timeout_s

    @staticmethod
    def api_key_from_keychain() -> str | None:
        cred = keychain.get_credential(OPENROUTER_KEYCHAIN_ACTOR)
        return cred.token if cred is not None else None

    async def complete(self, request: LLMRequest) -> LLMResponse:
        api_key = self.api_key_from_keychain()
        if not api_key:
            raise DependencyUnavailable(
                "OpenRouter API key is not configured.",
                details={"missing": "keychain", "actor": OPENROUTER_KEYCHAIN_ACTOR},
            )

        model = request.model_hint or default_model(request.task_class)
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.response_format == "json":
            body["response_format"] = {"type": "json_object"}

        url = f"{self._api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Optional headers OpenRouter recommends for usage analytics. Cheap and
            # explicit ownership tag — change if the project moves.
            "HTTP-Referer": "https://github.com/giuseppelopesme/OpenClaw_Bridge",
            "X-Title": "OpenClaw Bridge",
        }

        started = time.perf_counter()
        try:
            resp = await self._client.post(
                url,
                json=body,
                headers=headers,
                timeout=self._timeout_s,
            )
        except httpx.TimeoutException as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            raise DependencyUnavailable(
                "OpenRouter request timed out.",
                details={
                    "timeout": True,
                    "upstream_status": None,
                    "latency_ms": latency_ms,
                    "model": model,
                },
            ) from exc
        except httpx.HTTPError as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            raise DependencyUnavailable(
                "OpenRouter HTTP error.",
                details={
                    "timeout": False,
                    "upstream_status": None,
                    "latency_ms": latency_ms,
                    "model": model,
                    "error": str(exc),
                },
            ) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        if resp.status_code >= 400:
            payload: dict[str, Any] = {}
            with contextlib.suppress(ValueError, json.JSONDecodeError):
                payload = resp.json()
            raise DependencyUnavailable(
                f"OpenRouter returned HTTP {resp.status_code}.",
                details={
                    "timeout": False,
                    "upstream_status": resp.status_code,
                    "latency_ms": latency_ms,
                    "model": model,
                    "upstream_error": payload.get("error", {}),
                },
            )

        data = resp.json()
        return _parse_response(data, model_requested=model, latency_ms=latency_ms)

    async def healthcheck(self) -> Literal["ok", "degraded", "down"]:
        api_key = self.api_key_from_keychain()
        # No key? We can still report network reachability but mark degraded
        # since calls won't succeed.
        try:
            resp = await self._client.get(
                f"{self._api_base}/models",
                headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                timeout=2.0,
            )
        except httpx.HTTPError:
            return "down"
        if resp.status_code >= 500:
            return "down"
        if resp.status_code >= 400 or not api_key:
            return "degraded"
        return "ok"


def _parse_response(
    data: dict[str, Any],
    *,
    model_requested: str,
    latency_ms: int,
) -> LLMResponse:
    """Translate OpenRouter's chat/completions JSON into our `LLMResponse`."""
    model = str(data.get("model") or model_requested)
    choices = data.get("choices") or []
    content = ""
    if choices and isinstance(choices, list):
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict):
            raw_content = message.get("content")
            if isinstance(raw_content, str):
                content = raw_content
    usage_raw = data.get("usage") or {}
    prompt_tokens = int(usage_raw.get("prompt_tokens", 0) or 0)
    completion_tokens = int(usage_raw.get("completion_tokens", 0) or 0)
    cost_usd = compute_cost_usd(model, prompt_tokens, completion_tokens)
    extras: dict[str, object] = {}
    finish_reason = (
        choices[0].get("finish_reason") if choices and isinstance(choices[0], dict) else None
    )
    if finish_reason:
        extras["finish_reason"] = finish_reason
    if "id" in data:
        extras["upstream_id"] = data["id"]
    return LLMResponse(
        provider="openrouter",
        model=model,
        content=content,
        usage=LLMUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
        ),
        latency_ms=latency_ms,
        extras=extras,
    )
