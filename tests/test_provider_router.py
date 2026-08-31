"""Tests for the adaptive provider router (Phase 12.6).

Tests the health-aware ordering strategy with recovery penalty:
- Gemini fails → Groq selected next request
- Gemini cooldown active → never selected
- Gemini cooldown expired but Groq healthy → Groq remains primary
- Gemini successful recovery → priority restored
"""

import time

import pytest
from backend.ai.gemini import GenerationUsage
from backend.services.ai.provider_health import ProviderHealthStore
from backend.services.ai.provider_router import AdaptiveProviderRouter


class StubProvider:
    """Minimal generation client stub for router tests."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._usage = GenerationUsage(input_tokens=1, output_tokens=1)
        self.calls = 0

    @property
    def usage(self) -> GenerationUsage:
        return self._usage

    async def stream_generate(self, *, system: str, messages: list[tuple[str, str]]):
        self.calls += 1
        yield "ok"


async def _collect(stream) -> list[str]:
    return [delta async for delta in stream]


@pytest.fixture
def fake_redis():
    """In-memory dict pretending to be Redis for ProviderHealthStore."""
    store: dict[str, str] = {}

    class FakeRedis:
        async def get(self, key: str) -> str | None:
            return store.get(key)

        async def set(self, key: str, value: str) -> None:
            store[key] = value

    return FakeRedis()


@pytest.fixture
def health_store(fake_redis) -> ProviderHealthStore:
    return ProviderHealthStore(
        redis=fake_redis,  # type: ignore[arg-type]
        cooldown_seconds=60,
        health_check_interval=300,
        latency_smoothing=0.3,
    )


@pytest.fixture
def providers():
    return [StubProvider("gemini"), StubProvider("groq"), StubProvider("openrouter")]


def _provider_names(router: AdaptiveProviderRouter) -> list[str]:
    """Extract the current provider order from the router's internal map."""
    return list(router._provider_map.keys())


# ── Test cases ──────────────────────────────────────────────────────────────


async def test_gemini_fails_groq_selected_next(health_store, providers):
    """After Gemini fails and enters cooldown, Groq should be selected."""
    # Record a failure for Gemini.
    await health_store.record_failure("gemini")

    router = AdaptiveProviderRouter(
        providers=providers,
        health=health_store,
        recovery_window_seconds=120,
    )

    ordered = await router._build_ordered_providers()
    names = [getattr(p, "name", type(p).__name__) for p in ordered]

    # Gemini should not be first — Groq or openrouter should lead.
    assert names[0] != "gemini"
    # Gemini should be at the end (cooldown).
    assert names.index("gemini") > names.index("groq")


async def test_gemini_cooldown_active_never_selected(health_store, providers):
    """When Gemini is in active cooldown, it must not be first in order."""
    # Record multiple failures to ensure cooldown is active.
    await health_store.record_failure("gemini")
    await health_store.record_failure("gemini")

    # Verify cooldown is active.
    available = await health_store.is_available("gemini")
    assert available is False

    router = AdaptiveProviderRouter(
        providers=providers,
        health=health_store,
        recovery_window_seconds=120,
    )

    ordered = await router._build_ordered_providers()
    names = [getattr(p, "name", type(p).__name__) for p in ordered]

    # Gemini must be last (in cooldown).
    assert names[-1] == "gemini"
    # Groq must come before Gemini.
    assert names.index("groq") < names.index("gemini")


async def test_cooldown_expired_groq_stays_primary(health_store, providers):
    """After cooldown expires, Gemini stays below healthy providers (recovery)."""
    # Give Groq a realistic latency so scoring works properly.
    await health_store.record_success("groq", latency_ms=500.0)
    await health_store.record_success("openrouter", latency_ms=600.0)

    # Simulate Gemini cooldown expiry (happened long ago).
    now = time.time()
    await health_store._redis.set(  # type: ignore[union-attr]
        "ai_provider_health:gemini",
        (
            '{"status":"cooldown","failures":1,'
            f'"last_failure":{now - 120},"cooldown_until":{now - 60},'
            f'"average_latency_ms":150.0,"last_check":{now - 60},'
            '"consecutive_failures":1,"last_success":null}'
        ),
    )

    # Verify cooldown is now expired.
    available = await health_store.is_available("gemini")
    assert available is True

    router = AdaptiveProviderRouter(
        providers=providers,
        health=health_store,
        recovery_window_seconds=120,
    )

    ordered = await router._build_ordered_providers()
    names = [getattr(p, "name", type(p).__name__) for p in ordered]

    # Gemini is in recovery → health_score=0.5 puts it behind healthy providers.
    assert names[0] != "gemini"
    assert names.index("gemini") > names.index("groq")


