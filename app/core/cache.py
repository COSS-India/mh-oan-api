"""
Core cache instance configuration using Redis and aiocache.

Patched for clusters where Redis requires AUTH (REDIS_PASSWORD env).
Upstream mh-oan-api omits password in aiocache config.
"""
import os

from aiocache import Cache
from aiocache.serializers import JsonSerializer
from app.config import settings
from helpers.utils import get_logger

logger = get_logger(__name__)

_cache_kwargs = {
    "endpoint": settings.redis_host,
    "port": settings.redis_port,
    "db": settings.redis_db,
    "serializer": JsonSerializer(),
    "ttl": settings.default_cache_ttl,
    "timeout": settings.redis_socket_timeout,
    "pool_max_size": settings.redis_max_connections,
    "create_connection_timeout": settings.redis_socket_connect_timeout,
    "connection_pool_kwargs": {
        "socket_keepalive": True,
        "retry_on_timeout": settings.redis_retry_on_timeout,
        "health_check_interval": 30,
    },
    "key_builder": lambda key, namespace: (
        f"{settings.redis_key_prefix}{namespace}:{key}"
        if namespace
        else f"{settings.redis_key_prefix}{key}"
    ),
}

_redis_password = os.getenv("REDIS_PASSWORD")
if _redis_password:
    _cache_kwargs["password"] = _redis_password

cache = Cache(Cache.REDIS, **_cache_kwargs)

logger.info(
    f"Cache configured with Redis at {settings.redis_host}:{settings.redis_port} "
    f"(DB: {settings.redis_db}, Prefix: {settings.redis_key_prefix}, "
    f"Max Connections: {settings.redis_max_connections}, "
    f"Auth: {'yes' if _redis_password else 'no'}, Auto-cleanup: Enabled)"
)
