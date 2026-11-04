"""Fixed-window rate limiting backed by Redis."""
from __future__ import annotations

import time
from typing import Any


class RateLimiter:
    def __init__(self, redis_client: Any) -> None:
        self._r = redis_client

    def hit(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        """Register one hit for `key`. Returns (allowed, remaining)."""
        bucket = int(time.time() // window_seconds)
        rkey = f"rl:{key}:{bucket}"
        count = self._r.incr(rkey)
        if count == 1:
            self._r.expire(rkey, window_seconds)
        allowed = count <= limit
        remaining = max(0, limit - count)
        return allowed, remaining
