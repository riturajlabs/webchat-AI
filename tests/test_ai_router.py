"""Tests for the Phase 9 fallback router (ADR-009).

`FallbackGenerationClient`/`FallbackEmbeddingClient` wrap provider sequences;
they must keep the existing `GenerationClient`/`EmbeddingClient` Protocol
surfaces while adding: ordered fallback, pre-stream-only generation fallback
(no mid-stream restart), usage of the serving provider, `active_provider`
observability, and - for embeddings - a dimension gate that refuses to commit
vectors whose length differs from `EMBEDDING_DIMENSIONS`.
"""

import logging

import pytest
from backend.ai.gemini import GenerationUsage
from backend.ai.router import FallbackEmbeddingClient, FallbackGenerationClient
from backend.core.config import Settings
from backend.core.errors import (
    EmbeddingError,
    EmbeddingUnavailableError,
    GenerationError,
    GenerationUnavailableError,
)
from backend.services.knowledge.embedding import EmbeddingUsage


@pytest.fixture(autouse=True)
def embedding_settings(monkeypatch) -> Settings:
    """Fix the index dimension to match the stub vectors (2-dim).

    The router's embedding gate reads `EMBEDDING_DIMENSIONS` at call time; the
    stub vectors below are 2-dimensional, so a matching settings object keeps
    the fallback tests focused on fallback behavior rather than dimensions.
    """
    import backend.ai.router as router_module

    settings = Settings(_env_file=None, embedding_dimensions=2)
    monkeypatch.setattr(router_module, "get_settings", lambda: settings)
    return settings


class StubGenerationClient:
    """Canned generation client. `raise_before` fails the whole stream up
    front; `raise_after` emits all deltas, then fails (mid-stream failure)."""

    def __init__(
        self,
        *,
        name: str,
        deltas: tuple[str, ...] = ("hello",),
        raise_before: Exception | None = None,
        raise_after: Exception | None = None,
        usage: GenerationUsage | None = None,
    ) -> None:
        self.name = name
        self.deltas = deltas
        self.raise_before = raise_before
        self.raise_after = raise_after
        self.calls = 0
        self._usage = (
            usage if usage is not None else GenerationUsage(input_tokens=3, output_tokens=4)
        )

    @property
    def usage(self) -> GenerationUsage:
        return self._usage

    async def stream_generate(self, *, system: str, messages: list[tuple[str, str]]):
        self.calls += 1
        if self.raise_before is not None:
            raise self.raise_before
        for delta in self.deltas:
            yield delta
        if self.raise_after is not None:
            raise self.raise_after


class StubEmbeddingClient:
    def __init__(
        self,
        *,
        name: str,
        vector: tuple[float, ...] = (0.1, 0.2),
        raise_error: Exception | None = None,
        usage: EmbeddingUsage | None = None,
    ) -> None:
        self.name = name
        self.vector = vector
        self.raise_error = raise_error
        self.calls = 0
        self._usage = (
            usage
            if usage is not None
            else EmbeddingUsage(calls=1, characters=5, estimated_tokens=2)
        )

    @property
    def usage(self) -> EmbeddingUsage:
        return self._usage

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self.raise_error is not None:
            raise self.raise_error
        return [list(self.vector) for _ in texts]


async def _collect(stream) -> list[str]:
    return [delta async for delta in stream]


# ---- FallbackGenerationClient ----


async def test_generation_uses_first_provider_and_skips_rest() -> None:
    first = StubGenerationClient(name="first", deltas=("a", "b"))
    second = StubGenerationClient(name="second")
    fallback = FallbackGenerationClient([first, second])

    assert await _collect(fallback.stream_generate(system="s", messages=[("user", "q")])) == [
        "a",
        "b",
    ]
    assert first.calls == 1
    assert second.calls == 0
    assert fallback.active_provider == "first"
    assert fallback.usage == first.usage


async def test_generation_falls_back_when_first_fails_before_output() -> None:
    first = StubGenerationClient(
        name="first", raise_before=GenerationUnavailableError("primary down")
    )
    second = StubGenerationClient(name="second", deltas=("fallback answer",))
    fallback = FallbackGenerationClient([first, second])

    assert await _collect(fallback.stream_generate(system="s", messages=[("user", "q")])) == [
        "fallback answer"
    ]
    assert first.calls == 1
    assert second.calls == 1
    assert fallback.active_provider == "second"
    assert fallback.usage == second.usage


