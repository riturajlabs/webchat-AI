"""Hybrid search: vector similarity + keyword relevance via Reciprocal Rank Fusion.

Combines the strengths of semantic vector search (understanding meaning) with
keyword matching (exact term hits) using RRF.  The current vector-only path
remains the default — hybrid search is opt-in and available as an alternative
ranking strategy for benchmarking and evaluation.

References
----------
- Cormack, V.A., Clarke, C.L.A., & Butt, S. (2009).
  "Feature-Based Route Merging with Reciprocal Rank Fusion."
  ``https://dl.acm.org/doi/10.1145/1571941.1572114``
"""

from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass

from backend.repositories.vector.base import VectorSearchResult

logger = logging.getLogger("webchat_ai")

# ---------------------------------------------------------------------------
# RRF core
# ---------------------------------------------------------------------------

DEFAULT_RRF_K = 60


def reciprocal_rank_fusion(
    rankings: list[list[VectorSearchResult]],
    *,
    k: int = DEFAULT_RRF_K,
) -> list[VectorSearchResult]:
    """Combine multiple ranked lists via Reciprocal Rank Fusion.

    Each result is identified by its chunk id.  When the same chunk appears
    in multiple rankings its RRF scores are summed.  The combined score is
    ``sum(1 / (k + rank_i))`` across all rankings where the chunk appears.

    Parameters
    ----------
    rankings:
        Two or more pre-ranked result lists.  Empty lists are silently
        ignored — the fusion degrades gracefully to the non-empty ranking(s).
    k:
        RRF constant (default 60, standard in literature).  Higher values
        reduce the impact of top-ranked positions.

    Returns
    -------
    list[VectorSearchResult]
        Fused results sorted by descending RRF score.
    """
    if not rankings:
        return []

    rrf_scores: dict[str, float] = defaultdict(float)
    chunk_map: dict[str, VectorSearchResult] = {}

    for ranking in rankings:
        for rank, result in enumerate(ranking):
            cid = result.chunk.id
            rrf_scores[cid] += 1.0 / (k + rank + 1)
            # Keep the version with the highest original score for tie-breaking
            if cid not in chunk_map or result.score > chunk_map[cid].score:
                chunk_map[cid] = result

    fused = [
        VectorSearchResult(chunk=chunk_map[cid].chunk, score=score)
        for cid, score in sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    ]
    return fused


# ---------------------------------------------------------------------------
# Keyword search
# ---------------------------------------------------------------------------

_STOP_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "and",
        "but",
        "or",
        "nor",
        "not",
        "so",
        "yet",
        "both",
        "either",
        "neither",
        "each",
        "every",
        "all",
        "any",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "only",
        "own",
        "same",
        "than",
        "too",
        "very",
        "just",
        "because",
        "if",
        "when",
        "where",
        "how",
        "what",
        "which",
        "who",
        "whom",
        "this",
        "that",
        "these",
        "those",
        "i",
        "you",
        "he",
        "she",
        "it",
        "we",
        "they",
        "me",
        "him",
        "her",
        "us",
        "them",
        "my",
        "your",
        "his",
        "its",
        "our",
        "their",
    }
)

