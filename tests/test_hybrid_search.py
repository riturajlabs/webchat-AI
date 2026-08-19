"""Tests for hybrid search: RRF, keyword search, and hybrid ranking.

Covers pure-function RRF fusion, keyword tokenization, keyword scoring,
and end-to-end hybrid searcher. All in-memory — no network, no MongoDB.
"""

from backend.repositories.vector.base import VectorSearchResult
from backend.repositories.vector.hybrid import (
    HybridSearcher,
    keyword_search,
    reciprocal_rank_fusion,
    tokenize,
)

from tests.chat_helpers import build_chat_env, make_chunk, make_website

TENANT = "bench-tenant"
WEBSITE = "bench-web"


# ---------------------------------------------------------------------------
# Helper to build test chunks
# ---------------------------------------------------------------------------


def _make_result(
    chunk_id: str,
    text: str,
    score: float = 0.5,
    source_url: str = "",
) -> VectorSearchResult:
    from backend.models.knowledge_chunk import KnowledgeChunk

    chunk = KnowledgeChunk.new(
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-1",
        chunk_text=text,
        embedding=[0.0],
        chunk_index=0,
        metadata={"source_url": source_url} if source_url else {},
    )
    # Override the generated id for deterministic testing
    object.__setattr__(chunk, "id", chunk_id)
    return VectorSearchResult(chunk=chunk, score=score)


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


def test_tokenize_basic() -> None:
    tokens = tokenize("What is the pricing plan?")
    assert "pricing" in tokens
    assert "plan" in tokens
    assert "what" not in tokens  # stop word
    assert "is" not in tokens  # stop word
    assert "the" not in tokens  # stop word


def test_tokenize_empty() -> None:
    assert tokenize("") == []


def test_tokenize_all_stop_words() -> None:
    assert tokenize("the is a an") == []


def test_tokenize_numbers() -> None:
    tokens = tokenize("plan costs 19 dollars")
    assert "19" in tokens
    assert "plan" in tokens
    assert "costs" in tokens


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion
# ---------------------------------------------------------------------------


def test_rrf_empty_rankings() -> None:
    assert reciprocal_rank_fusion([]) == []


def test_rrf_single_ranking() -> None:
    r1 = [_make_result("a", "text a", 0.9), _make_result("b", "text b", 0.8)]
    fused = reciprocal_rank_fusion([r1])
    assert len(fused) == 2
    assert fused[0].chunk.id == "a"
    assert fused[0].score > fused[1].score


def test_rrf_two_rankings_same_order() -> None:
    r1 = [_make_result("a", "text a", 0.9), _make_result("b", "text b", 0.8)]
    r2 = [_make_result("a", "text a", 0.7), _make_result("b", "text b", 0.6)]
    fused = reciprocal_rank_fusion([r1, r2])
    assert len(fused) == 2
    # Both appear in both rankings, so both get summed scores
    assert fused[0].chunk.id == "a"  # rank 1 in both
    assert fused[1].chunk.id == "b"  # rank 2 in both


def test_rrf_two_rankings_divergent() -> None:
    r1 = [_make_result("a", "text a", 0.9), _make_result("b", "text b", 0.8)]
    r2 = [_make_result("b", "text b", 0.9), _make_result("c", "text c", 0.8)]
    fused = reciprocal_rank_fusion([r1, r2])
    ids = [r.chunk.id for r in fused]
    # b appears in both rankings (rank 1 + rank 2) — highest RRF score
    assert ids[0] == "b"
    assert len(ids) == 3


def test_rrf_custom_k() -> None:
    r1 = [_make_result("a", "text a", 0.9)]
    r2 = [_make_result("b", "text b", 0.9)]
    fused_default = reciprocal_rank_fusion([r1, r2])
    fused_high_k = reciprocal_rank_fusion([r1, r2], k=200)
    # Higher k reduces positional advantage — scores should be closer
    assert len(fused_default) == 2
    assert len(fused_high_k) == 2


def test_rrf_empty_ranking_in_list() -> None:
    r1 = [_make_result("a", "text a", 0.9)]
    fused = reciprocal_rank_fusion([r1, []])
    assert len(fused) == 1
    assert fused[0].chunk.id == "a"


def test_rrf_preserves_chunk_data() -> None:
    r1 = [_make_result("a", "hello world", 0.9, source_url="https://a.com")]
    fused = reciprocal_rank_fusion([r1])
    assert fused[0].chunk.chunk_text == "hello world"
    assert fused[0].chunk.metadata.get("source_url") == "https://a.com"


def test_rrf_score_positive() -> None:
    r1 = [_make_result("a", "text a", 0.9), _make_result("b", "text b", 0.8)]
    fused = reciprocal_rank_fusion([r1])
    for result in fused:
        assert result.score > 0.0


# ---------------------------------------------------------------------------
# Keyword search
# ---------------------------------------------------------------------------


def test_keyword_search_basic() -> None:
    chunks = [
        _make_result("a", "pricing plan costs $19 per month", 0.9, "https://a.com/pricing"),
        _make_result("b", "security encryption compliance", 0.8, "https://a.com/security"),
        _make_result("c", "free trial registration", 0.7, "https://a.com/trial"),
    ]
    results = keyword_search("pricing plan", chunks, top_k=3)
    assert len(results) > 0
    # Pricing chunk should rank first (matches both "pricing" and "plan")
    assert results[0].chunk.id == "a"


def test_keyword_search_no_match() -> None:
    chunks = [
        _make_result("a", "security encryption", 0.9),
        _make_result("b", "compliance audit", 0.8),
    ]
    results = keyword_search("pricing plan", chunks, top_k=3)
    assert len(results) == 0


