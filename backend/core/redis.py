"""Redis connection management (async client).

Used for caching, rate limiting, and the ARQ task queue broker.
"""

from redis.asyncio import Redis

from backend.core.config import get_settings

# Phase 7 (DB-04): cap the shared client pool so a connection thundering herd
# cannot exhaust the Redis server. 50 is generous for the API + worker + ARQ
# queue workloads of a single deployment while still bounding resource use.
# Worker jobs build their own ARQ pool from the same bound (workers/redis.py).
REDIS_MAX_CONNECTIONS = 50

_redis: Redis | None = None


def get_redis() -> Redis:
    """Return the shared async Redis client, creating it lazily."""
    global _redis
    if _redis is None:
        settings = get_settings()
        _redis = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=REDIS_MAX_CONNECTIONS,
        )
    return _redis


async def ping_redis() -> bool:
    """Return True if Redis is reachable, False otherwise."""
    try:
        return bool(await get_redis().ping())
    except Exception:
        return False


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        try:
            await _redis.aclose()
        except Exception:
            pass
        _redis = None