async def test_generation_never_falls_back_after_output_starts() -> None:
    first = StubGenerationClient(
        name="first", deltas=("partial",), raise_after=GenerationError("mid-stream boom")
    )
    second = StubGenerationClient(name="second")
    fallback = FallbackGenerationClient([first, second])

    deltas: list[str] = []
    with pytest.raises(GenerationError, match="mid-stream"):
        async for delta in fallback.stream_generate(system="s", messages=[("user", "q")]):
            deltas.append(delta)

    assert deltas == ["partial"]
    assert second.calls == 0
    assert fallback.active_provider == "first"


async def test_generation_raises_last_error_when_all_fail() -> None:
    first = StubGenerationClient(name="first", raise_before=GenerationUnavailableError("a"))
    second = StubGenerationClient(name="second", raise_before=GenerationError("b"))
    fallback = FallbackGenerationClient([first, second])

    with pytest.raises(GenerationError, match="b"):
        async for _ in fallback.stream_generate(system="s", messages=[("user", "q")]):
            pass


async def test_generation_empty_chain_raises_unavailable() -> None:
    fallback = FallbackGenerationClient([])

    with pytest.raises(GenerationUnavailableError):
        async for _ in fallback.stream_generate(system="s", messages=[("user", "q")]):
            pass


async def test_generation_non_normalized_error_propagates_without_fallback() -> None:
    first = StubGenerationClient(name="first", raise_before=RuntimeError("internal bug"))
    second = StubGenerationClient(name="second")
    fallback = FallbackGenerationClient([first, second])

    with pytest.raises(RuntimeError, match="internal bug"):
        async for _ in fallback.stream_generate(system="s", messages=[("user", "q")]):
            pass
    assert second.calls == 0


async def test_generation_active_provider_starts_unset() -> None:
    fallback = FallbackGenerationClient([StubGenerationClient(name="first")])
    assert fallback.active_provider is None


# ---- FallbackEmbeddingClient ----


async def test_embedding_uses_first_provider_and_skips_rest() -> None:
    first = StubEmbeddingClient(name="first", vector=(0.5, 0.5))
    second = StubEmbeddingClient(name="second")
    fallback = FallbackEmbeddingClient([first, second])

    assert await fallback.embed(["q"]) == [[0.5, 0.5]]
    assert first.calls == 1
    assert second.calls == 0
    assert fallback.active_provider == "first"
    assert fallback.usage == first.usage


async def test_embedding_falls_back_on_first_failure() -> None:
    first = StubEmbeddingClient(name="first", raise_error=EmbeddingUnavailableError("down"))
    second = StubEmbeddingClient(name="second", vector=(0.7, 0.7))
    fallback = FallbackEmbeddingClient([first, second])

    assert await fallback.embed(["q"]) == [[0.7, 0.7]]
    assert fallback.active_provider == "second"
    assert fallback.usage == second.usage


async def test_embedding_raises_last_error_when_all_fail() -> None:
    first = StubEmbeddingClient(name="first", raise_error=EmbeddingUnavailableError("a"))
    second = StubEmbeddingClient(name="second", raise_error=EmbeddingError("b"))
    fallback = FallbackEmbeddingClient([first, second])

    with pytest.raises(EmbeddingError, match="b"):
        await fallback.embed(["q"])


async def test_embedding_empty_chain_raises_unavailable() -> None:
    fallback = FallbackEmbeddingClient([])

    with pytest.raises(EmbeddingUnavailableError):
        await fallback.embed(["q"])


async def test_embedding_non_normalized_error_propagates_without_fallback() -> None:
    first = StubEmbeddingClient(name="first", raise_error=RuntimeError("internal bug"))
    second = StubEmbeddingClient(name="second")
    fallback = FallbackEmbeddingClient([first, second])

    with pytest.raises(RuntimeError, match="internal bug"):
        await fallback.embed(["q"])
    assert second.calls == 0