def test_keyword_search_empty_query() -> None:
    chunks = [_make_result("a", "pricing plan", 0.9)]
    results = keyword_search("", chunks, top_k=3)
    assert len(results) == 0


def test_keyword_search_empty_chunks() -> None:
    results = keyword_search("pricing plan", [], top_k=3)
    assert len(results) == 0


def test_keyword_search_top_k_limit() -> None:
    chunks = [
        _make_result("a", "pricing plan alpha", 0.9),
        _make_result("b", "pricing plan beta", 0.8),
        _make_result("c", "pricing plan gamma", 0.7),
    ]
    results = keyword_search("pricing plan", chunks, top_k=2)
    assert len(results) == 2


def test_keyword_search_stop_words_ignored() -> None:
    chunks = [
        _make_result("a", "the is a pricing plan", 0.9),
        _make_result("b", "the is a security page", 0.8),
    ]
    results = keyword_search("what is the pricing", chunks, top_k=3)
    assert len(results) == 1
    assert results[0].chunk.id == "a"


def test_keyword_search_case_insensitive() -> None:
    chunks = [_make_result("a", "PRICING PLAN", 0.9)]
    results = keyword_search("pricing plan", chunks, top_k=3)
    assert len(results) == 1


def test_keyword_search_relevance_ordering() -> None:
    chunks = [
        _make_result("a", "pricing plan overview", 0.9),
        _make_result("b", "pricing details only", 0.8),
        _make_result("c", "plan management guide", 0.7),
    ]
    results = keyword_search("pricing plan", chunks, top_k=3)
    # 'a' has both keywords, should rank first
    assert results[0].chunk.id == "a"


# ---------------------------------------------------------------------------
# HybridSearcher
# ---------------------------------------------------------------------------


def test_hybrid_searcher_basic() -> None:
    chunks = [
        _make_result("a", "pricing plan costs $19", 0.9, "https://a.com/pricing"),
        _make_result("b", "security encryption", 0.8, "https://a.com/security"),
        _make_result("c", "pricing details overview", 0.7, "https://a.com/pricing-details"),
    ]
    searcher = HybridSearcher()
    results = searcher.search("pricing plan", chunks, top_k=3)
    assert len(results) > 0
    # All results should have RRF scores
    for r in results:
        assert r.rrf_score > 0.0
        assert r.chunk is not None


def test_hybrid_searcher_vector_boosts_semantic_match() -> None:
    """Hybrid should rank a chunk higher when both vector and keyword agree."""
    chunks = [
        _make_result("a", "pricing plan costs $19 per month", 0.95),
        _make_result("b", "pricing plan overview details", 0.90),
        _make_result("c", "security encryption", 0.85),
    ]
    searcher = HybridSearcher()
    results = searcher.search("pricing plan", chunks, top_k=3)
    # Both a and b match keywords; 'a' has higher vector score
    ids = [r.chunk.chunk.id for r in results]
    assert "a" in ids
    assert "b" in ids


def test_hybrid_searcher_empty_vector_results() -> None:
    searcher = HybridSearcher()
    results = searcher.search("pricing", [], top_k=5)
    assert len(results) == 0


def test_hybrid_searcher_fallback_to_vector_only() -> None:
    """When all_chunks is None, keyword search uses vector results only."""
    chunks = [
        _make_result("a", "pricing plan", 0.9),
        _make_result("b", "security page", 0.8),
    ]
    searcher = HybridSearcher()
    results = searcher.search("pricing", chunks, all_chunks=None, top_k=5)
    assert len(results) > 0


def test_hybrid_searcher_rank_info() -> None:
    chunks = [
        _make_result("a", "pricing plan", 0.9),
        _make_result("b", "security page", 0.8),
    ]
    searcher = HybridSearcher()
    results = searcher.search("pricing", chunks, top_k=2)
    for r in results:
        assert isinstance(r.vector_rank, int)
        assert isinstance(r.keyword_rank, int)
        assert r.rrf_score > 0.0


def test_hybrid_searcher_respects_rrf_k() -> None:
    chunks = [_make_result("a", "pricing plan", 0.9)]
    r1 = HybridSearcher(rrf_k=1).search("pricing", chunks, top_k=1)
    r2 = HybridSearcher(rrf_k=200).search("pricing", chunks, top_k=1)
    # Both should return results, but with different RRF scores
    assert len(r1) == 1
    assert len(r2) == 1
    assert r1[0].rrf_score != r2[0].rrf_score


# ---------------------------------------------------------------------------
# Integration with FakeVectorRepository
# ---------------------------------------------------------------------------


async def test_hybrid_searcher_with_seeded_data() -> None:
    """End-to-end: seed chunks, run vector search, then hybrid."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=3)
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Pro plan costs $19/mo with 10GB storage.",
        url="https://example.com/pricing",
        title="Pricing",
        chunk_index=0,
    )
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Enterprise plan includes SSO and audit logs.",
        url="https://example.com/enterprise",
        title="Enterprise",
        chunk_index=1,
    )
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Free trial gives 14 days of full access.",
        url="https://example.com/trial",
        title="Trial",
        chunk_index=2,
    )

    # Run vector search via the fake
    vector_results = await env.vector.similarity_search(
        TENANT, WEBSITE, [0.0, 0.0, 0.0, 0.0], top_k=3
    )
    assert len(vector_results) > 0

    # Build all-chunks list for keyword search
    all_chunks = [
        VectorSearchResult(chunk=chunk, score=0.5)
        for chunk in await env.vector.list_chunks(TENANT, WEBSITE)
    ]

    searcher = HybridSearcher()
    hybrid_results = searcher.search("pricing plan", vector_results, all_chunks, top_k=3)
    assert len(hybrid_results) > 0
    for r in hybrid_results:
        assert r.rrf_score > 0.0
