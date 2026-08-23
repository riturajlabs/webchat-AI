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
        method="POST",
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


async def test_widget_ip_limiter_budgets_per_ip_per_endpoint(monkeypatch) -> None:
    """Production hardening: the per-IP widget budget backs up the entity-keyed
    limits, which a hostile client can rotate via `visitor_id` / widget_id."""
    import backend.api.deps as deps

    get_settings.cache_clear()
    monkeypatch.setenv("WIDGET_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("WIDGET_IP_LIMIT", "3")
    store = FakeRateLimitStore()
    monkeypatch.setattr(deps, "get_redis", lambda: store)

    config_req = _fake_request("/api/widget/v1/config/widget-1")
    for _ in range(3):
        await deps.widget_ip_limiter(config_req)
    with pytest.raises(RateLimitExceededError):
        await deps.widget_ip_limiter(config_req)

    # The budget is keyed per method + path + IP: a different endpoint (or
    # caller) on the same IP has its own window.
    sessions_req = _fake_request("/api/widget/v1/sessions")
    await deps.widget_ip_limiter(sessions_req)

    # `widget_ip_limiter` on the same endpoint from a different IP is a fresh
    # budget too (the key includes `client_ip`).
    other_ip = _fake_request("/api/widget/v1/config/widget-1")
    other_ip.client.host = "203.0.113.7"
    await deps.widget_ip_limiter(other_ip)
    get_settings.cache_clear()


async def test_widget_ip_limiter_disabled_by_switch(monkeypatch) -> None:
    """The per-IP limiter honors the master widget rate-limit switch."""
    import backend.api.deps as deps

    get_settings.cache_clear()
    monkeypatch.setenv("WIDGET_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("WIDGET_IP_LIMIT", "1")
    store = FakeRateLimitStore()
    monkeypatch.setattr(deps, "get_redis", lambda: store)
    request = _fake_request("/api/widget/v1/config/widget-1")
    for _ in range(3):
        await deps.widget_ip_limiter(request)  # never raises
    get_settings.cache_clear()


# -----------------------------------------------------------------------
# P0-4: dedicated per-IP burst budgets on /sessions and /chat
# -----------------------------------------------------------------------


async def test_widget_session_ip_limiter_bounds_minting(monkeypatch) -> None:
    """Anonymous token minting gets its own tight IP budget (P0-4): rotating
    the body `widget_id` (which resets the entity key) cannot escape it."""
    import backend.api.deps as deps

    get_settings.cache_clear()
    monkeypatch.setenv("WIDGET_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("WIDGET_SESSION_ISSUE_IP_LIMIT", "3")
    store = FakeRateLimitStore()
    monkeypatch.setattr(deps, "get_redis", lambda: store)

    for _ in range(3):
        await deps.widget_session_ip_limiter(_fake_request("/api/widget/v1/sessions"))
    with pytest.raises(RateLimitExceededError):
        await deps.widget_session_ip_limiter(_fake_request("/api/widget/v1/sessions"))

    # A different IP has a fresh budget.
    other = _fake_request("/api/widget/v1/sessions")
    other.client.host = "203.0.113.9"
    await deps.widget_session_ip_limiter(other)
    get_settings.cache_clear()


async def test_widget_chat_ip_limiter_is_independent_of_sessions(monkeypatch) -> None:
    """The chat burst budget is a separate window: exhausting session minting
    does not consume the chat budget on the same IP."""
    import backend.api.deps as deps

    get_settings.cache_clear()
    monkeypatch.setenv("WIDGET_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("WIDGET_SESSION_ISSUE_IP_LIMIT", "1")
    monkeypatch.setenv("WIDGET_CHAT_IP_LIMIT", "2")
    store = FakeRateLimitStore()
    monkeypatch.setattr(deps, "get_redis", lambda: store)

    sessions_req = _fake_request("/api/widget/v1/sessions")
    await deps.widget_session_ip_limiter(sessions_req)
    with pytest.raises(RateLimitExceededError):
        await deps.widget_session_ip_limiter(sessions_req)

    chat_req = _fake_request("/api/widget/v1/chat")
    await deps.widget_chat_ip_limiter(chat_req)
    await deps.widget_chat_ip_limiter(chat_req)
    with pytest.raises(RateLimitExceededError):
        await deps.widget_chat_ip_limiter(chat_req)
    get_settings.cache_clear()


async def test_widget_burst_limiters_disabled_by_switch(monkeypatch) -> None:
    """Both dedicated budgets honor WIDGET_RATE_LIMIT_ENABLED (localhost dev)."""
    import backend.api.deps as deps

    get_settings.cache_clear()
    monkeypatch.setenv("WIDGET_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("WIDGET_SESSION_ISSUE_IP_LIMIT", "1")
    monkeypatch.setenv("WIDGET_CHAT_IP_LIMIT", "1")
    store = FakeRateLimitStore()
    monkeypatch.setattr(deps, "get_redis", lambda: store)
    for _ in range(5):
        await deps.widget_session_ip_limiter(_fake_request("/api/widget/v1/sessions"))
        await deps.widget_chat_ip_limiter(_fake_request("/api/widget/v1/chat"))
    get_settings.cache_clear()


# -----------------------------------------------------------------------
# SEC-7: refresh_limiter (per-session-token sliding window)
# -----------------------------------------------------------------------


def _fake_refresh_request(token: str = "test-token") -> SimpleNamespace:
    """Build a minimal request-like object with a refresh_token cookie."""
    return SimpleNamespace(
        method="POST",
        url=SimpleNamespace(path="/api/auth/refresh"),
        headers={},
        client=SimpleNamespace(host="127.0.0.1"),
        cookies={"refresh_token": token},
    )


async def test_refresh_limiter_allows_normal_use(monkeypatch) -> None:
    """A handful of refresh calls with a valid token succeed."""
    import backend.api.deps as deps

    get_settings.cache_clear()
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("REFRESH_RATE_LIMIT_PER_MINUTE", "5")
    store = FakeRateLimitStore()
    monkeypatch.setattr(deps, "get_redis", lambda: store)
    req = _fake_refresh_request("my-session-token")
    for _ in range(5):
        await deps.refresh_limiter(req)
    get_settings.cache_clear()


async def test_refresh_limiter_rejects_over_limit(monkeypatch) -> None:
    """Exceeding the per-token refresh budget raises RateLimitExceededError."""
    import backend.api.deps as deps

    get_settings.cache_clear()
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("REFRESH_RATE_LIMIT_PER_MINUTE", "3")
    store = FakeRateLimitStore()
    monkeypatch.setattr(deps, "get_redis", lambda: store)
    req = _fake_refresh_request("stolen-token")
    for _ in range(3):
        await deps.refresh_limiter(req)
    with pytest.raises(RateLimitExceededError):
        await deps.refresh_limiter(req)
    get_settings.cache_clear()


async def test_refresh_limiter_different_tokens_are_isolated(monkeypatch) -> None:
    """Two different refresh tokens have independent budgets."""
    import backend.api.deps as deps

    get_settings.cache_clear()
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("REFRESH_RATE_LIMIT_PER_MINUTE", "2")
    store = FakeRateLimitStore()
    monkeypatch.setattr(deps, "get_redis", lambda: store)

    req_a = _fake_refresh_request("token-for-user-a")
    req_b = _fake_refresh_request("token-for-user-b")

    # Exhaust token A's budget.
    await deps.refresh_limiter(req_a)
    await deps.refresh_limiter(req_a)
    with pytest.raises(RateLimitExceededError):
        await deps.refresh_limiter(req_a)

    # Token B still has its own budget.
    await deps.refresh_limiter(req_b)
    await deps.refresh_limiter(req_b)
    with pytest.raises(RateLimitExceededError):
        await deps.refresh_limiter(req_b)
    get_settings.cache_clear()


async def test_refresh_limiter_noop_when_token_cookie_missing(monkeypatch) -> None:
    """If no refresh_token cookie is set, the limiter is a no-op (endpoint
    rejects with 401 anyway)."""
    import backend.api.deps as deps

    get_settings.cache_clear()
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("REFRESH_RATE_LIMIT_PER_MINUTE", "1")
    store = FakeRateLimitStore()
    monkeypatch.setattr(deps, "get_redis", lambda: store)
    req = _fake_refresh_request("")
    req.cookies = {}  # no cookie at all
    for _ in range(10):
        await deps.refresh_limiter(req)  # never raises
    get_settings.cache_clear()


async def test_refresh_limiter_fails_closed_on_store_error(monkeypatch) -> None:
    """Redis outage raises ServiceUnavailableError (fail closed)."""
    import backend.api.deps as deps

    get_settings.cache_clear()
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    store = FakeRateLimitStore()
    store.fail = True
    monkeypatch.setattr(deps, "get_redis", lambda: store)
    with pytest.raises(ServiceUnavailableError):
        await deps.refresh_limiter(_fake_refresh_request("any-token"))
    get_settings.cache_clear()


async def test_refresh_limiter_disabled_by_switch(monkeypatch) -> None:
    """When rate_limit_enabled=false, the limiter is a no-op."""
    import backend.api.deps as deps

    get_settings.cache_clear()
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    store = FakeRateLimitStore()
    monkeypatch.setattr(deps, "get_redis", lambda: store)
    req = _fake_refresh_request("any-token")
    for _ in range(100):
        await deps.refresh_limiter(req)  # never raises
    get_settings.cache_clear()
