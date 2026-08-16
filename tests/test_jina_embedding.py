"""Tests for the Jina AI embedding provider (ADR-009 cloud fallback).

Exercised through `httpx.MockTransport`; the client needs only an API key, a
model and a dimension. Covers: successful embedding, empty input, API failure
mapping (auth/quota/rate-limit vs 5xx), timeout, transport error, invalid
responses and the dimension gate.
"""

import json

import httpx
import pytest
from backend.ai.providers.jina import JinaEmbeddingClient
from backend.core.errors import EmbeddingError, EmbeddingUnavailableError


def _provider(
    client: httpx.AsyncClient, api_key: str = "test-key", **kwargs
) -> JinaEmbeddingClient:
    return JinaEmbeddingClient(
        model="jina-embeddings-v3",
        api_key=api_key,
        dimensions=2,
        timeout_seconds=5,
        http_client=client,
        **kwargs,
    )


def _ok_payload(vectors: list[list[float]]) -> dict:
    return {
        "model": "jina-embeddings-v3",
        "data": [
            {"object": "embedding", "index": i, "embedding": vector}
            for i, vector in enumerate(vectors)
        ],
        "usage": {"total_tokens": 4, "prompt_tokens": 4},
    }


async def test_embeds_texts_in_order() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, json=_ok_payload([[0.1, 0.2], [0.3, 0.4]]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        vectors = await provider.embed(["one", "two"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert captured[0]["model"] == "jina-embeddings-v3"
    assert captured[0]["input"] == ["one", "two"]
    assert captured[0]["dimensions"] == 2
    assert provider.usage.calls == 1
    assert provider.usage.characters == len("one") + len("two")
    assert provider.usage.estimated_tokens > 0


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
        with pytest.raises(EmbeddingUnavailableError, match="JINA_API_KEY"):
            await provider.embed(["q"])


async def test_vector_count_mismatch_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_payload([[0.1, 0.2]]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        with pytest.raises(EmbeddingError, match="1 vectors for 2 texts"):
            await provider.embed(["a", "b"])


async def test_invalid_response_missing_data_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"usage": {"total_tokens": 1}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        with pytest.raises(EmbeddingError, match="no vectors"):
            await provider.embed(["a"])


async def test_invalid_response_malformed_items_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"object": "embedding", "index": 0, "embedding": "nope"}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        with pytest.raises(EmbeddingError, match="usable vectors"):
            await provider.embed(["a"])


async def test_dimension_mismatch_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_payload([[0.1, 0.2, 0.3]]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        with pytest.raises(EmbeddingError, match="dimension mismatch.*jina.*3.*2"):
            await provider.embed(["a"])


@pytest.mark.parametrize("status", [401, 402, 403, 429])
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


async def test_health_returns_true_on_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ok_payload([[0.1, 0.2]]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        assert await provider.health() is True


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
    assert provider.usage.calls == 1
    assert provider.usage.failures == 0
