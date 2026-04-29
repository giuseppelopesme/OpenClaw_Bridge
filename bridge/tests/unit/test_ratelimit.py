"""Token bucket: in-memory allow/deny/refill + Redis Lua atomicity."""

from __future__ import annotations

import asyncio

import fakeredis.aioredis
from bridge.ratelimit import BucketSpec, RateLimiter, _Bucket, spec_for


def test_default_specs_match_api_contract() -> None:
    assert spec_for("vault:write").burst == 20
    assert abs(spec_for("vault:write").rate_per_second - (120 / 60.0)) < 1e-9
    assert spec_for("llm:call").burst == 10
    assert spec_for("imessage:send").burst == 5
    # Catch-all
    everything_else = spec_for("apple:calendar:read")
    assert everything_else.burst == 50
    assert abs(everything_else.rate_per_second - (300 / 60.0)) < 1e-9


def test_bucket_allows_burst_then_denies() -> None:
    spec = BucketSpec(rate_per_second=1.0, burst=3)
    b = _Bucket(spec)
    now = 0.0
    assert b.take(now) == 0.0
    assert b.take(now) == 0.0
    assert b.take(now) == 0.0
    # Fourth attempt at the same instant: bucket empty.
    retry = b.take(now)
    assert retry > 0.0


def test_bucket_refills_continuously() -> None:
    spec = BucketSpec(rate_per_second=2.0, burst=2)
    b = _Bucket(spec)
    assert b.take(0.0) == 0.0
    assert b.take(0.0) == 0.0
    # Out of tokens.
    assert b.take(0.0) > 0.0
    # 0.5s later, 1 token has refilled.
    assert b.take(0.5) == 0.0
    assert b.take(0.5) > 0.0


def test_rate_limiter_isolated_per_actor_scope() -> None:
    rl = RateLimiter()
    # Drain actor=A, scope=vault:write — burst is 20.
    for _ in range(20):
        assert rl.check("A", "vault:write", now=0.0) == 0.0
    assert rl.check("A", "vault:write", now=0.0) > 0.0
    # Different actor: fresh bucket.
    assert rl.check("B", "vault:write", now=0.0) == 0.0
    # Different scope: fresh bucket.
    assert rl.check("A", "llm:call", now=0.0) == 0.0


def test_rate_limited_endpoint_returns_429_with_retry_after(client) -> None:  # type: ignore[no-untyped-def]
    """Hammering /v1/vault/write past the burst yields 429 with Retry-After.

    The default test fixture wires the limiter against fakeredis, so this
    exercises the Redis-backed path end-to-end (Lua script + key expiry).
    """
    headers = {"Authorization": "Bearer dev-token-clu"}
    spec = spec_for("vault:write")
    # Fire burst+1 unique paths to defeat any conflict on the same name.
    for i in range(spec.burst):
        resp = client.post(
            "/v1/vault/write",
            json={"path": f"Inbox/burst-{i}.md", "mode": "create", "content": f"#{i}"},
            headers=headers,
        )
        assert resp.status_code == 201

    final = client.post(
        "/v1/vault/write",
        json={"path": "Inbox/burst-final.md", "mode": "create", "content": "x"},
        headers=headers,
    )
    assert final.status_code == 429
    assert final.json()["error"]["code"] == "rate_limited"
    assert int(final.headers["Retry-After"]) >= 1


# --- Redis-backed limiter (atomic Lua) -----------------------------------


def test_redis_limiter_allows_within_burst_then_denies() -> None:
    """Redis Lua bucket: first `burst` calls allowed; next denied."""

    async def run() -> None:
        client = fakeredis.aioredis.FakeRedis(decode_responses=False)
        try:
            rl = RateLimiter(client)
            spec = spec_for("vault:write")
            for _ in range(spec.burst):
                assert await rl.check_async("actor.A", "vault:write") == 0.0
            retry = await rl.check_async("actor.A", "vault:write")
            assert retry > 0.0
        finally:
            await client.aclose()

    asyncio.run(run())


def test_redis_limiter_isolates_actors() -> None:
    """`bucket:{actor}:{scope}` keying — exhausting A leaves B fresh."""

    async def run() -> None:
        client = fakeredis.aioredis.FakeRedis(decode_responses=False)
        try:
            rl = RateLimiter(client)
            spec = spec_for("vault:write")
            for _ in range(spec.burst):
                assert await rl.check_async("actor.A", "vault:write") == 0.0
            assert await rl.check_async("actor.A", "vault:write") > 0.0
            # B has its own bucket.
            assert await rl.check_async("actor.B", "vault:write") == 0.0
            # Different scope is also isolated.
            assert await rl.check_async("actor.A", "llm:call") == 0.0
        finally:
            await client.aclose()

    asyncio.run(run())


def test_redis_limiter_writes_expected_keys() -> None:
    """Confirm the bucket lives at `bucket:{actor}:{scope}` with TTL set."""

    async def run() -> None:
        client = fakeredis.aioredis.FakeRedis(decode_responses=False)
        try:
            rl = RateLimiter(client)
            await rl.check_async("brain.clu", "vault:write")
            assert await client.exists(b"bucket:brain.clu:vault:write") == 1
            ttl = await client.ttl(b"bucket:brain.clu:vault:write")
            assert ttl > 0  # EXPIRE was set
            fields = await client.hkeys(b"bucket:brain.clu:vault:write")
            field_set = {f.decode() if isinstance(f, bytes) else f for f in fields}
            assert "tokens" in field_set
            assert "last_refill_ms" in field_set
        finally:
            await client.aclose()

    asyncio.run(run())


def test_redis_limiter_falls_back_to_memory_on_error() -> None:
    """A Redis error during check should fall back to in-memory for the call.

    We force an error by passing a closed client.
    """

    async def run() -> None:
        client = fakeredis.aioredis.FakeRedis(decode_responses=False)
        await client.aclose()

        from redis.exceptions import ConnectionError as RedisConnError

        async def boom(*_args: object, **_kwargs: object) -> bytes:
            raise RedisConnError("simulated")

        client.eval = boom  # type: ignore[assignment]

        rl = RateLimiter(client)
        # In-memory fallback should still allow the first call.
        assert await rl.check_async("actor.A", "vault:write") == 0.0

    asyncio.run(run())
