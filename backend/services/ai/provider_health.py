"""Redis-backed provider health tracking with circuit breaker.

Maintains per-provider state (status, failures, cooldown, latency) in Redis
so the adaptive router can skip unhealthy providers before they consume their
full timeout.  All Redis operations are wrapped in try/except with fail-open
semantics: a Redis outage degrades to the static fallback chain rather than
blocking the chat path.

State key: ``ai_provider_health:{provider_name}``
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger("webchat_ai")

# ── Status constants ────────────────────────────────────────────────────────

STATUS_HEALTHY = "healthy"
STATUS_COOLDOWN = "cooldown"

# ── Internal state shape ────────────────────────────────────────────────────

_KEY_PREFIX = "ai_provider_health"


def _health_key(provider_name: str) -> str:
    return f"{_KEY_PREFIX}:{provider_name}"


@dataclass(frozen=True)
class ProviderHealth:
    """Snapshot of a single provider's health state."""

    provider: str
    status: str
    failures: int
    last_failure: float | None
    cooldown_until: float | None
    average_latency_ms: float
    last_check: float
    consecutive_failures: int = 0
    last_success: float | None = None


# ── Store ───────────────────────────────────────────────────────────────────


class ProviderHealthStore:
    """Async provider health state backed by Redis.

    Every public method is fail-open: a Redis failure is logged at WARNING
    and the caller receives safe defaults so the chat path is never blocked.
    """

    def __init__(
        self,
        redis: Redis,
        *,
        cooldown_seconds: int = 60,
        health_check_interval: int = 300,
        latency_smoothing: float = 0.3,
    ) -> None:
        self._redis = redis
        self._cooldown_seconds = cooldown_seconds
        self._health_check_interval = health_check_interval
        self._latency_smoothing = latency_smoothing

    # ── Read ────────────────────────────────────────────────────────────

    async def get_health(self, provider_name: str) -> ProviderHealth:
        """Return the current health snapshot for a provider.

        When Redis is unavailable or the key is missing, returns a healthy
        default so the static fallback chain is used unchanged.
        """
        try:
            raw = await self._redis.get(_health_key(provider_name))
            if raw is None:
                return self._default_health(provider_name)
            data = json.loads(raw)
            return ProviderHealth(
                provider=provider_name,
                status=data.get("status", STATUS_HEALTHY),
                failures=int(data.get("failures", 0)),
                last_failure=data.get("last_failure"),
                cooldown_until=data.get("cooldown_until"),
                average_latency_ms=float(data.get("average_latency_ms", 0.0)),
                last_check=float(data.get("last_check", 0.0)),
                consecutive_failures=int(data.get("consecutive_failures", 0)),
                last_success=data.get("last_success"),
            )
        except Exception:
            logger.warning(
                "provider health GET failed (provider=%s); using default",
                provider_name,
                exc_info=True,
            )
            return self._default_health(provider_name)

    async def is_available(self, provider_name: str) -> bool:
        """True when a provider may be tried (not in active cooldown)."""
        health = await self.get_health(provider_name)
        if health.status != STATUS_COOLDOWN:
            return True
        if health.cooldown_until is None:
            return True
        now = time.time()
        if now >= health.cooldown_until:
            return True
        # Stale health data: if the last check was more than
        # ``health_check_interval`` ago, treat the provider as recoverable
        # (the original failure may be long-resolved).
        if health.last_check and (now - health.last_check) > self._health_check_interval:
            return True
        return False

    # ── Write ───────────────────────────────────────────────────────────

    async def record_success(self, provider_name: str, latency_ms: float) -> None:
        """Record a successful request: update latency EMA, clear failures."""
        try:
            health = await self.get_health(provider_name)
            if health.average_latency_ms > 0:
                alpha = self._latency_smoothing
                new_latency = alpha * latency_ms + (1 - alpha) * health.average_latency_ms
            else:
                new_latency = latency_ms
            now = time.time()
            state: dict[str, Any] = {
                "status": STATUS_HEALTHY,
                "failures": 0,
                "last_failure": None,
                "cooldown_until": None,
                "average_latency_ms": round(new_latency, 2),
                "last_check": now,
                "consecutive_failures": 0,
                "last_success": now,
            }
            await self._redis.set(
                _health_key(provider_name),
                json.dumps(state),
            )
        except Exception:
            logger.warning(
                "provider health record_success failed (provider=%s)",
                provider_name,
                exc_info=True,
            )

    async def record_failure(self, provider_name: str) -> None:
        """Record a failure: enter or extend cooldown.

        First failure → ``cooldown_seconds``.
        Subsequent failures → ``cooldown_seconds * 2^(failures-1)``
        (capped at 5 minutes).
        """
        try:
            health = await self.get_health(provider_name)
            new_failures = health.failures + 1
            new_consecutive = health.consecutive_failures + 1
            base = self._cooldown_seconds
            multiplier = 2 ** (new_failures - 1)
            cooldown_secs = min(base * multiplier, 300)
            now = time.time()
            state: dict[str, Any] = {
                "status": STATUS_COOLDOWN,
                "failures": new_failures,
                "last_failure": now,
                "cooldown_until": now + cooldown_secs,
                "average_latency_ms": health.average_latency_ms,
                "last_check": now,
                "consecutive_failures": new_consecutive,
                "last_success": health.last_success,
            }
            await self._redis.set(
                _health_key(provider_name),
                json.dumps(state),
            )
            logger.info(
                "ai_provider_failed provider=%s cooldown_seconds=%s failures=%s",
                provider_name,
                cooldown_secs,
                new_failures,
            )
        except Exception:
            logger.warning(
                "provider health record_failure failed (provider=%s)",
                provider_name,
                exc_info=True,
            )

    # ── Internal ────────────────────────────────────────────────────────

    def _default_health(self, provider_name: str) -> ProviderHealth:
        """Healthy default when Redis is unreachable or key is missing."""
        return ProviderHealth(
            provider=provider_name,
            status=STATUS_HEALTHY,
            failures=0,
            last_failure=None,
            cooldown_until=None,
            average_latency_ms=0.0,
            last_check=0.0,
            consecutive_failures=0,
            last_success=None,
        )


__all__ = [
    "ProviderHealth",
    "ProviderHealthStore",
    "STATUS_COOLDOWN",
    "STATUS_HEALTHY",
]
