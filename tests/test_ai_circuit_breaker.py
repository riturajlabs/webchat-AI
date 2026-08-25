"""Phase 4 per-provider circuit-breaker tests.

Required coverage:
- provider failures open the circuit;
- the cooldown allows exactly one probe request (HALF_OPEN);
- a successful probe closes the circuit;
- the fallback chain keeps serving answers while a provider is open;
- AI_CIRCUIT_BREAKER_ENABLED=false preserves the pre-Phase-4 behaviour.

Breaker state is process-global by design (chains are rebuilt per request);
`tests/conftest.py` resets it between tests.
"""

import logging

import pytest
from backend.ai import circuit_breaker
from backend.ai.circuit_breaker import (
    ROLE_EMBEDDING,
    ROLE_GENERATION,
    CircuitState,
    allow_provider,
    circuit_snapshot,
    record_provider_failure,
    record_provider_success,
)
from backend.ai.gemini import GenerationUsage
from backend.ai.router import FallbackEmbeddingClient, FallbackGenerationClient
from backend.core.config import Settings
from backend.core.errors import (
    EmbeddingUnavailableError,
    GenerationUnavailableError,
)
from backend.services.knowledge.embedding import EmbeddingUsage


class _Clock:
    """Controllable monotonic clock swapped in for ``_monotonic``."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    clock = _Clock()
    monkeypatch.setattr(circuit_breaker, "_monotonic", clock)
    return clock


@pytest.fixture(autouse=True)
def embedding_dimensions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fix the index dimension to the stub vectors (2-dim), like test_ai_router."""
    import backend.ai.router as router_module

    settings = Settings(_env_file=None, embedding_dimensions=2)
    monkeypatch.setattr(router_module, "get_settings", lambda: settings)


def _breaker_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    enabled: bool = True,
    threshold: int = 3,
    cooldown: float = 30.0,
) -> None:
    """Point the breaker module's ``get_settings`` at an explicit Settings."""
    settings = Settings(
        _env_file=None,
        ai_circuit_breaker_enabled=enabled,
        ai_circuit_failure_threshold=threshold,
        ai_circuit_cooldown_seconds=cooldown,
    )
    monkeypatch.setattr(circuit_breaker, "get_settings", lambda: settings)


class StubGenerationClient:
    """Minimal GenerationClient double (same shape as test_ai_router's)."""

    def __init__(
        self,
        *,
        name: str,
        deltas: tuple[str, ...] = ("hello",),
        fail_before: bool = False,
        model_name: str | None = None,
    ) -> None:
        self.name = name
        self.deltas = deltas
        self.fail_before = fail_before
        self.model_name = model_name
        self.calls = 0
        self._usage = GenerationUsage(input_tokens=1, output_tokens=1)

    @property
    def usage(self) -> GenerationUsage:
        return self._usage

    async def stream_generate(self, *, system: str, messages: list[tuple[str, str]]):
        self.calls += 1
        if self.fail_before:
            raise GenerationUnavailableError(f"{self.name} down")
        for delta in self.deltas:
            yield delta


class StubEmbeddingClient:
    def __init__(self, *, name: str, fail: bool = False) -> None:
        self.name = name
        self.fail = fail
        self.calls = 0
        self._usage = EmbeddingUsage(calls=1, characters=5, estimated_tokens=2)

    @property
    def usage(self) -> EmbeddingUsage:
        return self._usage

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self.fail:
            raise EmbeddingUnavailableError(f"{self.name} down")
        return [[0.1, 0.2] for _ in texts]


async def _collect(stream) -> list[str]:
    return [delta async for delta in stream]


# ---------------------------------------------------------------------------
# Breaker unit behaviour
# ---------------------------------------------------------------------------


def test_consecutive_failures_open_circuit(clock: _Clock, monkeypatch) -> None:
    _breaker_settings(monkeypatch, threshold=2)
    assert allow_provider(ROLE_GENERATION, "p1") is True
    record_provider_failure(ROLE_GENERATION, "p1")
    # Below threshold: still allowed.
    assert allow_provider(ROLE_GENERATION, "p1") is True
    record_provider_failure(ROLE_GENERATION, "p1")
    # Threshold reached: circuit is open, provider skipped.
    assert allow_provider(ROLE_GENERATION, "p1") is False
    snapshot = circuit_snapshot()[f"{ROLE_GENERATION}:p1"]
    assert snapshot["state"] == CircuitState.OPEN


