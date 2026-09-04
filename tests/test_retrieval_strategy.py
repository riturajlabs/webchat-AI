"""Tests for retrieval strategy abstraction and hybrid search feature flag.

Covers:
- VectorRetrievalStrategy passes through results unchanged.
- HybridRetrievalStrategy applies RRF fusion and returns correct metrics.
- RagService uses vector strategy by default (flag off).
- RagService uses hybrid strategy when flag is on.
- RagService accepts explicit strategy override.
- Timing logs include retrieval_method fields.
- Existing RAG pipeline behavior is fully preserved.
"""

from unittest.mock import patch

from backend.repositories.vector.hybrid import keyword_search
from backend.services.chat.rag_service import RagService
from backend.services.chat.retrieval_strategy import (
    HybridRetrievalStrategy,
    RetrievalMetricsInfo,
    VectorRetrievalStrategy,
)

from tests.chat_helpers import build_chat_env, consume, make_chunk, make_website

TENANT = "strat-tenant"
WEBSITE = "strat-web"


# ---------------------------------------------------------------------------
# VectorRetrievalStrategy
# ---------------------------------------------------------------------------


def test_vector_strategy_returns_results_unchanged() -> None:
    from backend.models.knowledge_chunk import KnowledgeChunk
    from backend.repositories.vector.base import VectorSearchResult

    chunk = KnowledgeChunk.new(
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-1",
        chunk_text="test",
        embedding=[0.0],
        chunk_index=0,
    )
    results = [VectorSearchResult(chunk=chunk, score=0.9)]
    strategy = VectorRetrievalStrategy()
    final, metrics = strategy.search(query="test", vector_results=results, top_k=5)
    assert final == results
    assert metrics.retrieval_method == "vector"
    assert metrics.vector_result_count == 1
    assert metrics.keyword_result_count == 0
    assert metrics.final_result_count == 1


def test_vector_strategy_empty_results() -> None:
    strategy = VectorRetrievalStrategy()
    final, metrics = strategy.search(query="test", vector_results=[], top_k=5)
    assert final == []
    assert metrics.final_result_count == 0


# ---------------------------------------------------------------------------
# HybridRetrievalStrategy
# ---------------------------------------------------------------------------


def test_hybrid_strategy_empty_results() -> None:
    strategy = HybridRetrievalStrategy()
    final, metrics = strategy.search(query="test", vector_results=[], top_k=5)
    assert final == []
    assert metrics.retrieval_method == "hybrid"
    assert metrics.vector_result_count == 0


def test_hybrid_strategy_with_chunks() -> None:
    from backend.models.knowledge_chunk import KnowledgeChunk
    from backend.repositories.vector.base import VectorSearchResult

    c1 = KnowledgeChunk.new(
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-1",
        chunk_text="pricing plan costs $19 per month",
        embedding=[0.0],
        chunk_index=0,
        metadata={"source_url": "https://example.com/pricing", "title": "Pricing"},
    )
    c2 = KnowledgeChunk.new(
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-2",
        chunk_text="enterprise includes SSO and audit logs",
        embedding=[0.0],
        chunk_index=1,
        metadata={"source_url": "https://example.com/enterprise", "title": "Enterprise"},
    )
    c3 = KnowledgeChunk.new(
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-3",
        chunk_text="free trial gives 14 days of access",
        embedding=[0.0],
        chunk_index=2,
        metadata={"source_url": "https://example.com/trial", "title": "Trial"},
    )
    vector_results = [
        VectorSearchResult(chunk=c1, score=0.9),
        VectorSearchResult(chunk=c2, score=0.8),
    ]
    all_chunks = [
        VectorSearchResult(chunk=c1, score=0.5),
        VectorSearchResult(chunk=c2, score=0.5),
        VectorSearchResult(chunk=c3, score=0.5),
    ]
    strategy = HybridRetrievalStrategy(rrf_k=60)
    final, metrics = strategy.search(
        query="pricing plan",
        vector_results=vector_results,
        all_chunks=all_chunks,
        top_k=3,
    )
    assert metrics.retrieval_method == "hybrid"
    assert metrics.vector_result_count == 2
    assert metrics.keyword_result_count == 2
    assert metrics.hybrid_candidate_count == 2
    assert max(result.score for result in final) == 0.9
    assert len(final) <= 3
    # Hybrid should include the pricing chunk (keyword match on "pricing plan")
    urls = {r.chunk.metadata.get("source_url") for r in final}
    assert any("pricing" in u for u in urls)


