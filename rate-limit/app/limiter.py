from hashlib import sha256

from app.policies import RateLimitPolicy
from app.redis_store import RateLimitDecision, RedisRateLimiter


def build_key(subject: str, path: str, policy: RateLimitPolicy) -> str:
    subject_digest = sha256(subject.encode("utf-8")).hexdigest()
    return f"rate-limit:v1:{policy.algorithm}:{path}:{subject_digest}"


class RateLimiter:
    def __init__(self, store: RedisRateLimiter) -> None:
        self._store = store

    async def check(
        self, subject: str, path: str, policy: RateLimitPolicy
    ) -> RateLimitDecision:
        return await self._store.check(build_key(subject, path, policy), policy)