import json
import math
import os
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.limiter import RateLimiter
from app.policies import resolve_policy
from app.redis_store import RedisRateLimiter


redis_client = Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    decode_responses=True,
    socket_connect_timeout=0.5,
    socket_timeout=0.5,
)
rate_limiter = RateLimiter(RedisRateLimiter(redis_client))
app = FastAPI(title="Rate Limit Service")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> JSONResponse:
    try:
        await redis_client.ping()
    except RedisError:
        return JSONResponse(status_code=503, content={"status": "redis-unavailable"})
    return JSONResponse(content={"status": "ready"})


@app.api_route(
    "/authorize", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
)
async def authorize(request: Request) -> Response:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse(status_code=400, content={"detail": "Expected a JSON body"})

    user_id = payload.get("user_id") if isinstance(payload, dict) else None
    if not isinstance(user_id, str) or not user_id.strip() or len(user_id) > 128:
        return JSONResponse(
            status_code=400,
            content={"detail": "user_id must be a non-empty string of at most 128 characters"},
        )

    forwarded_uri = request.headers.get("x-forwarded-uri", "")
    path = urlsplit(forwarded_uri).path
    policy = resolve_policy(path, user_id)
    if policy is None:
        return JSONResponse(status_code=404, content={"detail": "No rate-limit policy for route"})

    try:
        decision = await rate_limiter.check(user_id.strip(), path, policy)
    except RedisError:
        return JSONResponse(
            status_code=503,
            content={"detail": "Rate-limit backend unavailable"},
        )

    headers = {
        "X-RateLimit-Limit": str(policy.limit),
        "X-RateLimit-Remaining": str(decision.remaining),
    }
    if not decision.allowed:
        headers["Retry-After"] = str(max(1, math.ceil(decision.retry_after_ms / 1000)))
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
            headers=headers,
        )
    return Response(status_code=200, headers=headers)