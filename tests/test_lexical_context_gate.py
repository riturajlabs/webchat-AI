"""Focused tests for score-type-aware lexical context gating.

Regression coverage for the retrieval score-semantics fix:

- A strong lexical match (chairperson / dean-of-SOIT) that carries explicit
  RRF/keyword evidence reaches the final context even though its true cosine
  falls below ``CHAT_CONTEXT_MIN_SCORE`` (0.56), WITHOUT lowering the cosine
  threshold or faking the cosine score.
- Weak / non-protected candidates below the cosine threshold are still
  rejected.
- ``result.score`` always remains the true cosine — no fabricated score.
- Normal above-threshold cosine candidates pass exactly as before.
"""

from __future__ import annotations

from backend.models.knowledge_chunk import KnowledgeChunk
from backend.repositories.vector.base import VectorSearchResult
from backend.repositories.vector.reranker import EmbeddingReranker

from tests.chat_helpers import ChatEnv, build_chat_env

TENANT = "bench-tenant"
WEBSITE = "bench-web"

QUERY_VECTOR = [1.0, 0.0, 0.0]
CHAT_CONTEXT_MIN_SCORE = 0.56


class _NoopEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError("fast path supplies a precomputed query embedding")


def _chunk(
    chunk_id: str,
    text: str,
    embedding: list[float],
    *,
    url: str,
) -> KnowledgeChunk:
    chunk = KnowledgeChunk.new(
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-1",
        chunk_text=text,
        embedding=embedding,
        chunk_index=0,
        metadata={"title": text[:20], "source_url": url},
    )
    object.__setattr__(chunk, "id", chunk_id)
    return chunk


def _res(chunk: KnowledgeChunk, score: float, lexical: float | None) -> VectorSearchResult:
    return VectorSearchResult(chunk=chunk, score=score, lexical_score=lexical)


async def _rerank(top_result: VectorSearchResult, query: str) -> list[VectorSearchResult]:
    """Run the protected top candidate through the reranker top-5."""
    sem = [
        _chunk(f"sem-{i}", f"pricing plan variant {i}", [0.95 - 0.05 * i, 0.0, 0.0],
               url=f"https://x/sem-{i}")
        for i in range(4)
    ]
    candidates = [
        top_result,
        *[VectorSearchResult(chunk=c, score=0.9) for c in sem],
    ]
    reranker = EmbeddingReranker(embedder=_NoopEmbedder(), top_k=5)
    out, _ = await reranker.rerank(query, candidates, query_embedding=QUERY_VECTOR)
    return out


def _gate(
    rag_env: ChatEnv, results: list[VectorSearchResult]
) -> tuple[list[str], dict[str, float]]:
    """Run _build_context and return (reached chunk ids, score by id).

    ``rag_env._min_score`` must already be set to CHAT_CONTEXT_MIN_SCORE.
    """
    items, sources, _ = rag_env.rag._build_context(results)
    reached = {s["chunk_id"] for s in sources}
    scores = {s["chunk_id"]: s["score"] for s in sources}
    return sorted(reached), scores


async def test_chairperson_lexical_reaches_context_despite_low_cosine() -> None:
    """A protected chairperson chunk with real RRF evidence reaches context."""
    env = build_chat_env()
    env.rag._min_score = CHAT_CONTEXT_MIN_SCORE
    chair = _chunk(
        "chair-1",
        "The chairperson of the board welcomed all members.",
        [0.0, 1.0, 0.0],  # cosine 0.0 to the query embedding
        url="https://indirauniversity.edu.in/event/chairperson",
    )
    chair_result = _res(chair, 0.0164, lexical=0.0159)  # RRF keyword evidence
    reranked = await _rerank(chair_result, "who is chairperson")

    by_id = {r.chunk.id: r for r in reranked}
    assert by_id["chair-1"].score == 0.0  # true cosine, not faked
    assert by_id["chair-1"].lexical_score == 0.0159  # evidence preserved

    reached, _scores = _gate(env, reranked)
    assert "chair-1" in reached, (
        "chairperson chunk must reach context on its lexical/RRF evidence "
        "despite cosine < 0.56"
    )


async def test_dean_of_soit_lexical_reaches_context() -> None:
    """The dean/SOIT protected chunk (cosine 0.5349 < 0.56) reaches context."""
    env = build_chat_env()
    env.rag._min_score = CHAT_CONTEXT_MIN_SCORE
    doit = _chunk(
        "soit-1",
        "The dean of SOIT heads the School of Information Technology.",
        [0.0, 1.0, 0.0],
        url="https://indirauniversity.edu.in/school/school-of-information-technology",
    )
    doit_result = _res(doit, 0.0164, lexical=0.0164)
    reranked = await _rerank(doit_result, "who is the dean of SOIT")

    by_id = {r.chunk.id: r for r in reranked}
    assert by_id["soit-1"].score == 0.0  # true cosine; nothing fabricated

    reached, _ = _gate(env, reranked)
    assert "soit-1" in reached


async def test_weak_non_protected_cosine_below_threshold_still_rejected() -> None:
    """A below-threshold cosine candidate with no lexical evidence is dropped."""
    env = build_chat_env()
    env.rag._min_score = CHAT_CONTEXT_MIN_SCORE
    weak = _chunk(
        "weak-1",
        "unrelated boilerplate with no query terms",
        [1.0, 0.0, 0.0],  # will be cosine 1.0 — must use a muted score via gate
        url="https://x/weak",
    )
    # Directly exercise the gate with a low cosine and no lexical evidence.
    # cosine must be < 0.56 here; bypass reranker cosine (which would be 1.0)
    # by feeding the gate a result whose cosine is genuinely low.
    low_cosine = _res(
        weak,
        0.40,
        lexical=None,
    )

    reached, _ = _gate(env, [low_cosine])
    assert reached == []


