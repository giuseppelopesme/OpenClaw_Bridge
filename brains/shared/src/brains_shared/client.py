"""Public client surface for brains.

This module re-exports the generated `AuthenticatedClient` from
`brains_shared._generated.client`, but constructs it with a custom
httpx transport that:

1. Auto-stamps `Idempotency-Key` on POST requests if the caller did not.
2. Retries `429 Too Many Requests` responses, honouring the
   `Retry-After` header, with bounded exponential backoff.
3. Re-uses the same Idempotency-Key across retries (so the bridge sees
   the second attempt as a replay, not a fresh write).

Brains import `BridgeClient`, never the generated client directly. The
generated module lives behind an underscore prefix to flag "auto-managed
— don't hand-edit". Re-generate with `tools/regen-sdk.sh`.

### Usage

    async with BridgeClient(base_url="http://127.0.0.1:8788", token="…") as client:
        from brains_shared._generated.api.health import health_v1_health_get
        resp = await health_v1_health_get.asyncio_detailed(client=client)

The `BridgeClient` class is a thin facade — `client._inner` is the real
`AuthenticatedClient` the generated API functions accept. We expose
`get_inner()` for that pattern; the helpers in `obsidian.py` and
`llm.py` use it internally.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextvars import ContextVar
from types import TracebackType
from typing import Final

import httpx

from brains_shared._generated.client import AuthenticatedClient

logger = logging.getLogger("brains_shared.client")

# Maximum 429 retries per call. Lower than the relay's 3 because LLM
# rate limits in particular use much longer Retry-After windows.
_MAX_429_RETRIES: Final[int] = 3
# Cap on Retry-After honouring; if the bridge says "wait longer than
# this", we raise instead of sleeping. Keeps a misbehaving server from
# stalling the brain indefinitely.
_RETRY_AFTER_CAP_S: Final[float] = 30.0
# Default request timeout (seconds). LLM endpoints can run long; brains
# can override per-call via `httpx_args`.
_DEFAULT_TIMEOUT_S: Final[float] = 30.0

_IDEMPOTENCY_HEADER: Final[str] = "Idempotency-Key"

# Per-call override seam used by helpers that want to pin a specific
# Idempotency-Key on a single POST without threading it through every
# helper signature. Helpers `set` it inside an `async with
# idempotency_key("...")` block; the transport reads it.
_idempotency_override: ContextVar[str | None] = ContextVar(
    "_brains_shared_idempotency_override",
    default=None,
)


class BridgeClientError(RuntimeError):
    """Raised when the bridge returns a 429 after all retries are spent."""

    def __init__(self, *, status: int, message: str, retry_after: float | None) -> None:
        super().__init__(f"bridge call failed: {status} {message}")
        self.status = status
        self.message = message
        self.retry_after = retry_after


class _RetryAndIdempotencyTransport(httpx.AsyncBaseTransport):
    """httpx transport wrapper that handles Idempotency-Key + 429 retry.

    Wrapping a transport (rather than overriding `httpx.AsyncClient.send`)
    keeps the generated client unmodified: the transport is invisible to
    callers and survives the generated client's `evolve()` clones.
    """

    def __init__(
        self,
        wrapped: httpx.AsyncBaseTransport,
        *,
        max_retries: int = _MAX_429_RETRIES,
        retry_after_cap_s: float = _RETRY_AFTER_CAP_S,
    ) -> None:
        self._wrapped = wrapped
        self._max_retries = max_retries
        self._cap = retry_after_cap_s

    async def handle_async_request(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        self._stamp_idempotency_key(request)

        for attempt in range(self._max_retries + 1):
            response = await self._wrapped.handle_async_request(request)
            if response.status_code != 429:
                return response

            retry_after = self._read_retry_after(response)
            if attempt == self._max_retries:
                # Out of attempts. Drain so httpx doesn't complain about
                # an unread response when the caller later tries to read
                # it; we'll wrap into BridgeClientError below.
                await response.aread()
                raise BridgeClientError(
                    status=429,
                    message="Rate limited; out of retries.",
                    retry_after=retry_after,
                )

            sleep_for = self._sleep_for(attempt, retry_after)
            if sleep_for > self._cap:
                await response.aread()
                raise BridgeClientError(
                    status=429,
                    message=(
                        f"Rate limited; Retry-After {sleep_for:.1f}s exceeds cap {self._cap:.1f}s."
                    ),
                    retry_after=sleep_for,
                )
            await response.aread()
            await response.aclose()
            logger.info(
                "bridge_client_429_retry",
                extra={
                    "attempt": attempt + 1,
                    "sleep_s": sleep_for,
                    "url": str(request.url),
                },
            )
            await asyncio.sleep(sleep_for)
        # Unreachable — the loop returns or raises in every branch.
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _stamp_idempotency_key(request: httpx.Request) -> None:
        if request.method != "POST":
            return
        # Caller-supplied via context-var wins over the generated header
        # (which the SDK never sets), and both win over auto-stamping.
        override = _idempotency_override.get()
        if override is not None:
            request.headers[_IDEMPOTENCY_HEADER] = override
            return
        if _IDEMPOTENCY_HEADER in request.headers:
            return
        request.headers[_IDEMPOTENCY_HEADER] = str(uuid.uuid4())

    @staticmethod
    def _read_retry_after(response: httpx.Response) -> float | None:
        raw = response.headers.get("Retry-After")
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    @staticmethod
    def _sleep_for(attempt: int, retry_after: float | None) -> float:
        # Honour Retry-After if the server gave one; otherwise fall back
        # to exponential. Floor of 0.1s to avoid a busy loop on a
        # misconfigured server returning Retry-After: 0.
        if retry_after is not None and retry_after > 0:
            return max(float(retry_after), 0.1)
        # 0.5, 1.0, 2.0, 4.0 …
        return max(0.5 * (2.0**attempt), 0.1)

    async def aclose(self) -> None:
        await self._wrapped.aclose()


class BridgeClient:
    """Public bridge client. Brains hold one of these per process."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        max_429_retries: int = _MAX_429_RETRIES,
    ) -> None:
        # Build our own httpx.AsyncClient so we can plug in the retry
        # transport. The generated client picks this up via
        # `set_async_httpx_client`.
        wrapped_transport = httpx.AsyncHTTPTransport()
        self._transport = _RetryAndIdempotencyTransport(
            wrapped_transport,
            max_retries=max_429_retries,
        )
        self._httpx = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_s,
            transport=self._transport,
            headers={"Authorization": f"Bearer {token}"},
        )
        self._inner: AuthenticatedClient = AuthenticatedClient(
            base_url=base_url,
            token=token,
        ).set_async_httpx_client(self._httpx)

    @property
    def base_url(self) -> str:
        return str(self._httpx.base_url)

    def get_inner(self) -> AuthenticatedClient:
        """Return the generated `AuthenticatedClient` for use with the
        generated per-endpoint API functions."""
        return self._inner

    async def __aenter__(self) -> BridgeClient:
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._httpx.aclose()


def idempotency_key(value: str) -> _IdempotencyOverride:
    """Pin a specific Idempotency-Key for any POSTs made inside the
    `async with` block. Useful when a caller wants explicit replay
    semantics (e.g. retries across process restarts)."""
    return _IdempotencyOverride(value)


class _IdempotencyOverride:
    def __init__(self, value: str) -> None:
        self._value = value
        self._token: object | None = None

    def __enter__(self) -> _IdempotencyOverride:
        self._token = _idempotency_override.set(self._value)
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        if self._token is not None:
            _idempotency_override.reset(self._token)  # type: ignore[arg-type]
            self._token = None

    # Allow `async with idempotency_key("…")` for symmetry, even though
    # the override is purely a sync ContextVar.
    async def __aenter__(self) -> _IdempotencyOverride:
        return self.__enter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.__exit__(exc_type, exc, tb)


__all__ = [
    "BridgeClient",
    "BridgeClientError",
    "idempotency_key",
]
