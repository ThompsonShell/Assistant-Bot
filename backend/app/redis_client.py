"""Redis client factory (connection is lazy — created on first command)."""
from __future__ import annotations

import redis


def get_redis(url: str) -> redis.Redis:
    return redis.from_url(url, decode_responses=False)
