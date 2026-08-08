"""Sliding-window rate limiter tests (ADR-004)."""

from types import SimpleNamespace

import pytest
from backend.core.config import get_settings
from backend.core.errors import RateLimitExceededError, ServiceUnavailableError
from backend.core.rate_limit import SlidingWindowRateLimiter


class FakeRateLimitStore:
    def __init__(self) -> None:
        self._members: dict[str, dict[str, float]] = {}
        self.fail = False

    async def zadd(self, name: str, mapping: dict[str, float]) -> int:
        if self.fail:
            raise RuntimeError("redis down")
        self._members.setdefault(name, {}).update(mapping)
        return len(mapping)

    async def zremrangebyscore(self, name: str, min: int, max: float) -> int:
        members = self._members.get(name, {})
        stale = [k for k, v in members.items() if v <= max]
        for key in stale:
            del members[key]
        return len(stale)

    async def zcard(self, name: str) -> int:
        return len(self._members.get(name, {}))

    async def expire(self, name: str, time: int) -> bool:
        return True


async def test_limiter_allows_up_to_limit_then_rejects() -> None:
    limiter = SlidingWindowRateLimiter(FakeRateLimitStore(), limit=3, window_seconds=60)
    assert await limiter.consume("k") is True
    assert await limiter.consume("k") is True
    assert await limiter.consume("k") is True
    assert await limiter.consume("k") is False


async def test_limiter_keys_are_isolated() -> None:
    limiter = SlidingWindowRateLimiter(FakeRateLimitStore(), limit=1, window_seconds=60)
    assert await limiter.consume("a") is True
    assert await limiter.consume("b") is True


def _fake_request(path: str) -> SimpleNamespace:
    return SimpleNamespace(
        url=SimpleNamespace(path=path),
        headers={},
        client=SimpleNamespace(host="127.0.0.1"),
    )


async def test_dependency_rejects_over_limit(monkeypatch) -> None:
    import backend.api.deps as deps

    get_settings.cache_clear()
    store = FakeRateLimitStore()
    monkeypatch.setattr(deps, "get_redis", lambda: store)
    request = _fake_request("/api/auth/login")
    for _ in range(deps.login_limiter.limit):
        await deps.login_limiter(request)
    with pytest.raises(RateLimitExceededError):
        await deps.login_limiter(request)
    get_settings.cache_clear()


async def test_dependency_fails_closed_when_store_unavailable(monkeypatch) -> None:
    import backend.api.deps as deps

    get_settings.cache_clear()
    store = FakeRateLimitStore()
    store.fail = True
    monkeypatch.setattr(deps, "get_redis", lambda: store)
    with pytest.raises(ServiceUnavailableError):
        await deps.login_limiter(_fake_request("/api/auth/login"))
    get_settings.cache_clear()
