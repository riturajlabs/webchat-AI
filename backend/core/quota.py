"""Per-tenant AI usage quota enforcement (Phase 14.9.4).

Tracks, in Redis, per-tenant:
  * cumulative daily token usage   ``llm:quota:tok:daily:{tenant}:{YYYYMMDD}``
  * cumulative monthly token usage ``llm:quota:tok:monthly:{tenant}:{YYYYMM}``
  * per-minute request count       ``llm:quota:req:{tenant}:{YYYYMMDDHHMM}``

Before an LLM call, the chat route calls :meth:`LLMQuotaService.check`. If any
budget is exhausted an :class:`AIQuotaExceededError` is raised and surfaced as
HTTP 429 ("AI usage limit exceeded. Please upgrade your plan."). After a
completed turn, :meth:`LLMQuotaService.record` adds the turn's token usage to
the running totals.

All Redis access is best-effort: ``check`` fails OPEN (allow) when Redis is
unavailable so a cache outage never blocks legitimate traffic, while ``record``
silently swallows errors. Rejections are counted by the
``llm_quota_exceeded_total`` metric (label ``window`` is tenant-safe).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from backend.core.config import Settings, get_settings
from backend.core.errors import AIQuotaExceededError
from backend.core.metrics import record_llm_quota_exceeded
from backend.core.redis import get_redis

if TYPE_CHECKING:
    from redis.asyncio import Redis as AsyncRedisClient

logger = logging.getLogger("webchat_ai")

_DAILY_KEY = "llm:quota:tok:daily:{tenant}:{date}"
_MONTHLY_KEY = "llm:quota:tok:monthly:{tenant}:{month}"
_REQ_KEY = "llm:quota:req:{tenant}:{minute}"
# TTL for daily token counters: long enough to cover the day plus headroom.
_DAILY_TOKEN_TTL_SECONDS = 2 * 24 * 60 * 60  # 2 days
# TTL for monthly token counters: long enough to cover the full calendar month
# plus headroom so the counter never expires mid-month (budget bypass).
_MONTHLY_TOKEN_TTL_SECONDS = 35 * 24 * 60 * 60  # 35 days
# Per-minute request counter TTL: long enough to cover the current minute.
_REQ_TTL_SECONDS = 120


class LLMQuotaService:
    """Redis-backed, tenant-isolated AI quota limiter."""

    def __init__(
        self, redis: AsyncRedisClient | None = None, settings: Settings | None = None
    ) -> None:
        self._redis = redis
        self._settings = settings

    async def _redis_client(self) -> AsyncRedisClient:
        if self._redis is not None:
            return self._redis
        return get_redis()

    def _settings_obj(self) -> Settings:
        return self._settings if self._settings is not None else get_settings()

    # --- key builders (UTC windows) ---
    @staticmethod
    def _daily_key(tenant_id: str) -> str:
        date = datetime.now(UTC).strftime("%Y%m%d")
        return _DAILY_KEY.format(tenant=tenant_id, date=date)

    @staticmethod
    def _monthly_key(tenant_id: str) -> str:
        month = datetime.now(UTC).strftime("%Y%m")
        return _MONTHLY_KEY.format(tenant=tenant_id, month=month)

    @staticmethod
    def _req_key(tenant_id: str) -> str:
        minute = datetime.now(UTC).strftime("%Y%m%d%H%M")
        return _REQ_KEY.format(tenant=tenant_id, minute=minute)

    async def check(self, tenant_id: str) -> None:
        """Raise :class:`AIQuotaExceededError` if any budget is exhausted.

        A limit of ``0`` means "unlimited" and is skipped. A Redis outage is
        treated as "allow" (fail open) to protect availability.
        """
        settings = self._settings_obj()
        daily_limit = settings.llm_daily_token_limit
        monthly_limit = settings.llm_monthly_token_limit
        req_limit = settings.llm_request_limit_per_minute
        if daily_limit <= 0 and monthly_limit <= 0 and req_limit <= 0:
            return
        try:
            redis = await self._redis_client()
        except Exception:  # pragma: no cover - redis unavailable
            logger.warning("llm_quota_check_redis_unavailable tenant=%s", tenant_id)
            return
        try:
            if daily_limit > 0:
                used = int(await redis.get(self._daily_key(tenant_id)) or 0)
                if used >= daily_limit:
                    record_llm_quota_exceeded("daily")
                    raise AIQuotaExceededError(AIQuotaExceededError.message)
            if monthly_limit > 0:
                used = int(await redis.get(self._monthly_key(tenant_id)) or 0)
                if used >= monthly_limit:
                    record_llm_quota_exceeded("monthly")
                    raise AIQuotaExceededError(AIQuotaExceededError.message)
            if req_limit > 0:
                # Atomic INCR-then-check: eliminates the TOCTOU race where
                # concurrent requests read the same count and all pass.
                new_count = await redis.incr(self._req_key(tenant_id))
                await redis.expire(self._req_key(tenant_id), _REQ_TTL_SECONDS)
                if new_count > req_limit:
                    record_llm_quota_exceeded("request")
                    raise AIQuotaExceededError(AIQuotaExceededError.message)
        except AIQuotaExceededError:
            raise
        except Exception:  # pragma: no cover - redis read error
            logger.warning("llm_quota_check_error tenant=%s", tenant_id)
            return

    async def record(self, tenant_id: str, input_tokens: int, output_tokens: int) -> None:
        """Best-effort: add a turn's token usage to the tenant's running totals."""
        total = int(input_tokens or 0) + int(output_tokens or 0)
        if total <= 0:
            return
        settings = self._settings_obj()
        daily = settings.llm_daily_token_limit > 0
        monthly = settings.llm_monthly_token_limit > 0
        if not (daily or monthly):
            return
        try:
            redis = await self._redis_client()
        except Exception:
            return
        try:
            if daily:
                await redis.incrby(self._daily_key(tenant_id), total)
                await redis.expire(self._daily_key(tenant_id), _DAILY_TOKEN_TTL_SECONDS)
            if monthly:
                await redis.incrby(self._monthly_key(tenant_id), total)
                await redis.expire(self._monthly_key(tenant_id), _MONTHLY_TOKEN_TTL_SECONDS)
        except Exception:
            logger.warning("llm_quota_record_error tenant=%s", tenant_id)

    async def reset(self, tenant_id: str) -> None:
        """Clear all quota counters for a tenant (tests / admin tooling)."""
        try:
            redis = await self._redis_client()
            await redis.delete(
                self._daily_key(tenant_id),
                self._monthly_key(tenant_id),
                self._req_key(tenant_id),
            )
        except Exception:
            logger.warning("llm_quota_reset_error tenant=%s", tenant_id)
