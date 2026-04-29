"""Per-(actor, scope) token bucket rate limiter.

Defaults from `docs/api-contract.md`:

| scope               | rate (req/min) | burst |
|---------------------|----------------|-------|
| llm:call            | 60             | 10    |
| imessage:send       | 30             | 5     |
| vault:write         | 120            | 20    |
| (everything else)   | 300            | 50    |

Limits we plumb in this session use the `vault:write` row and the
"everything else" default; the others are reserved for later steps and
declared here so the catalogue is one source.

### Single-process / in-memory

This implementation is in-memory and process-local. That is fine for a single
bridge process running on the Mac Mini. Once Redis lands in step 4, swap the
backing store for an atomic Redis Lua script keyed on `bucket:{actor}:{scope}`.
The `RateLimiter` interface stays the same; only the storage layer changes.

### Exposed as a FastAPI dependency

`require_rate(scope)` returns a dependency function, mirroring `require_scope`.
Apply it to routes alongside `require_scope`. On exhaustion it raises
`RateLimited` with `Retry-After` populated in the error envelope's `details`,
and the dependency also stamps the header on the response via `request.state`
(observed by `RateLimitHeaderMiddleware`).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Annotated

from fastapi import Depends, Request

from bridge.auth import AuthContext, require_auth
from bridge.errors import RateLimited

logger = logging.getLogger("bridge.ratelimit")


@dataclass(frozen=True)
class BucketSpec:
    """Rate (tokens / second) plus burst capacity (max tokens in bucket)."""

    rate_per_second: float
    burst: int

    @classmethod
    def from_per_minute(cls, per_minute: int, burst: int) -> BucketSpec:
        return cls(rate_per_second=per_minute / 60.0, burst=burst)


# Defaults map. A scope absent from this dict falls back to `_DEFAULT_SPEC`.
_SPECS: dict[str, BucketSpec] = {
    "llm:call": BucketSpec.from_per_minute(60, 10),
    "imessage:send": BucketSpec.from_per_minute(30, 5),
    "vault:write": BucketSpec.from_per_minute(120, 20),
}
_DEFAULT_SPEC: BucketSpec = BucketSpec.from_per_minute(300, 50)


def spec_for(scope: str) -> BucketSpec:
    return _SPECS.get(scope, _DEFAULT_SPEC)


class _Bucket:
    """One token bucket. Refills continuously at `spec.rate_per_second`."""

    __slots__ = ("last_refill", "spec", "tokens")

    def __init__(self, spec: BucketSpec) -> None:
        self.spec = spec
        self.tokens: float = float(spec.burst)
        # `None` = first-take initialises last_refill from the supplied `now`.
        # This keeps the bucket clock-domain agnostic (tests pass 0.0; prod
        # passes monotonic).
        self.last_refill: float | None = None

    def take(self, now: float) -> float:
        """Consume one token. Returns 0 on success, else seconds to wait."""
        if self.last_refill is None:
            self.last_refill = now
        elapsed = now - self.last_refill
        if elapsed > 0:
            self.tokens = min(
                float(self.spec.burst),
                self.tokens + elapsed * self.spec.rate_per_second,
            )
            self.last_refill = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return 0.0
        deficit = 1.0 - self.tokens
        if self.spec.rate_per_second <= 0:
            return float("inf")
        return deficit / self.spec.rate_per_second


class RateLimiter:
    """Process-local token-bucket store keyed on `(actor, scope)`.

    Replace the backing store with Redis in step 4; the public surface
    (`check`, `clear`) is the contract.
    """

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._lock = Lock()

    def check(self, actor: str, scope: str, *, now: float | None = None) -> float:
        """Try to consume one token. Returns 0 on success, else retry-after seconds."""
        ts = now if now is not None else time.monotonic()
        key = (actor, scope)
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(spec_for(scope))
                self._buckets[key] = bucket
            return bucket.take(ts)

    def clear(self) -> None:
        with self._lock:
            self._buckets.clear()


def require_rate(scope: str) -> Callable[..., AuthContext]:
    """Dependency: enforce the rate limit for `(auth.actor, scope)`.

    Use alongside `require_scope(scope)`. We re-derive the auth context here so
    routes can list dependencies in any order; both depend on `require_auth`,
    which FastAPI memoises.
    """

    def _check(
        request: Request,
        auth: Annotated[AuthContext, Depends(require_auth)],
    ) -> AuthContext:
        limiter: RateLimiter = request.app.state.rate_limiter
        retry_after = limiter.check(auth.actor, scope)
        if retry_after > 0:
            seconds = max(1, int(retry_after) + (1 if retry_after % 1 else 0))
            logger.info(
                "rate_limited",
                extra={"actor": auth.actor, "scope": scope, "retry_after_s": seconds},
            )
            raise RateLimited(
                f"Rate limit exceeded for scope {scope}.",
                details={"retry_after_s": seconds, "scope": scope},
                headers={"Retry-After": str(seconds)},
            )
        return auth

    return _check
