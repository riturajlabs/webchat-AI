"""Adaptive generation provider router with weighted scoring.

Wraps the existing ``FallbackGenerationClient`` and ``GenerationClient``
Protocol so the RAG service continues depending on the same interface.
Before each request the adaptive router queries ``ProviderHealthStore``
for provider health, computes a weighted score for each provider, and
delegates streaming to the original fallback client.

When ``AI_PROVIDER_ROUTING_MODE=static``, health lookups are skipped and
the static ``GENERATION_PROVIDER_ORDER`` is used unchanged — zero
behavioural change for deployments that do not opt in.
"""

import logging
import time
from collections.abc import AsyncIterator

from backend.ai.gemini import GenerationClient, GenerationUsage
from backend.ai.router import FallbackGenerationClient, ProviderLatencyMetrics
from backend.services.ai.provider_health import ProviderHealth, ProviderHealthStore

logger = logging.getLogger("webchat_ai")

# ── Scoring weights ────────────────────────────────────────────────────────
# Higher score = better provider.  Components are normalised to 0..1.
# Priority is a small tie-breaker and must never override a materially
# faster provider (requirement: Groq@900ms beats Gemini@2000ms).
WEIGHT_LATENCY = 0.70
WEIGHT_HEALTH = 0.28
WEIGHT_PRIORITY = 0.02

# ── Provider priority (lower number = higher priority, tie-breaker only) ───
PROVIDER_PRIORITY: dict[str, int] = {
    "gemini": 1,
    "groq": 2,
    "openrouter": 3,
}

# Latency ceiling (ms) used to normalise the latency component.  Any
# provider at or above this value receives a latency score of 0.
_MAX_LATENCY_MS = 3000.0


