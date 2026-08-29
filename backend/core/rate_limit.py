"""Redis sliding-window rate limiting.

The limiter depends only on a minimal async command interface (`RateLimitStore`),
so it can be unit-tested with an in-memory fake and wired to `redis.asyncio` in
production.  When the store supports ``eval_sliding_window`` (the Redis adapter
does), the entire prune → check → add → expire sequence executes as a single
atomic Lua script, eliminating the race window that existed in the four-command
fallback path.  See docs/07-Architecture-Decisions.md ADR-004 (abuse protection).
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

    async def eval_sliding_window(  # noqa: ANN401 – protocol method
        self, key: str, window_start_ms: float, now_ms: float, limit: int, window_seconds: int
    ) -> bool: ...


class SlidingWindowRateLimiter:
    """Sliding-window limiter: at most `limit` events per `window_seconds`.

    Each call adds a unique member scored by wall-clock milliseconds; members
    older than the window are pruned before counting.

    When the backing store exposes ``eval_sliding_window`` (the Redis adapter
    does), the four logical steps execute as one atomic Lua script -- no race
    window, no orphaned members on rejection.  Stores that lack the method
    (the in-memory ``FakeRateLimitStore`` used by tests) fall back to the
    four-command sequential path with the orphan bug fixed (count is checked
    *before* adding).
    """

    def __init__(self, store: RateLimitStore, *, limit: int, window_seconds: int) -> None:
        self._store = store
        self.limit = limit
        self.window_seconds = window_seconds
        self._atomic_ok: bool | None = None  # None = untested, True/False = cached

    async def consume(self, key: str) -> bool:
        """Record one event for `key` and return True if still within the limit."""
        now_ms = time.time() * 1000
        window_start_ms = now_ms - self.window_seconds * 1000

        # Fast path: atomic Lua script (production Redis adapter).
        # _atomic_ok is None on first call; subsequent calls skip the probe.
        if self._atomic_ok is not False and hasattr(self._store, "eval_sliding_window"):
            try:
                result = await self._store.eval_sliding_window(
                    key, window_start_ms, now_ms, self.limit, self.window_seconds
                )
                self._atomic_ok = True
                return result
            except (AttributeError, TypeError):
                # Store has the method but the underlying client does not
                # support register_script (e.g. FakeRateLimitStore in tests).
                self._atomic_ok = False

        # Fallback: sequential commands (in-memory FakeRateLimitStore in tests).
        # Check count *before* adding so rejected requests never pollute the
        # ZSET with orphaned members.
        await self._store.zremrangebyscore(key, 0, window_start_ms)
        count = await self._store.zcard(key)
        if count >= self.limit:
            return False
        member = f"{now_ms}-{uuid.uuid4()}"
        await self._store.zadd(key, {member: now_ms})
        await self._store.expire(key, self.window_seconds)
        return True
