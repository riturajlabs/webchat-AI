"""Shared client for OpenAI-compatible chat-completions providers (Phase 9).

Groq and OpenRouter expose the same `POST /chat/completions` streaming API
(SSE lines of `data: {json}`, terminated by `data: [DONE]`). This module
centralizes the wire format and error mapping so each provider stays a thin
config: base URL + model + API key.

The API key comes from settings (env) and is never logged or exposed
(00-AI-Development-Rules §12, §20). Raw `httpx` errors are normalized to the
application error taxonomy (`backend/core/errors.py`) so no SDK error ever
escapes the AI layer (00 rules §18).
"""

import json
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from backend.core.errors import AppError, GenerationError, GenerationUnavailableError

logger = logging.getLogger("webchat_ai")

# One connection pool per process, created lazily on first use and shared by
# every OpenAI-compatible provider. Uvicorn and the ARQ worker each run a
# single event loop, so a module-level client is safe; tests inject their own
# client (e.g. backed by `httpx.MockTransport`).
_shared_client: httpx.AsyncClient | None = None

# Roles passed by the RAG service are already user/assistant; anything
# unexpected is demoted to "user" rather than rejected by the upstream API.
_KNOWN_ROLES = {"system", "user", "assistant"}


def shared_http_client(timeout_seconds: float) -> httpx.AsyncClient:
    """Return the process-wide `httpx.AsyncClient` (created on first use)."""
    global _shared_client
    if _shared_client is None:
        _shared_client = httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))
    return _shared_client


def build_chat_payload(
    *,
    model: str,
    system: str,
    messages: Sequence[tuple[str, str]],
    **extra: Any,
) -> dict[str, Any]:
    """Build the OpenAI chat-completions streaming payload.

    `stream_options.include_usage` asks the provider to emit a final chunk
    carrying token usage, which is how `GenerationUsage` is captured without
    a second request.
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            *[
                {
                    "role": role if role in _KNOWN_ROLES else "user",
                    "content": text,
                }
                for role, text in messages
            ],
        ],
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    payload.update(extra)
    return payload


async def iter_openai_sse(
    response: httpx.Response,
) -> AsyncIterator[tuple[str | None, dict[str, Any] | None]]:
    """Yield `(content_delta, usage)` tuples from an SSE completion stream.

    Malformed lines are logged and skipped so one bad chunk cannot kill the
    answer; a missing `[DONE]` (stream ended by the server) simply ends the
    iteration. The usage chunk carries no content delta.
    """
    async for line in response.aiter_lines():
        if not line.startswith("data:"):
            continue
        data = line[len("data:") :].strip()
        if not data:
            continue
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            logger.warning("dropping malformed SSE chunk from provider stream: %.200s", data)
            continue
        if not isinstance(chunk, dict):
            continue
        usage = chunk.get("usage")
        delta: str | None = None
        choices = chunk.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                choice_delta = first.get("delta") or {}
                if isinstance(choice_delta, dict):
                    delta = choice_delta.get("content")
        yield delta, usage if isinstance(usage, dict) else None


def map_openai_http_error(status: int, provider_name: str) -> AppError:
    """Map an upstream HTTP status onto the app error taxonomy.

    Auth (401/403), insufficient credits (402) and rate limits (429) are
    treated as "unavailable" so the Phase 9 fallback chain can move on;
    anything else is a plain generation failure.
    """
    if status in (401, 403):
        return GenerationUnavailableError(
            f"{provider_name} authentication failed (HTTP {status})."
        )
    if status == 402:
        return GenerationUnavailableError(
            f"{provider_name} credits exhausted (HTTP {status})."
        )
    if status == 429:
        return GenerationUnavailableError(
            f"{provider_name} rate limit exceeded (HTTP {status})."
        )
    return GenerationError(f"{provider_name} request failed (HTTP {status}).")


__all__ = [
    "build_chat_payload",
    "iter_openai_sse",
    "map_openai_http_error",
    "shared_http_client",
]
