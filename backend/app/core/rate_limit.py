"""Fixed-window rate limiter.

In-memory by default (single-process dev/test). Swapping in Redis later only
requires reimplementing `_Store`.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict

from ..config import settings
from .errors import RateLimitError


class _Store:
    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def hit(self, bucket: str, limit: int, window: int = 60) -> bool:
        now = time.time()
        with self._lock:
            stamps = [t for t in self._hits[bucket] if now - t < window]
            if len(stamps) >= limit:
                self._hits[bucket] = stamps
                return False
            stamps.append(now)
            self._hits[bucket] = stamps
            return True

    def reset(self, bucket: str | None = None) -> None:
        with self._lock:
            if bucket is None:
                self._hits.clear()
            else:
                self._hits.pop(bucket, None)


store = _Store()


def enforce(bucket: str, *, limit: int | None = None, window: int = 60) -> None:
    """Raise `RateLimitError` once `bucket` exceeds its allowance."""
    allowed = limit if limit is not None else settings.rate_limit_per_minute
    if not store.hit(bucket, allowed, window):
        raise RateLimitError()


def enforce_ai(bucket: str) -> None:
    enforce(f"ai:{bucket}", limit=settings.ai_rate_limit_per_minute)


__all__ = ["enforce", "enforce_ai", "store"]
