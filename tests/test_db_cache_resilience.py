"""Database & cache production resilience tests (Phase 14.8.3).

Covers:
  * MongoDB / Redis connection-pool reuse (no per-request clients),
  * graceful reconnect after a connection is closed,
  * Redis unavailable -> cache degrades to a miss (fail-open),
  * MongoDB unavailable -> ping() reports down, never raises,
  * the shared Redis client is a process-wide singleton.
"""

from __future__ import annotations

from typing import Any

import pytest
from backend.core import redis as redis_module
from backend.core.cache import RedisCacheStore
from backend.core.database import MongoDB

# Capture the genuine classmethod at import time, before the autouse conftest
# fixture stubs `MongoDB.client` with a NoopClient for hermetic tests.
_REAL_MONGO_CLIENT = MongoDB.__dict__["client"]


class _FailingRedis:
    """Every operation raises: simulates a dead Redis without touching sockets."""

    async def get(self, *_: Any, **__: Any) -> None:  # noqa: ANN401
        raise ConnectionError("redis down")

    async def setex(self, *_: Any, **__: Any) -> None:  # noqa: ANN401
        raise ConnectionError("redis down")

    async def set(self, *_: Any, **__: Any) -> None:  # noqa: ANN401
        raise ConnectionError("redis down")

    async def delete(self, *_: Any, **__: Any) -> None:  # noqa: ANN401
        raise ConnectionError("redis down")

    async def scan(self, *_: Any, **__: Any) -> tuple[int, list[str]]:  # noqa: ANN401
        raise ConnectionError("redis down")


def test_get_redis_returns_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """The shared client is created once and reused (pool reuse, not per-request)."""
    monkeypatch.setattr(redis_module, "_redis", None)
    first = redis_module.get_redis()
    second = redis_module.get_redis()
    assert first is second


async def test_close_redis_allows_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    """After close, the next get_redis() builds a fresh client (reconnect)."""
    monkeypatch.setattr(redis_module, "_redis", None)
    before = redis_module.get_redis()
    await redis_module.close_redis()
    after = redis_module.get_redis()
    assert before is not after


async def test_cache_get_degrades_to_miss_when_redis_down() -> None:
    store = RedisCacheStore(_FailingRedis(), prefix="webchat_ai")
    assert await store.get("rag", "missing") is None


async def test_cache_set_never_raises_when_redis_down() -> None:
    store = RedisCacheStore(_FailingRedis(), prefix="webchat_ai")
    # Must not raise even though the underlying Redis is dead.
    await store.set("rag", "k", "v", ttl=60)
    await store.delete("rag", "k")
    assert await store.delete_by_prefix("rag", "k") == 0


def test_mongodb_client_is_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """MongoDB.client() memoizes the Motor client (connection-pool reuse).

    The real classmethod is restored (conftest stubs it with a NoopClient) so
    the genuine memoization branch is exercised.
    """
    monkeypatch.setattr(MongoDB, "client", _REAL_MONGO_CLIENT)
    sentinel = object()
    monkeypatch.setattr(MongoDB, "_client", sentinel)
    assert MongoDB.client() is sentinel
    assert MongoDB.client() is sentinel


async def test_mongodb_ping_reports_down_without_raising() -> None:
    """When Mongo is unreachable, ping() returns False rather than raising."""
    assert await MongoDB.ping() is False


async def test_mongodb_close_resets_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """close() clears the cached client so a reconnect rebuilds it."""

    class _FakeClient:
        closed = False

        def close(self) -> None:
            self.closed = True

    fake = _FakeClient()
    monkeypatch.setattr(MongoDB, "_client", fake)
    await MongoDB.close()
    assert fake.closed is True
    assert MongoDB._client is None  # noqa: SLF001
