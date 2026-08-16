"""Tests for the Phase 9 provider registry (ADR-009).

The registry resolves `*_PROVIDER_ORDER` into concrete clients: unknown names
fail fast with `ProviderConfigurationError`, providers whose required API key
is missing are skipped, and embedding chains warn on vector-dimension
mismatches. A fresh `Settings` is injected via monkeypatch so tests are
independent of the developer's `.env`.
"""

import logging

import backend.ai.registry as registry_module
import pytest
from backend.ai.gemini import GoogleGeminiClient
from backend.ai.providers.cohere import CohereEmbeddingClient
from backend.ai.providers.groq import GroqGenerationClient
from backend.ai.providers.jina import JinaEmbeddingClient
from backend.ai.providers.openrouter import OpenRouterGenerationClient
from backend.ai.registry import (
    ProviderRegistry,
    build_embedding_fallback,
    build_generation_fallback,
)
from backend.ai.router import FallbackEmbeddingClient, FallbackGenerationClient
from backend.core.config import Settings
from backend.core.errors import ProviderConfigurationError
from backend.services.knowledge.embedding import GoogleEmbeddingClient


def _patch_settings(monkeypatch, **overrides) -> Settings:
    settings = Settings(_env_file=None, **overrides)
    monkeypatch.setattr(registry_module, "get_settings", lambda: settings)
    return settings


# ---- default registry ----


def test_default_registry_registers_builtin_providers() -> None:
    registry = registry_module._registry
    assert {"gemini", "groq", "openrouter"} <= set(registry.generation_names())
    assert {"gemini", "jina", "cohere"} <= set(registry.embedding_names())


def test_build_generation_chain_resolves_configured_providers(monkeypatch) -> None:
    _patch_settings(monkeypatch, gemini_api_key="k")
    chain = registry_module._registry.build_generation_chain(["gemini"])
    assert len(chain) == 1
    assert isinstance(chain[0], GoogleGeminiClient)


def test_build_generation_chain_skips_missing_key(monkeypatch) -> None:
    _patch_settings(monkeypatch, gemini_api_key=None, groq_api_key=None)
    chain = registry_module._registry.build_generation_chain(["gemini", "groq"])
    assert chain == []


def test_build_generation_chain_filters_keyed_providers(monkeypatch) -> None:
    _patch_settings(monkeypatch, gemini_api_key=None, groq_api_key="gk")
    chain = registry_module._registry.build_generation_chain(["gemini", "groq", "openrouter"])
    assert len(chain) == 1
    assert isinstance(chain[0], GroqGenerationClient)


def test_build_generation_chain_unknown_provider_raises(monkeypatch) -> None:
    _patch_settings(monkeypatch, gemini_api_key="k")
    with pytest.raises(ProviderConfigurationError, match="Unknown generation provider"):
        registry_module._registry.build_generation_chain(["gemini", "nope"])


def test_build_embedding_chain_resolves_configured_providers(monkeypatch) -> None:
    _patch_settings(monkeypatch, gemini_api_key="k")
    chain = registry_module._registry.build_embedding_chain(["gemini"])
    assert len(chain) == 1
    assert isinstance(chain[0], GoogleEmbeddingClient)


def test_build_embedding_chain_includes_keyed_jina_and_cohere(monkeypatch) -> None:
    _patch_settings(monkeypatch, jina_api_key="jk", cohere_api_key="ck")
    chain = registry_module._registry.build_embedding_chain(["jina", "cohere"])
    assert len(chain) == 2
    assert isinstance(chain[0], JinaEmbeddingClient)
    assert isinstance(chain[1], CohereEmbeddingClient)


def test_build_embedding_chain_skips_keyless_fallback(monkeypatch) -> None:
    # gemini has a key; jina/cohere do not -> they are skipped gracefully and
    # the chain still resolves to gemini (missing key must not crash the app).
    _patch_settings(monkeypatch, gemini_api_key="gk", jina_api_key=None, cohere_api_key=None)
    chain = registry_module._registry.build_embedding_chain(["gemini", "jina", "cohere"])
    assert len(chain) == 1
    assert isinstance(chain[0], GoogleEmbeddingClient)


