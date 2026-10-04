from hashlib import sha256

from app.policies import RateLimitPolicy
from app.redis_store import RateLimitDecision, RedisRateLimiter


def build_key(user_id: str, path: str, policy: RateLimitPolicy) -> str:
    user_digest = sha256(user_id.encode("utf-8")).hexdigest()
    return f"rate-limit:v1:{policy.algorithm}:{path}:{user_digest}"


class RateLimiter:
    def __init__(self, store: RedisRateLimiter) -> None:
        self._store = store

    async def check(
        self, user_id: str, path: str, policy: RateLimitPolicy
    ) -> RateLimitDecision:
        return await self._store.check(build_key(user_id, path, policy), policy)