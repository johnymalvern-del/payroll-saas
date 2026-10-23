"""Rate-limiter abstraction.

Two implementations:

  * InMemoryRateLimiter - development and test default.
  * RedisRateLimiter    - production, shared across workers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class RateLimiter(ABC):
    @abstractmethod
    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        """Record a hit for `key`. Return True if allowed, False if exceeded."""