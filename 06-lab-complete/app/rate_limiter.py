"""
Rate limiting (tiêu chí 7) — Sliding window 60s lưu trong Redis.
"""
import secrets
import time

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    """Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request / 60 giây."""
    now = time.time()
    window_start = now - WINDOW_SECONDS
    redis_key = f"ratelimit:{key}"

    pipe = r.pipeline()
    pipe.zremrangebyscore(redis_key, 0, window_start)
    pipe.zcard(redis_key)
    _, count = pipe.execute()

    if count >= settings.rate_limit_per_minute:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(WINDOW_SECONDS)},
        )

    member = f"{now}:{secrets.token_hex(4)}"
    pipe = r.pipeline()
    pipe.zadd(redis_key, {member: now})
    pipe.expire(redis_key, WINDOW_SECONDS + 5)
    pipe.execute()