async def test_successful_recovery_restores_priority(health_store, providers):
    """After Gemini succeeds, it should return to normal priority."""
    # First, put Gemini in cooldown.
    await health_store.record_failure("gemini")

    # Then simulate cooldown expiry and a success.
    now = time.time()
    await health_store._redis.set(  # type: ignore[union-attr]
        "ai_provider_health:gemini",
        (
            '{"status":"cooldown","failures":1,'
            f'"last_failure":{now - 120},"cooldown_until":{now - 60},'
            f'"average_latency_ms":100.0,"last_check":{now - 60},'
            '"consecutive_failures":1,"last_success":null}'
        ),
    )

    # Gemini succeeds.
    await health_store.record_success("gemini", latency_ms=100.0)

    # Now Gemini should be healthy again with consecutive_failures=0.
    health = await health_store.get_health("gemini")
    assert health.status == "healthy"
    assert health.consecutive_failures == 0
    assert health.last_success is not None

    router = AdaptiveProviderRouter(
        providers=providers,
        health=health_store,
        recovery_window_seconds=120,
    )

    ordered = await router._build_ordered_providers()
    names = [getattr(p, "name", type(p).__name__) for p in ordered]

    # Gemini should now be in the healthy group (first position possible).
    # With latency 100ms it should be first.
    assert names[0] == "gemini"


async def test_all_healthy_uses_latency_ordering(health_store, providers):
    """When all providers are healthy with no failures, order by latency."""
    # Give Gemini a higher latency.
    await health_store.record_success("gemini", latency_ms=200.0)
    await health_store.record_success("groq", latency_ms=50.0)
    await health_store.record_success("openrouter", latency_ms=100.0)

    router = AdaptiveProviderRouter(
        providers=providers,
        health=health_store,
        recovery_window_seconds=120,
    )

    ordered = await router._build_ordered_providers()
    names = [getattr(p, "name", type(p).__name__) for p in ordered]

    # Groq (50ms) < openrouter (100ms) < gemini (200ms).
    assert names == ["groq", "openrouter", "gemini"]


async def test_cooldown_provider_last_even_with_high_latency(health_store, providers):
    """A provider in cooldown is always last regardless of latency."""
    # Give Gemini low latency but put it in cooldown.
    await health_store.record_success("gemini", latency_ms=10.0)
    await health_store.record_failure("gemini")

    # Give Groq higher latency but healthy.
    await health_store.record_success("groq", latency_ms=200.0)

    router = AdaptiveProviderRouter(
        providers=providers,
        health=health_store,
        recovery_window_seconds=120,
    )

    ordered = await router._build_ordered_providers()
    names = [getattr(p, "name", type(p).__name__) for p in ordered]

    # Gemini must be last despite low latency.
    assert names[-1] == "gemini"
    assert names.index("groq") < names.index("gemini")


async def test_structured_log_on_selection(health_store, providers, caplog):
    """Provider selection emits structured log with reason."""
    await health_store.record_failure("gemini")

    router = AdaptiveProviderRouter(
        providers=providers,
        health=health_store,
        recovery_window_seconds=120,
    )

    import logging

    with caplog.at_level(logging.INFO, logger="webchat_ai"):
        await router._build_ordered_providers()

    assert "ai_provider_selected" in caplog.text
    assert "provider=" in caplog.text
    assert "reason=" in caplog.text


# ── Weighted scoring tests ─────────────────────────────────────────────────


async def test_fastest_healthy_provider_selected(health_store, providers):
    """Provider with lowest latency wins when all are healthy."""
    await health_store.record_success("gemini", latency_ms=800.0)
    await health_store.record_success("groq", latency_ms=500.0)
    await health_store.record_success("openrouter", latency_ms=600.0)

    router = AdaptiveProviderRouter(
        providers=providers,
        health=health_store,
    )

    ordered = await router._build_ordered_providers()
    names = [getattr(p, "name", type(p).__name__) for p in ordered]

    # Groq is fastest (500ms) → first.
    assert names[0] == "groq"


