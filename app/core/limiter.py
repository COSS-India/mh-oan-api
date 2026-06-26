"""
Shared rate limiter instance for the application.

Patched for clusters where Redis requires AUTH (REDIS_PASSWORD env).
"""
import os

from slowapi import Limiter
from app.auth.rate_limit import get_rate_limit_key
from app.config import settings

_redis_password = os.getenv("REDIS_PASSWORD")
if _redis_password:
    _storage_uri = (
        f"redis://:{_redis_password}@{settings.redis_host}:"
        f"{settings.redis_port}/{settings.redis_db}"
    )
else:
    _storage_uri = (
        f"redis://{settings.redis_host}:{settings.redis_port}/{settings.redis_db}"
    )

limiter = Limiter(
    key_func=get_rate_limit_key,
    storage_uri=_storage_uri,
    default_limits=[],
)
