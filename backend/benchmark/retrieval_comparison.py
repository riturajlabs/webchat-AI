"""Retrieval comparison framework: vector-only vs keyword-only vs hybrid.

Runs the same query through three retrieval strategies and captures
per-method metrics so the caller can compare quality.  All operations are
pure in-memory — no network, no MongoDB, no production state mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from backend.repositories.vector.base import VectorSearchResult
from backend.repositories.vector.hybrid import (
    HybridSearcher,
    keyword_search,
)


class RetrievalMethod(StrEnum):
    """Which retrieval strategy produced a result set."""

    VECTOR = "vector"
    KEYWORD = "keyword"
    HYBRID = "hybrid"


@dataclass(frozen=True)
class RetrievalMethodResult:
    """Outcome of a single retrieval method for one query."""

    method: RetrievalMethod
    results: list[VectorSearchResult]
    chunk_count: int = 0
    avg_score: float = 0.0
    unique_source_urls: int = 0


@dataclass(frozen=True)
class RetrievalComparisonResult:
    """Side-by-side comparison of three retrieval strategies for one query."""

    query: str
    vector: RetrievalMethodResult
    keyword: RetrievalMethodResult
    hybrid: RetrievalMethodResult
    overlap_vector_keyword: int = 0
    overlap_hybrid_vector: int = 0
    overlap_hybrid_keyword: int = 0


def compare_retrieval_methods(
    query: str,
    vector_results: list[VectorSearchResult],
    all_chunks: list[VectorSearchResult],
    *,
    top_k: int = 5,
    rrf_k: int = 60,
) -> RetrievalComparisonResult:
    """Run vector, keyword, and hybrid retrieval on the same query.

    Parameters
    ----------
    query:
        User question text.
    vector_results:
        Pre-computed vector search results (from the existing pipeline).
    all_chunks:
        Full candidate set for keyword scoring.
    top_k:
        Maximum results per method.
    rrf_k:
        RRF constant for hybrid fusion.

    Returns
    -------
    RetrievalComparisonResult
        Side-by-side metrics for all three methods.
    """
    # Vector-only
    vector_mr = _build_method_result(RetrievalMethod.VECTOR, vector_results, top_k)

    # Keyword-only
    kw_results = keyword_search(query, all_chunks, top_k=top_k)
    keyword_mr = _build_method_result(RetrievalMethod.KEYWORD, kw_results, top_k)

    # Hybrid (RRF)
    searcher = HybridSearcher(rrf_k=rrf_k)
    hybrid_raw = searcher.search(query, vector_results, all_chunks, top_k=top_k)
    hybrid_results = [hr.chunk for hr in hybrid_raw]
    hybrid_mr = _build_method_result(RetrievalMethod.HYBRID, hybrid_results, top_k)

    # Overlap counts
    v_urls = _result_urls(vector_mr.results)
    k_urls = _result_urls(keyword_mr.results)
    h_urls = _result_urls(hybrid_mr.results)

    return RetrievalComparisonResult(
        query=query,
        vector=vector_mr,
        keyword=keyword_mr,
        hybrid=hybrid_mr,
        overlap_vector_keyword=len(v_urls & k_urls),
        overlap_hybrid_vector=len(h_urls & v_urls),
        overlap_hybrid_keyword=len(h_urls & k_urls),
    )


def _build_method_result(
    method: RetrievalMethod,
    results: list[VectorSearchResult],
    top_k: int,
) -> RetrievalMethodResult:
    """Build a ``RetrievalMethodResult`` from raw search results."""
    truncated = results[:top_k]
    avg = (
        round(sum(r.score for r in truncated) / len(truncated), 4) if truncated else 0.0
    )
    urls = {r.chunk.metadata.get("source_url", "") for r in truncated if r.chunk.metadata}
    return RetrievalMethodResult(
        method=method,
        results=truncated,
        chunk_count=len(truncated),
        avg_score=avg,
        unique_source_urls=len(urls - {""}),
    )


def _result_urls(results: list[VectorSearchResult]) -> set[str]:
    """Extract unique non-empty source URLs from results."""
    return {
        r.chunk.metadata.get("source_url", "")
        for r in results
        if r.chunk.metadata and r.chunk.metadata.get("source_url")
    }


__all__ = [
    "RetrievalComparisonResult",
    "RetrievalMethod",
    "RetrievalMethodResult",
    "compare_retrieval_methods",
]
