"""Fallback-chain tests for the cloud embedding providers (ADR-009).

Verifies the end-to-end behavior required of the fallback system: when Gemini
fails, Jina is called; when Gemini and Jina both fail, Cohere is called; when
all providers fail, a clear exception surfaces. Also verifies the registry
skips keyless providers gracefully while preserving the configured order.
"""

import pytest
from backend.ai.registry import ProviderRegistry
from backend.ai.router import FallbackEmbeddingClient
from backend.core.config import Settings
from backend.core.errors import EmbeddingError, EmbeddingUnavailableError
from backend.services.knowledge.embedding import EmbeddingUsage


class FakeEmbeddingProvider:
    """Recording fake that can fail per provider name."""

    def __init__(
        self,
        name: str,
        *,
        fail: bool = False,
        dimensions: int = 1024,
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self.fail = fail
        self.dimensions = dimensions
        self.error = error
        self.calls = 0
        self._usage = EmbeddingUsage(calls=0, characters=0, estimated_tokens=0)

    @property
    def usage(self) -> EmbeddingUsage:
        return self._usage

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self.fail:
            raise self.error or EmbeddingUnavailableError(f"{self.name} is unavailable")
        return [[0.1] * self.dimensions for _ in texts]


def _patch_settings(monkeypatch, **overrides) -> Settings:
    import backend.ai.registry as registry_module

    settings = Settings(_env_file=None, **overrides)
    monkeypatch.setattr(registry_module, "get_settings", lambda: settings)
    return settings


# ---- ordered fallback scenarios ----


async def test_gemini_success_serves_alone() -> None:
    gemini = FakeEmbeddingProvider("gemini")
    jina = FakeEmbeddingProvider("jina")
    fallback = FallbackEmbeddingClient([gemini, jina])

    vectors = await fallback.embed(["one", "two"])

    assert len(vectors) == 2
    assert gemini.calls == 1
    assert jina.calls == 0
    assert fallback.active_provider == "gemini"


async def test_gemini_failure_triggers_jina() -> None:
    gemini = FakeEmbeddingProvider("gemini", fail=True)
    jina = FakeEmbeddingProvider("jina")
    cohere = FakeEmbeddingProvider("cohere")
    fallback = FallbackEmbeddingClient([gemini, jina, cohere])

    vectors = await fallback.embed(["q"])

    assert vectors == [[0.1] * 1024]
    assert gemini.calls == 1
    assert jina.calls == 1
    assert cohere.calls == 0
    assert fallback.active_provider == "jina"
    assert fallback.usage == jina.usage


async def test_gemini_and_jina_failure_triggers_cohere() -> None:
    gemini = FakeEmbeddingProvider("gemini", fail=True)
    jina = FakeEmbeddingProvider("jina", fail=True)
    cohere = FakeEmbeddingProvider("cohere")
    fallback = FallbackEmbeddingClient([gemini, jina, cohere])

    vectors = await fallback.embed(["q"])

    assert vectors == [[0.1] * 1024]
    assert gemini.calls == 1
    assert jina.calls == 1
    assert cohere.calls == 1
    assert fallback.active_provider == "cohere"


async def test_all_fail_raises_clear_error() -> None:
    gemini = FakeEmbeddingProvider("gemini", fail=True)
    jina = FakeEmbeddingProvider("jina", fail=True)
    cohere = FakeEmbeddingProvider("cohere", fail=True)
    fallback = FallbackEmbeddingClient([gemini, jina, cohere])

    with pytest.raises(EmbeddingUnavailableError, match="All embedding providers failed"):
        await fallback.embed(["q"])

    assert gemini.calls == 1
    assert jina.calls == 1
    assert cohere.calls == 1


async def test_all_fail_raises_last_provider_error() -> None:
    gemini = FakeEmbeddingProvider("gemini", fail=True)
    cohere = FakeEmbeddingProvider("cohere", fail=True, error=EmbeddingError("cohere exploded"))
    fallback = FallbackEmbeddingClient([gemini, cohere])

    with pytest.raises(EmbeddingError, match="cohere exploded"):
        await fallback.embed(["q"])


# ---- registry wiring ----


def test_registry_builds_ordered_chain_skipping_keyless(monkeypatch) -> None:
    _patch_settings(monkeypatch, gemini_api_key="gk", jina_api_key=None, cohere_api_key="ck")
    registry = ProviderRegistry()

    from backend.ai.providers.cohere import CohereEmbeddingClient
    from backend.ai.providers.jina import JinaEmbeddingClient

    registry.register_embedding("gemini", lambda: FakeEmbeddingProvider("gemini"))
    registry.register_embedding("jina", lambda: JinaEmbeddingClient(), required_key="jina_api_key")
    registry.register_embedding(
        "cohere", lambda: CohereEmbeddingClient(), required_key="cohere_api_key"
    )

    chain = registry.build_embedding_chain(["gemini", "jina", "cohere"])

    # jina is keyless -> skipped gracefully; gemini + cohere stay, in order.
    names = [getattr(p, "name", type(p).__name__) for p in chain]
    assert names == ["gemini", "cohere"]


async def test_dimension_gate_blocks_incoherent_fallback(monkeypatch) -> None:
    """A fallback whose dimension differs from the index is refused, not committed."""
    import backend.ai.router as router_module

    settings = Settings(_env_file=None, embedding_dimensions=1024)
    monkeypatch.setattr(router_module, "get_settings", lambda: settings)

    gemini = FakeEmbeddingProvider("gemini", fail=True)
    jina = FakeEmbeddingProvider("jina", dimensions=512)  # mismatched!
    fallback = FallbackEmbeddingClient([gemini, jina])

    with pytest.raises(EmbeddingError, match="dimension mismatch.*jina.*512.*1024"):
        await fallback.embed(["q"])
