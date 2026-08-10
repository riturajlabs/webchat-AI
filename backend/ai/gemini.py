"""Gemini answer generation (Phase 6, ADR-008).

`GoogleGeminiClient` streams answers from `gemini-2.5-flash` through the
Google GenAI async SDK (`client.aio.models.generate_content_stream`). Each
chunk's `.text` delta is yielded to the caller; the final chunk's
`usage_metadata` (input/output tokens) is captured for ADR-005 §5.8 token
usage tracking. Application code depends on the `GenerationClient` Protocol
only - the Google SDK stays inside this module, and the API key comes from
settings (env) and is never logged or exposed (00-AI-Development-Rules §12,
§20).
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from backend.core.config import get_settings
from backend.core.errors import GenerationError, GenerationUnavailableError

# Gemini roles mapped onto prompt roles (user/model). A "model" turn in the
# prompt becomes a "model" content block (conversation memory).
_ROLE_MAP: dict[str, str] = {
    "user": "user",
    "assistant": "model",
    "system": "user",
}


@dataclass(frozen=True)
class GenerationUsage:
    """Gemini token usage for the latest request (ADR-005 §5.8)."""

    input_tokens: int = 0
    output_tokens: int = 0


class GenerationClient(Protocol):
    """Streaming answer generation. Never raises raw SDK errors."""

    @property
    def usage(self) -> GenerationUsage:
        """Token usage captured for the most recent request (ADR-005 §5.8)."""
        ...

    def stream_generate(
        self,
        *,
        system: str,
        messages: list[tuple[str, str]],
    ) -> AsyncIterator[str]: ...


class GoogleGeminiClient:
    """`gemini-2.5-flash` streaming via the Google GenAI async SDK."""

    name = "gemini"

    def __init__(
        self,
        *,
        model: str | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        timeout_seconds: float | None = None,
        genai_client: Any | None = None,
    ) -> None:
        settings = get_settings()
        self._model = model or settings.gemini_model
        self._max_output_tokens = max_output_tokens or settings.chat_max_output_tokens
        self._temperature = temperature if temperature is not None else settings.chat_temperature
        self._timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else settings.generation_timeout_seconds
        )
        self._genai_client = genai_client
        self._usage = GenerationUsage()

    @property
    def usage(self) -> GenerationUsage:
        return self._usage

    def _client(self) -> Any:
        """Lazily build the SDK client (never touches network until first call)."""
        if self._genai_client is None:
            api_key = get_settings().gemini_api_key
            if not api_key:
                raise GenerationUnavailableError(
                    "GEMINI_API_KEY is not configured; cannot generate answers."
                )
            from google.genai import Client

            self._genai_client = Client(api_key=api_key)
        return self._genai_client

    async def stream_generate(
        self,
        *,
        system: str,
        messages: list[tuple[str, str]],
    ) -> AsyncIterator[str]:
        """Stream answer deltas. Raises `GenerationError` on SDK failure."""
        contents = [
            {"role": _ROLE_MAP.get(role, role), "parts": [{"text": text}]}
            for role, text in messages
        ]
        request = {
            "model": self._model,
            "contents": contents,
            "config": {
                "system_instruction": system,
                "max_output_tokens": self._max_output_tokens,
                "temperature": self._temperature,
            },
        }
        try:
            # SDK 2.17: `aio.models.generate_content_stream` is an async def
            # that *returns* the stream, so it must be awaited before
            # iteration.
            stream = await self._client().aio.models.generate_content_stream(**request)
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        stream.__anext__(), timeout=self._timeout_seconds
                    )
                except StopAsyncIteration:
                    break
                text = getattr(chunk, "text", None)
                if text:
                    yield text
                metadata = getattr(chunk, "usage_metadata", None)
                if metadata is not None:
                    self._usage = GenerationUsage(
                        input_tokens=int(getattr(metadata, "prompt_token_count", 0)),
                        output_tokens=int(getattr(metadata, "candidates_token_count", 0)),
                    )
        except GenerationUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalized below
            raise GenerationError(f"Answer generation failed: {exc}") from exc


__all__ = ["GenerationClient", "GenerationUsage", "GoogleGeminiClient"]
