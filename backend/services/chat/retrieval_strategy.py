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

    Wraps the existing ``HybridSearcher`` and adds keyword-based ranking
    on top of the vector results.  The RRF constant is configurable.

    Keyword matching is restricted to the vector candidate set, so hybrid
    ranking cannot introduce unrelated website chunks. RRF determines the
    ordering, while the original vector score is retained for context
    filtering and confidence decisions.
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
            score=vector_scores.get(hr.chunk.chunk.id, 0.0),
        )
        for hr in hybrid_results
    ]


__all__ = [
    "HybridRetrievalStrategy",
    "RetrievalMetricsInfo",
    "RetrievalStrategy",
    "VectorRetrievalStrategy",
]
