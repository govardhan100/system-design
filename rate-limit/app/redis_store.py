from dataclasses import dataclass
from secrets import token_hex

from redis.asyncio import Redis

from app.policies import RateLimitPolicy


FIXED_WINDOW_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('PEXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('PTTL', KEYS[1])
local limit = tonumber(ARGV[2])
if count <= limit then
    return {1, limit - count, ttl}
end
return {0, 0, ttl}
"""

SLIDING_WINDOW_SCRIPT = """
local time = redis.call('TIME')
local now = tonumber(time[1]) * 1000 + math.floor(tonumber(time[2]) / 1000)
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
local count = redis.call('ZCARD', KEYS[1])
if count >= limit then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    local retry = math.max(1, window - (now - tonumber(oldest[2])))
    return {0, 0, retry}
end
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('PEXPIRE', KEYS[1], window)
return {1, limit - count - 1, 0}
"""

TOKEN_BUCKET_SCRIPT = """
local time = redis.call('TIME')
local now = tonumber(time[1]) * 1000 + math.floor(tonumber(time[2]) / 1000)
local capacity = tonumber(ARGV[1])
local refill_per_ms = tonumber(ARGV[2]) / 1000
local state = redis.call('HMGET', KEYS[1], 'tokens', 'updated_at')
local tokens = tonumber(state[1]) or capacity
local updated_at = tonumber(state[2]) or now
local elapsed = math.max(0, now - updated_at)
tokens = math.min(capacity, tokens + elapsed * refill_per_ms)
local allowed = 0
local retry = 0
if tokens >= 1 then
    tokens = tokens - 1
    allowed = 1
else
    retry = math.ceil((1 - tokens) / refill_per_ms)
end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'updated_at', now)
redis.call('PEXPIRE', KEYS[1], math.max(1000, math.ceil(capacity / refill_per_ms * 2)))
return {allowed, math.floor(tokens), retry}
"""


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_ms: int


class RedisRateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def check(
        self, key: str, policy: RateLimitPolicy
    ) -> RateLimitDecision:
        window_ms = policy.window_seconds * 1000
        if policy.algorithm == "fixed_window":
            result = await self._redis.eval(
                FIXED_WINDOW_SCRIPT, 1, key, window_ms, policy.limit
            )
        elif policy.algorithm == "sliding_window":
            result = await self._redis.eval(
                SLIDING_WINDOW_SCRIPT,
                1,
                key,
                window_ms,
                policy.limit,
                token_hex(16),
            )
        else:
            if not policy.refill_rate_per_second or policy.refill_rate_per_second <= 0:
                raise ValueError("token bucket requires a positive refill rate")
            result = await self._redis.eval(
                TOKEN_BUCKET_SCRIPT,
                1,
                key,
                policy.limit,
                policy.refill_rate_per_second,
            )
        return RateLimitDecision(
            allowed=bool(int(result[0])),
            remaining=int(result[1]),
            retry_after_ms=int(result[2]),
        )