def test_hybrid_strategy_rrf_k_impact() -> None:
    from backend.models.knowledge_chunk import KnowledgeChunk
    from backend.repositories.vector.base import VectorSearchResult

    c1 = KnowledgeChunk.new(
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-1",
        chunk_text="pricing plan details",
        embedding=[0.0],
        chunk_index=0,
        metadata={"source_url": "https://example.com/pricing", "title": "Pricing"},
    )
    c2 = KnowledgeChunk.new(
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-2",
        chunk_text="security compliance information",
        embedding=[0.0],
        chunk_index=1,
        metadata={"source_url": "https://example.com/security", "title": "Security"},
    )
    vector_results = [
        VectorSearchResult(chunk=c1, score=0.9),
        VectorSearchResult(chunk=c2, score=0.85),
    ]
    all_chunks = [
        VectorSearchResult(chunk=c1, score=0.5),
        VectorSearchResult(chunk=c2, score=0.5),
    ]
    # Different rrf_k values should produce different rankings
    s1 = HybridRetrievalStrategy(rrf_k=10)
    s2 = HybridRetrievalStrategy(rrf_k=100)
    _, m1 = s1.search(
        query="pricing", vector_results=vector_results, all_chunks=all_chunks, top_k=2
    )
    _, m2 = s2.search(
        query="pricing", vector_results=vector_results, all_chunks=all_chunks, top_k=2
    )
    assert m1.retrieval_method == "hybrid"
    assert m2.retrieval_method == "hybrid"


# ---------------------------------------------------------------------------
# RetrievalMetricsInfo
# ---------------------------------------------------------------------------


def test_retrieval_metrics_info_defaults() -> None:
    m = RetrievalMetricsInfo()
    assert m.retrieval_method == "vector"
    assert m.vector_result_count == 0
    assert m.keyword_result_count == 0
    assert m.final_result_count == 0


def test_retrieval_metrics_info_frozen() -> None:
    m = RetrievalMetricsInfo(retrieval_method="hybrid", final_result_count=5)
    assert m.retrieval_method == "hybrid"
    assert m.final_result_count == 5


# ---------------------------------------------------------------------------
# RagService strategy selection
# ---------------------------------------------------------------------------


def test_rag_service_default_uses_vector_strategy() -> None:
    env = build_chat_env()
    assert isinstance(env.rag._retrieval_strategy, HybridRetrievalStrategy)


def test_rag_service_explicit_strategy_override() -> None:
    env = build_chat_env()
    custom = HybridRetrievalStrategy(rrf_k=30)
    rag = RagService(
        websites=env.websites,
        vector=env.vector,
        embedder=env.embedder,
        generation=env.generation,
        sessions=env.sessions,
        messages=env.messages,
        usage=env.usage,
        cache=env.cache,
        retrieval_strategy=custom,
    )
    assert rag._retrieval_strategy is custom


