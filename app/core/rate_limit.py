"""Simple in-memory rate limiter for login attempts."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import threading
import time


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after: int = 0
    remaining: int = 0


class SlidingWindowRateLimiter:
    """Fixed-capacity sliding window limiter keyed by arbitrary strings (e.g. IP)."""

    def __init__(self, *, max_attempts: int = 5, window_seconds: int = 60) -> None:
        self.max_attempts = max(1, max_attempts)
        self.window_seconds = max(1, window_seconds)
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> RateLimitResult:
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            self._prune(bucket, now)
            if len(bucket) >= self.max_attempts:
                retry_after = max(1, int(self.window_seconds - (now - bucket[0])) + 1)
                return RateLimitResult(allowed=False, retry_after=retry_after, remaining=0)
            return RateLimitResult(
                allowed=True,
                remaining=self.max_attempts - len(bucket),
            )

    def hit(self, key: str) -> RateLimitResult:
        """Record an attempt and return whether it was within the limit."""

        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            self._prune(bucket, now)
            if len(bucket) >= self.max_attempts:
                retry_after = max(1, int(self.window_seconds - (now - bucket[0])) + 1)
                return RateLimitResult(allowed=False, retry_after=retry_after, remaining=0)
            bucket.append(now)
            return RateLimitResult(
                allowed=True,
                remaining=self.max_attempts - len(bucket),
            )

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def _prune(self, bucket: deque[float], now: float) -> None:
        cutoff = now - self.window_seconds
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
