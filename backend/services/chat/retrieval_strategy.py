"""Retrieval strategy abstraction for RAG pipeline.

Provides a pluggable strategy layer between the embedding/vector-search step
and the context-building step in ``RagService``.  Two strategies ship out of
the box:

- ``VectorRetrievalStrategy``: the current default (vector-only).
- ``HybridRetrievalStrategy``: combines vector similarity with keyword-based
  ranking via Reciprocal Rank Fusion (RRF).

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

    Wraps the existing ``HybridSearcher`` and adds keyword-based ranking
    on top of the vector results.  The RRF constant is configurable.

    RRF scores are rescaled to the [0, 1] range so the existing
    ``chat_context_min_score`` filter in ``RagService._build_context``
    continues to work correctly.  The rescaled score preserves the relative
    ordering from RRF while being comparable to cosine-similarity scores.
    """

    def __init__(self, *, rrf_k: int = 60) -> None:
        self._rrf_k = rrf_k

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

        searcher = HybridSearcher(rrf_k=self._rrf_k)
        hybrid_results = searcher.search(query, vector_results, all_chunks, top_k=top_k)

        # Rescale RRF scores to [0, 1] so the min_score filter in
        # _build_context works correctly.  RRF raw scores are typically
        # in the 0.01-0.03 range which would be dropped by a 0.25 floor.
        final = _rescale_rrf_scores(hybrid_results)

        return final, RetrievalMetricsInfo(
            retrieval_method="hybrid",
            vector_result_count=len(vector_results),
            keyword_result_count=len(all_chunks) if all_chunks else 0,
            final_result_count=len(final),
        )


def _rescale_rrf_scores(
    hybrid_results: list[HybridSearchResult],
) -> list[VectorSearchResult]:
    """Rescale RRF scores to [0, 1] range.

    RRF raw scores are typically in the 0.01-0.03 range, which would be
    dropped by the default ``chat_context_min_score=0.25`` filter.  This
    rescales the top result to 1.0 and the rest proportionally, preserving
    relative ordering while making scores compatible with the min_score
    floor in ``RagService._build_context``.
    """
    if not hybrid_results:
        return []

    # Extract RRF scores from HybridSearchResult objects.
    rrf_scores = [hr.rrf_score for hr in hybrid_results]
    max_score = max(rrf_scores) if rrf_scores else 1.0
    if max_score <= 0:
        max_score = 1.0

    return [
        VectorSearchResult(
            chunk=hr.chunk.chunk,
            score=round(rrf / max_score, 4),
        )
        for hr, rrf in zip(hybrid_results, rrf_scores, strict=True)
    ]


__all__ = [
    "HybridRetrievalStrategy",
    "RetrievalMetricsInfo",
    "RetrievalStrategy",
    "VectorRetrievalStrategy",
]