def test_rag_service_hybrid_flag_enables_hybrid() -> None:
    env = build_chat_env()
    with patch("backend.services.chat.rag_service.get_settings") as mock_settings:
        mock_settings.return_value.enable_hybrid_search = True
        mock_settings.return_value.hybrid_rrf_k = 40
        mock_settings.return_value.chat_top_k = 8
        mock_settings.return_value.rag_prompt_version = 1
        mock_settings.return_value.chat_memory_turns = 12
        mock_settings.return_value.chat_context_chunk_chars = 4000
        mock_settings.return_value.chat_context_max_chars = 20000
        mock_settings.return_value.chat_context_min_score = 0.25
        mock_settings.return_value.perf_timing_log_enabled = False
        mock_settings.return_value.embedding_cache_size = 256
        mock_settings.return_value.embedding_cache_ttl_seconds = 3600
        mock_settings.return_value.chat_retrieval_cache_size = 512
        mock_settings.return_value.chat_retrieval_cache_ttl_seconds = 900
        mock_settings.return_value.enable_reranking = False
        mock_settings.return_value.rerank_top_k = 0
        mock_settings.return_value.enable_faithfulness_check = False
        mock_settings.return_value.faithfulness_warning_threshold = 0.6
        mock_settings.return_value.hybrid_search_candidate_limit = 50
        mock_settings.return_value.ai_model_pricing_json = ""
        rag = RagService(
            websites=env.websites,
            vector=env.vector,
            embedder=env.embedder,
            generation=env.generation,
            sessions=env.sessions,
            messages=env.messages,
            usage=env.usage,
            cache=env.cache,
        )
    assert isinstance(rag._retrieval_strategy, HybridRetrievalStrategy)


# ---------------------------------------------------------------------------
# End-to-end: vector strategy produces identical output to baseline
# ---------------------------------------------------------------------------


async def test_vector_strategy_e2e_identical_output() -> None:
    """Default vector strategy produces identical output to pre-integration."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="We offer Pro and Team plans.",
    )
    events = await consume(
        env.rag.stream_answer(tenant_id=TENANT, website_id=WEBSITE, question="What plans?")
    )
    sources = next(e for e in events if e["event"] == "sources")
    assert len(sources["data"]["sources"]) >= 1
    done = next(e for e in events if e["event"] == "done")
    assert done["data"]["fallback"] is False


async def test_hybrid_strategy_e2e_produces_sources() -> None:
    """Hybrid strategy still produces valid sources and done events."""
    env = build_chat_env()
    custom = HybridRetrievalStrategy(rrf_k=60)
    rag = RagService(
        websites=env.websites,
        vector=env.vector,
        embedder=env.embedder,
        generation=env.generation,
        sessions=env.sessions,
        messages=env.messages,
        usage=env.usage,
        cache=env.cache,
        retrieval_strategy=custom,
        allow_reranking=False,
    )
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=2)
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Pro plan costs $19 per month.",
        url="https://example.com/pricing",
        title="Pricing",
        chunk_index=0,
    )
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Enterprise includes SSO.",
        url="https://example.com/enterprise",
        title="Enterprise",
        chunk_index=1,
    )
    events = await consume(
        rag.stream_answer(tenant_id=TENANT, website_id=WEBSITE, question="pricing plan")
    )
    sources = next(e for e in events if e["event"] == "sources")
    assert len(sources["data"]["sources"]) >= 1
    done = next(e for e in events if e["event"] == "done")
    assert done["data"]["fallback"] is False


# ---------------------------------------------------------------------------
# Timing logs include retrieval_method
# ---------------------------------------------------------------------------


async def test_timing_logs_include_retrieval_method() -> None:
    env = build_chat_env()
    env.rag._timing_enabled = True
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Pro plan costs $19.",
    )
    events = await consume(
        env.rag.stream_answer(tenant_id=TENANT, website_id=WEBSITE, question="pricing?")
    )
    done = next(e for e in events if e["event"] == "done")
    timing = done["data"].get("timing")
    assert timing is not None
    assert timing["retrieval_method"] == "hybrid"
    assert "vector_result_count" in timing
    assert "keyword_result_count" in timing
    assert "final_result_count" in timing


async def test_timing_logs_hybrid_method() -> None:
    env = build_chat_env()
    custom = HybridRetrievalStrategy(rrf_k=60)
    rag = RagService(
        websites=env.websites,
        vector=env.vector,
        embedder=env.embedder,
        generation=env.generation,
        sessions=env.sessions,
        messages=env.messages,
        usage=env.usage,
        cache=env.cache,
        retrieval_strategy=custom,
        allow_reranking=False,
    )
    rag._timing_enabled = True
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Pro plan costs $19.",
    )
    events = await consume(
        rag.stream_answer(tenant_id=TENANT, website_id=WEBSITE, question="pricing?")
    )
    done = next(e for e in events if e["event"] == "done")
    timing = done["data"].get("timing")
    assert timing is not None
    assert timing["retrieval_method"] == "hybrid"
    assert timing["vector_result_count"] >= 1
    assert timing["keyword_result_count"] >= 1


# ---------------------------------------------------------------------------
# _load_all_chunks
# ---------------------------------------------------------------------------


async def test_load_all_chunks_returns_chunks() -> None:
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=2)
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Chunk one.",
        chunk_index=0,
    )
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Chunk two.",
        chunk_index=1,
    )
    chunks = await env.rag._load_all_chunks(TENANT, WEBSITE)
    assert len(chunks) == 2
    assert all(c.score == 0.5 for c in chunks)


async def test_load_all_chunks_empty_for_unknown_website() -> None:
    env = build_chat_env()
    chunks = await env.rag._load_all_chunks(TENANT, "nonexistent")
    assert chunks == []


# ---------------------------------------------------------------------------
# Existing RAG tests still pass (key behaviors preserved)
# ---------------------------------------------------------------------------


async def test_fallback_still_works_with_strategy() -> None:
    """Empty knowledge base triggers fallback regardless of strategy."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=0)
    events = await consume(
        env.rag.stream_answer(tenant_id=TENANT, website_id=WEBSITE, question="test?")
    )
    done = next(e for e in events if e["event"] == "done")
    assert done["data"]["fallback"] is True


