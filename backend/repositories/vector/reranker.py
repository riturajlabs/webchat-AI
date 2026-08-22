"""Embedding-based reranker for retrieval results.

After the initial vector search (or hybrid search), this module re-scores
the top-k candidates by computing query-chunk cosine similarity.  The
reranker accepts a precomputed query embedding and uses stored chunk
embeddings (from ``KnowledgeChunk.embedding``) to avoid redundant API
calls.  This is the optimized P0 path: no embedding API calls are made
during reranking.

The reranker is opt-in via ``enable_reranking`` in ``backend.core.config``.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Protocol

from backend.repositories.vector.base import VectorSearchResult

logger = logging.getLogger("webchat_ai")


class EmbeddingProvider(Protocol):
    """Minimal protocol for the embedding call used by the reranker."""

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class RerankMetrics:
    """Timing breakdown for a single rerank call."""

    rerank_ms: float = 0.0
    rerank_embedding_ms: float = 0.0
    input_count: int = 0
    output_count: int = 0


class EmbeddingReranker:
    """Re-rank search results using stored embeddings and cosine similarity.

    Accepts a precomputed query embedding and uses each candidate's stored
    ``KnowledgeChunk.embedding`` vector to score query-chunk similarity.
    No embedding API calls are made during reranking — only local cosine
    similarity computation.
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
        *,
        query_embedding: list[float] | None = None,
    ) -> tuple[list[VectorSearchResult], RerankMetrics]:
        """Re-score and return the top-k candidates.

        Parameters
        ----------
        query:
            The original user question (used for logging only).
        candidates:
            Results from the initial retrieval step (vector or hybrid).
        query_embedding:
            Precomputed embedding for ``query``.  When provided, stored
            chunk embeddings are used for cosine similarity (no API call).
            When ``None``, falls back to embedding query + chunk texts
            via the embedder (legacy path).

        Returns
        -------
        tuple[list[VectorSearchResult], RerankMetrics]
            The top-k candidates re-ordered by cosine similarity
            plus timing/count metrics.  If the embedder call fails, the
            original ordering is preserved.
        """
        input_count = len(candidates)
        rerank_start = time.perf_counter()

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "rerank_before query=%r candidate_count=%d",
                query,
                input_count,
            )
            for idx, cand in enumerate(candidates):
                logger.debug(
                    "rerank_candidate_before idx=%d chunk_id=%s title=%s "
                    "score=%.4f chunk_text_150=%r",
                    idx,
                    cand.chunk.id,
                    cand.chunk.metadata.get("title", ""),
                    cand.score,
                    cand.chunk.chunk_text[:150],
                )

        if not candidates or self._top_k <= 0:
            return candidates, RerankMetrics(
                input_count=input_count, output_count=input_count
            )

        limit = min(self._top_k, len(candidates))

        # Fast path: use precomputed query embedding + stored chunk embeddings.
        if query_embedding is not None:
            rerank_embedding_ms = 0.0
            scored: list[tuple[float, int]] = []
            for idx, candidate in enumerate(candidates):
                chunk_emb = candidate.chunk.embedding
                if not chunk_emb:
                    scored.append((0.0, idx))
                    continue
                sim = _cosine_similarity(query_embedding, chunk_emb)
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

            _log_rerank_after(query, reranked)
            return reranked, RerankMetrics(
                rerank_ms=(time.perf_counter() - rerank_start) * 1000.0,
                rerank_embedding_ms=rerank_embedding_ms,
                input_count=input_count,
                output_count=len(reranked),
            )

        # Legacy path: embed query + chunk texts (no precomputed embedding).
        texts = [query] + [c.chunk.chunk_text for c in candidates]

        try:
            emb_start = time.perf_counter()
            embeddings = await self._embedder.embed(texts)
            rerank_embedding_ms = (time.perf_counter() - emb_start) * 1000.0
        except Exception:
            rerank_embedding_ms = (time.perf_counter() - emb_start) * 1000.0
            logger.exception("reranker embed failed; falling back to original ranking")
            return candidates[:limit], RerankMetrics(
                rerank_ms=(time.perf_counter() - rerank_start) * 1000.0,
                rerank_embedding_ms=rerank_embedding_ms,
                input_count=input_count,
                output_count=min(limit, input_count),
            )

        if len(embeddings) != len(texts):
            logger.warning(
                "reranker embed count mismatch expected=%d got=%d",
                len(texts),
                len(embeddings),
            )
            return candidates[:limit], RerankMetrics(
                rerank_ms=(time.perf_counter() - rerank_start) * 1000.0,
                rerank_embedding_ms=rerank_embedding_ms,
                input_count=input_count,
                output_count=min(limit, input_count),
            )

        query_vec = embeddings[0]
        chunk_vecs = embeddings[1:]

        scored_legacy: list[tuple[float, int]] = []
        for idx, chunk_vec in enumerate(chunk_vecs):
            sim = _cosine_similarity(query_vec, chunk_vec)
            scored_legacy.append((sim, idx))

        scored_legacy.sort(key=lambda x: x[0], reverse=True)

        reranked_legacy: list[VectorSearchResult] = []
        for sim, orig_idx in scored_legacy[:limit]:
            original = candidates[orig_idx]
            reranked_legacy.append(
                VectorSearchResult(
                    chunk=original.chunk,
                    score=round(sim, 4),
                )
            )

        _log_rerank_after(query, reranked_legacy)
        return reranked_legacy, RerankMetrics(
            rerank_ms=(time.perf_counter() - rerank_start) * 1000.0,
            rerank_embedding_ms=rerank_embedding_ms,
            input_count=input_count,
            output_count=len(reranked_legacy),
        )


def _log_rerank_after(query: str, reranked: list[VectorSearchResult]) -> None:
    """Log post-rerank state when DEBUG is enabled."""
    if not logger.isEnabledFor(logging.DEBUG):
        return
    logger.debug(
        "rerank_after query=%r reranked_count=%d",
        query,
        len(reranked),
    )
    for idx, res in enumerate(reranked):
        logger.debug(
            "rerank_candidate_after idx=%d chunk_id=%s title=%s "
            "score=%.4f chunk_text_150=%r",
            idx,
            res.chunk.id,
            res.chunk.metadata.get("title", ""),
            res.score,
            res.chunk.chunk_text[:150],
        )


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


__all__ = ["EmbeddingReranker", "RerankMetrics"]
