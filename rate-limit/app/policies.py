from dataclasses import dataclass
from typing import Literal


Algorithm = Literal["fixed_window", "sliding_window", "token_bucket"]


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    algorithm: Algorithm
    limit: int
    window_seconds: int
    refill_rate_per_second: float | None = None


_ROUTE_POLICIES: dict[str, dict[str, RateLimitPolicy]] = {
    "/v1/fixed": {
        "basic": RateLimitPolicy("fixed_window", limit=5, window_seconds=60),
        "premium": RateLimitPolicy("fixed_window", limit=10, window_seconds=60),
    },
    "/v1/sliding": {
        "basic": RateLimitPolicy("sliding_window", limit=5, window_seconds=60),
        "premium": RateLimitPolicy("sliding_window", limit=10, window_seconds=60),
    },
    "/v1/token": {
        "basic": RateLimitPolicy(
            "token_bucket", limit=5, window_seconds=60, refill_rate_per_second=5 / 60
        ),
        "premium": RateLimitPolicy(
            "token_bucket", limit=10, window_seconds=60, refill_rate_per_second=10 / 60
        ),
    },
}

def resolve_policy(path: str, tier: str) -> RateLimitPolicy | None:
    route_policies = _ROUTE_POLICIES.get(path)
    if route_policies is None:
        return None
    return route_policies.get(tier)