class AdaptiveProviderRouter:
    """Health-aware generation router using weighted adaptive scoring.

    Each healthy provider receives a composite score:
        score = W_latency * latency_score
              + W_health * health_score
              + W_priority * priority_score

    Cooldown providers always rank below healthy ones regardless of
    score.  Priority is a small tie-breaker and never overrides a
    materially faster provider.
    """

    def __init__(
        self,
        *,
        providers: list[GenerationClient],
        health: ProviderHealthStore,
        recovery_window_seconds: int = 120,
    ) -> None:
        self._health = health
        self._recovery_window_seconds = recovery_window_seconds
        self._provider_map: dict[str, GenerationClient] = {
            getattr(p, "name", type(p).__name__): p for p in providers
        }
        # The inner fallback client handles the actual streaming fallback.
        # Its initial order is the static config order — it will be
        # overridden by the reordered list on each request.
        self._fallback = FallbackGenerationClient(providers)

    @property
    def usage(self) -> GenerationUsage:
        return self._fallback.usage

    @property
    def active_provider(self) -> str | None:
        return self._fallback.active_provider

    @property
    def last_latency_metrics(self) -> ProviderLatencyMetrics | None:
        return self._fallback.last_latency_metrics

    async def stream_generate(
        self,
        *,
        system: str,
        messages: list[tuple[str, str]],
    ) -> AsyncIterator[str]:
        """Stream answer deltas, preferring healthy low-latency providers.

        Health lookup is fail-open: on Redis errors the configured order
        is used unchanged (degrading to the static fallback chain).
        """
        ordered = await self._build_ordered_providers()
        self._fallback._providers = ordered
        async for delta in self._fallback.stream_generate(system=system, messages=messages):
            yield delta
        # After the stream completes, report success/failure for health
        # tracking.  ``FallbackGenerationClient`` already set
        # ``_last_latency_metrics``.
        await self._update_health_from_metrics()

    # ── Internal ────────────────────────────────────────────────────────

    async def _build_ordered_providers(self) -> list[GenerationClient]:
        """Fetch health for every registered provider and sort by score.

        Healthy providers are ranked by weighted score (descending).
        Cooldown providers are appended at the end sorted by latency.
        """
        now = time.time()
        names = list(self._provider_map.keys())
        health_snapshots: list[tuple[str, ProviderHealth, bool]] = []
        for name in names:
            snapshot = await self._health.get_health(name)
            available = await self._health.is_available(name)
            health_snapshots.append((name, snapshot, available))

        healthy: list[tuple[str, float, str]] = []
        cooldown: list[tuple[str, float]] = []

        for name, snapshot, available in health_snapshots:
            latency = snapshot.average_latency_ms or float("inf")
            if not available:
                cooldown.append((name, latency))
                continue
            in_recovery = self._is_in_recovery(snapshot, now)
            score = self._compute_score(name, latency, in_recovery)
            health_label = "recovery" if in_recovery else "healthy"
            healthy.append((name, score, health_label))

        # Sort healthy by score descending (higher = better).
        healthy.sort(key=lambda x: x[1], reverse=True)
        # Sort cooldown by latency ascending (fastest first among cooldown).
        cooldown.sort(key=lambda x: x[1])

        ordered_names = [n for n, _, _ in healthy] + [n for n, _ in cooldown]

        # Structured log for the selected provider.
        if healthy:
            best_name, best_score, best_health = healthy[0]
            best_snapshot = next((s for n, s, _ in health_snapshots if n == best_name), None)
            best_latency = best_snapshot.average_latency_ms if best_snapshot else 0.0
            reason = "highest_score"
        elif cooldown:
            best_name = cooldown[0][0]
            best_score = 0.0
            best_latency = cooldown[0][1]
            best_health = "cooldown"
            reason = "cooldown_only"
        else:
            best_name = "none"
            best_score = 0.0
            best_latency = 0.0
            best_health = "unknown"
            reason = "fallback_order"

        logger.info(
            "ai_provider_selected provider=%s reason=%s "
            "score=%.3f latency_ms=%.0f health=%s "
            "healthy_count=%d cooldown_count=%d",
            best_name,
            reason,
            best_score,
            best_latency,
            best_health,
            len(healthy),
            len(cooldown),
        )

        ordered = []
        for name in ordered_names:
            provider = self._provider_map.get(name)
            if provider is not None:
                ordered.append(provider)
        return ordered

    def _is_in_recovery(self, health: ProviderHealth, now: float) -> bool:
        """True when a provider is healthy but lacks a recent success.

        A provider that has never succeeded, or whose last success was
        more than ``recovery_window_seconds`` ago, is in recovery.  This
        prevents a just-recovered provider from immediately becoming the
        primary choice.
        """
        if health.consecutive_failures == 0 and health.last_success is not None:
            return False
        if health.last_success is None:
            # Never succeeded — treat as recovery unless zero failures.
            return health.consecutive_failures > 0
        return (now - health.last_success) > self._recovery_window_seconds

    def _compute_score(
        self,
        name: str,
        latency_ms: float,
        in_recovery: bool,
    ) -> float:
        """Weighted composite score for a healthy provider.

        Components (all 0..1, higher = better):
        - latency: 1 - (latency / MAX_LATENCY), clamped to [0, 1]
        - health:  1.0 if recently successful, 0.5 if in recovery
        - priority: (max_priority - provider_priority + 1) / max_priority
        """
        # Latency component (inverted: lower latency → higher score).
        capped = min(latency_ms, _MAX_LATENCY_MS)
        latency_score = 1.0 - (capped / _MAX_LATENCY_MS)

        # Health component.
        health_score = 0.5 if in_recovery else 1.0

        # Priority component (tie-breaker).
        max_priority = max(PROVIDER_PRIORITY.values()) or 1
        provider_priority = PROVIDER_PRIORITY.get(name, max_priority)
        priority_score = (max_priority - provider_priority + 1) / max_priority

        return (
            WEIGHT_LATENCY * latency_score
            + WEIGHT_HEALTH * health_score
            + WEIGHT_PRIORITY * priority_score
        )

    async def _update_health_from_metrics(self) -> None:
        """Push success/failure to the health store from fallback metrics."""
        metrics = self._fallback.last_latency_metrics
        if metrics is None:
            return
        # Record failure for every provider that was tried and failed.
        for name in metrics.failed_providers:
            await self._health.record_failure(name)
        # Record success for the provider that actually served the response.
        if metrics.success and metrics.provider not in ("none", "unknown"):
            latency = metrics.total_generation_latency_ms
            if metrics.first_token_latency_ms is not None:
                latency = metrics.first_token_latency_ms
            await self._health.record_success(metrics.provider, latency)


__all__ = ["AdaptiveProviderRouter"]
