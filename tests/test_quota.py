"""Regression tests for the LLM quota limiter.

Covers two production-hardening fixes:
  * monthly token counter uses a 35-day TTL (previously 2 days => budget
    reset mid-month, i.e. a limit bypass);
  * the per-minute request counter is INCR-then-check (previously GET-then-
    INCR, a TOCTOU race that let concurrent requests all pass).
"""

import pytest
from backend.core.errors import AIQuotaExceededError
from backend.core.quota import (
    _DAILY_TOKEN_TTL_SECONDS,
    _MONTHLY_TOKEN_TTL_SECONDS,
    LLMQuotaService,
)


class _FakeRedis:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.store: dict[str, str] = {}
        self.expirations: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def mget(self, *keys: str) -> list[str | None]:
        return [self.store.get(k) for k in keys]

    def pipeline(self, transaction: bool = False) -> "_FakePipeline":
        return _FakePipeline(self, transaction=transaction)

    async def incr(self, key: str) -> int:
        self.store[key] = str(int(self.store.get(key, 0)) + 1)
        return int(self.store[key])

    async def incrby(self, key: str, amount: int) -> int:
        self.store[key] = str(int(self.store.get(key, 0)) + amount)
        return int(self.store[key])

    async def expire(self, key: str, seconds: int) -> None:
        self.expirations[key] = seconds

    async def delete(self, *keys: str) -> int:
        deleted = sum(1 for k in keys if k in self.store)
        for k in keys:
            self.store.pop(k, None)
        return deleted


class _FakePipeline:
    """Mirrors redis.asyncio.Pipeline: queues ops, executes them as one batch."""

    def __init__(self, redis: _FakeRedis, transaction: bool = False) -> None:
        self._redis = redis
        self._ops: list[tuple] = []

    def incr(self, key: str) -> "_FakePipeline":
        self._ops.append(("incr", key))
        return self

    def expire(self, key: str, seconds: int) -> "_FakePipeline":
        self._ops.append(("expire", key, seconds))
        return self

    async def __aenter__(self) -> "_FakePipeline":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def execute(self) -> list:
        results = []
        for op in self._ops:
            if op[0] == "incr":
                results.append(await self._redis.incr(op[1]))
            elif op[0] == "expire":
                await self._redis.expire(op[1], op[2])
                results.append(True)
        return results


async def _run_check(quota, tenant_id: str, req_limit: int):
    quota._settings.llm_request_limit_per_minute = req_limit
    return await quota.check(tenant_id)


async def test_monthly_counter_uses_35_day_ttl() -> None:
    """Regression: monthly token key must outlive the calendar month."""
    settings = _make_settings()
    settings.llm_daily_token_limit = 0
    settings.llm_monthly_token_limit = 1000
    fake = _FakeRedis(settings)
    quota = LLMQuotaService(redis=fake, settings=settings)

    await quota.record("tenant-a", input_tokens=100, output_tokens=50)

    monthly_key = next(k for k in fake.store if "monthly" in k)
    assert fake.expirations[monthly_key] == _MONTHLY_TOKEN_TTL_SECONDS
    assert _MONTHLY_TOKEN_TTL_SECONDS > 31 * 24 * 60 * 60
    assert _MONTHLY_TOKEN_TTL_SECONDS > _DAILY_TOKEN_TTL_SECONDS


async def test_per_minute_requests_use_atomic_incr_then_check() -> None:
    """Regression: the counter must INCR-then-check to close the TOCTOU race."""
    settings = _make_settings()
    settings.llm_daily_token_limit = 0
    settings.llm_monthly_token_limit = 0
    fake = _FakeRedis(settings)
    quota = LLMQuotaService(redis=fake, settings=settings)

    # First request passes (count = 1 <= limit 2); third is rejected (count 3).
    await _run_check(quota, "tenant-a", req_limit=2)
    await _run_check(quota, "tenant-a", req_limit=2)
    with pytest.raises(AIQuotaExceededError):
        await _run_check(quota, "tenant-a", req_limit=2)

    req_key = next(k for k in fake.store if "req" in k)
    assert int(fake.store[req_key]) == 3
    assert fake.expirations.get(req_key, 0) >= 120


