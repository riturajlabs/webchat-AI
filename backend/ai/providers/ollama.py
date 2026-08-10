"""Ollama embedding generation (Phase 9, ADR-009).

`OllamaEmbeddingClient` implements the `EmbeddingClient` Protocol
(`backend/services/knowledge/embedding.py`) using a self-hosted Ollama
server (`/api/embed`), so it can serve as a no-API-key fallback in the Phase 9
embedding chain. It is intended as a *local/secondary* provider: its vector
dimension differs from `gemini-embedding-001` (768 vs 3072), so the registry
warns loudly when a mixed-dimension chain is configured.

Raw `httpx` errors are normalized to `EmbeddingError`/
`EmbeddingUnavailableError` (00-AI-Development-Rules §18).
"""

import logging
from collections.abc import Sequence

import httpx

from backend.ai.providers.openai_compat import shared_http_client
from backend.core.config import get_settings
from backend.core.errors import EmbeddingError, EmbeddingUnavailableError
from backend.services.knowledge.chunker import count_tokens
from backend.services.knowledge.embedding import EmbeddingUsage

logger = logging.getLogger("webchat_ai")


class OllamaEmbeddingClient:
    """`ollama_model` (default `nomic-embed-text`) via a local Ollama server."""

    name = "ollama"

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self._model = model or settings.ollama_model
        self._base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self._timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.ai_provider_timeout_seconds
        )
        self._http_client = http_client
        self._dimensions = settings.ollama_embedding_dimensions
        self._usage = EmbeddingUsage()

    @property
    def usage(self) -> EmbeddingUsage:
        return self._usage

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed `texts` (one vector per input, in order)."""
        if not texts:
            return []
        client = self._http_client or shared_http_client(self._timeout_seconds)
        payload = {"model": self._model, "input": texts}
        try:
            response = await client.post(
                f"{self._base_url}/api/embed",
                json=payload,
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise EmbeddingUnavailableError("Ollama request timed out.") from exc
        except httpx.TransportError as exc:
            raise EmbeddingUnavailableError(f"Ollama is unreachable: {exc}") from exc

        if response.status_code >= 400:
            await response.aread()
            if response.status_code in (401, 403, 429):
                raise EmbeddingUnavailableError(
                    f"Ollama rejected the request (HTTP {response.status_code})."
                )
            raise EmbeddingError(
                f"Ollama embedding failed (HTTP {response.status_code})."
            )
        data = response.json()

        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise EmbeddingError(
                f"Ollama returned {len(embeddings) if isinstance(embeddings, list) else 'no'} "
                f"vectors for {len(texts)} texts."
            )
        parsed = [[float(value) for value in vector] for vector in embeddings]
        if parsed and len(parsed[0]) != self._dimensions:
            logger.warning(
                "Ollama returned %s-dim vectors but EMBEDDING_DIMENSIONS=%s is assumed; "
                "vector search consistency is the operator's responsibility.",
                len(parsed[0]),
                self._dimensions,
            )
        self._record_usage(texts)
        return parsed

    def _record_usage(self, texts: Sequence[str]) -> None:
        self._usage = EmbeddingUsage(
            calls=self._usage.calls + 1,
            characters=self._usage.characters + sum(len(text) for text in texts),
            estimated_tokens=self._usage.estimated_tokens
            + sum(count_tokens(text) for text in texts),
            failures=self._usage.failures,
        )


__all__ = ["OllamaEmbeddingClient"]
