"""Redis connection management (async client).

Used for caching, rate limiting, and the ARQ task queue broker.
"""

from redis.asyncio import Redis

from backend.core.config import get_settings

_redis: Redis | None = None


def get_redis() -> Redis:
    """Return the shared async Redis client, creating it lazily."""
    global _redis
    if _redis is None:
        settings = get_settings()
        _redis = Redis.from_url(settings.redis_url, decode_responses=True)
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
        await _redis.aclose()
        _redis = None