def test_cooldown_elapses_into_single_half_open_probe(clock: _Clock, monkeypatch) -> None:
    _breaker_settings(monkeypatch, threshold=1, cooldown=30.0)
    record_provider_failure(ROLE_GENERATION, "p1")
    assert allow_provider(ROLE_GENERATION, "p1") is False
    clock.advance(29.9)
    assert allow_provider(ROLE_GENERATION, "p1") is False
    clock.advance(0.1)  # cooldown fully elapsed
    # Exactly ONE probe request is allowed...
    assert allow_provider(ROLE_GENERATION, "p1") is True
    # ...concurrent callers during the probe are still skipped.
    assert allow_provider(ROLE_GENERATION, "p1") is False


def test_successful_probe_closes_circuit(clock: _Clock, monkeypatch) -> None:
    _breaker_settings(monkeypatch, threshold=1, cooldown=30.0)
    record_provider_failure(ROLE_GENERATION, "p1")
    clock.advance(30.0)
    assert allow_provider(ROLE_GENERATION, "p1") is True  # probe starts
    record_provider_success(ROLE_GENERATION, "p1")
    assert circuit_snapshot()[f"{ROLE_GENERATION}:p1"]["state"] == CircuitState.CLOSED
    # Closed circuits allow everything again and failures start from zero.
    assert allow_provider(ROLE_GENERATION, "p1") is True
    assert circuit_snapshot()[f"{ROLE_GENERATION}:p1"]["consecutive_failures"] == 0


def test_failed_probe_reopens_circuit_with_fresh_cooldown(clock: _Clock, monkeypatch) -> None:
    _breaker_settings(monkeypatch, threshold=3, cooldown=30.0)
    for _ in range(3):
        record_provider_failure(ROLE_GENERATION, "p1")
    clock.advance(30.0)
    assert allow_provider(ROLE_GENERATION, "p1") is True  # probe
    record_provider_failure(ROLE_GENERATION, "p1")
    assert circuit_snapshot()[f"{ROLE_GENERATION}:p1"]["state"] == CircuitState.OPEN
    # Reopened: needs a FULL fresh cooldown before the next probe.
    clock.advance(29.0)
    assert allow_provider(ROLE_GENERATION, "p1") is False
    clock.advance(1.0)
    assert allow_provider(ROLE_GENERATION, "p1") is True


def test_stalled_half_open_probe_rearms_after_another_cooldown(clock: _Clock, monkeypatch) -> None:
    """A probe whose result was never recorded cannot wedge the circuit."""
    _breaker_settings(monkeypatch, threshold=1, cooldown=30.0)
    record_provider_failure(ROLE_GENERATION, "p1")
    clock.advance(30.0)
    assert allow_provider(ROLE_GENERATION, "p1") is True  # probe lost mid-flight
    assert allow_provider(ROLE_GENERATION, "p1") is False
    clock.advance(30.0)  # probe never resolved; re-arm after a full window
    assert allow_provider(ROLE_GENERATION, "p1") is True


def test_generation_and_embedding_circuits_are_isolated(clock: _Clock, monkeypatch) -> None:
    _breaker_settings(monkeypatch, threshold=1)
    for _ in range(3):
        record_provider_failure(ROLE_GENERATION, "gemini")
    # Generation is open for this provider...
    assert allow_provider(ROLE_GENERATION, "gemini") is False
    # ...but embeddings of the same vendor keep working (retrieval must not
    # degrade just because generation does).
    assert allow_provider(ROLE_EMBEDDING, "gemini") is True


def test_disabled_flag_ignores_failures(clock: _Clock, monkeypatch) -> None:
    _breaker_settings(monkeypatch, enabled=False, threshold=1)
    for _ in range(10):
        record_provider_failure(ROLE_GENERATION, "p1")
    assert allow_provider(ROLE_GENERATION, "p1") is True
    assert circuit_snapshot() == {}


# ---------------------------------------------------------------------------
# Integration with the fallback chains
# ---------------------------------------------------------------------------


async def test_generation_fallback_serves_while_primary_circuit_opens(
    clock: _Clock,
) -> None:
    """Default settings: 3rd consecutive failure opens; fallback keeps working."""
    primary = StubGenerationClient(name="gemini", fail_before=True)
    secondary = StubGenerationClient(name="groq", deltas=("ok",), model_name="llama-3.3")
    fallback = FallbackGenerationClient([primary, secondary])

    for _ in range(3):
        assert await _collect(fallback.stream_generate(system="s", messages=[])) == ["ok"]
    assert primary.calls == 3  # tried every time until the circuit opened
    assert fallback.active_provider == "groq"

    # 4th request: primary is now circuit-skipped without a network call.
    assert await _collect(fallback.stream_generate(system="s", messages=[])) == ["ok"]
    assert primary.calls == 3
    assert secondary.calls == 4
    metrics = fallback.last_latency_metrics
    assert metrics is not None
    assert metrics.success is True
    assert metrics.skipped_providers == ("gemini",)
    assert metrics.failed_providers == ()
    # active_provider/active_model/usage tracking is untouched by skipping.
    assert fallback.active_provider == "groq"
    assert fallback.active_model == "llama-3.3"
    assert fallback.usage == secondary.usage


