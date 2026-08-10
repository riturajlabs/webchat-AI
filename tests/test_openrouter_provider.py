"""Tests for the Phase 9 OpenRouter generation provider (ADR-009).

Exercised through `httpx.MockTransport`; mirrors the Groq provider tests plus
the 402 (insufficient credits) mapping.
"""

import json

import httpx
import pytest
from backend.ai.gemini import GenerationUsage
from backend.ai.providers.openrouter import OpenRouterGenerationClient
from backend.core.errors import GenerationError, GenerationUnavailableError


def _sse(*chunks: dict) -> str:
    body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
    return body + "data: [DONE]\n\n"


def _delta(text: str) -> dict:
    return {
        "id": "1",
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
    }


def _usage(prompt: int, completion: int) -> dict:
    return {
        "id": "1",
        "choices": [],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        },
    }


def _provider(
    client: httpx.AsyncClient, *, api_key: str = "test-key"
) -> OpenRouterGenerationClient:
    return OpenRouterGenerationClient(
        model="meta-llama/llama-3.3-70b-instruct",
        api_key=api_key,
        timeout_seconds=5,
        http_client=client,
    )


async def test_streams_deltas_and_captures_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=_sse(_delta("Hel"), _delta("lo"), _usage(9, 3)),
            headers={"content-type": "text/event-stream"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        deltas = [
            d
            async for d in provider.stream_generate(system="sys", messages=[("user", "hi")])
        ]

    assert deltas == ["Hel", "lo"]
    assert provider.usage == GenerationUsage(input_tokens=9, output_tokens=3)


async def test_builds_openai_compatible_payload() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, text=_sse(_delta("ok")))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        async for _ in provider.stream_generate(system="sys", messages=[("user", "q")]):
            pass

    assert captured[0]["model"] == "meta-llama/llama-3.3-70b-instruct"
    assert captured[0]["stream"] is True
    assert captured[0]["stream_options"] == {"include_usage": True}


async def test_missing_api_key_raises_unavailable() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200))
    ) as client:
        provider = _provider(client, api_key="")
        with pytest.raises(GenerationUnavailableError, match="OPENROUTER_API_KEY"):
            async for _ in provider.stream_generate(system="s", messages=[("user", "q")]):
                pass


@pytest.mark.parametrize(
    "status",
    [401, 402, 403, 429],
)
async def test_http_status_maps_to_unavailable(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="{}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        with pytest.raises(GenerationUnavailableError):
            async for _ in provider.stream_generate(system="s", messages=[("user", "q")]):
                pass


async def test_http_500_maps_to_generation_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        with pytest.raises(GenerationError):
            async for _ in provider.stream_generate(system="s", messages=[("user", "q")]):
                pass


async def test_transport_error_maps_to_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        with pytest.raises(GenerationUnavailableError, match="unreachable"):
            async for _ in provider.stream_generate(system="s", messages=[("user", "q")]):
                pass
