"""Retrieval strategy abstraction for RAG pipeline.

Provides a pluggable strategy layer between the embedding/vector-search step
and the context-building step in ``RagService``.  Two strategies ship out of
the box:

- ``HybridRetrievalStrategy``: combines vector similarity with keyword-based
  ranking via Reciprocal Rank Fusion (RRF).  This is the deployed default
  (``enable_hybrid_search`` defaults to ``True``).
- ``VectorRetrievalStrategy``: the vector-only fallback used when
  ``enable_hybrid_search`` is disabled.

The feature flag ``enable_hybrid_search`` in ``backend.core.config`` controls
which strategy is active.  When disabled, ``VectorRetrievalStrategy`` is used
and the pipeline behaves identically to the pre-integration baseline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.repositories.vector.base import VectorSearchResult
from backend.repositories.vector.hybrid import HybridSearcher, HybridSearchResult


@dataclass(frozen=True)
class RetrievalMetricsInfo:
    """Structured metrics attached to a retrieval call for timing logs."""

    retrieval_method: str = "vector"
    vector_result_count: int = 0
    keyword_result_count: int = 0
    final_result_count: int = 0
    hybrid_candidate_count: int = 0


class RetrievalStrategy(Protocol):
    """Protocol for pluggable retrieval strategies."""

    def search(
        self,
        *,
        query: str,
        vector_results: list[VectorSearchResult],
        all_chunks: list[VectorSearchResult] | None = None,
        top_k: int = 5,
    ) -> tuple[list[VectorSearchResult], RetrievalMetricsInfo]:
        """Refine or pass through vector results.

        Parameters
        ----------
        query:
            The original user question (used by keyword strategies).
        vector_results:
            Pre-computed vector similarity results.
        all_chunks:
            All candidate chunks for the tenant/website.  Used by hybrid
            strategies for keyword scoring.  May be ``None`` for vector-only.
        top_k:
            Maximum results to return.

        Returns
        -------
        tuple[list[VectorSearchResult], RetrievalMetricsInfo]
            The final ranked results and per-call metrics.
        """


class VectorRetrievalStrategy:
    """Vector-only retrieval — the current default.

    Passes vector results through unchanged.  This is the baseline behavior
    when ``enable_hybrid_search`` is ``False``.
    """

    def search(
        self,
        *,
        query: str,
        vector_results: list[VectorSearchResult],
        all_chunks: list[VectorSearchResult] | None = None,
        top_k: int = 5,
    ) -> tuple[list[VectorSearchResult], RetrievalMetricsInfo]:
        return vector_results, RetrievalMetricsInfo(
            retrieval_method="vector",
            vector_result_count=len(vector_results),
            keyword_result_count=0,
            final_result_count=len(vector_results),
        )


class HybridRetrievalStrategy:
    """Hybrid retrieval: vector + keyword via Reciprocal Rank Fusion.

    Wraps the existing ``HybridSearcher`` and adds keyword-based retrieval
    over the website's full corpus (``all_chunks``) as a genuine second
    retrieval source, so exact-term matches the vector stage missed can be
    recovered. The RRF constant and keyword candidate limit are configurable.

    RRF determines the ordering. The original vector score is retained for
    chunks that also came from the vector stage (used for context filtering and
    confidence decisions); keyword-only chunks carry their RRF fusion score.
    """

    def __init__(
        self, *, rrf_k: int = 60, keyword_top_k: int = 50, candidate_top_k: int | None = None
    ) -> None:
        self._rrf_k = rrf_k
        self._keyword_top_k = keyword_top_k
        self._candidate_top_k = candidate_top_k

    def search(
        self,
        *,
        query: str,
        vector_results: list[VectorSearchResult],
        all_chunks: list[VectorSearchResult] | None = None,
        top_k: int = 5,
    ) -> tuple[list[VectorSearchResult], RetrievalMetricsInfo]:
        if not vector_results:
            return vector_results, RetrievalMetricsInfo(
                retrieval_method="hybrid",
                vector_result_count=0,
                keyword_result_count=0,
                final_result_count=0,
            )

        searcher = HybridSearcher(rrf_k=self._rrf_k, keyword_top_k=self._keyword_top_k)
        # When the full corpus is supplied, expand the RRF candidate pool past
        # ``top_k`` so keyword-only exact matches that RRF ranks below ``top_k``
        # still reach the downstream reranker, which then selects the final
        # ``top_k``. With no corpus, behavior is unchanged (pool == top_k).
        pool = (
            self._candidate_top_k if (all_chunks and self._candidate_top_k is not None) else top_k
        )
        hybrid_results = searcher.search(
            query, vector_results, all_chunks, top_k=top_k, candidate_top_k=pool
        )

        # RRF is a rank signal, not a similarity score. Preserve the original
        # vector score so a weak nearest neighbor cannot become 1.0 merely
        # because it was first in the fused ranking.
        final = _preserve_vector_scores(hybrid_results, vector_results)

        keyword_count = min(len(vector_results), top_k)
        return final, RetrievalMetricsInfo(
            retrieval_method="hybrid",
            vector_result_count=len(vector_results),
            keyword_result_count=keyword_count,
            final_result_count=len(final),
            hybrid_candidate_count=len(vector_results),
        )


def _preserve_vector_scores(
    hybrid_results: list[HybridSearchResult],
    vector_results: list[VectorSearchResult],
) -> list[VectorSearchResult]:
    """Keep RRF ordering while restoring each candidate's vector score."""
    if not hybrid_results:
        return []

    vector_scores = {result.chunk.id: result.score for result in vector_results}

    return [
        VectorSearchResult(
            chunk=hr.chunk.chunk,
            # Restore the original vector score for chunks that also came from
            # the vector stage. Keyword-only chunks recovered from the full
            # corpus have no vector score, so keep their RRF fusion score
            # (instead of 0.0) so they remain present in the result set.
            score=vector_scores.get(hr.chunk.chunk.id, hr.rrf_score),
            # Explicit lexical/RRF evidence, retained separately from ``score``
            # so the downstream gate can be score-type-aware. Only candidates
            # the keyword pass actually retrieved carry this evidence; vector
            # cosine remains the sole signal for everything else.
            lexical_score=(hr.rrf_score if hr.keyword_rank >= 1 else None),
            dense_score=vector_scores.get(hr.chunk.chunk.id),
        )
        for hr in hybrid_results
    ]


__all__ = [
    "HybridRetrievalStrategy",
    "RetrievalMetricsInfo",
    "RetrievalStrategy",
    "VectorRetrievalStrategy",
]
