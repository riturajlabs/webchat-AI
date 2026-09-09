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
from backend.core.errors import GenerationError
from backend.services.ai.provider_health import ProviderHealthStore, provider_health_name
from backend.services.ai.provider_router import AdaptiveProviderRouter


class StubProvider:
    """Minimal generation client stub for router tests."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._usage = GenerationUsage(input_tokens=1, output_tokens=1)
        self.calls = 0
        self.fail_before_output = False

    @property
    def usage(self) -> GenerationUsage:
        return self._usage

    async def stream_generate(self, *, system: str, messages: list[tuple[str, str]]):
        self.calls += 1
        if self.fail_before_output:
            raise GenerationError(f"{self.name} provider down")
        yield "ok"


async def _collect(stream) -> list[str]:
    return [delta async for delta in stream]


@pytest.fixture
def fake_redis():
    """In-memory dict pretending to be Redis for ProviderHealthStore."""
    store: dict[str, str] = {}

    class _FakePipeline:
        """Mimics redis.asyncio Pipeline: buffer get() calls, execute() lazily."""

        def __init__(self) -> None:
            self._commands: list[str] = []

        def get(self, key: str) -> None:
            self._commands.append(key)

        async def execute(self) -> list[str | None]:  # noqa: D102
            return [store.get(k) for k in self._commands]

    class FakeRedis:
        async def get(self, key: str) -> str | None:
            return store.get(key)

        async def set(self, key: str, value: str) -> None:
            store[key] = value

        def pipeline(self, transaction: bool = True):  # noqa: ARG001
            return _FakePipeline()

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


def gn(provider: str) -> str:
    """Namespaced provider name matching the router's ``provider_health_name`` calls."""
    return provider_health_name("generation", provider)


def _provider_names(router: AdaptiveProviderRouter) -> list[str]:
    """Extract the current provider order from the router's internal map."""
    return list(router._provider_map.keys())


# ── Test cases ──────────────────────────────────────────────────────────────


async def test_gemini_fails_groq_selected_next(health_store, providers):
    """After Gemini fails and enters cooldown, Groq should be selected."""
    # Record a failure for Gemini.
    await health_store.record_failure(gn("gemini"))

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
    await health_store.record_failure(gn("gemini"))
    await health_store.record_failure(gn("gemini"))

    # Verify cooldown is active.
    available = await health_store.is_available(gn("gemini"))
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
    await health_store.record_success(gn("groq"), latency_ms=500.0)
    await health_store.record_success(gn("openrouter"), latency_ms=600.0)

    # Simulate Gemini cooldown expiry (happened long ago).
    now = time.time()
    await health_store._redis.set(  # type: ignore[union-attr]
        gn("gemini"),
        (
            '{"status":"cooldown","failures":1,'
            f'"last_failure":{now - 120},"cooldown_until":{now - 60},'
            f'"average_latency_ms":150.0,"last_check":{now - 60},'
            '"consecutive_failures":1,"last_success":null}'
        ),
    )

    # Verify cooldown is now expired.
    available = await health_store.is_available(gn("gemini"))
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
    await health_store.record_failure(gn("gemini"))

    # Then simulate cooldown expiry and a success.
    now = time.time()
    await health_store._redis.set(  # type: ignore[union-attr]
        gn("gemini"),
        (
            '{"status":"cooldown","failures":1,'
            f'"last_failure":{now - 120},"cooldown_until":{now - 60},'
            f'"average_latency_ms":100.0,"last_check":{now - 60},'
            '"consecutive_failures":1,"last_success":null}'
        ),
    )

    # Gemini succeeds.
    await health_store.record_success(gn("gemini"), latency_ms=100.0)

    # Now Gemini should be healthy again with consecutive_failures=0.
    health = await health_store.get_health(gn("gemini"))
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
    await health_store.record_success(gn("gemini"), latency_ms=200.0)
    await health_store.record_success(gn("groq"), latency_ms=50.0)
    await health_store.record_success(gn("openrouter"), latency_ms=100.0)

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
    await health_store.record_success(gn("gemini"), latency_ms=10.0)
    await health_store.record_failure(gn("gemini"))

    # Give Groq higher latency but healthy.
    await health_store.record_success(gn("groq"), latency_ms=200.0)

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
    await health_store.record_failure(gn("gemini"))

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
    await health_store.record_success(gn("gemini"), latency_ms=800.0)
    await health_store.record_success(gn("groq"), latency_ms=500.0)
    await health_store.record_success(gn("openrouter"), latency_ms=600.0)

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
    await health_store.record_success(gn("gemini"), latency_ms=200.0)
    await health_store.record_success(gn("groq"), latency_ms=300.0)
    await health_store.record_failure(gn("gemini"))

    available = await health_store.is_available(gn("gemini"))
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
    await health_store.record_success(gn("groq"), latency_ms=100.0)
    await health_store.record_success(gn("openrouter"), latency_ms=200.0)
    await health_store.record_failure(gn("gemini"))
    await health_store.record_failure(gn("gemini"))

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
    await health_store.record_success(gn("gemini"), latency_ms=1000.0)
    await health_store.record_success(gn("groq"), latency_ms=1000.0)
    await health_store.record_success(gn("openrouter"), latency_ms=1000.0)

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

        def pipeline(self, transaction: bool = True):  # noqa: ARG001
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
    await health_store.record_success(gn("gemini"), latency_ms=2000.0)
    await health_store.record_success(gn("groq"), latency_ms=900.0)

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
    await health_store.record_success(gn("groq"), latency_ms=500.0)

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


