"""LocalRateLimiter — OSS default: in-process sliding-window rate limiting.

Protects the LLM budget. Enterprise swaps in a distributed limiter (Redis).
"""
import time
from collections import deque


class LocalRateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str, limit: int, window_s: float = 60.0) -> bool:
        now = time.monotonic()
        bucket = self._hits.setdefault(key, deque())
        while bucket and now - bucket[0] > window_s:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)
