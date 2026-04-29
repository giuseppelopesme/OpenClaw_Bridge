"""Per-(actor, scope) token bucket rate limiter.

Defaults from `docs/api-contract.md`:

| scope               | rate (req/min) | burst |
|---------------------|----------------|-------|
| llm:call            | 60             | 10    |
| imessage:send       | 30             | 5     |
| vault:write         | 120            | 20    |
| (everything else)   | 300            | 50    |

### Backing store

Session 4 swaps the in-memory store for a Redis Lua script keyed on
`bucket:{actor}:{scope}`. The script is a single atomic EVAL so two
bridge processes (a future scenario) cannot race the same bucket.

When Redis is unavailable at startup (Keychain `provider.redis` not
seeded, daemon down, etc.), `RateLimiter` falls back to the Session 2
in-process bucket map — degraded but functional. The route surface is
unchanged in either case.

### Exposed as a FastAPI dependency

`require_rate(scope)` returns a dependency function, mirroring
`require_scope`. Apply it to routes alongside `require_scope`. On
exhaustion it raises `RateLimited` with `Retry-After` populated in the
error envelope's `details`, and the `BridgeError.headers` field stamps
the response header.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from threading import Lock
from typing import Annotated, Any, Final

from fastapi import Depends, Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

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


_SPECS: dict[str, BucketSpec] = {
    "llm:call": BucketSpec.from_per_minute(60, 10),
    "imessage:send": BucketSpec.from_per_minute(30, 5),
    "vault:write": BucketSpec.from_per_minute(120, 20),
}
_DEFAULT_SPEC: BucketSpec = BucketSpec.from_per_minute(300, 50)


def spec_for(scope: str) -> BucketSpec:
    return _SPECS.get(scope, _DEFAULT_SPEC)


# --- in-memory implementation (fallback when Redis isn't configured) -----


class _Bucket:
    """One in-memory token bucket. Refills continuously at `spec.rate_per_second`."""

    __slots__ = ("last_refill", "spec", "tokens")

    def __init__(self, spec: BucketSpec) -> None:
        self.spec = spec
        self.tokens: float = float(spec.burst)
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


# --- Redis Lua script ----------------------------------------------------

# Single-shot atomic check. KEYS[1] is the bucket hash key. ARGV[1..2] are
# burst (int) and rate (tokens/sec, float). The script reads server time
# via `redis.call('TIME')` so all bridge processes agree on `now` without
# coordinating clocks.
#
# Returns retry_ms as a string:
#   "0"  → allowed; one token consumed
#   ">0" → denied; integer milliseconds to wait
#
# Hash fields:
#   tokens          — current count (float, persisted as string)
#   last_refill_ms  — server time of last refill, ms epoch
#
# Idle buckets expire after burst/rate seconds + 60s slack, keeping
# Redis tidy without affecting hot keys.
_LUA_TAKE: Final[str] = """
local key = KEYS[1]
local burst = tonumber(ARGV[1])
local rate  = tonumber(ARGV[2])

local t = redis.call('TIME')
local now_ms = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)

local data = redis.call('HMGET', key, 'tokens', 'last_refill_ms')
local tokens = tonumber(data[1])
local last_refill_ms = tonumber(data[2])

if tokens == nil then
  tokens = burst
end
if last_refill_ms == nil then
  last_refill_ms = now_ms
end

local elapsed_s = (now_ms - last_refill_ms) / 1000.0
if elapsed_s > 0 then
  tokens = math.min(burst, tokens + elapsed_s * rate)
end

local retry_ms = 0
if tokens >= 1.0 then
  tokens = tokens - 1.0
else
  local deficit = 1.0 - tokens
  if rate <= 0 then
    retry_ms = -1
  else
    retry_ms = math.ceil(deficit / rate * 1000)
  end
end

redis.call('HSET', key, 'tokens', tostring(tokens), 'last_refill_ms', tostring(now_ms))
local ttl = math.ceil(burst / rate) + 60
if ttl < 1 then ttl = 1 end
redis.call('EXPIRE', key, ttl)

return tostring(retry_ms)
"""


# --- the limiter ---------------------------------------------------------


class RateLimiter:
    """Token-bucket store keyed on `(actor, scope)`.

    Backing store is Redis when `redis_client` is provided, otherwise an
    in-process dict. Either way, `check_async()` returns retry-after seconds
    (0 = allowed). The public surface does not change between modes.
    """

    def __init__(self, redis_client: Redis | None = None) -> None:
        self._client = redis_client
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._lock = Lock()

    @staticmethod
    def _key(actor: str, scope: str) -> str:
        return f"bucket:{actor}:{scope}"

    async def check_async(
        self,
        actor: str,
        scope: str,
        *,
        now: float | None = None,
    ) -> float:
        """Async check. Uses Redis if configured; falls back to in-memory.

        `now` is honoured only on the in-memory path (Redis uses server
        TIME). If Redis returns an error, fall back to in-memory for this
        single check; the next call will retry Redis.
        """
        if self._client is not None:
            try:
                return await self._check_redis(actor, scope)
            except RedisError as exc:
                logger.warning(
                    "rate_limiter_redis_failed",
                    extra={"actor": actor, "scope": scope, "error": str(exc)},
                )
                # Fall through to in-memory for this call.
        return self._check_memory(actor, scope, now=now)

    def check(self, actor: str, scope: str, *, now: float | None = None) -> float:
        """Sync wrapper for tests of the in-memory path. Bypasses Redis."""
        return self._check_memory(actor, scope, now=now)

    async def _check_redis(self, actor: str, scope: str) -> float:
        assert self._client is not None
        spec = spec_for(scope)
        # redis-py's stubs type eval() as `Awaitable[Any] | Any`. The async
        # client always returns an awaitable; the union covers the sync
        # sibling. We assert the awaitable shape to satisfy mypy.
        eval_call = self._client.eval(
            _LUA_TAKE,
            1,
            self._key(actor, scope),
            str(spec.burst),
            f"{spec.rate_per_second}",
        )
        result = await eval_call  # type: ignore[misc]
        retry_ms = int(result.decode("utf-8") if isinstance(result, bytes) else result)
        if retry_ms < 0:
            return float("inf")
        return retry_ms / 1000.0

    def _check_memory(
        self,
        actor: str,
        scope: str,
        *,
        now: float | None,
    ) -> float:
        ts = now if now is not None else time.monotonic()
        key = (actor, scope)
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(spec_for(scope))
                self._buckets[key] = bucket
            return bucket.take(ts)

    async def clear(self) -> None:
        """Wipe all buckets — tests and admin-reset use only."""
        with self._lock:
            self._buckets.clear()
        if self._client is not None:
            try:
                # Iterate keys via SCAN to avoid blocking on large sets.
                async for k in self._client.scan_iter(match="bucket:*"):
                    await self._client.delete(k)
            except RedisError:
                logger.warning("rate_limiter_redis_clear_failed", exc_info=True)


def require_rate(
    scope: str,
) -> Callable[..., Coroutine[Any, Any, AuthContext]]:
    """Dependency: enforce the rate limit for `(auth.actor, scope)`."""

    async def _check(
        request: Request,
        auth: Annotated[AuthContext, Depends(require_auth)],
    ) -> AuthContext:
        limiter: RateLimiter = request.app.state.rate_limiter
        retry_after = await limiter.check_async(auth.actor, scope)
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