async def test_streaming_failover_feeds_health_store_and_reranks_next_request(
    health_store, providers
) -> None:
    """The full failover round-trip (TEST-01): a provider that fails on the
    wire is recorded as a failure in the health store, and the next request
    ranks it after the provider that actually served the stream."""
    gemini, groq, _openrouter = providers
    gemini.fail_before_output = True
    await health_store.record_success(gn("gemini"), latency_ms=10.0)
    await health_store.record_success(gn("groq"), latency_ms=100.0)
    await health_store.record_success(gn("openrouter"), latency_ms=200.0)

    router = AdaptiveProviderRouter(
        providers=providers,
        health=health_store,
        recovery_window_seconds=120,
    )

    deltas = await _collect(router.stream_generate(system="system", messages=[]))

    # Groq served the stream after Gemini failed before producing output.
    assert deltas == ["ok"]
    assert gemini.calls == 1
    assert groq.calls == 1

    # The failure was pushed into the health store; the serving provider
    # recorded a success against its own namespaced key.
    gemini_health = await health_store.get_health(gn("gemini"))
    assert gemini_health.status == "cooldown"
    assert gemini_health.consecutive_failures == 1
    groq_health = await health_store.get_health(gn("groq"))
    assert groq_health.status == "healthy"
    assert groq_health.last_success is not None

    # The next request ranks the failed provider last (failover persisted).
    ordered = await router._build_ordered_providers()
    names = [getattr(p, "name", type(p).__name__) for p in ordered]
    assert names[-1] == "gemini"
    assert names.index("groq") < names.index("gemini")


async def test_failure_backoff_doubles_cooldown_window(health_store) -> None:
    """Repeated failures extend cooldown exponentially (health tracking)."""
    await health_store.record_failure(gn("gemini"))
    first = await health_store.get_health(gn("gemini"))
    assert first.status == "cooldown"
    assert first.consecutive_failures == 1
    now = time.time()
    assert first.cooldown_until is not None
    assert 55 <= first.cooldown_until - now <= 61

    await health_store.record_failure(gn("gemini"))
    second = await health_store.get_health(gn("gemini"))
    assert second.consecutive_failures == 2
    now = time.time()
    assert second.cooldown_until is not None
    assert 115 <= second.cooldown_until - now <= 121

    # Still inside the (extended) cooldown: unavailable until it expires.
    assert await health_store.is_available(gn("gemini")) is False


