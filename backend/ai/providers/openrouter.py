"""OpenRouter answer generation (Phase 9, ADR-009).

`OpenRouterGenerationClient` implements the `GenerationClient` Protocol
(`backend/ai/gemini.py`) via OpenRouter's OpenAI-compatible chat-completions
streaming API, so it slots into the Phase 9 fallback chain exactly like
`GoogleGeminiClient`. The API key comes from settings (env) and is never
logged or exposed (00-AI-Development-Rules §12, §20); raw `httpx` errors are
normalized to `GenerationError`/`GenerationUnavailableError` (§18).
"""

import logging
from collections.abc import AsyncIterator

import httpx

from backend.ai.gemini import GenerationUsage
from backend.ai.providers.openai_compat import (
    build_chat_payload,
    iter_openai_sse,
    map_openai_http_error,
    shared_http_client,
)
from backend.core.config import get_settings
from backend.core.errors import GenerationUnavailableError

logger = logging.getLogger("webchat_ai")

_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterGenerationClient:
    """OpenRouter (default `meta-llama/llama-3.3-70b-instruct`) streaming."""

    name = "openrouter"

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self._model = model or settings.openrouter_model
        self._api_key = api_key if api_key is not None else settings.openrouter_api_key
        self._timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.ai_provider_timeout_seconds
        )
        self._http_client = http_client
        self._usage = GenerationUsage()

    @property
    def usage(self) -> GenerationUsage:
        return self._usage

    async def stream_generate(
        self,
        *,
        system: str,
        messages: list[tuple[str, str]],
    ) -> AsyncIterator[str]:
        """Stream answer deltas from OpenRouter. Never raises raw SDK errors."""
        api_key = self._api_key
        if not api_key:
            raise GenerationUnavailableError("OPENROUTER_API_KEY is not configured.")
        client = self._http_client or shared_http_client(self._timeout_seconds)
        payload = build_chat_payload(model=self._model, system=system, messages=messages)
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            async with client.stream(
                "POST",
                _BASE_URL,
                headers=headers,
                json=payload,
                timeout=self._timeout_seconds,
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise map_openai_http_error(response.status_code, "OpenRouter")
                async for delta, usage in iter_openai_sse(response):
                    if usage is not None:
                        self._usage = GenerationUsage(
                            input_tokens=int(usage.get("prompt_tokens") or 0),
                            output_tokens=int(usage.get("completion_tokens") or 0),
                        )
                    if delta:
                        yield delta
        except httpx.TimeoutException as exc:
            raise GenerationUnavailableError("OpenRouter request timed out.") from exc
        except httpx.TransportError as exc:
            raise GenerationUnavailableError(f"OpenRouter is unreachable: {exc}") from exc


__all__ = ["OpenRouterGenerationClient"]
