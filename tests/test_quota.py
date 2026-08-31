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


def _make_settings():
    from backend.core.config import Settings

    return Settings(_env_file=None)
