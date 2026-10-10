import asyncio
import os
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from starlette.requests import Request

from app import rate_limit
from app.limiter import RateLimiter, build_key
from app.policies import RateLimitPolicy, resolve_policy
from app.redis_store import RedisRateLimiter


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/15")


def test_policies_are_selected_by_route_and_server_owned_tier() -> None:
    basic = resolve_policy("/v1/fixed", "basic")
    premium = resolve_policy("/v1/fixed", "premium")

    assert basic is not None and basic.limit == 5
    assert premium is not None and premium.limit == 10
    assert resolve_policy("/v1/fixed", "unknown") is None
    assert resolve_policy("/v1/unknown", "basic") is None


def test_authorization_fails_closed_when_redis_is_unavailable(monkeypatch) -> None:
    class UnavailableLimiter:
        async def check(self, user_id, path, policy):
            raise RedisConnectionError("Redis is unavailable")

    async def receive():
        return {
            "type": "http.request",
            "body": b'{}',
            "more_body": False,
        }

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/authorize",
            "headers": [
                (b"x-forwarded-uri", b"/v1/fixed"),
                (b"x-auth-subject", b"verified-user"),
                (b"x-auth-tier", b"basic"),
            ],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("test", 12345),
            "scheme": "http",
            "http_version": "1.1",
        },
        receive,
    )
    monkeypatch.setattr(rate_limit, "rate_limiter", UnavailableLimiter())

    response = asyncio.run(rate_limit.authorize(request))

    assert response.status_code == 503


def test_authorization_uses_verified_identity_not_request_body(monkeypatch) -> None:
    class RecordingLimiter:
        subject = None

        async def check(self, subject, path, policy):
            self.subject = subject
            from app.redis_store import RateLimitDecision

            return RateLimitDecision(allowed=True, remaining=4, retry_after_ms=0)

    async def receive():
        return {
            "type": "http.request",
            "body": b'{"user_id":"forged-user"}',
            "more_body": False,
        }

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/authorize",
            "headers": [
                (b"x-forwarded-uri", b"/v1/fixed"),
                (b"x-auth-subject", b"verified-user"),
                (b"x-auth-tier", b"basic"),
            ],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("test", 12345),
            "scheme": "http",
            "http_version": "1.1",
        },
        receive,
    )
    limiter = RecordingLimiter()
    monkeypatch.setattr(rate_limit, "rate_limiter", limiter)

    response = asyncio.run(rate_limit.authorize(request))

    assert response.status_code == 200
    assert limiter.subject == "verified-user"


def test_authorization_rejects_missing_verified_identity() -> None:
    async def receive():
        return {"type": "http.request", "body": b"{}", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/authorize",
            "headers": [(b"x-forwarded-uri", b"/v1/fixed")],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("test", 12345),
            "scheme": "http",
            "http_version": "1.1",
        },
        receive,
    )

    response = asyncio.run(rate_limit.authorize(request))

    assert response.status_code == 401


def test_rate_limit_keys_isolate_users_and_routes() -> None:
    policy = RateLimitPolicy("fixed_window", limit=2, window_seconds=60)

    assert build_key("user-a", "/v1/fixed", policy) != build_key(
        "user-b", "/v1/fixed", policy
    )
    assert build_key("user-a", "/v1/fixed", policy) != build_key(
        "user-a", "/v1/sliding", policy
    )
    assert "user-a" not in build_key("user-a", "/v1/fixed", policy)


def test_user_limits_are_independent() -> None:
    async def scenario() -> None:
        redis = Redis.from_url(REDIS_URL, decode_responses=True)
        limiter = RateLimiter(RedisRateLimiter(redis))
        policy = RateLimitPolicy("fixed_window", limit=1, window_seconds=60)
        user_a = f"isolated-a-{uuid4()}"
        user_b = f"isolated-b-{uuid4()}"
        try:
            assert (await limiter.check(user_a, "/v1/fixed", policy)).allowed
            assert not (await limiter.check(user_a, "/v1/fixed", policy)).allowed
            assert (await limiter.check(user_b, "/v1/fixed", policy)).allowed
        finally:
            await redis.delete(
                build_key(user_a, "/v1/fixed", policy),
                build_key(user_b, "/v1/fixed", policy),
            )
            await redis.aclose()

    asyncio.run(scenario())


def test_fixed_window_enforces_limit() -> None:
    async def scenario() -> None:
        redis = Redis.from_url(REDIS_URL, decode_responses=True)
        limiter = RateLimiter(RedisRateLimiter(redis))
        user_id = f"fixed-{uuid4()}"
        policy = RateLimitPolicy("fixed_window", limit=2, window_seconds=60)
        try:
            first = await limiter.check(user_id, "/v1/fixed", policy)
            second = await limiter.check(user_id, "/v1/fixed", policy)
            third = await limiter.check(user_id, "/v1/fixed", policy)
            assert first.allowed and first.remaining == 1
            assert second.allowed and second.remaining == 0
            assert not third.allowed and third.retry_after_ms > 0
        finally:
            await redis.delete(build_key(user_id, "/v1/fixed", policy))
            await redis.aclose()

    asyncio.run(scenario())


def test_sliding_window_log_enforces_limit() -> None:
    async def scenario() -> None:
        redis = Redis.from_url(REDIS_URL, decode_responses=True)
        limiter = RateLimiter(RedisRateLimiter(redis))
        user_id = f"sliding-{uuid4()}"
        policy = RateLimitPolicy("sliding_window", limit=1, window_seconds=60)
        try:
            assert (await limiter.check(user_id, "/v1/sliding", policy)).allowed
            denied = await limiter.check(user_id, "/v1/sliding", policy)
            assert not denied.allowed and denied.retry_after_ms > 0
        finally:
            await redis.delete(build_key(user_id, "/v1/sliding", policy))
            await redis.aclose()

    asyncio.run(scenario())


def test_token_bucket_denies_until_tokens_refill() -> None:
    async def scenario() -> None:
        redis = Redis.from_url(REDIS_URL, decode_responses=True)
        limiter = RateLimiter(RedisRateLimiter(redis))
        user_id = f"token-{uuid4()}"
        policy = RateLimitPolicy(
            "token_bucket", limit=1, window_seconds=60, refill_rate_per_second=100
        )
        try:
            assert (await limiter.check(user_id, "/v1/token", policy)).allowed
            denied = await limiter.check(user_id, "/v1/token", policy)
            assert not denied.allowed and denied.retry_after_ms > 0
            await asyncio.sleep(0.02)
            assert (await limiter.check(user_id, "/v1/token", policy)).allowed
        finally:
            await redis.delete(build_key(user_id, "/v1/token", policy))
            await redis.aclose()

    asyncio.run(scenario())


def test_concurrent_requests_share_atomic_limit() -> None:
    async def scenario() -> None:
        redis = Redis.from_url(REDIS_URL, decode_responses=True)
        limiter = RateLimiter(RedisRateLimiter(redis))
        user_id = f"concurrent-{uuid4()}"
        policy = RateLimitPolicy("fixed_window", limit=7, window_seconds=60)
        try:
            decisions = await asyncio.gather(
                *(limiter.check(user_id, "/v1/fixed", policy) for _ in range(25))
            )
            assert sum(decision.allowed for decision in decisions) == 7
        finally:
            await redis.delete(build_key(user_id, "/v1/fixed", policy))
            await redis.aclose()

    asyncio.run(scenario())