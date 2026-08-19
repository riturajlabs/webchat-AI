"""Cross-process shared caching backed by Redis.

Provides a Protocol-based ``CacheStore`` abstraction and a ``RedisCacheStore``
implementation that gracefully degrades when Redis is unavailable — callers see
a cache miss instead of an error, keeping the hot path (RAG generation) flowing.
"""

import json
import logging
from typing import Protocol

from redis.asyncio import Redis

logger = logging.getLogger("webchat_ai")


class CacheStore(Protocol):
    """Namespaced async key-value cache with optional TTL (seconds)."""

    async def get(self, namespace: str, key: str) -> str | None: ...
    async def set(
        self, namespace: str, key: str, value: str, *, ttl: int | None = None
    ) -> None: ...
    async def delete(self, namespace: str, key: str) -> None: ...


class RedisCacheStore:
    """Redis-backed ``CacheStore`` with fail-open semantics.

    Every Redis operation is wrapped in a ``try/except`` — if Redis is
    unreachable the operation is silently skipped (logged at WARNING) and the
    caller receives the "miss" path, so the main request is never blocked.
    """

    def __init__(self, redis: Redis, prefix: str = "rag") -> None:
        self._redis = redis
        self._prefix = prefix

    def _key(self, namespace: str, key: str) -> str:
        return f"{self._prefix}:{namespace}:{key}"

    async def get(self, namespace: str, key: str) -> str | None:
        try:
            value: str | None = await self._redis.get(self._key(namespace, key))
            return value
        except Exception:
            logger.warning("Redis cache GET failed (namespace=%s)", namespace, exc_info=True)
            return None

    async def set(
        self,
        namespace: str,
        key: str,
        value: str,
        *,
        ttl: int | None = None,
    ) -> None:
        try:
            full_key = self._key(namespace, key)
            if ttl is not None and ttl > 0:
                await self._redis.setex(full_key, ttl, value)
            else:
                await self._redis.set(full_key, value)
        except Exception:
            logger.warning("Redis cache SET failed (namespace=%s)", namespace, exc_info=True)

    async def delete(self, namespace: str, key: str) -> None:
        try:
            await self._redis.delete(self._key(namespace, key))
        except Exception:
            logger.warning("Redis cache DEL failed (namespace=%s)", namespace, exc_info=True)


# ---------------------------------------------------------------------------
# Serialization helpers for RAG cache entries
# ---------------------------------------------------------------------------


def dumps(obj: object) -> str:
    """Serialize an object to a JSON string for cache storage."""
    return json.dumps(obj)


def loads(raw: str) -> object:
    """Deserialize a JSON string from cache storage."""
    return json.loads(raw)