async def test_embedding_dimension_gate_rejects_mismatched_vectors() -> None:
    first = StubEmbeddingClient(name="gemini", vector=(0.1, 0.2, 0.3))
    second = StubEmbeddingClient(name="jina", vector=(0.4, 0.5))
    fallback = FallbackEmbeddingClient([first, second])

    # The primary succeeded but returned 3-dim vectors while the index expects
    # 2: this must NOT fall through to jina or commit anything.
    with pytest.raises(EmbeddingError, match="dimension mismatch.*gemini.*3.*2"):
        await fallback.embed(["q"])
    assert second.calls == 0
    assert fallback.active_provider is None


async def test_embedding_logs_selected_provider(caplog) -> None:
    first = StubEmbeddingClient(name="gemini", vector=(0.5, 0.5))
    fallback = FallbackEmbeddingClient([first])

    with caplog.at_level(logging.INFO, logger="webchat_ai"):
        await fallback.embed(["q"])

    assert "Embedding provider selected: gemini" in caplog.text


async def test_embedding_logs_switch_and_all_failed(caplog) -> None:
    first = StubEmbeddingClient(name="gemini", raise_error=EmbeddingUnavailableError("down"))
    second = StubEmbeddingClient(name="jina", raise_error=EmbeddingUnavailableError("down"))
    fallback = FallbackEmbeddingClient([first, second])

    with caplog.at_level(logging.WARNING, logger="webchat_ai"):
        with pytest.raises(EmbeddingUnavailableError):
            await fallback.embed(["q"])

    assert "gemini embedding failed" in caplog.text
    assert "switching to jina" in caplog.text
    assert "no providers left" in caplog.text
    assert "All embedding providers failed" in caplog.text


# ---- Provider latency metrics (Phase 3 Step 2) ----


async def test_generation_latency_metrics_are_tracked() -> None:
    """Provider latency metrics are captured for the most recent request."""
    first = StubGenerationClient(name="gemini", deltas=("hello",))
    fallback = FallbackGenerationClient([first])

    assert fallback.last_latency_metrics is None

    deltas = []
    async for delta in fallback.stream_generate(system="s", messages=[("user", "q")]):
        deltas.append(delta)

    metrics = fallback.last_latency_metrics
    assert metrics is not None
    assert metrics.provider == "gemini"
    assert metrics.success is True
    assert metrics.first_token_latency_ms is not None
    assert metrics.first_token_latency_ms >= 0
    assert metrics.total_generation_latency_ms >= 0
    assert metrics.fallback_attempts == 0
    assert metrics.input_tokens == 3
    assert metrics.output_tokens == 4


async def test_generation_latency_metrics_on_fallback() -> None:
    """Latency metrics track fallback attempts when primary fails."""
    first = StubGenerationClient(
        name="gemini", raise_before=GenerationUnavailableError("down")
    )
    second = StubGenerationClient(name="groq", deltas=("fallback",))
    fallback = FallbackGenerationClient([first, second])

    deltas = []
    async for delta in fallback.stream_generate(system="s", messages=[("user", "q")]):
        deltas.append(delta)

    metrics = fallback.last_latency_metrics
    assert metrics is not None
    assert metrics.provider == "groq"
    assert metrics.success is True
    assert metrics.fallback_attempts == 1
    assert metrics.first_token_latency_ms is not None


async def test_generation_latency_metrics_on_failure() -> None:
    """Latency metrics capture failure state when all providers fail."""
    first = StubGenerationClient(
        name="gemini", raise_before=GenerationUnavailableError("down")
    )
    second = StubGenerationClient(
        name="groq", raise_before=GenerationUnavailableError("also down")
    )
    fallback = FallbackGenerationClient([first, second])

    with pytest.raises(GenerationUnavailableError):
        async for _ in fallback.stream_generate(system="s", messages=[("user", "q")]):
            pass

    metrics = fallback.last_latency_metrics
    assert metrics is not None
    assert metrics.success is False
    assert metrics.fallback_attempts == 2
    assert metrics.error is not None


async def test_generation_latency_metrics_empty_chain() -> None:
    """Latency metrics are set when all providers fail with an empty chain."""
    fallback = FallbackGenerationClient([])

    with pytest.raises(GenerationUnavailableError):
        async for _ in fallback.stream_generate(system="s", messages=[("user", "q")]):
            pass

    metrics = fallback.last_latency_metrics
    assert metrics is not None
    assert metrics.success is False
    assert metrics.fallback_attempts == 0
    assert metrics.error is not None