async def test_strong_protected_but_no_keyword_evidence_is_rejected() -> None:
    """A chunk that would be lexical-protected but has no RRF evidence is dropped.

    Ensures strong lexical *protection* alone (token coverage) does not let an
    unrelated/unretrieved weak candidate through — real RRF/keyword evidence is
    required to qualify for the lexical gate.
    """
    env = build_chat_env()
    env.rag._min_score = CHAT_CONTEXT_MIN_SCORE
    # This chunk contains every query token, so the reranker marks it protected,
    # but it was never retrieved by the keyword pass (lexical_score is None).
    unrelated = _chunk(
        "unrel-1",
        "The chairperson spoke about admission and security.",
        [0.0, 1.0, 0.0],  # cosine 0.0 < 0.56 -> must be rejected w/o keyword evidence
        url="https://x/unrel",
    )
    reranked = await _rerank(
        _res(unrelated, 0.0164, lexical=None),
        "who is chairperson",
    )

    by_id = {r.chunk.id: r for r in reranked}
    assert by_id["unrel-1"].lexical_score is None, (
        "protected-but-unretrieved chunk must NOT carry lexical evidence"
    )
    reached, _ = _gate(env, reranked)
    assert "unrel-1" not in reached


async def test_score_stays_true_cosine_and_no_fake_created() -> None:
    """result.score is the genuine cosine; lexical evidence stays separate."""
    env = build_chat_env()
    env.rag._min_score = CHAT_CONTEXT_MIN_SCORE
    chair = _chunk(
        "chair-1",
        "The chairperson of the board welcomed all members.",
        [0.0, 1.0, 0.0],
        url="https://x/chair",
    )
    reranked = await _rerank(_res(chair, 0.0164, lexical=0.0159), "who is chairperson")
    by_id = {r.chunk.id: r for r in reranked}
    assert by_id["chair-1"].score == 0.0
    assert by_id["chair-1"].lexical_score == 0.0159
    # The score is NOT set to the lexical/RRF value — cosine semantics intact.
    assert by_id["chair-1"].score != by_id["chair-1"].lexical_score


async def test_above_threshold_cosine_candidate_passes_unconditionally() -> None:
    """Normal high-cosine candidates pass — admission/cyber behavior unchanged."""
    env = build_chat_env()
    env.rag._min_score = CHAT_CONTEXT_MIN_SCORE
    admission = _chunk(
        "adm-1",
        "Here is the admission process for all programs.",
        [1.0, 0.0, 0.0],  # cosine 1.0
        url="https://x/admission",
    )
    # Above-threshold cosine, no lexical evidence needed (like vector hits).
    reached, scores = _gate(env, [_res(admission, 0.99, lexical=None)])
    assert reached == ["adm-1"]
    assert scores["adm-1"] == 0.99


def test_preserve_vector_scores_carries_keyword_evidence() -> None:
    """The hybrid strategy tags keyword-retrieved chunks with RRF evidence."""
    from backend.repositories.vector.hybrid import HybridSearchResult
    from backend.services.chat.retrieval_strategy import _preserve_vector_scores

    kw = _chunk("kw-1", "chairperson text", [0.0, 1.0, 0.0], url="https://x/kw")
    vec = _chunk("vec-1", "plain text", [1.0, 0.0, 0.0], url="https://x/vec")

    hybrid = [
        HybridSearchResult(  # keyword-only, keyword_rank=1 -> RRF evidence
            chunk=VectorSearchResult(chunk=kw, score=0.0164),
            vector_rank=0,
            keyword_rank=1,
            rrf_score=0.0159,
        ),
        HybridSearchResult(  # vector hit only, keyword_rank=0 -> no lexical evidence
            chunk=VectorSearchResult(chunk=vec, score=0.9),
            vector_rank=1,
            keyword_rank=0,
            rrf_score=0.015,
        ),
    ]
    out = _preserve_vector_scores(
        hybrid,
        [VectorSearchResult(chunk=vec, score=0.9)],
    )
    by_id = {r.chunk.id: r for r in out}
    assert by_id["kw-1"].lexical_score == 0.0159  # keyword-evidenced
    assert by_id["kw-1"].score == 0.0159  # keyword-only keeps RRF as score
    assert by_id["vec-1"].lexical_score is None  # vector-only, no lexical evidence
    assert by_id["vec-1"].score == 0.9  # vector score restored


async def test_reranker_carries_and_clears_lexical_evidence() -> None:
    """Reranker preserves evidence for protected matches and clears it otherwise."""
    protected = _chunk(
        "prot-1",
        "The chairperson of the board spoke.",
        [0.0, 1.0, 0.0],
        url="https://x/prot",
    )
    other = _chunk("sem-1", "pricing plan", [0.99, 0.0, 0.0], url="https://x/sem")
    candidates = [
        _res(protected, 0.0164, lexical=0.0159),  # keyword import, protected
        _res(other, 0.95, lexical=0.014),          # keyword-imported but NOT protected
    ]
    reranker = EmbeddingReranker(embedder=_NoopEmbedder(), top_k=5)
    out, _ = await reranker.rerank("who is chairperson", candidates, query_embedding=QUERY_VECTOR)
    by_id = {r.chunk.id: r for r in out}

    assert by_id["prot-1"].lexical_score == 0.0159  # carried (protected + evidence)
    assert by_id["sem-1"].lexical_score is None      # cleared (unprotected)
    assert by_id["prot-1"].score == 0.0               # true cosine preserved
    assert by_id["prot-1"].score != by_id["prot-1"].lexical_score
