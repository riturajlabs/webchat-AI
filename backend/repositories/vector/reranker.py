"""Embedding-based reranker for retrieval results.

After the initial vector search (or hybrid search), this module re-scores
the top-k candidates by computing query-chunk cosine similarity.  The
reranker accepts a precomputed query embedding and uses stored chunk
embeddings (from ``KnowledgeChunk.embedding``) to avoid redundant API
calls.  This is the optimized P0 path: no embedding API calls are made
during reranking.

The reranker is opt-in via ``enable_reranking`` in ``backend.core.config``.

Reranking is lexical-aware: cosine similarity remains the primary ranking
signal and the returned score (so ``CHAT_CONTEXT_MIN_SCORE`` semantics are
unchanged), but a candidate containing every content token of the query
(a strong keyword/entity match such as "chairperson" or "dean of SOIT")
is guaranteed a slot in the top-k output, so such a match cannot be
discarded solely because its stored embedding is semantically far from the
query.  For these protected candidates the upstream lexical/RRF evidence is
carried through on ``VectorSearchResult.lexical_score`` so downstream
score-type-aware gating (not the cosine threshold) can accept genuinely
strong lexical evidence.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Protocol

from backend.repositories.vector.base import VectorSearchResult
from backend.repositories.vector.hybrid import tokenize

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
            return candidates, RerankMetrics(input_count=input_count, output_count=input_count)

        limit = min(self._top_k, len(candidates))

        # Fast path: use precomputed query embedding + stored chunk embeddings.
        if query_embedding is not None:
            rerank_embedding_ms = 0.0
            query_tokens = tokenize(query)
            scored: list[tuple[float, int, bool]] = []
            for idx, candidate in enumerate(candidates):
                chunk_emb = candidate.chunk.embedding
                if not chunk_emb:
                    scored.append((0.0, idx, False))
                    continue
                sim = _cosine_similarity(query_embedding, chunk_emb)
                strong = _strong_lexical_match(query_tokens, candidate.chunk.chunk_text)
                scored.append((sim, idx, strong))

            reranked = _select_top_k(scored, limit, candidates)

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

        query_tokens = tokenize(query)
        scored_legacy: list[tuple[float, int, bool]] = []
        for idx, chunk_vec in enumerate(chunk_vecs):
            sim = _cosine_similarity(query_vec, chunk_vec)
            strong = _strong_lexical_match(query_tokens, candidates[idx].chunk.chunk_text)
            scored_legacy.append((sim, idx, strong))

        reranked_legacy = _select_top_k(scored_legacy, limit, candidates)

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
            "rerank_candidate_after idx=%d chunk_id=%s title=%s score=%.4f chunk_text_150=%r",
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
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _strong_lexical_match(query_tokens: list[str], chunk_text: str) -> bool:
    """True when a chunk contains every content token of the query.

    A lexical/entity match (e.g. "chairperson", "dean", "SOIT") that appears
    verbatim in a chunk is a strong, exact signal independent of embedding
    similarity. Pure-cosine reranking can wrongly discard such a chunk when
    its stored embedding is semantically far from the query (which is why the
    vector stage missed it). Protecting these matches ensures they are not
    dropped solely because their cosine is low.
    """
    if not query_tokens:
        return False
    text_tokens = set(tokenize(chunk_text))
    return all(token in text_tokens for token in query_tokens)


def _select_top_k(
    scored: list[tuple[float, int, bool]],
    limit: int,
    candidates: list[VectorSearchResult],
) -> list[VectorSearchResult]:
    """Pick the top-k candidates without discarding strong lexical matches.

    ``scored`` holds ``(cosine, index, strong_lexical)`` tuples. The primary
    ranking is still cosine (unchanged semantics); strong lexical matches are
    simply guaranteed a slot in the output so an exact entity match cannot be
    trimmed purely by low embedding similarity. The returned ``score`` stays
    the true cosine, so ``CHAT_CONTEXT_MIN_SCORE`` filtering is unaffected.

    Lexical/RRF evidence is carried through only for candidates that are both
    strong lexical matches AND were actually retrieved by the keyword pass
    (``lexical_score`` already set upstream). Unprotected candidates have
    ``lexical_score`` cleared, so a below-threshold chunk can never qualify
    for lexical evidence unless it is a genuine strong lexical match.
    """
    protected = sorted((s for s in scored if s[2]), key=lambda x: x[0], reverse=True)
    unprotected = sorted((s for s in scored if not s[2]), key=lambda x: x[0], reverse=True)
    ordered = protected + unprotected
    return [
        VectorSearchResult(
            chunk=candidates[idx].chunk,
            score=round(sim, 4),
            lexical_score=candidates[idx].lexical_score if _protected else None,
            dense_score=round(sim, 4),
            lexical_exact=_protected and candidates[idx].lexical_score is not None,
        )
        for sim, idx, _protected in ordered[:limit]
    ]


__all__ = ["EmbeddingReranker", "RerankMetrics"]