async def test_all_generation_providers_skipped_raises_unavailable(
    clock: _Clock,
) -> None:
    fallback = FallbackGenerationClient([StubGenerationClient(name="solo", fail_before=True)])
    for _ in range(3):
        with pytest.raises(GenerationUnavailableError, match="solo down"):
            await _collect(fallback.stream_generate(system="s", messages=[]))
    with pytest.raises(GenerationUnavailableError, match="circuits open"):
        await _collect(fallback.stream_generate(system="s", messages=[]))
    metrics = fallback.last_latency_metrics
    assert metrics is not None
    assert metrics.skipped_providers == ("solo",)


async def test_generation_circuit_recovers_via_probe_success(clock: _Clock) -> None:
    recovered = StubGenerationClient(name="heals", deltas=("back",))
    fallback = FallbackGenerationClient([recovered])
    for _ in range(3):
        recovered.fail_before = True
        with pytest.raises(GenerationUnavailableError):
            await _collect(fallback.stream_generate(system="s", messages=[]))
    recovered.fail_before = False
    # Still open before the cooldown elapses: skipped without an attempt
    # (3 failed attempts from the warmup + 0 for the skipped request).
    with pytest.raises(GenerationUnavailableError, match="circuits open"):
        await _collect(fallback.stream_generate(system="s", messages=[]))
    assert recovered.calls == 3
    clock.advance(30.0)
    # Cooldown over: the probe goes through and its success closes the circuit.
    assert await _collect(fallback.stream_generate(system="s", messages=[])) == ["back"]
    assert recovered.calls == 4
    assert circuit_snapshot()[f"{ROLE_GENERATION}:heals"]["state"] == CircuitState.CLOSED
    # Closed: subsequent requests try the provider normally.
    assert await _collect(fallback.stream_generate(system="s", messages=[])) == ["back"]
    assert recovered.calls == 5


async def test_embedding_circuit_skips_failed_provider(clock: _Clock) -> None:
    flaky = StubEmbeddingClient(name="jina", fail=True)
    healthy = StubEmbeddingClient(name="cohere")
    fallback = FallbackEmbeddingClient([flaky, healthy])
    for _ in range(3):
        assert await fallback.embed(["q"]) == [[0.1, 0.2]]
    assert flaky.calls == 3
    assert await fallback.embed(["q"]) == [[0.1, 0.2]]
    # Open circuit: jina is skipped entirely, cohere serves.
    assert flaky.calls == 3
    assert healthy.calls == 4
    assert fallback.active_provider == "cohere"


async def test_disabled_flag_keeps_trying_provider_every_time(monkeypatch, clock: _Clock) -> None:
    _breaker_settings(monkeypatch, enabled=False)
    primary = StubGenerationClient(name="flaky-primary", fail_before=True)
    secondary = StubGenerationClient(name="backup", deltas=("ok",))
    fallback = FallbackGenerationClient([primary, secondary])
    for _ in range(5):
        assert await _collect(fallback.stream_generate(system="s", messages=[])) == ["ok"]
    # Old behaviour preserved: the failing provider is attempted every time.
    assert primary.calls == 5
    assert secondary.calls == 5
    metrics = fallback.last_latency_metrics
    assert metrics is not None
    assert metrics.skipped_providers == ()


def test_circuit_transitions_are_logged(clock: _Clock, monkeypatch, caplog) -> None:
    _breaker_settings(monkeypatch, threshold=1)
    with caplog.at_level(logging.INFO, logger="webchat_ai"):
        record_provider_failure(ROLE_GENERATION, "logged-out")
        assert "ai_circuit_opened" in caplog.text
        clock.advance(30.0)
        assert allow_provider(ROLE_GENERATION, "logged-out") is True
        assert "ai_circuit_half_open" in caplog.text
        record_provider_success(ROLE_GENERATION, "logged-out")
        assert "ai_circuit_closed" in caplog.text


async def test_circuit_skip_and_transition_logs_emitted(clock: _Clock, caplog) -> None:
    primary = StubGenerationClient(name="loud", fail_before=True)
    fallback = FallbackGenerationClient([primary])
    with caplog.at_level(logging.WARNING, logger="webchat_ai"):
        for _ in range(3):
            with pytest.raises(GenerationUnavailableError):
                await _collect(fallback.stream_generate(system="s", messages=[]))
        with pytest.raises(GenerationUnavailableError, match="circuits open"):
            await _collect(fallback.stream_generate(system="s", messages=[]))

    assert "ai_circuit_opened" in caplog.text
    assert "ai_circuit_skipped" in caplog.text