_WORD_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, remove stop words, return content tokens."""
    words = _WORD_RE.findall(text.lower())
    return [w for w in words if w not in _STOP_WORDS]


def keyword_search(
    query: str,
    chunks: list[VectorSearchResult],
    *,
    top_k: int = 5,
) -> list[VectorSearchResult]:
    """Score chunks by keyword overlap with the query.

    Uses TF-IDF-inspired scoring: each query token matched in a chunk's text
    contributes ``1 / sqrt(chunk_text_token_count)`` to the score (length
    normalization).  Returns the *top_k* highest-scoring chunks sorted
    descending.

    Parameters
    ----------
    query:
        User question text.
    chunks:
        Candidate chunks to rank (e.g. all chunks for a tenant/website).
    top_k:
        Maximum results to return.
    """
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    scored: list[tuple[float, VectorSearchResult]] = []
    for result in chunks:
        text_tokens = tokenize(result.chunk.chunk_text)
        if not text_tokens:
            scored.append((0.0, result))
            continue
        text_freq: dict[str, int] = defaultdict(int)
        for t in text_tokens:
            text_freq[t] += 1
        # Sum IDF-weighted frequency for query tokens present in the chunk
        score = 0.0
        for qt in query_tokens:
            if qt in text_freq:
                score += text_freq[qt] / math.sqrt(len(text_tokens))
        scored.append((score, result))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [VectorSearchResult(chunk=r.chunk, score=s) for s, r in scored[:top_k] if s > 0.0]


# ---------------------------------------------------------------------------
# Hybrid searcher
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HybridSearchResult:
    """Result from a hybrid search with per-source scores."""

    chunk: VectorSearchResult
    vector_rank: int
    keyword_rank: int
    rrf_score: float


@dataclass
class HybridSearcher:
    """Orchestrates vector + keyword search with RRF fusion.

    Wraps any ``VectorRepository``-like object (protocol-compatible) and adds
    keyword ranking on top of the supplied vector results. It does not perform
    a second retrieval over the website's full chunk set.

    Attributes
    ----------
    rrf_k:
        RRF constant (default 60).
    keyword_weight:
        Multiplier applied to keyword scores before fusion (1.0 = equal weight).
    """

    rrf_k: int = DEFAULT_RRF_K
    keyword_weight: float = 1.0

    def search(
        self,
        query: str,
        vector_results: list[VectorSearchResult],
        all_chunks: list[VectorSearchResult] | None = None,
        *,
        top_k: int = 5,
    ) -> list[HybridSearchResult]:
        """Run hybrid search combining vector and keyword rankings.

        Parameters
        ----------
        query:
            User question text.
        vector_results:
            Pre-computed vector search results (the current pipeline output).
        all_chunks:
            Deprecated compatibility parameter. Keyword scoring is always
            restricted to ``vector_results``.
        top_k:
            Maximum results to return.

        Returns
        -------
        list[HybridSearchResult]
            Top-k results sorted by descending RRF score with per-source rank info.
        """
        # Keyword matching is a reranking signal, not a second retrieval
        # source. Restricting it to vector hits prevents generic exact-term
        # matches elsewhere in the website from entering the result set.
        kw_results = keyword_search(query, vector_results, top_k=top_k)

        # Build rank maps (1-indexed)
        vector_ranks: dict[str, int] = {
            r.chunk.id: rank + 1 for rank, r in enumerate(vector_results)
        }
        keyword_ranks: dict[str, int] = {r.chunk.id: rank + 1 for rank, r in enumerate(kw_results)}

        # RRF fusion
        fused = reciprocal_rank_fusion(
            [vector_results, kw_results],
            k=self.rrf_k,
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "hybrid_retrieval_debug vector_top5=%s keyword_top5=%s final_top5=%s",
                _debug_results(vector_results[:5]),
                _debug_results(kw_results[:5]),
                _debug_results(fused[:5]),
            )

        return [
            HybridSearchResult(
                chunk=result,
                vector_rank=vector_ranks.get(result.chunk.id, 0),
                keyword_rank=keyword_ranks.get(result.chunk.id, 0),
                rrf_score=result.score,
            )
            for result in fused[:top_k]
        ]


def _debug_results(results: list[VectorSearchResult]) -> list[dict[str, object]]:
    """Return safe retrieval diagnostics without including chunk text."""
    return [
        {
            "chunk_id": result.chunk.id,
            "score": round(result.score, 4),
            "url": result.chunk.metadata.get("source_url"),
            "title": result.chunk.metadata.get("title"),
        }
        for result in results
    ]


__all__ = [
    "DEFAULT_RRF_K",
    "HybridSearchResult",
    "HybridSearcher",
    "keyword_search",
    "reciprocal_rank_fusion",
    "tokenize",
]
