"""Redis sliding-window rate limiting.

The limiter depends only on a minimal async command interface (`RateLimitStore`),
so it can be unit-tested with an in-memory fake and wired to `redis.asyncio` in
production. See docs/07-Architecture-Decisions.md ADR-004 (abuse protection).
"""

import time
import uuid
from collections.abc import Mapping
from typing import Protocol


class RateLimitStore(Protocol):
    """Minimal ZSET command surface used by the sliding-window limiter."""

    async def zadd(self, name: str, mapping: Mapping[str, float]) -> int: ...

    async def zremrangebyscore(self, name: str, min: int, max: float) -> int: ...

    async def zcard(self, name: str) -> int: ...

    async def expire(self, name: str, time: int) -> bool: ...


class SlidingWindowRateLimiter:
    """Sliding-window limiter: at most `limit` events per `window_seconds`.

    Each call adds a unique member scored by wall-clock milliseconds; members
    older than the window are pruned before counting.
    """

    def __init__(self, store: RateLimitStore, *, limit: int, window_seconds: int) -> None:
        self._store = store
        self.limit = limit
        self.window_seconds = window_seconds

    async def consume(self, key: str) -> bool:
        """Record one event for `key` and return True if still within the limit."""
        now_ms = time.time() * 1000
        window_start_ms = now_ms - self.window_seconds * 1000

        await self._store.zremrangebyscore(key, 0, window_start_ms)
        member = f"{now_ms}-{uuid.uuid4()}"
        await self._store.zadd(key, {member: now_ms})
        count = await self._store.zcard(key)
        await self._store.expire(key, self.window_seconds)
        return count <= self.limit
