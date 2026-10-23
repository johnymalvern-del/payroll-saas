"""Factory for the rate limiter."""
from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.core.rate_limiter.base import RateLimiter
from app.core.rate_limiter.in_memory import InMemoryRateLimiter
from app.core.rate_limiter.redis_impl import RedisRateLimiter


def _build(settings: Settings) -> RateLimiter:
    if settings.environment in ("development", "test"):
        return InMemoryRateLimiter()

    if settings.workers_count > 1 and not settings.redis_url:
        raise RuntimeError(
            "Production with workers_count > 1 requires REDIS_URL "
            "(in-memory rate limiter cannot be shared across workers)"
        )
    if not settings.redis_url:
        raise RuntimeError(
            f"RateLimiter requires REDIS_URL when ENVIRONMENT={settings.environment}"
        )
    return RedisRateLimiter(redis_url=settings.redis_url)


@lru_cache(maxsize=1)
def get_rate_limiter() -> RateLimiter:
    return _build(get_settings())