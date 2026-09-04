"""Focused tests for MAX-2 per-source diversification of the reranker input.

Regression coverage for the Q3 source-diversity fix: for broad faceting
queries like "which courses are available", a single highly-similar source
(e.g. one course page) can monopolize the reranker's cosine-based top-k and
crowd out genuinely relevant other sources. ``_diversify_sources`` caps
unprotected chunks per source URL at ``rerank_max_chunks_per_source`` while:

- keeping the pool in its existing (RRF) order,
- always exempting strong lexical/protected candidates so the
  chairperson / dean-of-SOIT lexical protection is never regressed,
- preserving every ``VectorSearchResult`` field (true cosine score,
  ``lexical_score``, chunk metadata/source URL),
- doing nothing when diversification is disabled (``<= 0``).
"""

from __future__ import annotations

from backend.models.knowledge_chunk import KnowledgeChunk
from backend.repositories.vector.base import VectorSearchResult
from backend.services.chat.rag_service import RagService

from tests.chat_helpers import build_chat_env

TENANT = "bench-tenant"
WEBSITE = "bench-web"

URL_A = "https://example.com/course/bba"
URL_B = "https://example.com/course/bcom"
URL_C = "https://example.com/course/accounting"

QUERY = "which courses are available"


def _chunk(
    chunk_id: str,
    text: str,
    url: str,
) -> KnowledgeChunk:
    chunk = KnowledgeChunk.new(
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-1",
        chunk_text=text,
        embedding=[0.9, 0.0, 0.0, 0.0],
        chunk_index=0,
        metadata={"title": text[:20], "source_url": url},
    )
    object.__setattr__(chunk, "id", chunk_id)
    return chunk


def _res(
    chunk: KnowledgeChunk,
    score: float,
    lexical: float | None = None,
) -> VectorSearchResult:
    return VectorSearchResult(chunk=chunk, score=score, lexical_score=lexical)


def _env(max_per_url: int) -> RagService:
    env = build_chat_env()
    env.rag._rerank_max_chunks_per_source = max_per_url
    return env.rag


def _ids(results: list[VectorSearchResult]) -> list[str]:
    return [r.chunk.id for r in results]


def test_max_2_chunks_per_url_and_multiple_urls_retained() -> None:
    rag = _env(max_per_url=2)
    pool = [
        _res(_chunk("a1", "program curriculum and fees schedule", URL_A), 0.90),
        _res(_chunk("b1", "commerce degree program structure", URL_B), 0.80),
        _res(_chunk("a2", "admissions requirements for the bba", URL_A), 0.78),
        _res(_chunk("a3", "semester break and examination dates", URL_A), 0.75),
        _res(_chunk("a4", "hostel and campus accommodation", URL_A), 0.72),
        _res(_chunk("c1", "taxation accounting syllabus modules", URL_C), 0.70),
    ]
    out = rag._diversify_sources(pool, QUERY)
    assert _ids(out) == ["a1", "b1", "a2", "c1"], _ids(out)


def test_strong_lexical_candidate_never_evicted_by_cap() -> None:
    rag = _env(max_per_url=2)
    pool = [
        # First two non-strong chunks fill URL_A's per-source budget.
        _res(_chunk("a1", "bba program curriculum and fees", URL_A), 0.90),
        _res(_chunk("a2", "admissions requirements for the bba", URL_A), 0.85),
        # A strong lexical match (contains BOTH query content tokens) on the
        # same URL, ranked later — it must never be evicted by the cap.
        _res(_chunk("a3", "list the courses available this term", URL_A), 0.50),
        _res(_chunk("b1", "commerce degree program structure", URL_B), 0.80),
    ]
    out = rag._diversify_sources(pool, QUERY)
    assert "a3" in _ids(out), _ids(out)
    assert _ids(out) == ["a1", "a2", "a3", "b1"], _ids(out)


def test_true_cosine_and_lexical_score_are_preserved() -> None:
    rag = _env(max_per_url=2)
    pool = [
        _res(_chunk("a1", "program curriculum and fees", URL_A), 0.90, lexical=0.016),
        _res(_chunk("a2", "admissions requirements", URL_A), 0.85, lexical=0.015),
        _res(_chunk("a3", "semester and exam dates", URL_A), 0.72, lexical=None),
        _res(_chunk("b1", "commerce degree structure", URL_B), 0.80, lexical=0.013),
    ]
    out = rag._diversify_sources(pool, QUERY)
    by_id = {r.chunk.id: r for r in out}
    # Kept chunks are the SAME objects: true cosine and lexical_score preserved.
    assert by_id["a1"].score == 0.90 and by_id["a1"].lexical_score == 0.016
    assert by_id["a2"].score == 0.85 and by_id["a2"].lexical_score == 0.015
    assert by_id["b1"].score == 0.80 and by_id["b1"].lexical_score == 0.013
    # Third URL_A chunk (over the cap) is evicted, but untouched elsewhere.
    assert "a3" not in by_id


def test_disabled_diversification_returns_pool_unchanged() -> None:
    rag = _env(max_per_url=0)
    pool = [
        _res(_chunk("a1", "program curriculum", URL_A), 0.90),
        _res(_chunk("a2", "admissions requirements", URL_A), 0.85),
        _res(_chunk("a3", "semester exam dates", URL_A), 0.72),
        _res(_chunk("a4", "hostel accommodation", URL_A), 0.70),
        _res(_chunk("b1", "commerce degree structure", URL_B), 0.80),
    ]
    out = rag._diversify_sources(pool, QUERY)
    assert _ids(out) == _ids(pool)
    assert all(a is b for a, b in zip(out, pool, strict=True))


def test_normal_semantic_ranking_unchanged_for_unaffected_sources() -> None:
    # Sources with <= cap chunks flow through untouched and stay in order.
    rag = _env(max_per_url=2)
    pool = [
        _res(_chunk("b1", "commerce degree structure", URL_B), 0.80),
        _res(_chunk("c1", "taxation accounting syllabus", URL_C), 0.70),
    ]
    out = rag._diversify_sources(pool, QUERY)
    assert _ids(out) == ["b1", "c1"]