async def test_daily_and_monthly_budgets_read_via_mget() -> None:
    """Regression: daily/monthly budgets are read together via mget (PERF-06)."""
    daily_key = LLMQuotaService._daily_key("dne-tenant")
    monthly_key = LLMQuotaService._monthly_key("dne-tenant")

    settings = _make_settings()
    settings.llm_daily_token_limit = 100
    settings.llm_monthly_token_limit = 1000
    settings.llm_request_limit_per_minute = 0
    fake = _FakeRedis(settings)
    fake.store[daily_key] = "100"  # at exact limit -> rejected
    fake.store[monthly_key] = "500"
    quota = LLMQuotaService(redis=fake, settings=settings)

    with pytest.raises(AIQuotaExceededError):
        await quota.check("dne-tenant")

    # Monthly budget exhausted while daily still has headroom -> rejected too.
    fake.store[daily_key] = "10"
    fake.store[monthly_key] = "1000"
    with pytest.raises(AIQuotaExceededError):
        await quota.check("dne-tenant")

    # Both within budget -> passes, and no request counter is touched.
    fake.store[daily_key] = "10"
    fake.store[monthly_key] = "900"
    await quota.check("dne-tenant")
    assert fake.store.get(daily_key) == "10"


class _BoomRedis(_FakeRedis):
    """Raises a configurable failure on every Redis operation."""

    def __init__(self, settings, exc: Exception) -> None:
        super().__init__(settings)
        self._exc = exc

    async def get(self, key: str) -> str | None:
        raise self._exc

    async def mget(self, *keys: str) -> list[str | None]:
        raise self._exc

    def pipeline(self, transaction: bool = False) -> _FakePipeline:
        raise self._exc

    async def incr(self, key: str) -> int:
        raise self._exc

    async def incrby(self, key: str, amount: int) -> int:
        raise self._exc

    async def expire(self, key: str, seconds: int) -> None:
        raise self._exc

    async def delete(self, *keys: str) -> int:
        raise self._exc


async def test_check_fails_open_when_redis_unavailable() -> None:
    """A Redis/network outage must never block traffic (BE-Q06 fail open)."""
    settings = _make_settings()
    settings.llm_daily_token_limit = 0
    settings.llm_monthly_token_limit = 0
    settings.llm_request_limit_per_minute = 5
    quota = LLMQuotaService(
        redis=_BoomRedis(settings=settings, exc=ConnectionError("redis down")),
        settings=settings,
    )

    await quota.check("tenant-a")  # must not raise


async def test_record_and_reset_fail_open_when_redis_unavailable() -> None:
    """Best-effort accounting: a Redis outage is silently skipped (BE-Q06)."""
    settings = _make_settings()
    settings.llm_daily_token_limit = 1000
    settings.llm_monthly_token_limit = 1000
    quota = LLMQuotaService(
        redis=_BoomRedis(settings=settings, exc=TimeoutError("redis down")),
        settings=settings,
    )

    await quota.record("tenant-a", input_tokens=100, output_tokens=50)
    await quota.reset("tenant-a")


async def test_check_surfaces_non_redis_errors() -> None:
    """Only infra failures fail open; programming bugs must surface (BE-Q06)."""
    settings = _make_settings()
    settings.llm_daily_token_limit = 0
    settings.llm_monthly_token_limit = 0
    settings.llm_request_limit_per_minute = 5
    quota = LLMQuotaService(
        redis=_BoomRedis(settings=settings, exc=RuntimeError("programming bug")),
        settings=settings,
    )

    with pytest.raises(RuntimeError):
        await quota.check("tenant-a")


def _make_settings():
    from backend.core.config import Settings

    return Settings(_env_file=None)