async def test_health_store_fails_open_on_redis_unavailable() -> None:
    """BE-Q08: a Redis outage degrades to the healthy default, never raises."""

    class _BoomRedis:
        async def get(self, key: str) -> str | None:  # noqa: ARG001
            raise ConnectionError("redis down")

        async def set(self, key: str, value: str) -> None:  # noqa: ARG001
            raise ConnectionError("redis down")

        def pipeline(self, transaction: bool = True):  # noqa: ARG001
            raise ConnectionError("redis down")

    store = ProviderHealthStore(
        redis=_BoomRedis(),  # type: ignore[arg-type]
        cooldown_seconds=60,
        health_check_interval=300,
        latency_smoothing=0.3,
    )
    name = provider_health_name("generation", "gemini")
    health = await store.get_health(name)
    assert health.status == "healthy"

    await store.record_success(name, latency_ms=100.0)
    await store.record_failure(name)


async def test_health_store_fails_open_on_corrupt_payload() -> None:
    """BE-Q08: an unparseable JSON payload is treated as "no data"."""

    class _CorruptRedis:
        def __init__(self) -> None:
            self.store = {"ai_provider_health:generation:gemini": "{not json"}

        class _Pipe:
            def __init__(self, outer: "_CorruptRedis") -> None:
                self._outer = outer
                self._keys: list[str] = []

            def get(self, key: str) -> None:
                self._keys.append(key)

            async def execute(self) -> list[str | None]:
                return [self._outer.store.get(k) for k in self._keys]

        async def get(self, key: str) -> str | None:
            return self.store.get(key)

        async def set(self, key: str, value: str) -> None:
            self.store[key] = value

        def pipeline(self, transaction: bool = True):  # noqa: ARG001
            return self._Pipe(self)

    store = ProviderHealthStore(
        redis=_CorruptRedis(),  # type: ignore[arg-type]
        cooldown_seconds=60,
        health_check_interval=300,
        latency_smoothing=0.3,
    )
    name = provider_health_name("generation", "gemini")
    health = await store.get_health(name)
    assert health.status == "healthy"
    assert health.failures == 0


async def test_health_store_surfaces_non_redis_errors() -> None:
    """BE-Q08: programming errors surface instead of silently failing open."""

    class _BoomRedis:
        async def get(self, key: str) -> str | None:  # noqa: ARG001
            raise RuntimeError("programming bug")

        async def set(self, key: str, value: str) -> None:  # noqa: ARG001
            raise RuntimeError("programming bug")

        def pipeline(self, transaction: bool = True):  # noqa: ARG001
            raise RuntimeError("programming bug")

    store = ProviderHealthStore(
        redis=_BoomRedis(),  # type: ignore[arg-type]
        cooldown_seconds=60,
        health_check_interval=300,
        latency_smoothing=0.3,
    )
    name = provider_health_name("generation", "gemini")
    with pytest.raises(RuntimeError):
        await store.get_health(name)


# ── RAG-PERF-04: Redis health read optimization regression tests ─────────


class InstrumentedRedis:
    """Redis wrapper that counts GET operations for instrumentation.

    Individual ``get()`` calls increment ``get_count`` (used by the
    pre-pipeline read-count tests). The ``pipeline()`` path counts each
    GET command queued into the pipeline (via ``pipeline_get_count``),
    since a single pipelined round trip batches multiple GETs.
    """

    def __init__(self, store: dict[str, str]) -> None:
        self._store = store
        self.get_count = 0
        self.pipeline_get_count = 0

    class _Pipe:
        def __init__(self, outer: "InstrumentedRedis") -> None:
            self._outer = outer
            self._keys: list[str] = []

        def get(self, key: str) -> None:
            self._keys.append(key)
            self._outer.pipeline_get_count += 1

        async def execute(self) -> list[str | None]:
            return [self._outer._store.get(k) for k in self._keys]

    async def get(self, key: str) -> str | None:
        self.get_count += 1
        return self._store.get(key)

    async def set(self, key: str, value: str) -> None:
        self._store[key] = value

    def pipeline(self, transaction: bool = True):  # noqa: ARG001
        return self._Pipe(self)

    def reset_counts(self) -> None:
        self.get_count = 0
        self.pipeline_get_count = 0


@pytest.fixture
def instrumented_redis():
    store: dict[str, str] = {}
    return InstrumentedRedis(store)


@pytest.fixture
def instrumented_health_store(instrumented_redis) -> ProviderHealthStore:
    return ProviderHealthStore(
        redis=instrumented_redis,  # type: ignore[arg-type]
        cooldown_seconds=60,
        health_check_interval=300,
        latency_smoothing=0.3,
    )


