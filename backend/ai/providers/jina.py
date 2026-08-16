"""Jina AI embeddings (cloud fallback provider, ADR-009).

`JinaEmbeddingClient` implements the `EmbeddingClient` Protocol
(`backend/services/knowledge/embedding.py`) using Jina's `v1/embeddings`
REST API (`jina-embeddings-v3`), slotting into the Phase 9 embedding fallback
chain after Gemini. It is a cloud provider: it needs `JINA_API_KEY`, supports
a configurable output dimension (`JINA_EMBEDDING_DIMENSIONS`, default 1024,
matching `EMBEDDING_DIMENSIONS`), and returns 1024-dim vectors for
`jina-embeddings-v3`.

The API key comes from settings (env) and is never logged or exposed
(00-AI-Development-Rules §12, §20); raw `httpx` errors are normalized to
`EmbeddingError`/`EmbeddingUnavailableError` (§18). Timeouts, rate limits
(429), quota exhaustion (402) and auth failures (401/403) surface as
`EmbeddingUnavailableError` so the fallback chain moves on to the next
provider. Returned vectors are validated against the configured dimension
before use (docs/EMBEDDING_PROVIDERS.md).
"""

import logging
from collections.abc import Sequence

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

_BASE_URL = "https://api.jina.ai/v1/embeddings"


class JinaEmbeddingClient:
    """`jina_embedding_model` (default `jina-embeddings-v3`) via the Jina API."""

    name = "jina"

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
        self._model = model or settings.jina_embedding_model
        self._api_key = api_key if api_key is not None else settings.jina_api_key
        self._dimensions = (
            dimensions if dimensions is not None else settings.jina_embedding_dimensions
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
            raise EmbeddingUnavailableError("JINA_API_KEY is not configured.")
        client = self._http_client or shared_http_client(self._timeout_seconds)
        payload = {
            "model": self._model,
            "input": texts,
            "dimensions": self._dimensions,
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
            raise EmbeddingUnavailableError("Jina request timed out.") from exc
        except httpx.TransportError as exc:
            raise EmbeddingUnavailableError(f"Jina is unreachable: {exc}") from exc

        if response.status_code >= 400:
            await response.aread()
            if response.status_code in (401, 402, 403, 429):
                raise EmbeddingUnavailableError(
                    f"Jina rejected the request (HTTP {response.status_code})."
                )
            raise EmbeddingError(f"Jina embedding failed (HTTP {response.status_code}).")
        data = response.json()

        raw_embeddings = data.get("data") if isinstance(data, dict) else None
        if not isinstance(raw_embeddings, list) or len(raw_embeddings) != len(texts):
            count = len(raw_embeddings) if isinstance(raw_embeddings, list) else "no"
            raise EmbeddingError(f"Jina returned {count} vectors for {len(texts)} texts.")
        parsed = [
            [float(value) for value in item["embedding"]]
            for item in raw_embeddings
            if isinstance(item, dict) and isinstance(item.get("embedding"), list)
        ]
        if len(parsed) != len(texts):
            raise EmbeddingError(
                f"Jina returned {len(parsed)} usable vectors for {len(texts)} texts."
            )
        ensure_vector_dimensions("jina", parsed, self._dimensions)
        self._record_usage(texts)
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


__all__ = ["JinaEmbeddingClient"]
