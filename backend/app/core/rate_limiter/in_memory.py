"""InMemoryRateLimiter - development and test default.

Thread-safe sliding window using a deque of timestamps per key.
Suitable only for a single-process API.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.core.rate_limiter.base import RateLimiter


class InMemoryRateLimiter(RateLimiter):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] < cutoff:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            return True