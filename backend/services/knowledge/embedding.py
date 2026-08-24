"""Embedding generation for the knowledge base (Phase 5, ADR-008).

`GoogleEmbeddingClient` calls `gemini-embedding-001` through the Google GenAI
async SDK (`client.aio.models.embed_content`). Texts are sent in configurable
batches, each batch retried with exponential backoff and jitter, and every
successful batch reports usage through an optional hook. Application code
depends on the `EmbeddingClient` Protocol only - the worker receives a client
via its container (`ctx["embedding_client"]`), keeping the Google SDK out of
the processor core. The API key comes from settings (env) and is never logged
or returned (00-AI-Development-Rules §12, §20).
"""

import asyncio
import hashlib
import logging
import random
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from backend.core.config import get_settings
from backend.core.embedding_identity import EmbeddingIdentity, ensure_embedding_compatibility
from backend.core.errors import (
    EmbeddingError,
    EmbeddingUnavailableError,
)
from backend.services.knowledge.chunker import count_tokens

logger = logging.getLogger("webchat_ai")

# Audit R-09: in-process memo of successfully embedded texts (text hash ->
# vector). Purely in-memory on the client instance - no storage architecture
# change - bounded so long-running workers cannot grow it without limit.
_MEMO_MAX_ENTRIES = 1024


def ensure_vector_dimensions(
    provider_name: str,
    vectors: list[list[float]],
    expected_dimensions: int,
) -> None:
    """Reject vectors whose length differs from the configured index dimension.

    MongoDB `$vectorSearch` indexes a fixed vector length; silently inserting
    vectors of another length (e.g. after an embedding-provider fallback)
    corrupts retrieval. Raises a clear `EmbeddingError` before any vector is
    committed (ADR-009, docs/EMBEDDING_PROVIDERS.md).
    """
    if not vectors:
        return
    mismatches = {
        len(vector)
        for vector in vectors
        if len(vector) != expected_dimensions
    }
    if mismatches:
        raise EmbeddingError(
            f"Embedding dimension mismatch: {provider_name} returned dimensions "
            f"{sorted(mismatches)}, configured index expects {expected_dimensions}."
        )


@dataclass(frozen=True)
class EmbeddingUsage:
    """Aggregate embedding-API usage so far (hooks, ADR-008 token capture)."""

    calls: int = 0
    characters: int = 0
    estimated_tokens: int = 0
    failures: int = 0