async def test_prompt_injection_protection_preserved() -> None:
    """Long questions are still truncated by sanitize_question."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=0)
    long_q = "A" * 5000
    events = await consume(
        env.rag.stream_answer(tenant_id=TENANT, website_id=WEBSITE, question=long_q)
    )
    # Should still get a fallback, not an error
    done = next(e for e in events if e["event"] == "done")
    assert done["data"]["fallback"] is True


# ---------------------------------------------------------------------------
# Complete embedding-free lexical corpus loading
# ---------------------------------------------------------------------------


async def test_load_all_chunks_has_no_first_50_recall_cap() -> None:
    """A rare exact term outside an old 50-record slice remains retrievable."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=51)
    for i in range(50):
        await make_chunk(
            env,
            tenant_id=TENANT,
            website_id=WEBSITE,
            text=f"ordinary content {i}",
            chunk_index=i,
        )
    target = await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="SOIT rarefaculty exact information.",
        chunk_index=50,
        document_id="rare-document",
    )

    all_chunks = await env.rag._load_all_chunks(TENANT, WEBSITE)
    results = keyword_search("SOIT rarefaculty", all_chunks, top_k=5)

    assert len(all_chunks) == 51
    assert [result.chunk.id for result in results] == [target.id]


async def test_lexical_corpus_is_tenant_and_website_scoped() -> None:
    """Lexical loading must never include another tenant or website."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
    await make_website(env, tenant_id=TENANT, website_id="other-web", knowledge_chunks=1)
    await make_website(env, tenant_id="other-tenant", website_id=WEBSITE, knowledge_chunks=1)
    own = await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="SOIT own fact")
    await make_chunk(env, tenant_id=TENANT, website_id="other-web", text="SOIT other site fact")
    await make_chunk(
        env, tenant_id="other-tenant", website_id=WEBSITE, text="SOIT other tenant fact"
    )

    chunks = await env.rag._load_all_chunks(TENANT, WEBSITE, corpus_version="v1")

    assert [chunk.chunk.id for chunk in chunks] == [own.id]
    assert all(chunk.chunk.embedding == [] for chunk in chunks)


async def test_lexical_corpus_cache_reuses_embedding_free_payload(monkeypatch) -> None:
    """Cache hit avoids a second Mongo light load and stores no vector values."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=2)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="A", chunk_index=0)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="B", chunk_index=1)
    calls: list[int] = []
    original = env.vector.list_chunks_light

    async def spy(tenant_id: str, website_id: str, *, limit: int = 0):
        calls.append(limit)
        return await original(tenant_id, website_id, limit=limit)

    monkeypatch.setattr(env.vector, "list_chunks_light", spy)
    first = await env.rag._load_all_chunks(TENANT, WEBSITE, corpus_version="v1")
    second = await env.rag._load_all_chunks(TENANT, WEBSITE, corpus_version="v1")

    assert len(first) == len(second) == 2
    assert calls == [0]
    lexical_write = next(call for call in env.cache.set_calls if call[0] == "lexical")
    raw = await env.cache.get("lexical", lexical_write[1])
    assert raw is not None
    assert '"embedding"' not in raw


