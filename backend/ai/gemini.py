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
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from backend.core.config import get_settings
from backend.core.errors import GenerationError, GenerationUnavailableError

logger = logging.getLogger("webchat_ai")

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
        first_token_timeout_seconds: float | None = None,
        genai_client: Any | None = None,
    ) -> None:
        settings = get_settings()
        self._model = model or settings.gemini_model
        self._max_output_tokens = max_output_tokens or settings.chat_max_output_tokens
        self._temperature = temperature if temperature is not None else settings.chat_temperature
        self._timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else settings.generation_timeout_seconds
        )
        self._first_token_timeout_seconds = (
            first_token_timeout_seconds
            if first_token_timeout_seconds is not None
            else settings.generation_first_token_timeout_seconds
        )
        self._genai_client = genai_client
        self._usage = GenerationUsage()

    @property
    def usage(self) -> GenerationUsage:
        return self._usage

    @property
    def model_name(self) -> str:
        """Model id used for generation (rate-card key, Phase 1 cost tracking)."""
        return self._model

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
        """Stream answer deltas. Raises `GenerationError` on SDK failure.

        Retries transient failures (timeout, rate limit, provider errors)
        up to ``llm_max_retries`` times with exponential backoff before
        giving up.  First-token timeouts are treated as unavailable and
        immediately propagated (no retry) so the Phase 9 router can fall
        through to another provider.
        """
        settings = get_settings()
        max_retries = settings.llm_max_retries
        base_delay = settings.llm_retry_base_delay
        last_exc: Exception | None = None

        for attempt in range(max_retries + 1):
            emitted_any = False
            try:
                async for delta in self._stream_generate_once(
                    system=system, messages=messages
                ):
                    emitted_any = True
                    yield delta
                return  # success — exit retry loop
            except GenerationUnavailableError:
                # First-token timeout → do NOT retry; let the router fall through.
                raise
            except GenerationError as exc:
                last_exc = exc
                # Once any delta has been streamed to the caller a retry would
                # append a second, complete answer to the already-delivered
                # partial prefix, corrupting the response. Fail instead so the
                # caller emits an error and discards the partial text.
                if emitted_any or attempt >= max_retries:
                    raise
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "gemini_retry attempt=%d/%d delay=%.1fs error=%s",
                    attempt + 1,
                    max_retries,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
                continue
        if last_exc is not None:
            raise last_exc

    async def _stream_generate_once(
        self,
        *,
        system: str,
        messages: list[tuple[str, str]],
    ) -> AsyncIterator[str]:
        """Single attempt at streaming generation (no retry)."""
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
                "top_p": 0.95,
            },
        }
        try:
            stream = await self._client().aio.models.generate_content_stream(**request)
            first_chunk = True
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        stream.__anext__(),
                        timeout=(
                            self._first_token_timeout_seconds
                            if first_chunk
                            else self._timeout_seconds
                        ),
                    )
                except TimeoutError as exc:
                    if first_chunk:
                        raise GenerationUnavailableError(
                            "Gemini did not produce a first token within "
                            f"{self._first_token_timeout_seconds}s."
                        ) from exc
                    raise GenerationError(
                        f"Gemini answer stream stalled for {self._timeout_seconds}s."
                    ) from exc
                except StopAsyncIteration:
                    break
                first_chunk = False
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
