"""Tests for the embedding client (Phase 5, ADR-008).

`GoogleEmbeddingClient` is exercised with a fake `genai_client` so no network
or API key is needed. `get_settings().gemini_api_key` is cleared to assert the
unavailable path.
"""

import asyncio
from dataclasses import dataclass

import pytest
from backend.core.config import get_settings
from backend.core.errors import EmbeddingError, EmbeddingUnavailableError
from backend.services.knowledge.embedding import EmbeddingUsage, GoogleEmbeddingClient


@dataclass
class FakeEmbeddingResponse:
    embeddings: list[object]


@dataclass
class FakeEmbeddingItem:
    values: list[float]


class _FakeModels:
    def __init__(self, client: "FakeGenAIClient") -> None:
        self._client = client

    async def embed_content(self, model: str, contents: list[str], config=None):
        self._client.configs.append(config)
        return await self._client._embed_content(model, contents)


class _FakeAio:
    def __init__(self, client: "FakeGenAIClient") -> None:
        self.models = _FakeModels(client)


class FakeGenAIClient:
    """Simulates the Google GenAI async SDK surface used by the client.

    The real SDK is reached as `Client(api_key).aio.models.embed_content(...)`,
    so the fake mirrors that shape: `.aio.models.embed_content` routes into
    `_embed_content`.
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.configs: list[object] = []
        self.failures: list[Exception] = []
        self.next_values: list[list[float]] | None = None
        self.delay: float = 0.0
        self.aio = _FakeAio(self)

    def _make_response(self, texts: list[str]) -> FakeEmbeddingResponse:
        if self.next_values is not None:
            return FakeEmbeddingResponse(
                embeddings=[FakeEmbeddingItem(v) for v in self.next_values]
            )
        return FakeEmbeddingResponse(
            embeddings=[FakeEmbeddingItem([float(len(text)), 1.0]) for text in texts]
        )

    async def _embed_content(self, model: str, contents: list[str]) -> FakeEmbeddingResponse:
        self.calls.append(contents)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.failures:
            raise self.failures.pop(0)
        return self._make_response(contents)


@pytest.fixture
def fake_sdk() -> FakeGenAIClient:
    return FakeGenAIClient()


def _client(fake_sdk: FakeGenAIClient, **kwargs):
    return GoogleEmbeddingClient(
        model="test-embedding",
        batch_size=2,
        max_retries=3,
        base_delay_ms=1,
        timeout_seconds=5.0,
        dimensions=2,
        genai_client=fake_sdk,
        **kwargs,
    )


async def test_embeds_in_batches_and_returns_vectors_in_order(fake_sdk) -> None:
    client = _client(fake_sdk)
    texts = ["a", "bb", "ccc", "dddd", "eeeee"]
    vectors = await client.embed(texts)

    assert len(vectors) == len(texts)
    assert [v[0] for v in vectors] == [1.0, 2.0, 3.0, 4.0, 5.0]
    # Batch size 2 => ceil(5/2) = 3 SDK calls.
    assert fake_sdk.calls == [["a", "bb"], ["ccc", "dddd"], ["eeeee"]]


async def test_sends_output_dimensionality_for_non_default_dimension(fake_sdk) -> None:
    client = _client(fake_sdk)  # dimensions=2 -> output_dimensionality must be sent
    await client.embed(["a", "b"])

    assert all(config == {"output_dimensionality": 2} for config in fake_sdk.configs)


async def test_default_dimension_sends_no_output_dimensionality(fake_sdk) -> None:
    # 3072 is the model's native output; the request stays byte-identical to
    # the pre-fallback client so existing 3072-index deployments see no change.
    client = GoogleEmbeddingClient(
        model="test-embedding",
        batch_size=2,
        max_retries=3,
        base_delay_ms=1,
        timeout_seconds=5.0,
        dimensions=3072,
        genai_client=fake_sdk,
    )
    fake_sdk.next_values = [[1.0] * 3072]
    await client.embed(["a"])

    assert all(config is None for config in fake_sdk.configs)


async def test_raises_embedding_error_on_dimension_mismatch(fake_sdk) -> None:
    fake_sdk.next_values = [[0.1, 0.2, 0.3]]  # 3-dim, client expects 2
    client = _client(fake_sdk)

    with pytest.raises(EmbeddingError, match="dimension mismatch.*gemini.*3.*2"):
        await client.embed(["a"])


async def test_empty_input_makes_no_sdk_calls(fake_sdk) -> None:
    client = _client(fake_sdk)
    assert await client.embed([]) == []
    assert fake_sdk.calls == []


async def test_tracks_usage_and_invokes_hook(fake_sdk) -> None:
    seen: list[EmbeddingUsage] = []
    client = _client(fake_sdk, on_usage=seen.append)
    await client.embed(["hello world", "second text"])

    assert client.usage.calls == 1
    assert client.usage.characters == 22  # 11 + 11
    assert client.usage.estimated_tokens == 4  # 2 + 2 words
    assert client.usage.failures == 0
    assert len(seen) == 1  # hook called once per completed batch
    assert seen[-1].calls == 1


async def test_retries_transient_failures_then_succeeds(fake_sdk) -> None:
    fake_sdk.failures = [TimeoutError("slow")]
    client = _client(fake_sdk)
    vectors = await client.embed(["a", "b"])

    assert len(vectors) == 2
    assert len(fake_sdk.calls) == 2  # first attempt failed, second succeeded


async def test_exhausts_retries_and_raises_embedding_error(fake_sdk) -> None:
    fake_sdk.failures = [RuntimeError("boom")] * 10
    client = _client(fake_sdk)

    with pytest.raises(EmbeddingError) as exc:
        await client.embed(["a"])

    assert "after 3 attempts" in str(exc.value)
    assert client.usage.failures == 1
    # Backoff used between attempts: 2 sleeps (attempt 0 and 1).
    assert len(fake_sdk.calls) == 3


async def test_raises_embedding_error_on_response_length_mismatch(fake_sdk) -> None:
    fake_sdk.next_values = [[1.0]]  # one vector for two requested texts
    client = _client(fake_sdk)

    with pytest.raises(EmbeddingError) as exc:
        await client.embed(["a", "b"])

    assert "1 vectors" in str(exc.value)


async def test_raises_embedding_error_on_missing_embeddings(fake_sdk) -> None:
    fake_sdk.next_values = []
    client = _client(fake_sdk)

    with pytest.raises(EmbeddingError) as exc:
        await client.embed(["a"])

    assert "no embeddings" in str(exc.value)


async def test_raises_embedding_error_on_embedded_item_without_values(fake_sdk) -> None:
    class NoValues:
        pass

    fake_sdk.next_values = None  # bypass default builder
    fake_sdk._make_response = lambda texts: FakeEmbeddingResponse(  # type: ignore[method-assign]
        embeddings=[NoValues()]
    )
    client = _client(fake_sdk)

    with pytest.raises(EmbeddingError):
        await client.embed(["a"])


async def test_unavailable_without_api_key(fake_sdk) -> None:
    settings = get_settings()
    old_key = settings.gemini_api_key
    settings.gemini_api_key = ""
    try:
        # No injected client: the SDK client must refuse to build without a key.
        client = GoogleEmbeddingClient()
        with pytest.raises(EmbeddingUnavailableError):
            await client.embed(["a"])
    finally:
        settings.gemini_api_key = old_key


def test_client_never_uses_sdk_without_api_key(fake_sdk) -> None:
    """Building the client is inert; only a real `embed` call needs the SDK."""
    client = GoogleEmbeddingClient(genai_client=fake_sdk)
    assert client._genai_client is not None  # injected, no key required
