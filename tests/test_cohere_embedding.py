"""Tests for the Cohere embedding provider (ADR-009 cloud fallback).

Exercised through `httpx.MockTransport`; the client needs only an API key, a
model and a dimension. Covers: successful embedding (v2 response shape), empty
input, API failure mapping, timeout, transport error and the dimension gate.
"""

import json

import httpx
import pytest
from backend.ai.providers.cohere import CohereEmbeddingClient
from backend.core.errors import EmbeddingError, EmbeddingUnavailableError
from backend.services.knowledge.embedding import EmbeddingUsage


def _provider(
    client: httpx.AsyncClient, api_key: str = "test-key", **kwargs
) -> CohereEmbeddingClient:
    return CohereEmbeddingClient(
        model="embed-multilingual-v3.0",
        api_key=api_key,
        dimensions=2,
        timeout_seconds=5,
        http_client=client,
        **kwargs,
    )


def _ok_payload(vectors: list[list[float]]) -> dict:
    return {
        "id": "req-1",
        "model": "embed-multilingual-v3.0",
        "texts": ["one", "two"],
        "embeddings": {"float": vectors},
        "meta": {"billed_units": {"input_tokens": 4}},
    }


async def test_embeds_texts_in_order_v2_shape() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, json=_ok_payload([[0.1, 0.2], [0.3, 0.4]]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        vectors = await provider.embed(["one", "two"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert captured[0]["model"] == "embed-multilingual-v3.0"
    assert captured[0]["texts"] == ["one", "two"]
    assert captured[0]["input_type"] == "search_document"
    assert captured[0]["embedding_types"] == ["float"]
    assert provider.usage.calls == 1
    assert provider.usage.characters == len("one") + len("two")
    assert provider.usage.estimated_tokens > 0


async def test_embeds_texts_in_order_v1_shape() -> None:
    # Tolerate the v1 response shape (embeddings as a bare list) for resilience.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2]]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        assert await provider.embed(["one"]) == [[0.1, 0.2]]


async def test_empty_input_skips_request() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json=_ok_payload([]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        assert await provider.embed([]) == []
    assert called is False


async def test_missing_api_key_raises_unavailable() -> None:
    async with httpx.AsyncClient() as client:
        provider = _provider(client, api_key="")
        with pytest.raises(EmbeddingUnavailableError, match="COHERE_API_KEY"):
            await provider.embed(["q"])


async def test_vector_count_mismatch_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_payload([[0.1, 0.2]]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        with pytest.raises(EmbeddingError, match="1 vectors for 2 texts"):
            await provider.embed(["a", "b"])


async def test_invalid_response_non_object_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="[]")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        with pytest.raises(EmbeddingError, match="non-object"):
            await provider.embed(["a"])


async def test_dimension_mismatch_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_payload([[0.1, 0.2, 0.3]]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        with pytest.raises(EmbeddingError, match="dimension mismatch.*cohere.*3.*2"):
            await provider.embed(["a"])


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


async def test_timeout_maps_to_unavailable() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        with pytest.raises(EmbeddingUnavailableError, match="timed out"):
            await provider.embed(["q"])


async def test_transport_error_maps_to_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        with pytest.raises(EmbeddingUnavailableError, match="unreachable"):
            await provider.embed(["q"])


async def test_health_returns_false_on_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        assert await provider.health() is False


async def test_exposes_usage_and_dimensions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_payload([[0.1, 0.2]]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        await provider.embed(["q"])

    assert provider.dimensions == 2
    assert provider.usage == EmbeddingUsage(
        calls=1,
        characters=provider.usage.characters,
        estimated_tokens=provider.usage.estimated_tokens,
        failures=0,
    )
