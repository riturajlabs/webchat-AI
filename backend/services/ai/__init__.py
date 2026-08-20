"""Adaptive AI provider routing with health tracking (Phase 12.6).

Provides Redis-backed provider health state and circuit-breaker behavior
so the generation fallback chain skips unhealthy providers instead of
waiting for their full timeout before falling back.
"""

from backend.services.ai.provider_health import ProviderHealthStore
from backend.services.ai.provider_router import AdaptiveProviderRouter

__all__ = ["AdaptiveProviderRouter", "ProviderHealthStore"]
