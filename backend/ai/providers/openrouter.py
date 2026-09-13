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

from backend.ai.finish_reason import (
    FINISH_REASON_UNKNOWN,
    TRUNCATING_FINISH_REASONS,
    normalize_openai_finish_reason,
)
from backend.ai.gemini import GenerationUsage
from backend.ai.providers.openai_compat import (
    build_chat_payload,
    iter_openai_first_token_guarded,
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
        first_token_timeout_seconds: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self._model = model or settings.openrouter_model
        self._api_key = api_key if api_key is not None else settings.openrouter_api_key
        self._timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else settings.ai_provider_timeout_seconds
        )
        self._first_token_timeout_seconds = (
            first_token_timeout_seconds
            if first_token_timeout_seconds is not None
            else settings.generation_first_token_timeout_seconds
        )
        self._http_client = http_client
        self._usage = GenerationUsage()

    @property
    def usage(self) -> GenerationUsage:
        return self._usage

    @property
    def model_name(self) -> str:
        """Model id used for generation (rate-card key, Phase 1 cost tracking)."""
        return self._model

    async def stream_generate(
        self,
        *,
        system: str,
        messages: list[tuple[str, str]],
        max_tokens: int = 0,
    ) -> AsyncIterator[str]:
        """Stream answer deltas from OpenRouter. Never raises raw SDK errors."""
        api_key = self._api_key
        if not api_key:
            raise GenerationUnavailableError("OPENROUTER_API_KEY is not configured.")
        client = self._http_client or shared_http_client(self._timeout_seconds)
        payload = build_chat_payload(model=self._model, system=system, messages=messages)
        if max_tokens and max_tokens > 0:
            payload["max_tokens"] = max_tokens
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
                finish_reason = FINISH_REASON_UNKNOWN
                input_tokens = 0
                output_tokens = 0
                async for delta, usage, raw_finish in iter_openai_first_token_guarded(
                    response, first_token_timeout_seconds=self._first_token_timeout_seconds
                ):
                    if raw_finish is not None:
                        finish_reason = normalize_openai_finish_reason(raw_finish)
                    if usage is not None:
                        input_tokens = int(usage.get("prompt_tokens") or 0)
                        output_tokens = int(usage.get("completion_tokens") or 0)
                    if delta:
                        yield delta
                self._usage = GenerationUsage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    finish_reason=finish_reason,
                    truncated=finish_reason in TRUNCATING_FINISH_REASONS,
                )
        except httpx.TimeoutException as exc:
            raise GenerationUnavailableError("OpenRouter request timed out.") from exc
        except httpx.TransportError as exc:
            raise GenerationUnavailableError(f"OpenRouter is unreachable: {exc}") from exc


__all__ = ["OpenRouterGenerationClient"]
