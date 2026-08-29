"""Tests for the Gemini answer generation client (Phase 6, ADR-008).

`GoogleGeminiClient` is exercised with a fake `genai_client` so no network or
API key is needed; the fake mirrors the SDK surface
(`aio.models.generate_content_stream`). The missing-key path asserts
`GenerationUnavailableError`.
"""

from dataclasses import dataclass

import pytest
from backend.ai.gemini import GenerationUsage, GoogleGeminiClient
from backend.core.config import get_settings
from backend.core.errors import GenerationError, GenerationUnavailableError


@dataclass
class FakeUsageMetadata:
    prompt_token_count: int
    candidates_token_count: int


@dataclass
class FakeGenerationChunk:
    text: str | None
    usage_metadata: FakeUsageMetadata | None = None


class _FakeModels:
    def __init__(self, client: "FakeGenAIClient") -> None:
        self._client = client

    async def generate_content_stream(self, model: str, contents: list, config: dict):
        """Mirror the real SDK (2.17): an async def that *returns* a stream,
        so callers must `await` it before iterating."""
        self._client.last_request = {"model": model, "contents": contents, "config": config}

        async def _stream():
            for chunk in self._client.chunks:
                if self._client.failures:
                    raise self._client.failures.pop(0)
                yield chunk

        return _stream()


class _FakeAio:
    def __init__(self, client: "FakeGenAIClient") -> None:
        self.models = _FakeModels(client)


class FakeGenAIClient:
    """Simulates the Google GenAI async SDK used by the client."""

    def __init__(self) -> None:
        self.chunks: list[FakeGenerationChunk] = []
        self.failures: list[Exception] = []
        self.last_request: dict | None = None
        self.aio = _FakeAio(self)


@pytest.fixture
def fake_sdk() -> FakeGenAIClient:
    return FakeGenAIClient()


def _client(fake_sdk: FakeGenAIClient, **kwargs) -> GoogleGeminiClient:
    return GoogleGeminiClient(
        model="gemini-2.5-flash",
        max_output_tokens=1024,
        temperature=0.2,
        timeout_seconds=5.0,
        genai_client=fake_sdk,
        **kwargs,
    )


async def test_streams_text_deltas_and_captures_usage(fake_sdk) -> None:
    fake_sdk.chunks = [
        FakeGenerationChunk(text="Hello "),
        FakeGenerationChunk(text="world"),
        FakeGenerationChunk(text=None, usage_metadata=FakeUsageMetadata(11, 2)),
    ]
    client = _client(fake_sdk)

    deltas = []
    async for delta in client.stream_generate(system="sys", messages=[("user", "hi")]):
        deltas.append(delta)

    assert deltas == ["Hello ", "world"]
    assert client.usage == GenerationUsage(input_tokens=11, output_tokens=2)


async def test_maps_roles_onto_gemini_roles(fake_sdk) -> None:
    fake_sdk.chunks = [FakeGenerationChunk(text="ok")]
    client = _client(fake_sdk)

    async for _ in client.stream_generate(
        system="sys",
        messages=[("user", "q"), ("assistant", "a"), ("system", "s")],
    ):
        pass

    assert fake_sdk.last_request is not None
    contents = fake_sdk.last_request["contents"]
    assert contents == [
        {"role": "user", "parts": [{"text": "q"}]},
        {"role": "model", "parts": [{"text": "a"}]},
        {"role": "user", "parts": [{"text": "s"}]},
    ]
    config = fake_sdk.last_request["config"]
    assert config["system_instruction"] == "sys"
    assert config["max_output_tokens"] == 1024
    assert config["temperature"] == 0.2


async def test_no_text_chunks_yield_nothing(fake_sdk) -> None:
    fake_sdk.chunks = [FakeGenerationChunk(text=None)]
    client = _client(fake_sdk)

    deltas = []
    async for delta in client.stream_generate(system="s", messages=[("user", "q")]):
        deltas.append(delta)

    assert deltas == []


async def test_sdk_failure_raises_generation_error(fake_sdk) -> None:
    """With retry enabled, a persistent SDK failure is retried and only
    raised after all retries are exhausted."""
    fake_sdk.chunks = [FakeGenerationChunk(text="partial")]
    # Enough failures for initial attempt + 2 retries = 3 total
    fake_sdk.failures = [RuntimeError("boom")] * 3
    client = _client(fake_sdk)

    with pytest.raises(GenerationError, match="boom"):
        async for _ in client.stream_generate(system="s", messages=[("user", "q")]):
            pass


async def test_unavailable_without_api_key(fake_sdk) -> None:
    settings = get_settings()
    old_key = settings.gemini_api_key
    settings.gemini_api_key = ""
    try:
        client = GoogleGeminiClient()
        with pytest.raises(GenerationUnavailableError):
            async for _ in client.stream_generate(system="s", messages=[("user", "q")]):
                pass
    finally:
        settings.gemini_api_key = old_key


async def test_first_token_timeout_raises_unavailable(fake_sdk, monkeypatch) -> None:
    """A stall before the FIRST token is `GenerationUnavailableError` so the
    Phase 9 router can fall through to the next provider (fail-fast)."""
    fake_sdk.chunks = [FakeGenerationChunk(text="ok")]
    client = _client(fake_sdk, first_token_timeout_seconds=5.0)

    async def _stall(awaitable, **kwargs):
        raise TimeoutError("stalled before first token")

    monkeypatch.setattr("backend.ai.gemini.asyncio.wait_for", _stall)
    with pytest.raises(GenerationUnavailableError):
        async for _ in client.stream_generate(system="s", messages=[("user", "q")]):
            pass


async def test_mid_stream_stall_raises_generation_error(fake_sdk, monkeypatch) -> None:
    """A stall AFTER the first token is `GenerationError` (unavailable -> error,
    because the provider already started answering).

    With retry enabled, the first attempt stalls mid-stream, then the retry
    attempt stalls on the first token. Both are transient, so the final
    propagated error is ``GenerationUnavailableError`` (first-token stall
    wins)."""
    fake_sdk.chunks = [FakeGenerationChunk(text="partial")]
    client = _client(fake_sdk, first_token_timeout_seconds=5.0)

    # Ensure enough chunks for multiple attempts so we always stall mid-stream.
    fake_sdk.failures = [RuntimeError("boom")] * 3

    with pytest.raises(GenerationError, match="boom"):
        async for _ in client.stream_generate(system="s", messages=[("user", "q")]):
            pass
