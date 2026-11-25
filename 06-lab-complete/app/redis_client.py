"""
Kết nối Redis dùng chung cho rate limiter và cost guard.
App vẫn khởi động được khi Redis chưa sẵn sàng (không ping lúc import).
"""
import redis

from app.config import settings

r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)


def redis_healthy() -> bool:
    """Ping Redis cho GET /ready; lỗi kết nối -> False."""
    try:
        return bool(r.ping())
    except Exception:
        return False