@pytest.fixture
def instrumented_providers():
    return [StubProvider("gemini"), StubProvider("groq"), StubProvider("openrouter")]


async def test_redis_health_reads_reduced_from_six_to_three(
    instrumented_redis, instrumented_health_store, instrumented_providers
):
    """RAG-PERF-04: Before optimization, 3 providers × 2 reads = 6 GETs.
    After optimization: 3 provider reads batched into one pipeline round
    trip (0 individual GETs + 3 pipelined GETs)."""
    gn_prefix = "ai_provider_health:generation:"

    # Seed some health data so Redis GETs actually happen.
    for p in ["gemini", "groq", "openrouter"]:
        await instrumented_redis.set(
            f"{gn_prefix}{p}",
            '{"status":"healthy","failures":0,"last_failure":null,'
            '"cooldown_until":null,"average_latency_ms":100.0,'
            '"last_check":0.0,"consecutive_failures":0,"last_success":null}',
        )

    router = AdaptiveProviderRouter(
        providers=instrumented_providers,
        health=instrumented_health_store,
        recovery_window_seconds=120,
    )

    instrumented_redis.reset_counts()
    ordered = await router._build_ordered_providers()
    names = [getattr(p, "name", type(p).__name__) for p in ordered]

    # 0 individual GETs — all reads go through the pipelined path.
    assert instrumented_redis.get_count == 0
    # Exactly 3 GETs batched in one pipeline (one per provider).
    assert instrumented_redis.pipeline_get_count == 3
    assert len(names) == 3
    assert set(names) == {"gemini", "groq", "openrouter"}


async def test_redis_health_reads_reduced_with_cooldown_provider(
    instrumented_redis, instrumented_health_store, instrumented_providers
):
    """RAG-PERF-04: Cooldown providers still result in exactly 1 read each,
    all batched into a single pipeline round trip."""
    gn_prefix = "ai_provider_health:generation:"
    import time

    now = time.time()

    # Gemini in cooldown, others healthy.
    await instrumented_redis.set(
        f"{gn_prefix}gemini",
        '{"status":"cooldown","failures":2,'
        f'"last_failure":{now - 10},"cooldown_until":{now + 50},'
        f'"average_latency_ms":200.0,"last_check":{now},'
        f'"consecutive_failures":2,"last_success":{now - 120}'
        "}",
    )
    for p in ["groq", "openrouter"]:
        await instrumented_redis.set(
            f"{gn_prefix}{p}",
            '{"status":"healthy","failures":0,"last_failure":null,'
            '"cooldown_until":null,"average_latency_ms":100.0,'
            f'"last_check":{now},"consecutive_failures":0,"last_success":{now}'
            "}",
        )

    router = AdaptiveProviderRouter(
        providers=instrumented_providers,
        health=instrumented_health_store,
        recovery_window_seconds=120,
    )

    instrumented_redis.reset_counts()
    ordered = await router._build_ordered_providers()
    names = [getattr(p, "name", type(p).__name__) for p in ordered]

    # 0 individual GETs + 3 pipelined GETs — no extra reads for availability.
    assert instrumented_redis.get_count == 0
    assert instrumented_redis.pipeline_get_count == 3
    # Gemini is in cooldown → last.
    assert names[-1] == "gemini"


