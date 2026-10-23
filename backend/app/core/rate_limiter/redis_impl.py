"""RedisRateLimiter - production.

Fixed-window counter in Redis: INCR + EXPIRE.
"""
from __future__ import annotations

import time

from redis import Redis

from app.core.rate_limiter.base import RateLimiter


class RedisRateLimiter(RateLimiter):
    def __init__(self, redis_url: str) -> None:
        self._redis = Redis.from_url(redis_url)

    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        bucket = int(time.time() // window_seconds)
        redis_key = f"rl:{key}:{bucket}"
        pipe = self._redis.pipeline()
        pipe.incr(redis_key)
        pipe.expire(redis_key, window_seconds + 1)
        results = pipe.execute()
        count = int(results[0])
        return count <= limit