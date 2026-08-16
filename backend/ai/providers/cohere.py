"""Cohere embeddings (cloud fallback provider, ADR-009).

`CohereEmbeddingClient` implements the `EmbeddingClient` Protocol
(`backend/services/knowledge/embedding.py`) using Cohere's `v2/embed`
REST API (`embed-multilingual-v3.0`), slotting into the Phase 9 embedding
fallback chain after Gemini/Jina. It is a cloud provider: it needs
`COHERE_API_KEY`, supports a configurable output dimension
(`COHERE_EMBEDDING_DIMENSIONS`, default 1024, matching `EMBEDDING_DIMENSIONS`),
and returns 1024-dim vectors for `embed-multilingual-v3.0`.

The API key comes from settings (env) and is never logged or exposed
(00-AI-Development-Rules §12, §20); raw `httpx` errors are normalized to
`EmbeddingError`/`EmbeddingUnavailableError` (§18). Timeouts, rate limits
(429), quota exhaustion and auth failures (401/403) surface as
`EmbeddingUnavailableError` so the fallback chain moves on. Returned vectors
are validated against the configured dimension before use
(docs/EMBEDDING_PROVIDERS.md).
"""

import logging
from collections.abc import Sequence
from typing import Any

import httpx

from backend.ai.providers.openai_compat import shared_http_client
from backend.core.config import get_settings
from backend.core.errors import EmbeddingError, EmbeddingUnavailableError
from backend.services.knowledge.chunker import count_tokens
from backend.services.knowledge.embedding import (
    EmbeddingUsage,
    ensure_vector_dimensions,
)

logger = logging.getLogger("webchat_ai")

_BASE_URL = "https://api.cohere.com/v2/embed"


class CohereEmbeddingClient:
    """`cohere_embedding_model` (default `embed-multilingual-v3.0`) via Cohere v2."""

    name = "cohere"

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        dimensions: int | None = None,
        timeout_seconds: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self._model = model or settings.cohere_embedding_model
        self._api_key = api_key if api_key is not None else settings.cohere_api_key
        self._dimensions = (
            dimensions if dimensions is not None else settings.cohere_embedding_dimensions
        )
        self._timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else settings.ai_provider_timeout_seconds
        )
        self._http_client = http_client
        self._usage = EmbeddingUsage()

    @property
    def usage(self) -> EmbeddingUsage:
        return self._usage

    @property
    def dimensions(self) -> int:
        """Embedding vector length (registry dimension-compatibility check)."""
        return self._dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed `texts` (one vector per input, in order)."""
        if not texts:
            return []
        api_key = self._api_key
        if not api_key:
            raise EmbeddingUnavailableError("COHERE_API_KEY is not configured.")
        client = self._http_client or shared_http_client(self._timeout_seconds)
        payload = {
            "model": self._model,
            "texts": texts,
            "input_type": "search_document",
            "embedding_types": ["float"],
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            response = await client.post(
                _BASE_URL,
                headers=headers,
                json=payload,
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise EmbeddingUnavailableError("Cohere request timed out.") from exc
        except httpx.TransportError as exc:
            raise EmbeddingUnavailableError(f"Cohere is unreachable: {exc}") from exc

        if response.status_code >= 400:
            await response.aread()
            if response.status_code in (401, 403, 429):
                raise EmbeddingUnavailableError(
                    f"Cohere rejected the request (HTTP {response.status_code})."
                )
            raise EmbeddingError(f"Cohere embedding failed (HTTP {response.status_code}).")
        data = response.json()

        parsed = self._parse_embeddings(data, len(texts))
        ensure_vector_dimensions("cohere", parsed, self._dimensions)
        self._record_usage(texts)
        return parsed

    @staticmethod
    def _parse_embeddings(data: Any, expected: int) -> list[list[float]]:
        """Extract the float vectors from a v2 (or v1-shaped) Cohere response."""
        if not isinstance(data, dict):
            raise EmbeddingError("Cohere returned a non-object response.")
        embeddings = data.get("embeddings")
        if isinstance(embeddings, dict):
            # v2: {"embeddings": {"float": [[...], ...]}}
            embeddings = embeddings.get("float")
        if not isinstance(embeddings, list) or len(embeddings) != expected:
            raise EmbeddingError(
                f"Cohere returned {len(embeddings) if isinstance(embeddings, list) else 'no'} "
                f"vectors for {expected} texts."
            )
        parsed: list[list[float]] = []
        for vector in embeddings:
            if not isinstance(vector, list):
                raise EmbeddingError("Cohere embedding item was not a vector.")
            parsed.append([float(value) for value in vector])
        return parsed

    async def health(self) -> bool:
        """Probe the provider with a single short text (returns, never raises)."""
        try:
            await self.embed(["health"])
            return True
        except Exception:  # noqa: BLE001 - health probes must not raise
            return False

    def _record_usage(self, texts: Sequence[str]) -> None:
        self._usage = EmbeddingUsage(
            calls=self._usage.calls + 1,
            characters=self._usage.characters + sum(len(text) for text in texts),
            estimated_tokens=self._usage.estimated_tokens
            + sum(count_tokens(text) for text in texts),
            failures=self._usage.failures,
        )


__all__ = ["CohereEmbeddingClient"]