async def test_is_available_from_health_matches_is_available(health_store):
    """RAG-PERF-04: is_available_from_health() produces identical results
    to is_available() for all meaningful health states."""
    import time

    name = gn("gemini")

    # Case 1: healthy provider — both should return True.
    await health_store.record_success(name, latency_ms=100.0)
    h = await health_store.get_health(name)
    assert await health_store.is_available(name) is True
    assert health_store.is_available_from_health(h) is True

    # Case 2: cooldown provider (just failed) — both should return False.
    await health_store.record_failure(name)
    h = await health_store.get_health(name)
    assert await health_store.is_available(name) is False
    assert health_store.is_available_from_health(h) is False

    # Case 3: cooldown expired — both should return True.
    now = time.time()
    expired_state = (
        '{"status":"cooldown","failures":1,'
        f'"last_failure":{now - 120},"cooldown_until":{now - 60},'
        f'"average_latency_ms":100.0,"last_check":{now - 60},'
        '"consecutive_failures":1,"last_success":null}'
    )
    from backend.services.ai.provider_health import _health_key

    await health_store._redis.set(_health_key(name), expired_state)  # type: ignore[union-attr]
    h = await health_store.get_health(name)
    assert await health_store.is_available(name) is True
    assert health_store.is_available_from_health(h) is True

    # Case 4: stale health data (>health_check_interval) — both True.
    now2 = time.time()
    stale_state = (
        '{"status":"cooldown","failures":1,'
        f'"last_failure":{now2 - 400},"cooldown_until":{now2 + 300},'
        f'"average_latency_ms":100.0,"last_check":{now2 - 400},'
        '"consecutive_failures":1,"last_success":null}'
    )
    await health_store._redis.set(_health_key(name), stale_state)  # type: ignore[union-attr]
    h = await health_store.get_health(name)
    assert await health_store.is_available(name) is True
    assert health_store.is_available_from_health(h) is True


async def test_routing_order_unchanged_after_optimization(
    instrumented_health_store, instrumented_providers
):
    """RAG-PERF-04: Provider ordering is identical with single-read path."""
    await instrumented_health_store.record_success(gn("gemini"), latency_ms=200.0)
    await instrumented_health_store.record_success(gn("groq"), latency_ms=50.0)
    await instrumented_health_store.record_success(gn("openrouter"), latency_ms=100.0)

    router = AdaptiveProviderRouter(
        providers=instrumented_providers,
        health=instrumented_health_store,
        recovery_window_seconds=120,
    )

    ordered = await router._build_ordered_providers()
    names = [getattr(p, "name", type(p).__name__) for p in ordered]

    # Same expected order: groq(50) < openrouter(100) < gemini(200).
    assert names == ["groq", "openrouter", "gemini"]


async def test_fail_open_still_works_after_optimization(providers):
    """RAG-PERF-04: BE-Q08 fail-open semantics preserved with new method."""

    class BrokenRedis:
        async def get(self, key: str):
            raise ConnectionError("redis down")

        async def set(self, key: str, value: str) -> None:
            raise ConnectionError("redis down")

        def pipeline(self, transaction: bool = True):  # noqa: ARG001
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
    assert len(names) == 3
    assert set(names) == {"gemini", "groq", "openrouter"}


async def test_health_store_available_from_health_not_added_to_exports():
    """RAG-PERF-04: Verify is_available_from_health is a public method on ProviderHealthStore."""
    assert hasattr(ProviderHealthStore, "is_available_from_health")


# ── RAG-PERF-04: pipelined batch read (get_health_many) regression tests ──


async def test_get_health_many_returns_all_providers(health_store, fake_redis) -> None:
    """get_health_many returns a health snapshot for every requested provider."""
    await health_store.record_success(gn("gemini"), latency_ms=100.0)
    await health_store.record_success(gn("groq"), latency_ms=200.0)

    result = await health_store.get_health_many([gn("gemini"), gn("groq"), gn("openrouter")])

    assert set(result.keys()) == {gn("gemini"), gn("groq"), gn("openrouter")}
    assert result[gn("gemini")].average_latency_ms == 100.0
    assert result[gn("groq")].average_latency_ms == 200.0
    # Missing key defaults to healthy.
    assert result[gn("openrouter")].status == "healthy"
    assert result[gn("openrouter")].failures == 0


async def test_get_health_many_empty_list(health_store) -> None:
    """get_health_many([]) returns an empty dict without touching Redis."""
    result = await health_store.get_health_many([])
    assert result == {}