class EmbeddingClient(Protocol):
    """Async embedding interface. Never raises raw SDK errors."""

    @property
    def usage(self) -> EmbeddingUsage:
        """Aggregate usage so far (Phase 9 fallback reads the serving provider)."""
        ...

    @property
    def embedding_identity(self) -> EmbeddingIdentity:
        """Identity of the provider/model used for the most recent embedding."""
        ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class GoogleEmbeddingClient:
    """`gemini-embedding-001` via the Google GenAI async SDK."""

    name = "gemini"

    def __init__(
        self,
        *,
        model: str | None = None,
        batch_size: int | None = None,
        max_retries: int | None = None,
        base_delay_ms: int | None = None,
        timeout_seconds: float | None = None,
        dimensions: int | None = None,
        on_usage: Callable[[EmbeddingUsage], None] | None = None,
        genai_client: Any | None = None,
    ) -> None:
        settings = get_settings()
        self._model = model or settings.embedding_model
        self._batch_size = batch_size or settings.embedding_batch_size
        self._max_retries = (
            max_retries if max_retries is not None else settings.embedding_max_retries
        )
        self._base_delay_ms = base_delay_ms or settings.embedding_retry_base_delay_ms
        self._timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.embedding_request_timeout_seconds
        )
        self._dimensions = (
            dimensions if dimensions is not None else settings.gemini_embedding_dimensions
        )
        self._on_usage = on_usage
        self._genai_client = genai_client
        self._usage = EmbeddingUsage()
        # Audit R-09: texts embedded successfully by THIS client instance.
        # When a later batch of the same document fails and the processor
        # schedules a document-level retry, already-embedded batches are
        # served from this memo instead of being re-embedded (and re-billed).
        self._memo: OrderedDict[str, list[float]] = OrderedDict()

    def _memo_key(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _memo_put(self, text: str, vector: list[float]) -> None:
        key = self._memo_key(text)
        self._memo[key] = vector
        self._memo.move_to_end(key)
        while len(self._memo) > _MEMO_MAX_ENTRIES:
            self._memo.popitem(last=False)

    @property
    def usage(self) -> EmbeddingUsage:
        return self._usage

    @property
    def dimensions(self) -> int:
        """Embedding vector length (Phase 9 dimension-compatibility check)."""
        return self._dimensions

    @property
    def embedding_identity(self) -> EmbeddingIdentity:
        return EmbeddingIdentity(
            provider=self.name,
            model=self._model,
            dimensions=self._dimensions,
            version=getattr(get_settings(), "embedding_version", "1"),
        )

    def _client(self) -> Any:
        """Lazily build the SDK client (never touches network until first call)."""
        if self._genai_client is None:
            api_key = get_settings().gemini_api_key
            if not api_key:
                raise EmbeddingUnavailableError(
                    "GEMINI_API_KEY is not configured; cannot generate embeddings."
                )
            from google.genai import Client

            self._genai_client = Client(api_key=api_key)
        return self._genai_client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed `texts` in batches, retrying each batch with backoff.

        Returns one vector per input text, in order. Raises `EmbeddingError`
        when a batch exhausts its retries or the client is misconfigured.

        Audit R-09: texts this client instance already embedded successfully
        are served from the in-memory memo, so a document-level retry after a
        mid-document batch failure only re-embeds the batches that never
        succeeded. The retry policy itself (per-batch backoff + document-level
        deferred retries) is unchanged.
        """
        if not texts:
            return []
        slots: list[list[float] | None] = [None] * len(texts)
        pending: list[str] = []
        queued: set[str] = set()
        for i, text in enumerate(texts):
            key = self._memo_key(text)
            cached = self._memo.get(key)
            if cached is not None:
                self._memo.move_to_end(key)
                slots[i] = cached
            elif text not in queued:
                # Duplicate uncached texts are embedded once and shared.
                pending.append(text)
                queued.add(text)
        for start in range(0, len(pending), self._batch_size):
            batch = pending[start : start + self._batch_size]
            embedded = await self._embed_batch(batch)
            for text, vector in zip(batch, embedded, strict=True):
                self._memo_put(text, vector)
        final: list[list[float]] = []
        for i, text in enumerate(texts):
            slot = slots[i]
            vector = slot if slot is not None else self._memo[self._memo_key(text)]
            if vector is None:  # pragma: no cover - every slot is filled above
                raise EmbeddingError("Embedding assembly failed for a batch text.")
            final.append(vector)
        return final

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        last_error: Exception | None = None
        batch_characters = sum(len(text) for text in batch)
        batch_tokens = sum(count_tokens(text) for text in batch)
        for attempt in range(self._max_retries):
            try:
                # Truncate Gemini's output to EMBEDDING_DIMENSIONS so every
                # provider in the fallback chain emits the same vector length
                # (the MongoDB index dimension). gemini-embedding-001 supports
                # 1..3072 dimensions; the default 3072 is sent only implicitly
                # (omitted) so existing 3072-index deployments see no change.
                config: dict[str, int] | None = None
                if self._dimensions and self._dimensions != 3072:
                    config = {"output_dimensionality": self._dimensions}
                vectors = await asyncio.wait_for(
                    self._client().aio.models.embed_content(
                        model=self._model, contents=batch, config=config
                    ),
                    timeout=self._timeout_seconds,
                )
                parsed = self._parse_response(vectors, len(batch))
                self._record_usage(1, batch_characters, batch_tokens)
                return parsed
            except EmbeddingUnavailableError:
                # Configuration error (e.g. missing API key): fail fast, no
                # retries or backoff - retrying cannot fix a bad config.
                raise
            except Exception as exc:  # noqa: BLE001 - normalized below
                last_error = exc
                if attempt < self._max_retries - 1:
                    delay = self._backoff_ms(attempt) / 1000.0
                    logger.warning(
                        "embedding batch failed (attempt %s/%s): %s; retrying in %.2fs",
                        attempt + 1,
                        self._max_retries,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
        self._record_usage(0, 0, 0, failures=1)
        raise EmbeddingError(
            f"Embedding request failed after {self._max_retries} attempts: {last_error}"
        )

    def _parse_response(self, response: Any, expected: int) -> list[list[float]]:
        embeddings = getattr(response, "embeddings", None)
        if not embeddings:
            raise EmbeddingError("Embedding response contained no embeddings.")
        values: list[list[float]] = []
        for item in embeddings:
            vector = getattr(item, "values", None)
            if vector is None:
                raise EmbeddingError("Embedding response item had no values.")
            values.append([float(v) for v in vector])
        if len(values) != expected:
            raise EmbeddingError(
                f"Embedding response returned {len(values)} vectors for {expected} texts."
            )
        ensure_vector_dimensions("gemini", values, self._dimensions)
        return values

    def _record_usage(
        self,
        calls: int,
        characters: int,
        estimated_tokens: int,
        *,
        failures: int = 0,
    ) -> None:
        self._usage = EmbeddingUsage(
            calls=self._usage.calls + calls,
            characters=self._usage.characters + characters,
            estimated_tokens=self._usage.estimated_tokens + estimated_tokens,
            failures=self._usage.failures + failures,
        )
        if self._on_usage is not None:
            self._on_usage(self._usage)

    def _backoff_ms(self, attempt: int) -> int:
        """Exponential backoff with full jitter (base * 2^attempt * [0,1))."""
        cap = self._base_delay_ms * (2**attempt)
        return int(random.uniform(0, cap)) if cap > 0 else 0


__all__ = [
    "EmbeddingIdentity",
    "EmbeddingClient",
    "EmbeddingUsage",
    "GoogleEmbeddingClient",
    "ensure_embedding_compatibility",
    "ensure_vector_dimensions",
]
