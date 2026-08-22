"""Regression tests for the mixed-embedding-space bug (audit BUG-1).

Ingestion must never store vectors from different embedding identities in one
website corpus: providers that agree on `EMBEDDING_DIMENSIONS` still live in
incompatible vector spaces, so a Gemini->Jina failover while storing chunks
hides one identity from every identity-filtered `$vectorSearch`. These tests
pin the fix: ingestion resolves to exactly ONE provider, a failing primary is
retried on the same provider (never switched), and exhaustion quarantines.
"""

from typing import Any

import backend.ai.registry as registry_module
import pytest
from backend.ai.registry import ProviderRegistry, build_ingestion_embedding_client
from backend.ai.router import FallbackEmbeddingClient
from backend.core.config import Settings
from backend.core.errors import EmbeddingUnavailableError, ProviderConfigurationError
from backend.services.knowledge.embedding import EmbeddingUsage


class FakeEmbeddingProvider:
    """Recording fake provider with a fixed embedding identity."""

    def __init__(
        self,
        name: str,
        *,
        fail: bool = False,
        dimensions: int = 1024,
        model: str | None = None,
    ) -> None:
        self.name = name
        self.fail = fail
        self.dimensions = dimensions
        self.model = model or f"{name}-embedding"
        self.calls = 0
        self._usage = EmbeddingUsage()

    @property
    def usage(self) -> EmbeddingUsage:
        return self._usage

    @property
    def embedding_identity(self) -> Any:
        from backend.core.embedding_identity import EmbeddingIdentity

        return EmbeddingIdentity(
            provider=self.name,
            model=self.model,
            dimensions=self.dimensions,
            version="1",
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self.fail:
            raise EmbeddingUnavailableError(f"{self.name} is unavailable")
        return [[0.1] * self.dimensions for _ in texts]


_REQUIRED_KEYS = {
    "gemini": "gemini_api_key",
    "jina": "jina_api_key",
    "cohere": "cohere_api_key",
}


def _install_registry(monkeypatch: Any, providers: list[FakeEmbeddingProvider]) -> None:
    """Swap the default registry for one serving the given fake providers.

    Providers are gated on their settings key exactly like the default
    registry, so keyless-provider skipping behaves identically.
    """
    registry = ProviderRegistry()
    for provider in providers:
        registry.register_embedding(
            provider.name,
            lambda p=provider: p,
            required_key=_REQUIRED_KEYS.get(provider.name),
        )
    monkeypatch.setattr(registry_module, "_registry", registry)


def _patch_settings(monkeypatch: Any, **overrides: Any) -> Settings:
    settings = Settings(_env_file=None, **overrides)
    monkeypatch.setattr(registry_module, "get_settings", lambda: settings)
    return settings


# ---- ingestion resolves to a single provider (no mixed identities) ----


def test_ingestion_gets_only_the_primary_provider(monkeypatch) -> None:
    """Even with a fully keyed multi-provider order, ingestion receives ONE
    provider - so no code path can ever switch its embedding space."""
    gemini = FakeEmbeddingProvider("gemini")
    jina = FakeEmbeddingProvider("jina")
    cohere = FakeEmbeddingProvider("cohere")
    _install_registry(monkeypatch, [gemini, jina, cohere])
    _patch_settings(
        monkeypatch,
        embedding_provider_order=["gemini", "jina", "cohere"],
        gemini_api_key="gk",
        jina_api_key="jk",
        cohere_api_key="ck",
    )

    client = build_ingestion_embedding_client()

    assert client is gemini
    assert not isinstance(client, FallbackEmbeddingClient)


def test_ingestion_skips_keyless_primary_but_stays_single_provider(monkeypatch) -> None:
    """A keyless primary is skipped at build time; the next available provider
    becomes THE consistent ingestion space (never a per-request choice)."""
    gemini = FakeEmbeddingProvider("gemini")
    jina = FakeEmbeddingProvider("jina")
    _install_registry(monkeypatch, [gemini, jina])
    _patch_settings(
        monkeypatch,
        embedding_provider_order=["gemini", "jina"],
        gemini_api_key=None,
        jina_api_key="jk",
    )

    client = build_ingestion_embedding_client()

    assert client is jina


def test_ingestion_without_any_available_provider_fails_fast(monkeypatch) -> None:
    """No keyed provider at all is a boot-time configuration error instead of
    a silent runtime failure mid-crawl."""
    _install_registry(monkeypatch, [FakeEmbeddingProvider("gemini")])
    _patch_settings(
        monkeypatch,
        embedding_provider_order=["gemini"],
        gemini_api_key=None,
    )

    with pytest.raises(ProviderConfigurationError, match="No embedding provider"):
        build_ingestion_embedding_client()


# ---- primary failure retries the SAME provider, never another space ----


async def test_primary_failure_never_switches_embedding_space(monkeypatch) -> None:
    """The BUG-1 scenario: the primary provider fails during ingestion. The
    fallback providers must never be called - the error surfaces so the
    document-level retry can re-run the SAME provider."""
    gemini = FakeEmbeddingProvider("gemini", fail=True)
    jina = FakeEmbeddingProvider("jina")
    _install_registry(monkeypatch, [gemini, jina])
    _patch_settings(
        monkeypatch,
        embedding_provider_order=["gemini", "jina"],
        gemini_api_key="gk",
        jina_api_key="jk",
    )

    client = build_ingestion_embedding_client()

    with pytest.raises(EmbeddingUnavailableError, match="gemini is unavailable"):
        await client.embed(["q"])

    assert gemini.calls == 1
    assert jina.calls == 0


async def test_recovered_primary_serves_with_its_own_identity(monkeypatch) -> None:
    """After a transient failure the same provider serves again; every stored
    vector therefore carries one consistent identity."""
    gemini = FakeEmbeddingProvider("gemini")

    calls = {"n": 0}

    def make_gemini() -> FakeEmbeddingProvider:
        # First embed fails (transient outage), retry succeeds: same instance,
        # same identity throughout - mirroring client/document-level retries.
        provider = gemini

        async def flaky(texts: list[str]) -> list[list[float]]:
            calls["n"] += 1
            if calls["n"] == 1:
                raise EmbeddingUnavailableError("transient outage")
            return [[0.2] * provider.dimensions for _ in texts]

        provider.embed = flaky  # type: ignore[method-assign]
        return provider

    registry = ProviderRegistry()
    registry.register_embedding("gemini", make_gemini)
    monkeypatch.setattr(registry_module, "_registry", registry)
    _patch_settings(
        monkeypatch,
        embedding_provider_order=["gemini"],
        gemini_api_key="gk",
    )

    client = build_ingestion_embedding_client()
    assert client.embedding_identity.provider == "gemini"

    with pytest.raises(EmbeddingUnavailableError):
        await client.embed(["q"])
    vectors = await client.embed(["q"])  # same-provider retry succeeds

    assert vectors == [[0.2] * 1024]
    assert client.embedding_identity == gemini.embedding_identity