async def test_get_health_many_fails_open_on_pipeline_break() -> None:
    """A pipeline-level Redis failure degrades every provider to healthy default."""

    # Build a store whose Redis pipeline raises ConnectionError.
    class _BadPipe:
        def get(self, key: str) -> None:  # noqa: ARG001
            raise ConnectionError("redis down")

        async def execute(self) -> list[str | None]:
            raise ConnectionError("redis down")

    class _BadRedis:
        async def get(self, key: str) -> str | None:  # noqa: ARG001
            raise ConnectionError("redis down")

        async def set(self, key: str, value: str) -> None:  # noqa: ARG001
            raise ConnectionError("redis down")

        def pipeline(self, transaction: bool = True):  # noqa: ARG001
            return _BadPipe()

    store = ProviderHealthStore(
        redis=_BadRedis(),  # type: ignore[arg-type]
        cooldown_seconds=60,
        health_check_interval=300,
        latency_smoothing=0.3,
    )
    names = [gn("gemini"), gn("groq"), gn("openrouter")]
    result = await store.get_health_many(names)
    # Every provider degrades to the healthy default — no hard failure.
    assert set(result.keys()) == set(names)
    for h in result.values():
        assert h.status == "healthy"
        assert h.failures == 0


async def test_get_health_many_preserves_cooldown_state(
    instrumented_redis, instrumented_health_store
) -> None:
    """get_health_many preserves each provider's cooldown/health state."""
    import time

    now = time.time()
    gn_prefix = "ai_provider_health:generation:"
    await instrumented_redis.set(
        f"{gn_prefix}gemini",
        '{"status":"cooldown","failures":2,'
        f'"last_failure":{now - 10},"cooldown_until":{now + 50},'
        f'"average_latency_ms":200.0,"last_check":{now},'
        f'"consecutive_failures":2,"last_success":{now - 120}'
        "}",
    )
    await instrumented_redis.set(
        f"{gn_prefix}groq",
        '{"status":"healthy","failures":0,"last_failure":null,'
        '"cooldown_until":null,"average_latency_ms":100.0,'
        f'"last_check":{now},"consecutive_failures":0,"last_success":{now}'
        "}",
    )

    result = await instrumented_health_store.get_health_many([gn("gemini"), gn("groq")])

    assert result[gn("gemini")].status == "cooldown"
    assert result[gn("gemini")].consecutive_failures == 2
    assert result[gn("groq")].status == "healthy"


async def test_get_health_many_single_pipeline_round_trip(instrumented_redis) -> None:
    """get_health_many issues exactly one pipeline (no individual GETs)."""
    store = ProviderHealthStore(
        redis=instrumented_redis,  # type: ignore[arg-type]
        cooldown_seconds=60,
        health_check_interval=300,
        latency_smoothing=0.3,
    )
    instrumented_redis.reset_counts()
    await store.get_health_many([gn("gemini"), gn("groq"), gn("openrouter")])
    # 0 individual GETs, 3 batched in one pipeline.
    assert instrumented_redis.get_count == 0
    assert instrumented_redis.pipeline_get_count == 3


async def test_router_uses_single_pipeline_not_individual_gets(
    instrumented_redis, instrumented_health_store, instrumented_providers
) -> None:
    """The adaptive router reads provider health via one pipeline call."""
    gn_prefix = "ai_provider_health:generation:"
    await instrumented_redis.set(
        f"{gn_prefix}gemini",
        '{"status":"healthy","failures":0,"last_failure":null,'
        '"cooldown_until":null,"average_latency_ms":200.0,'
        '"last_check":0.0,"consecutive_failures":0,"last_success":null}',
    )
    await instrumented_redis.set(
        f"{gn_prefix}groq",
        '{"status":"healthy","failures":0,"last_failure":null,'
        '"cooldown_until":null,"average_latency_ms":50.0,'
        '"last_check":0.0,"consecutive_failures":0,"last_success":null}',
    )
    await instrumented_redis.set(
        f"{gn_prefix}openrouter",
        '{"status":"healthy","failures":0,"last_failure":null,'
        '"cooldown_until":null,"average_latency_ms":100.0,'
        '"last_check":0.0,"consecutive_failures":0,"last_success":null}',
    )

    router = AdaptiveProviderRouter(
        providers=instrumented_providers,
        health=instrumented_health_store,
        recovery_window_seconds=120,
    )

    instrumented_redis.reset_counts()
    ordered = await router._build_ordered_providers()
    names = [getattr(p, "name", type(p).__name__) for p in ordered]

    # Ordering unchanged: groq(50) < openrouter(100) < gemini(200).
    assert names == ["groq", "openrouter", "gemini"]
    assert instrumented_redis.get_count == 0
    assert instrumented_redis.pipeline_get_count == 3