async def test_failed_provider_enters_cooldown(health_store, providers):
    """A provider that fails enters cooldown and moves to the end."""
    await health_store.record_success("gemini", latency_ms=200.0)
    await health_store.record_success("groq", latency_ms=300.0)
    await health_store.record_failure("gemini")

    available = await health_store.is_available("gemini")
    assert available is False

    router = AdaptiveProviderRouter(
        providers=providers,
        health=health_store,
    )

    ordered = await router._build_ordered_providers()
    names = [getattr(p, "name", type(p).__name__) for p in ordered]

    # Gemini is in cooldown → last.
    assert names[-1] == "gemini"


async def test_cooldown_provider_skipped(health_store, providers):
    """Cooldown providers are placed after all healthy providers."""
    await health_store.record_success("groq", latency_ms=100.0)
    await health_store.record_success("openrouter", latency_ms=200.0)
    await health_store.record_failure("gemini")
    await health_store.record_failure("gemini")

    router = AdaptiveProviderRouter(
        providers=providers,
        health=health_store,
    )

    ordered = await router._build_ordered_providers()
    names = [getattr(p, "name", type(p).__name__) for p in ordered]

    # Both healthy providers must come before Gemini.
    healthy_idx = [names.index("groq"), names.index("openrouter")]
    cooldown_idx = names.index("gemini")
    assert all(i < cooldown_idx for i in healthy_idx)


async def test_priority_breaks_equal_latency(health_store, providers):
    """When latencies are equal, priority (gemini=1) wins over groq=2."""
    await health_store.record_success("gemini", latency_ms=1000.0)
    await health_store.record_success("groq", latency_ms=1000.0)
    await health_store.record_success("openrouter", latency_ms=1000.0)

    router = AdaptiveProviderRouter(
        providers=providers,
        health=health_store,
    )

    ordered = await router._build_ordered_providers()
    names = [getattr(p, "name", type(p).__name__) for p in ordered]

    # All equal latency → priority decides: gemini(1) > groq(2) > openrouter(3).
    assert names[0] == "gemini"
    assert names[1] == "groq"
    assert names[2] == "openrouter"


async def test_redis_unavailable_fallback_works(monkeypatch, providers):
    """When Redis is unavailable, router degrades gracefully."""
    from backend.services.ai.provider_health import ProviderHealthStore

    class BrokenRedis:
        async def get(self, key: str):
            raise ConnectionError("redis down")

        async def set(self, key: str, value: str) -> None:
            raise ConnectionError("redis down")

    broken_store = ProviderHealthStore(
        redis=BrokenRedis(),  # type: ignore[arg-type]
        cooldown_seconds=60,
        health_check_interval=300,
    )

    router = AdaptiveProviderRouter(
        providers=providers,
        health=broken_store,
    )

    # Should not raise — defaults to original provider order.
    ordered = await router._build_ordered_providers()
    names = [getattr(p, "name", type(p).__name__) for p in ordered]

    # All providers should be present.
    assert len(names) == 3
    assert set(names) == {"gemini", "groq", "openrouter"}


async def test_latency_dominates_priority(health_store, providers):
    """Groq at 900ms beats Gemini at 2000ms despite lower priority."""
    await health_store.record_success("gemini", latency_ms=2000.0)
    await health_store.record_success("groq", latency_ms=900.0)

    router = AdaptiveProviderRouter(
        providers=providers,
        health=health_store,
    )

    ordered = await router._build_ordered_providers()
    names = [getattr(p, "name", type(p).__name__) for p in ordered]

    # Groq is materially faster → first despite lower priority.
    assert names[0] == "groq"


async def test_log_includes_score_and_health(health_store, providers, caplog):
    """Structured log includes score, latency, and health fields."""
    await health_store.record_success("groq", latency_ms=500.0)

    router = AdaptiveProviderRouter(
        providers=providers,
        health=health_store,
    )

    import logging

    with caplog.at_level(logging.INFO, logger="webchat_ai"):
        await router._build_ordered_providers()

    assert "score=" in caplog.text
    assert "latency_ms=" in caplog.text
    assert "health=" in caplog.text
    assert "reason=highest_score" in caplog.text
