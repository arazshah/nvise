from __future__ import annotations

import logging
import time

import redis
from django.conf import settings

logger = logging.getLogger(__name__)


def allow_fixed_window(*, namespace: str, key: str, limit: int, window_seconds: int = 60) -> bool:
    if limit <= 0:
        return True
    bucket = int(time.time() // window_seconds)
    redis_key = f"nvise:ratelimit:{namespace}:{key}:{bucket}"
    try:
        client = redis.Redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        pipe = client.pipeline(transaction=True)
        pipe.incr(redis_key)
        pipe.expire(redis_key, window_seconds + 5)
        count, _ = pipe.execute()
        return int(count) <= limit
    except Exception:
        logger.exception("rate_limit_backend_unavailable", extra={"event": "rate_limit.backend_unavailable"})
        return True
