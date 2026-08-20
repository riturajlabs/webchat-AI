"""Embedding-based reranker for retrieval results.

After the initial vector search (or hybrid search), this module re-scores
the top-k candidates by computing query-chunk cosine similarity using the
embedding model.  This acts as a lightweight second-pass ranker: the
initial retrieval uses a single query embedding against pre-computed chunk
embeddings, while the reranker embeds both query and chunk texts in a fresh
call, which can correct ranking errors from the first pass.

The reranker is opt-in via ``enable_reranking`` in ``backend.core.config``.
"""

from __future__ import annotations

import logging
import math
from typing import Protocol

from backend.repositories.vector.base import VectorSearchResult

logger = logging.getLogger("webchat_ai")


class EmbeddingProvider(Protocol):
    """Minimal protocol for the embedding call used by the reranker."""

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class EmbeddingReranker:
    """Re-rank search results using the embedding model.

    Embeds the query and all candidate chunk texts in a single batch call,
    then scores each (query, chunk) pair via cosine similarity.  The
    reranked results replace the original ordering.
    """

    def __init__(
        self,
        *,
        embedder: EmbeddingProvider,
        top_k: int = 5,
    ) -> None:
        self._embedder = embedder
        self._top_k = top_k

    async def rerank(
        self,
        query: str,
        candidates: list[VectorSearchResult],
    ) -> list[VectorSearchResult]:
        """Re-score and return the top-k candidates.

        Parameters
        ----------
        query:
            The original user question.
        candidates:
            Results from the initial retrieval step (vector or hybrid).

        Returns
        -------
        list[VectorSearchResult]
            The top-k candidates re-ordered by embedding-model similarity.
            If the embedder call fails, the original ordering is preserved.
        """
        if not candidates or self._top_k <= 0:
            return candidates

        limit = min(self._top_k, len(candidates))
        texts = [query] + [c.chunk.chunk_text for c in candidates]

        try:
            embeddings = await self._embedder.embed(texts)
        except Exception:
            logger.exception("reranker embed failed; falling back to original ranking")
            return candidates[:limit]

        if len(embeddings) != len(texts):
            logger.warning(
                "reranker embed count mismatch expected=%d got=%d",
                len(texts),
                len(embeddings),
            )
            return candidates[:limit]

        query_vec = embeddings[0]
        chunk_vecs = embeddings[1:]

        scored: list[tuple[float, int]] = []
        for idx, chunk_vec in enumerate(chunk_vecs):
            sim = _cosine_similarity(query_vec, chunk_vec)
            scored.append((sim, idx))

        scored.sort(key=lambda x: x[0], reverse=True)

        reranked: list[VectorSearchResult] = []
        for sim, orig_idx in scored[:limit]:
            original = candidates[orig_idx]
            reranked.append(
                VectorSearchResult(
                    chunk=original.chunk,
                    score=round(sim, 4),
                )
            )

        return reranked


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


__all__ = ["EmbeddingReranker"]
