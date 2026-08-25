"""Regression tests for retrieval-cache invalidation prefix parity (R-01).

The crawl worker must invalidate exactly the namespace the API writes:
``{redis_prefix}:rag:retrieval:{website_id}:{query}``. A prefix mismatch made
invalidation a silent NO-OP, so stale answers survived the full 900 s TTL
after every re-crawl.
"""

from __future__ import annotations

import fnmatch
from typing import Any

import pytest
from backend.core.cache import RedisCacheStore
from backend.core.config import get_settings
from backend.workers.jobs.crawl import _build_cache


class _FakeRedis:
    """Minimal in-memory stand-in for ``redis.asyncio.Redis`` (full-key store)."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str) -> None:
        self.data[key] = value

    async def setex(self, key: str, _ttl: int, value: str) -> None:
        self.data[key] = value

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self.data:
                del self.data[key]
                deleted += 1
        return deleted

    async def scan(
        self, cursor: int = 0, match: str = "", count: int = 100
    ) -> tuple[int, list[str]]:
        keys = [key for key in self.data if fnmatch.fnmatchcase(key, match)]
        return 0, keys


async def test_worker_invalidation_deletes_api_prefixed_entries(monkeypatch) -> None:
    """Keys written under the API-side prefix are deleted by the worker store."""
    fake_redis = _FakeRedis()

    def fake_from_url(*_args: Any, **_kwargs: Any) -> _FakeRedis:
        return fake_redis

    monkeypatch.setattr("redis.asyncio.Redis.from_url", staticmethod(fake_from_url))

    api_style_prefix = f"{get_settings().redis_prefix}:rag"
    # The API side (deps.get_rag_service) writes entries through this shape.
    api_store = RedisCacheStore(fake_redis, prefix=api_style_prefix)
    await api_store.set("retrieval", "site-a:what is acme", '["old"]', ttl=900)
    await api_store.set("retrieval", "site-b:pricing", '["keep"]')

    # The worker builds its invalidation store via the production factory.
    worker_store = _build_cache()
    assert worker_store is not None

    deleted = await worker_store.delete_by_prefix("retrieval", "site-a:")

    assert deleted == 1
    assert await api_store.get("retrieval", "site-a:what is acme") is None
    # Entries for other websites are untouched.
    assert await api_store.get("retrieval", "site-b:pricing") == '["keep"]'


def test_worker_cache_uses_api_rag_prefix(monkeypatch) -> None:
    """The worker's cache store prefix equals the API-side `{prefix}:rag`."""
    captured: dict[str, str] = {}

    class _CapturingStore(RedisCacheStore):
        def __init__(self, redis: Any, *, prefix: str) -> None:
            captured["prefix"] = prefix

    monkeypatch.setattr("backend.workers.jobs.crawl.RedisCacheStore", _CapturingStore)

    def fake_from_url(*_args: Any, **_kwargs: Any) -> object:
        return object()

    monkeypatch.setattr("redis.asyncio.Redis.from_url", staticmethod(fake_from_url))

    assert isinstance(_build_cache(), _CapturingStore)
    assert captured["prefix"] == f"{get_settings().redis_prefix}:rag"


def test_redis_cache_store_has_no_default_prefix() -> None:
    """Omitting the prefix must be a constructor error (no silent default)."""
    with pytest.raises(TypeError):
        RedisCacheStore(redis=_FakeRedis())  # type: ignore[call-arg]
