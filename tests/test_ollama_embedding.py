"""Tests for the Phase 9 Ollama embedding provider (ADR-009).

Exercised through `httpx.MockTransport`; the client is a self-hosted fallback,
so it needs no API key and only a base URL + model.
"""

import json

import httpx
import pytest
from backend.ai.providers.ollama import OllamaEmbeddingClient
from backend.core.errors import EmbeddingError, EmbeddingUnavailableError
from backend.services.knowledge.embedding import EmbeddingUsage


def _provider(client: httpx.AsyncClient) -> OllamaEmbeddingClient:
    return OllamaEmbeddingClient(
        model="nomic-embed-text",
        base_url="http://localhost:11434",
        timeout_seconds=5,
        http_client=client,
    )


async def test_embeds_texts_in_order() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "nomic-embed-text",
                "embeddings": [[0.1, 0.2], [0.3, 0.4]],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        vectors = await provider.embed(["one", "two"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert captured[0]["model"] == "nomic-embed-text"
    assert captured[0]["input"] == ["one", "two"]
    assert provider.usage.calls == 1
    assert provider.usage.characters == len("one") + len("two")
    assert provider.usage.estimated_tokens > 0


async def test_empty_input_skips_request() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"embeddings": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        assert await provider.embed([]) == []
    assert called is False


async def test_vector_count_mismatch_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2]]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        with pytest.raises(EmbeddingError, match="1 vectors for 2 texts"):
            await provider.embed(["a", "b"])


@pytest.mark.parametrize("status", [401, 403, 429])
async def test_http_status_maps_to_unavailable(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="{}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        with pytest.raises(EmbeddingUnavailableError):
            await provider.embed(["q"])


async def test_http_500_maps_to_embedding_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        with pytest.raises(EmbeddingError):
            await provider.embed(["q"])


async def test_transport_error_maps_to_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        with pytest.raises(EmbeddingUnavailableError, match="unreachable"):
            await provider.embed(["q"])


async def test_exposes_usage_and_dimensions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2]]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        await provider.embed(["q"])

    assert provider.dimensions == 768
    assert provider.usage == EmbeddingUsage(
        calls=1,
        characters=provider.usage.characters,
        estimated_tokens=provider.usage.estimated_tokens,
        failures=0,
    )
