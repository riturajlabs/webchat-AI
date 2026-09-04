"""Focused tests for lexical-aware reranking.

These prove that strong keyword/entity matches (e.g. "chairperson", "dean of
SOIT") that the vector stage missed are not discarded by the reranker's pure
cosine top-k selection, while preserving true-cosine score semantics (so
``CHAT_CONTEXT_MIN_SCORE`` behavior is unchanged) and existing semantic
ranking.
"""

from __future__ import annotations

from backend.models.knowledge_chunk import KnowledgeChunk
from backend.repositories.vector.base import VectorSearchResult
from backend.repositories.vector.reranker import (
    EmbeddingReranker,
    _strong_lexical_match,
)

TENANT = "bench-tenant"
WEBSITE = "bench-web"

QUERY_VECTOR = [1.0, 0.0, 0.0]


class _NoopEmbedder:
    """Never called: the fast path supplies a precomputed query embedding."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError("fast-path require_query_embedding must avoid embed calls")


def _chunk(
    chunk_id: str,
    text: str,
    embedding: list[float],
) -> KnowledgeChunk:
    chunk = KnowledgeChunk.new(
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-1",
        chunk_text=text,
        embedding=embedding,
        chunk_index=0,
        metadata={"title": text[:20]},
    )
    object.__setattr__(chunk, "id", chunk_id)
    return chunk


def _semantic_chunks() -> list[KnowledgeChunk]:
    """Five unrelated chunks whose stored embeddings rank high by cosine."""
    texts = [
        "pricing plan overview",
        "refund policy details",
        "security compliance guide",
        "support contact information",
        "billing and invoicing guide",
    ]
    return [_chunk(f"sem-{i}", texts[i], [0.95 - 0.05 * i, 0.0, 0.0]) for i in range(5)]


def test_strong_lexical_match_full_coverage() -> None:
    assert _strong_lexical_match(["chairperson"], "The chairperson of the board spoke.")
    assert _strong_lexical_match(["dean", "soit"], "The dean of SOIT leads the school.")
    assert not _strong_lexical_match(["chairperson"], "The board appointed a leader.")
    assert not _strong_lexical_match(["dean", "soit"], "The dean leads the business school.")


async def test_chairperson_keyword_only_match_survives_reranking() -> None:
    """A chairperson-only chunk (low cosine) is not dropped by the reranker."""
    query = "who is chairperson"
    semantic = _semantic_chunks()
    chair = _chunk(
        "chair-1",
        "The chairperson of the board welcomed all the new members today.",
        [0.0, 1.0, 0.0],  # orthogonal to query -> cosine 0.0
    )
    candidates = [
        VectorSearchResult(chunk=chair, score=0.0164),
        *[VectorSearchResult(chunk=c, score=0.9) for c in semantic],
    ]

    reranker = EmbeddingReranker(embedder=_NoopEmbedder(), top_k=5)
    result, metrics = await reranker.rerank(query, candidates, query_embedding=QUERY_VECTOR)

    ids = [r.chunk.id for r in result]
    assert len(result) == 5
    assert "chair-1" in ids, "keyword-only chairperson chunk must survive reranking"
    assert metrics.output_count == 5


async def test_dean_of_soit_entity_match_survives_reranking() -> None:
    """An exact dean/SOIT entity chunk (low cosine) is not dropped."""
    query = "who is the dean of SOIT"
    semantic = _semantic_chunks()
    doit = _chunk(
        "soit-1",
        "The dean of SOIT is the head of the School of Information Technology.",
        [0.0, 1.0, 0.0],
    )
    candidates = [
        VectorSearchResult(chunk=doit, score=0.0164),
        *[VectorSearchResult(chunk=c, score=0.9) for c in semantic],
    ]

    reranker = EmbeddingReranker(embedder=_NoopEmbedder(), top_k=5)
    result, _ = await reranker.rerank(query, candidates, query_embedding=QUERY_VECTOR)

    ids = [r.chunk.id for r in result]
    assert "soit-1" in ids, "dean of SOIT entity chunk must survive reranking"


async def test_semantic_ranking_still_works() -> None:
    """With no lexical match, ordering is pure cosine (unchanged behavior)."""
    query = "how do I reset my password"
    # No chunk contains both "reset" and "password" -> no strong lexical match.
    semantic = _semantic_chunks()
    candidates = [VectorSearchResult(chunk=c, score=0.0) for c in semantic]

    reranker = EmbeddingReranker(embedder=_NoopEmbedder(), top_k=5)
    result, _ = await reranker.rerank(query, candidates, query_embedding=QUERY_VECTOR)

    scores = [r.score for r in result]
    assert scores == sorted(scores, reverse=True)
    assert [r.chunk.id for r in result] == ["sem-0", "sem-1", "sem-2", "sem-3", "sem-4"]


async def test_min_score_semantics_preserved() -> None:
    """The protected chunk keeps its true cosine; no fake cosine band is used."""
    query = "who is chairperson"
    semantic = _semantic_chunks()
    chair = _chunk(
        "chair-1",
        "The chairperson of the board welcomed all the new members today.",
        [0.0, 1.0, 0.0],
    )
    candidates = [
        VectorSearchResult(chunk=chair, score=0.0164),
        *[VectorSearchResult(chunk=c, score=0.9) for c in semantic],
    ]

    reranker = EmbeddingReranker(embedder=_NoopEmbedder(), top_k=5)
    result, _ = await reranker.rerank(query, candidates, query_embedding=QUERY_VECTOR)

    by_id = {r.chunk.id: r for r in result}
    # The chair chunk's output score is its genuine cosine (0.0), NOT an
    # inflated value, so a downstream CHAT_CONTEXT_MIN_SCORE filter still sees
    # the real score and behaves consistently.
    assert by_id["chair-1"].score == 0.0
    # Semantic chunks keep their real >0.56 cosine (unchanged min_score pass).
    assert all(by_id[f"sem-{i}"].score >= 0.56 for i in range(4))
