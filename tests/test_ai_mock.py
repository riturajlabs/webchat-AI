"""Tests for the Phase 12.1 deterministic mock AI providers.

The mock providers implement the same Protocols as the real Gemini/Ollama
clients but never touch the network, so they can back performance runs and
offline development. Output must be deterministic and text-hashed embeddings
must yield identical vectors for identical inputs (cosine-search signal).
"""

import backend.ai.registry as registry_module
from backend.ai.mock import MockEmbeddingClient, MockGenerationClient
from backend.ai.registry import (
    ProviderRegistry,
    build_embedding_fallback,
    build_generation_fallback,
)
from backend.ai.router import FallbackEmbeddingClient, FallbackGenerationClient
from backend.core.config import Settings


async def test_mock_generation_streams_deterministic_chunks() -> None:
    client = MockGenerationClient(words_per_chunk=4)
    chunks_a = [
        chunk async for chunk in client.stream_generate(system="s", messages=[("user", "hello")])
    ]
    chunks_b = [
        chunk async for chunk in client.stream_generate(system="s", messages=[("user", "hello")])
    ]
    assert chunks_a == chunks_b
    assert len(chunks_a) > 1
    assert all(isinstance(chunk, str) and chunk for chunk in chunks_a)
    assert client.usage.output_tokens > 0


async def test_mock_generation_answer_varies_with_prompt() -> None:
    client = MockGenerationClient()
    a = "".join(
        [chunk async for chunk in client.stream_generate(system="s", messages=[("user", "one")])]
    )
    b = "".join(
        [chunk async for chunk in client.stream_generate(system="s", messages=[("user", "two")])]
    )
    assert a != b


async def test_mock_embedding_is_deterministic_and_normalised() -> None:
    client = MockEmbeddingClient(dimensions=32)
    v1 = await client.embed(["hello world"])
    v2 = await client.embed(["hello world"])
    assert v1 == v2
    assert len(v1[0]) == 32
    norm = sum(x * x for x in v1[0]) ** 0.5
    assert round(norm, 6) == 1.0


async def test_mock_embedding_distinct_text_differs() -> None:
    client = MockEmbeddingClient(dimensions=32)
    a = await client.embed(["alpha"])
    b = await client.embed(["beta"])
    assert a[0] != b[0]


def test_mock_providers_are_registered_keyless() -> None:
    registry = ProviderRegistry()
    registry.register_generation("mock", MockGenerationClient)
    registry.register_embedding("mock", MockEmbeddingClient)
    assert "mock" in registry.generation_names()
    assert "mock" in registry.embedding_names()


def test_default_registry_includes_mock() -> None:
    assert "mock" in registry_module._registry.generation_names()
    assert "mock" in registry_module._registry.embedding_names()


def _patch_settings(monkeypatch, **overrides) -> Settings:
    settings = Settings(_env_file=None, **overrides)
    monkeypatch.setattr(registry_module, "get_settings", lambda: settings)
    return settings


def test_mock_chain_builds_without_api_key(monkeypatch) -> None:
    _patch_settings(
        monkeypatch,
        generation_provider_order=["mock"],
        embedding_provider_order=["mock"],
        gemini_api_key=None,
    )
    generation = build_generation_fallback()
    embedding = build_embedding_fallback()
    assert isinstance(generation, FallbackGenerationClient)
    assert isinstance(embedding, FallbackEmbeddingClient)
    assert generation._providers and isinstance(generation._providers[0], MockGenerationClient)
    assert embedding._providers and isinstance(embedding._providers[0], MockEmbeddingClient)