def test_build_embedding_chain_unknown_provider_raises(monkeypatch) -> None:
    _patch_settings(monkeypatch, gemini_api_key="k")
    with pytest.raises(ProviderConfigurationError, match="Unknown embedding provider"):
        registry_module._registry.build_embedding_chain(["gemini", "nope"])


# ---- builder helpers ----


def test_build_generation_fallback_respects_order(monkeypatch) -> None:
    _patch_settings(
        monkeypatch,
        generation_provider_order=["groq", "openrouter"],
        groq_api_key="gk",
        openrouter_api_key="ok",
    )
    fallback = build_generation_fallback()
    assert isinstance(fallback, FallbackGenerationClient)
    assert fallback._providers and isinstance(fallback._providers[0], GroqGenerationClient)
    assert isinstance(fallback._providers[1], OpenRouterGenerationClient)


def test_build_embedding_fallback_returns_fallback_client(monkeypatch) -> None:
    _patch_settings(monkeypatch, gemini_api_key="k")
    fallback = build_embedding_fallback()
    assert isinstance(fallback, FallbackEmbeddingClient)


def test_build_embedding_chain_forwards_retry_override(monkeypatch) -> None:
    """`max_retries` is forwarded to providers that accept it (the retry-capable
    Gemini client) and ignored by providers that do not (jina/cohere), so the
    chat path can stay fail-fast without changing provider defaults."""
    _patch_settings(monkeypatch, gemini_api_key="gk", jina_api_key="jk", cohere_api_key="ck")
    chain = registry_module._registry.build_embedding_chain(
        ["gemini", "jina", "cohere"], max_retries=1
    )
    assert isinstance(chain[0], GoogleEmbeddingClient)
    assert chain[0]._max_retries == 1
    assert isinstance(chain[1], JinaEmbeddingClient)
    assert isinstance(chain[2], CohereEmbeddingClient)


def test_build_embedding_fallback_forwards_retry_override(monkeypatch) -> None:
    _patch_settings(monkeypatch, gemini_api_key="k")
    fallback = build_embedding_fallback(max_retries=1)
    assert isinstance(fallback, FallbackEmbeddingClient)
    primary = fallback._providers[0]
    assert isinstance(primary, GoogleEmbeddingClient)
    assert primary._max_retries == 1


def test_build_generation_fallback_empty_when_no_keys(monkeypatch) -> None:
    _patch_settings(monkeypatch, gemini_api_key=None, groq_api_key=None, openrouter_api_key=None)
    assert build_generation_fallback()._providers == []


# ---- dimension mismatch warning ----


class _FakeEmbedding:
    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dimensions for _ in texts]


def test_embedding_chain_warns_on_dimension_mismatch(caplog) -> None:
    registry = ProviderRegistry()
    registry.register_embedding("gemini", lambda: _FakeEmbedding(3072))
    registry.register_embedding("jina", lambda: _FakeEmbedding(768))

    with caplog.at_level(logging.WARNING, logger="webchat_ai"):
        chain = registry.build_embedding_chain(["gemini", "jina"])

    assert len(chain) == 2
    assert "differing vector dimensions" in caplog.text


def test_embedding_chain_silent_on_matching_dimensions(caplog) -> None:
    registry = ProviderRegistry()
    registry.register_embedding("a", lambda: _FakeEmbedding(3072))
    registry.register_embedding("b", lambda: _FakeEmbedding(3072))

    with caplog.at_level(logging.WARNING, logger="webchat_ai"):
        chain = registry.build_embedding_chain(["a", "b"])

    assert len(chain) == 2
    assert "differing vector dimensions" not in caplog.text


# ---- custom registration ----


def test_registry_supports_custom_providers() -> None:
    registry = ProviderRegistry()
    registry.register_generation("custom", lambda: GoogleGeminiClient())
    registry.register_embedding("custom", lambda: GoogleEmbeddingClient())
    assert registry.generation_names() == ["custom"]
    assert registry.embedding_names() == ["custom"]
