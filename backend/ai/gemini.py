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
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from backend.ai.finish_reason import (
    FINISH_REASON_UNKNOWN,
    TRUNCATING_FINISH_REASONS,
    normalize_gemini_finish_reason,
)
from backend.core.config import get_settings
from backend.core.errors import GenerationError, GenerationUnavailableError
from backend.core.logging import get_request_id

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
    """Generation usage and termination metadata for the latest request.

    ``input_tokens``/``output_tokens`` follow ADR-005 §5.8. ``finish_reason`
    is the normalized provider termination reason (see
    ``backend/ai/finish_reason.py``); ``truncated`` is True when the provider
    stopped on a token-limit reason (MAX_TOKENS/LENGTH) — the answer may be
    visibly cut off. ``reasoning_tokens`` is the provider-reported reasoning
    budget when available (gemini-2.5 ``thoughts_token_count``, Groq
    ``completion_tokens_details.reasoning_tokens``). It is *metadata only*:
    billing cost uses ``output_tokens`` exactly as the provider charges it.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str = FINISH_REASON_UNKNOWN
    truncated: bool = False
    reasoning_tokens: int = 0


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
        max_tokens: int = 0,
    ) -> AsyncIterator[str]: ...


def _classify_gemini_exception(exc: BaseException) -> str:
    """Normalize upstream exception into stable safe taxonomy:
    timeout | provider_api_error | network_error | connection_error | stream_closed | unknown
    """
    candidates = [exc]
    if exc.__cause__ is not None:
        candidates.append(exc.__cause__)
    if exc.__context__ is not None:
        candidates.append(exc.__context__)

    for e in candidates:
        if isinstance(e, (TimeoutError, asyncio.TimeoutError)):
            return "timeout"
        type_name = type(e).__name__
        mod_name = type(e).__module__ or ""
        msg = str(e).lower()

        # Provider API errors (Google GenAI APIError, ServerError, ClientError, etc.)
        if "APIError" in type_name or "ClientError" in type_name or "ServerError" in type_name:
            return "provider_api_error"
        if "genai" in mod_name and "error" in mod_name.lower():
            return "provider_api_error"
        if any(
            code in msg
            for code in (
                "503",
                "429",
                "resourceexhausted",
                "service unavailable",
                "api error",
                "quota",
            )
        ):
            return "provider_api_error"

        # Connection reset / broken pipe / refused
        if isinstance(
            e, (ConnectionError, ConnectionResetError, BrokenPipeError, ConnectionRefusedError)
        ):
            return "connection_error"
        if "connection" in type_name.lower() or "connection reset" in msg or "broken pipe" in msg:
            return "connection_error"

        # Stream closed / EOF / protocol error
        if any(
            term in type_name
            for term in ("RemoteProtocolError", "ClientPayloadError", "IncompleteRead")
        ):
            return "stream_closed"
        if "stream closed" in msg or "eof occurred" in msg:
            return "stream_closed"

        # General network / transport errors
        if any(
            term in type_name
            for term in ("NetworkError", "TransportError", "SSLError", "SocketError", "gaierror")
        ):
            return "network_error"
        if "network" in msg or "socket" in msg or "dns" in msg:
            return "network_error"

    return "unknown"


def _emit_stream_telemetry(
    *,
    model: str,
    phase: str,
    started_streaming: bool,
    exc: BaseException,
    category: str,
    elapsed_ms: float,
    output_tokens: int = 0,
    finish_reason: str = "",
    timeout_seconds: float | None = None,
) -> None:
    """Emit structured telemetry for Gemini stream failure.

    Safe metadata only — never logs user content, prompts, or credentials.
    Logging failures are caught and swallowed so telemetry never breaks execution.
    """
    try:
        req_id = get_request_id()
        extra: dict[str, Any] = {
            "event": "gemini_stream_exception",
            "provider": "gemini",
            "model": model,
            "phase": phase,
            "started_streaming": started_streaming,
            "exception_type": type(exc).__name__,
            "exception_category": category,
            "elapsed_ms": round(elapsed_ms, 2),
            "output_tokens": output_tokens,
            "finish_reason": finish_reason,
            "request_id": req_id if req_id != "-" else None,
        }
        if timeout_seconds is not None:
            extra["timeout_seconds"] = timeout_seconds
        logger.warning(
            "gemini_stream_exception provider=gemini model=%s category=%s type=%s elapsed_ms=%.2f",
            model,
            category,
            type(exc).__name__,
            elapsed_ms,
            extra=extra,
        )
    except Exception:
        # Telemetry logging must NEVER cause generation to fail
        pass


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
        thinking_budget: int | None = None,
        genai_client: Any | None = None,
    ) -> None:
        settings = get_settings()
        self._model = model or settings.gemini_model
        self._max_output_tokens = max_output_tokens or settings.chat_max_output_tokens
        self._thinking_budget = (
            settings.gemini_thinking_budget if thinking_budget is None else thinking_budget
        )
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
        max_tokens: int = 0,
    ) -> AsyncIterator[str]:
        """Stream answer deltas. Raises `GenerationError` on SDK failure.

        ``max_tokens`` (0 = unset) overrides the client/output-cap configured
        at construction time — the RAG service passes its budgeted cap so the
        provider can never fall back to an unbounded default.

        Retries transient failures (timeout, rate limit, provider errors)
        up to ``llm_max_retries`` times with exponential backoff before
        giving up.  First-token timeouts are treated as unavailable and
        immediately propagated (no retry) so the Phase 9 router can fall
        through to another provider.

        A clean ``MAX_TOKENS`` termination is *not* an exception: the stream
        ends normally and ``usage.truncated`` reports the cap hit, so a
        token-limit stop is never retried or re-requested.
        """
        settings = get_settings()
        max_retries = settings.llm_max_retries
        base_delay = settings.llm_retry_base_delay
        last_exc: Exception | None = None

        for attempt in range(max_retries + 1):
            emitted_any = False
            try:
                async for delta in self._stream_generate_once(
                    system=system, messages=messages, max_tokens=max_tokens
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
                delay = base_delay * (2**attempt)
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
        max_tokens: int = 0,
    ) -> AsyncIterator[str]:
        """Single attempt at streaming generation (no retry)."""
        contents = [
            {"role": _ROLE_MAP.get(role, role), "parts": [{"text": text}]}
            for role, text in messages
        ]
        output_cap = max_tokens if max_tokens and max_tokens > 0 else self._max_output_tokens
        config: dict[str, Any] = {
            "system_instruction": system,
            "max_output_tokens": output_cap,
            "temperature": self._temperature,
            "top_p": 0.95,
        }
        # Thinking budget control (root-cause fix): Google counts Gemini 2.5
        # thinking tokens against `max_output_tokens`, so dynamic thinking can
        # eat the visible-output budget and truncate the answer. A budget >= 0
        # pins thinking explicitly (0 disables it); < 0 keeps the SDK default.
        if self._thinking_budget >= 0:
            config["thinking_config"] = {"thinking_budget": self._thinking_budget}
        request = {
            "model": self._model,
            "contents": contents,
            "config": config,
        }
        finish_reason = FINISH_REASON_UNKNOWN
        input_tokens = 0
        output_tokens = 0
        reasoning_tokens = 0
        started_time = time.perf_counter()
        first_chunk = True
        emitted_any = False
        try:
            stream = await self._client().aio.models.generate_content_stream(**request)
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
                    elapsed_ms = (time.perf_counter() - started_time) * 1000.0
                    if first_chunk:
                        _emit_stream_telemetry(
                            model=self._model,
                            phase="first_token",
                            started_streaming=False,
                            exc=exc,
                            category="timeout",
                            elapsed_ms=elapsed_ms,
                            output_tokens=output_tokens,
                            finish_reason=""
                            if finish_reason == FINISH_REASON_UNKNOWN
                            else finish_reason,
                            timeout_seconds=self._first_token_timeout_seconds,
                        )
                        raise GenerationUnavailableError(
                            "Gemini did not produce a first token within "
                            f"{self._first_token_timeout_seconds}s."
                        ) from exc
                    _emit_stream_telemetry(
                        model=self._model,
                        phase="inter_chunk",
                        started_streaming=emitted_any,
                        exc=exc,
                        category="timeout",
                        elapsed_ms=elapsed_ms,
                        output_tokens=output_tokens,
                        finish_reason=""
                        if finish_reason == FINISH_REASON_UNKNOWN
                        else finish_reason,
                        timeout_seconds=self._timeout_seconds,
                    )
                    raise GenerationError(
                        f"Gemini answer stream stalled for {self._timeout_seconds}s."
                    ) from exc
                except StopAsyncIteration:
                    break
                first_chunk = False
                text = getattr(chunk, "text", None)
                if text:
                    emitted_any = True
                    yield text
                # Termination metadata: the per-chunk `finish_reason` is None
                # until the final chunk; keep the last non-None value (defensive
                # against SDKs that surface it on any chunk).
                candidates = getattr(chunk, "candidates", None)
                if isinstance(candidates, (list, tuple)) and candidates:
                    fr = getattr(candidates[0], "finish_reason", None)
                    if fr is not None:
                        finish_reason = normalize_gemini_finish_reason(fr)
                metadata = getattr(chunk, "usage_metadata", None)
                if metadata is not None:
                    input_tokens = int(getattr(metadata, "prompt_token_count", 0))
                    output_tokens = int(getattr(metadata, "candidates_token_count", 0))
                    reasoning_tokens = int(getattr(metadata, "thoughts_token_count", 0))
            self._usage = GenerationUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason=finish_reason,
                truncated=finish_reason in TRUNCATING_FINISH_REASONS,
                reasoning_tokens=reasoning_tokens,
            )
        except GenerationUnavailableError:
            raise
        except GenerationError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalized below
            elapsed_ms = (time.perf_counter() - started_time) * 1000.0
            category = _classify_gemini_exception(exc)
            _emit_stream_telemetry(
                model=self._model,
                phase="inter_chunk" if not first_chunk else "first_token",
                started_streaming=emitted_any,
                exc=exc,
                category=category,
                elapsed_ms=elapsed_ms,
                output_tokens=output_tokens,
                finish_reason="" if finish_reason == FINISH_REASON_UNKNOWN else finish_reason,
            )
            raise GenerationError(f"Answer generation failed: {exc}") from exc


__all__ = ["GenerationClient", "GenerationUsage", "GoogleGeminiClient"]