async def test_hybrid_candidate_count_in_timing() -> None:
    """Timing dict includes hybrid_candidate_count when hybrid is active."""
    env = build_chat_env()
    env.rag._timing_enabled = True
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=3)
    for i in range(3):
        await make_chunk(
            env,
            tenant_id=TENANT,
            website_id=WEBSITE,
            text=f"Chunk {i} about pricing.",
            chunk_index=i,
        )
    events = await consume(
        env.rag.stream_answer(tenant_id=TENANT, website_id=WEBSITE, question="pricing?")
    )
    done = next(e for e in events if e["event"] == "done")
    timing = done["data"].get("timing")
    assert timing is not None
    assert "hybrid_candidate_count" in timing
    assert timing["hybrid_candidate_count"] >= 1


async def test_hybrid_e2e_sources_with_limit() -> None:
    """Hybrid e2e with bounded candidates still produces valid sources."""
    env = build_chat_env()
    rag = RagService(
        websites=env.websites,
        vector=env.vector,
        embedder=env.embedder,
        generation=env.generation,
        sessions=env.sessions,
        messages=env.messages,
        usage=env.usage,
        cache=env.cache,
        retrieval_strategy=HybridRetrievalStrategy(rrf_k=60),
        allow_reranking=False,
    )
    rag._timing_enabled = True
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=2)
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Pro plan costs $19 per month.",
        url="https://example.com/pricing",
        title="Pricing",
        chunk_index=0,
    )
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Enterprise includes SSO.",
        url="https://example.com/enterprise",
        title="Enterprise",
        chunk_index=1,
    )
    events = await consume(
        rag.stream_answer(tenant_id=TENANT, website_id=WEBSITE, question="pricing plan")
    )
    sources = next(e for e in events if e["event"] == "sources")
    assert len(sources["data"]["sources"]) >= 1
    done = next(e for e in events if e["event"] == "done")
    assert done["data"]["fallback"] is False
    timing = done["data"].get("timing")
    assert timing is not None
    assert timing["hybrid_candidate_count"] <= 2


async def test_vector_only_flow_unchanged_by_candidate_limit() -> None:
    """Vector-only strategy is unaffected by hybrid candidate limit."""
    env = build_chat_env()
    rag = RagService(
        websites=env.websites,
        vector=env.vector,
        embedder=env.embedder,
        generation=env.generation,
        sessions=env.sessions,
        messages=env.messages,
        usage=env.usage,
        cache=env.cache,
        retrieval_strategy=VectorRetrievalStrategy(),
        allow_reranking=False,
    )
    rag._timing_enabled = True
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=2)
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Pro plan details.",
        chunk_index=0,
    )
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Enterprise features.",
        chunk_index=1,
    )
    events = await consume(
        rag.stream_answer(tenant_id=TENANT, website_id=WEBSITE, question="plans?")
    )
    sources = next(e for e in events if e["event"] == "sources")
    assert len(sources["data"]["sources"]) >= 1
    done = next(e for e in events if e["event"] == "done")
    timing = done["data"].get("timing")
    assert timing is not None
    assert timing["retrieval_method"] == "vector"
    assert timing["hybrid_candidate_count"] == 0
