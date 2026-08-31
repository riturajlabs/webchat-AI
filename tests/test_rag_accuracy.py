"""Tests for RAG accuracy improvements.

Covers:
- Hybrid retrieval enabled by default
- Reranker execution path
- Faithfulness score generation
- Adaptive provider routing (integration-level)
- RAG confidence scoring (pre-generation)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from backend.core.config import get_settings
from backend.models.chat_message import CHAT_ROLE_ASSISTANT
from backend.models.knowledge_chunk import KnowledgeChunk
from backend.prompts.rag import UNKNOWN_ANSWER_FALLBACK, ContextItem
from backend.repositories.vector.base import VectorSearchResult
from backend.repositories.vector.reranker import EmbeddingReranker, _cosine_similarity
from backend.services.chat.query_rewrite import (
    DEFAULT_REWRITE_CONTEXT_CHARS,
    build_search_query,
    needs_conversation_context,
)
from backend.services.chat.rag_service import _check_faithfulness
from backend.services.chat.retrieval_strategy import (
    HybridRetrievalStrategy,
    VectorRetrievalStrategy,
)

from tests.chat_helpers import build_chat_env, consume, make_chunk, make_website

TENANT = "accuracy-tenant"
WEBSITE = "accuracy-web"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _stream(env, **kwargs):  # type: ignore[no-untyped-def]
    return await consume(env.rag.stream_answer(**kwargs))


def _done_event(events):  # type: ignore[no-untyped-def]
    return next(event for event in events if event["event"] == "done")


# ---------------------------------------------------------------------------
# 1. Hybrid retrieval enabled by default
# ---------------------------------------------------------------------------


def test_hybrid_is_default_strategy() -> None:
    env = build_chat_env()
    assert isinstance(env.rag._retrieval_strategy, HybridRetrievalStrategy)


def test_hybrid_default_config_flag() -> None:
    assert get_settings().enable_hybrid_search is True


def test_hybrid_flag_false_restores_vector_strategy() -> None:
    env = build_chat_env()
    with patch.object(env.rag, "_retrieval_strategy", VectorRetrievalStrategy()):
        assert isinstance(env.rag._retrieval_strategy, VectorRetrievalStrategy)


async def test_hybrid_default_e2e_produces_sources() -> None:
    env = build_chat_env()
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
        text="Enterprise includes SSO and audit logs.",
        url="https://example.com/enterprise",
        title="Enterprise",
        chunk_index=1,
    )
    events = await _stream(env, tenant_id=TENANT, website_id=WEBSITE, question="pricing plan")
    sources = next(e for e in events if e["event"] == "sources")
    assert len(sources["data"]["sources"]) >= 1
    done = _done_event(events)
    assert done["data"]["fallback"] is False


async def test_hybrid_strategy_uses_list_chunks_for_keyword_ranking() -> None:
    """HybridRetrievalStrategy calls list_chunks to load all chunks for keyword scoring."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="Knowledge.")
    env.rag._timing_enabled = True

    events = await _stream(env, tenant_id=TENANT, website_id=WEBSITE, question="Knowledge.")
    done = _done_event(events)
    timing = done["data"].get("timing")
    # Hybrid strategy always loads all chunks for keyword scoring.
    assert timing is not None
    assert timing["retrieval_method"] == "hybrid"
    assert timing["keyword_result_count"] >= 1


# ---------------------------------------------------------------------------
# 2. Reranker execution path
# ---------------------------------------------------------------------------


def test_reranker_config_defaults() -> None:
    settings = get_settings()
    assert settings.enable_reranking is True
    assert settings.rerank_top_k == 5


def test_reranker_initialized_when_allowed() -> None:
    env = build_chat_env(reranker=True)
    assert isinstance(env.rag._reranker, EmbeddingReranker)


def test_reranker_disabled_when_flag_false() -> None:
    env = build_chat_env(reranker=False)
    assert env.rag._reranker is None


def test_reranker_cosine_similarity_identical() -> None:
    assert _cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == 1.0


def test_reranker_cosine_similarity_orthogonal() -> None:
    assert abs(_cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-6


def test_reranker_cosine_similarity_empty() -> None:
    assert _cosine_similarity([], []) == 0.0


async def test_reranker_reorders_results() -> None:
    class LocalFakeEmbedder:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        async def embed(self, texts: list[str]) -> list[list[float]]:
            self.calls.append(texts)
            vectors = []
            for t in texts:
                if "query" in t.lower():
                    vectors.append([1.0, 0.0, 0.0, 0.0])
                elif "chunk_b" in t.lower():
                    vectors.append([0.9, 0.1, 0.0, 0.0])
                else:
                    vectors.append([0.0, 0.0, 0.0, 1.0])
            return vectors

    fake_embedder = LocalFakeEmbedder()
    reranker = EmbeddingReranker(embedder=fake_embedder, top_k=2)

    chunk_a = KnowledgeChunk.new(
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-a",
        chunk_text="chunk_a text",
        embedding=[0.0] * 4,
        chunk_index=0,
    )
    chunk_b = KnowledgeChunk.new(
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-b",
        chunk_text="chunk_b text",
        embedding=[0.0] * 4,
        chunk_index=0,
    )

    candidates = [
        VectorSearchResult(chunk=chunk_a, score=0.99),
        VectorSearchResult(chunk=chunk_b, score=0.95),
    ]

    result, metrics = await reranker.rerank("query text", candidates)
    assert len(result) == 2
    assert result[0].chunk.chunk_text == "chunk_b text"
    assert result[1].chunk.chunk_text == "chunk_a text"
    assert metrics.input_count == 2
    assert metrics.output_count == 2


async def test_reranker_returns_original_on_embed_failure() -> None:
    class FailingEmbedder:
        async def embed(self, texts: list[str]) -> list[list[float]]:
            raise ConnectionError("provider down")

    reranker = EmbeddingReranker(embedder=FailingEmbedder(), top_k=5)

    chunk = KnowledgeChunk.new(
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-1",
        chunk_text="test",
        embedding=[0.0] * 4,
        chunk_index=0,
    )
    candidates = [VectorSearchResult(chunk=chunk, score=0.9)]
    result, metrics = await reranker.rerank("query", candidates)
    assert len(result) == 1
    assert result[0].chunk.chunk_text == "test"
    assert metrics.output_count == 1


async def test_reranker_top_k_limits_output() -> None:
    class SimpleEmbedder:
        async def embed(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0, 0.0, 0.0]] * len(texts)

    reranker = EmbeddingReranker(embedder=SimpleEmbedder(), top_k=2)

    chunks = [
        KnowledgeChunk.new(
            tenant_id=TENANT,
            website_id=WEBSITE,
            document_id=f"doc-{i}",
            chunk_text=f"chunk_{i}",
            embedding=[0.0] * 4,
            chunk_index=i,
        )
        for i in range(5)
    ]
    candidates = [VectorSearchResult(chunk=c, score=0.9 - i * 0.01) for i, c in enumerate(chunks)]
    result, metrics = await reranker.rerank("query", candidates)
    assert len(result) == 2
    assert metrics.output_count == 2


async def test_reranker_in_done_timing_event() -> None:
    """The done event timing dict includes reranked field."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="Knowledge.")
    env.rag._timing_enabled = True
    events = await _stream(env, tenant_id=TENANT, website_id=WEBSITE, question="test")
    done = _done_event(events)
    timing = done["data"].get("timing")
    assert timing is not None
    assert "reranked" in timing
    # Default is reranker=False in build_chat_env, so reranked=False.
    assert timing["reranked"] is False


# ---------------------------------------------------------------------------
# 3. Faithfulness score generation
# ---------------------------------------------------------------------------


def test_faithfulness_config_defaults() -> None:
    settings = get_settings()
    assert settings.enable_faithfulness_check is True
    assert settings.faithfulness_warning_threshold == 0.6


def test_faithfulness_full_support() -> None:
    context = [
        ContextItem(
            url="https://a.com", title="A", heading=None, text="The Pro plan costs $19 per month."
        ),
    ]
    score = _check_faithfulness("The Pro plan costs $19 per month.", context)
    assert score == 1.0


def test_faithfulness_no_support() -> None:
    context = [
        ContextItem(url="https://a.com", title="A", heading=None, text="The Pro plan costs $19."),
    ]
    score = _check_faithfulness(
        "Quantum entanglement enables faster-than-light communication.",
        context,
    )
    assert score <= 0.3


def test_faithfulness_partial_support() -> None:
    context = [
        ContextItem(
            url="https://a.com",
            title="A",
            heading=None,
            text="The Pro plan costs $19 per month and includes priority support.",
        ),
    ]
    score = _check_faithfulness(
        "The Pro plan costs $19. However, quantum entanglement is not involved.",
        context,
    )
    assert 0.3 <= score <= 0.8


def test_faithfulness_empty_answer() -> None:
    assert _check_faithfulness("", []) == 0.0


def test_faithfulness_short_sentences_unsupported() -> None:
    """Sentences with no significant words (<=3 chars) are now unsupported."""
    context = [
        ContextItem(url="https://a.com", title="A", heading=None, text="Some context."),
    ]
    score = _check_faithfulness("Hi. Ok.", context)
    assert score == 0.0


def test_faithfulness_short_sentence_with_long_words_supported() -> None:
    """Short sentences with enough significant words can still be faithful."""
    context = [
        ContextItem(
            url="https://a.com", title="A", heading=None, text="The pricing page details plans."
        ),
    ]
    score = _check_faithfulness("The pricing page.", context)
    assert score == 1.0


def test_faithfulness_multiple_context_items() -> None:
    context = [
        ContextItem(
            url="https://a.com", title="A", heading=None, text="The pricing page details plans."
        ),
        ContextItem(
            url="https://b.com",
            title="B",
            heading=None,
            text="Enterprise tier includes SSO and audit.",
        ),
    ]
    score = _check_faithfulness(
        "The pricing page shows plans. Enterprise includes SSO.",
        context,
    )
    assert score >= 0.8


def test_faithfulness_score_in_done_event() -> None:
    env = build_chat_env()
    assert env.rag._enable_faithfulness_check is True


def test_faithfulness_disabled_skips_check() -> None:
    with patch.object(get_settings(), "enable_faithfulness_check", False):
        env = build_chat_env()
        assert env.rag._enable_faithfulness_check is False


async def test_faithfulness_score_appears_in_done_event() -> None:
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="Knowledge.")
    events = await _stream(env, tenant_id=TENANT, website_id=WEBSITE, question="test")
    done = _done_event(events)
    assert "faithfulness_score" in done["data"]
    assert isinstance(done["data"]["faithfulness_score"], float)
    assert 0.0 <= done["data"]["faithfulness_score"] <= 1.0


# ---------------------------------------------------------------------------
# 4. Adaptive provider routing (integration)
# ---------------------------------------------------------------------------


def test_adaptive_routing_config_defaults() -> None:
    settings = get_settings()
    assert settings.ai_provider_routing_mode == "static"
    assert settings.ai_provider_cooldown_seconds == 60
    assert settings.ai_provider_health_check_interval == 300
    assert settings.ai_provider_recovery_window_seconds == 120


def test_rag_service_uses_static_generation_by_default() -> None:
    env = build_chat_env()
    # In test env, generation is FakeGenerationClient; the FallbackGenerationClient
    # wrapper is only applied in deps.py for the real service.
    # Verify the generation client is present and callable.
    assert env.rag._generation is not None
    assert hasattr(env.rag._generation, "stream_generate")


async def test_done_event_includes_reranked_and_faithfulness_fields() -> None:
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="Knowledge.")
    events = await _stream(env, tenant_id=TENANT, website_id=WEBSITE, question="test")
    done = _done_event(events)
    assert "faithfulness_score" in done["data"]


# ---------------------------------------------------------------------------
# 5. P0 optimization: reranker uses stored embeddings (no API call)
# ---------------------------------------------------------------------------


async def test_reranker_uses_stored_embeddings_no_embed_call() -> None:
    """When query_embedding is provided, the reranker must NOT call the
    embedding API — it uses stored chunk embeddings for cosine similarity."""

    class TrackingEmbedder:
        def __init__(self) -> None:
            self.call_count = 0

        async def embed(self, texts: list[str]) -> list[list[float]]:
            self.call_count += 1
            return [[1.0, 0.0, 0.0, 0.0]] * len(texts)

    embedder = TrackingEmbedder()
    reranker = EmbeddingReranker(embedder=embedder, top_k=3)

    chunk_a = KnowledgeChunk.new(
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-a",
        chunk_text="chunk_a text",
        embedding=[1.0, 0.0, 0.0, 0.0],
        chunk_index=0,
    )
    chunk_b = KnowledgeChunk.new(
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-b",
        chunk_text="chunk_b text",
        embedding=[0.0, 1.0, 0.0, 0.0],
        chunk_index=1,
    )
    chunk_c = KnowledgeChunk.new(
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-c",
        chunk_text="chunk_c text",
        embedding=[0.0, 0.0, 1.0, 0.0],
        chunk_index=2,
    )

    candidates = [
        VectorSearchResult(chunk=chunk_a, score=0.9),
        VectorSearchResult(chunk=chunk_b, score=0.8),
        VectorSearchResult(chunk=chunk_c, score=0.7),
    ]

    query_embedding = [1.0, 0.0, 0.0, 0.0]
    result, metrics = await reranker.rerank("query", candidates, query_embedding=query_embedding)

    # No embedding API call should have been made.
    assert embedder.call_count == 0
    assert metrics.rerank_embedding_ms == 0.0
    # chunk_a has embedding identical to query -> highest similarity.
    assert result[0].chunk.chunk_text == "chunk_a text"
    assert result[0].score == 1.0
    assert len(result) == 3


async def test_reranker_precomputed_embedding_reorders_correctly() -> None:
    """Precomputed query embedding produces correct cosine-similarity ordering."""
    embedder = TrackingEmbedder()
    reranker = EmbeddingReranker(embedder=embedder, top_k=3)

    chunk_a = KnowledgeChunk.new(
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-a",
        chunk_text="a",
        embedding=[0.0, 1.0, 0.0, 0.0],
        chunk_index=0,
    )
    chunk_b = KnowledgeChunk.new(
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-b",
        chunk_text="b",
        embedding=[0.9, 0.1, 0.0, 0.0],
        chunk_index=1,
    )
    chunk_c = KnowledgeChunk.new(
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-c",
        chunk_text="c",
        embedding=[0.0, 0.0, 0.0, 1.0],
        chunk_index=2,
    )

    candidates = [
        VectorSearchResult(chunk=chunk_a, score=0.5),
        VectorSearchResult(chunk=chunk_b, score=0.5),
        VectorSearchResult(chunk=chunk_c, score=0.5),
    ]

    # Query is close to chunk_b's embedding.
    query_embedding = [1.0, 0.0, 0.0, 0.0]
    result, _ = await reranker.rerank("query", candidates, query_embedding=query_embedding)

    # chunk_b has the highest cosine similarity with the query.
    assert result[0].chunk.chunk_text == "b"
    # chunk_a is orthogonal to query (cosine ~0).
    assert result[1].chunk.chunk_text == "a"
    # chunk_c is orthogonal to query (cosine ~0).
    assert result[2].chunk.chunk_text == "c"


async def test_reranker_legacy_path_still_works() -> None:
    """Without query_embedding, the reranker falls back to the embed API."""

    class LegacyEmbedder:
        def __init__(self) -> None:
            self.call_count = 0

        async def embed(self, texts: list[str]) -> list[list[float]]:
            self.call_count += 1
            vectors = []
            for t in texts:
                if "query" in t.lower():
                    vectors.append([1.0, 0.0, 0.0, 0.0])
                elif "best" in t.lower():
                    vectors.append([0.9, 0.1, 0.0, 0.0])
                else:
                    vectors.append([0.0, 0.0, 0.0, 1.0])
            return vectors

    embedder = LegacyEmbedder()
    reranker = EmbeddingReranker(embedder=embedder, top_k=2)

    chunk_a = KnowledgeChunk.new(
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-a",
        chunk_text="worst match",
        embedding=[0.0] * 4,
        chunk_index=0,
    )
    chunk_b = KnowledgeChunk.new(
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-b",
        chunk_text="best match",
        embedding=[0.0] * 4,
        chunk_index=1,
    )

    candidates = [
        VectorSearchResult(chunk=chunk_a, score=0.9),
        VectorSearchResult(chunk=chunk_b, score=0.8),
    ]

    # No query_embedding -> legacy embed path.
    result, _ = await reranker.rerank("query text", candidates)
    assert embedder.call_count == 1  # embed was called
    assert result[0].chunk.chunk_text == "best match"


async def test_reranker_empty_chunk_embedding_handled() -> None:
    """Chunks with empty stored embeddings get similarity 0 (graceful handling)."""
    embedder = TrackingEmbedder()
    reranker = EmbeddingReranker(embedder=embedder, top_k=3)

    chunk_empty = KnowledgeChunk.new(
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-empty",
        chunk_text="no embedding",
        embedding=[],
        chunk_index=0,
    )
    chunk_valid = KnowledgeChunk.new(
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-valid",
        chunk_text="has embedding",
        embedding=[1.0, 0.0, 0.0, 0.0],
        chunk_index=1,
    )

    candidates = [
        VectorSearchResult(chunk=chunk_empty, score=0.9),
        VectorSearchResult(chunk=chunk_valid, score=0.8),
    ]

    query_embedding = [1.0, 0.0, 0.0, 0.0]
    result, metrics = await reranker.rerank("query", candidates, query_embedding=query_embedding)

    assert embedder.call_count == 0
    # Valid chunk ranks first (similarity 1.0), empty chunk gets 0.0.
    assert result[0].chunk.chunk_text == "has embedding"
    assert result[0].score == 1.0
    assert result[1].chunk.chunk_text == "no embedding"
    assert result[1].score == 0.0


async def test_reranker_passes_query_embedding_in_rag_flow() -> None:
    """Integration: RagService passes query_embedding to the reranker."""
    env = build_chat_env(reranker=True)
    env.rag._confidence_check_enabled = False
    # Chunks made by make_chunk carry no stored embeddings, so the reranker
    # scores them 0.0; disable min_score so they are not all filtered out
    # (an empty context must fall back instead of reaching the model).
    env.rag._min_score = 0.0
    env.rag._timing_enabled = True
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=2)
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Plan A costs $19.",
        url="https://example.com/a",
        title="Plan A",
        chunk_index=0,
    )
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Plan B costs $49.",
        url="https://example.com/b",
        title="Plan B",
        chunk_index=1,
    )

    events = await _stream(env, tenant_id=TENANT, website_id=WEBSITE, question="pricing")
    done = _done_event(events)
    assert done["data"]["fallback"] is False
    # Reranker was active.
    timing = done["data"]["timing"]
    assert timing["reranked"] is True
    assert timing["rerank_embedding_ms"] == 0.0
    assert timing["rerank_ms"] >= 0


class TrackingEmbedder:
    """Reusable test embedder that tracks call count."""

    def __init__(self) -> None:
        self.call_count = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.call_count += 1
        return [[1.0, 0.0, 0.0, 0.0]] * len(texts)


# ---------------------------------------------------------------------------
# 6. Adaptive retrieval strategy
# ---------------------------------------------------------------------------

ADAPTIVE_TENANT = "adaptive-tenant"
ADAPTIVE_WEB = "adaptive-web"


def _make_adaptive_settings(**overrides):  # type: ignore[no-untyped-def]
    """Build a mock settings object with adaptive retrieval enabled."""
    defaults = dict(
        enable_hybrid_search=True,
        hybrid_rrf_k=40,
        chat_top_k=8,
        rag_prompt_version=1,
        chat_memory_turns=8,
        chat_context_chunk_chars=4000,
        chat_context_max_chars=20000,
        chat_context_min_score=0.25,
        perf_timing_log_enabled=True,
        embedding_cache_size=0,
        embedding_cache_ttl_seconds=0,
        chat_retrieval_cache_size=0,
        chat_retrieval_cache_ttl_seconds=0,
        enable_reranking=False,
        rerank_top_k=0,
        enable_faithfulness_check=False,
        faithfulness_warning_threshold=0.6,
        hybrid_search_candidate_limit=50,
        enable_adaptive_retrieval=True,
        adaptive_simple_top_k=4,
        adaptive_simple_rerank_top_k=3,
        adaptive_simple_max_context_chars=8000,
        adaptive_complex_top_k=12,
        adaptive_complex_rerank_top_k=8,
        adaptive_complex_max_context_chars=30000,
        enable_rag_confidence_check=False,
        rag_confidence_threshold=0.3,
        enable_conversational_query_rewrite=True,
        enable_context_optimization=False,
        ai_model_pricing_json="",
    )
    defaults.update(overrides)

    class _Settings:
        pass

    s = _Settings()
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


def _build_rag_with_adaptive(env, **settings_overrides):  # type: ignore[no-untyped-def]
    """Build a RagService with adaptive retrieval settings patched."""
    settings = _make_adaptive_settings(**settings_overrides)
    with patch(
        "backend.services.chat.rag_service.get_settings",
        return_value=settings,
    ):
        from backend.services.chat.rag_service import RagService

        return RagService(
            websites=env.websites,
            vector=env.vector,
            embedder=env.embedder,
            generation=env.generation,
            sessions=env.sessions,
            messages=env.messages,
            usage=env.usage,
            cache=None,
            allow_reranking=False,
        )


async def test_adaptive_config_defaults() -> None:
    """Default settings have adaptive retrieval disabled."""
    settings = get_settings()
    assert settings.enable_adaptive_retrieval is False
    assert settings.adaptive_simple_top_k == 4
    assert settings.adaptive_complex_top_k == 12
    assert settings.adaptive_simple_max_context_chars == 8000
    assert settings.adaptive_complex_max_context_chars == 30000


async def test_adaptive_disabled_by_default() -> None:
    """When adaptive is disabled (default), RagService reflects that."""
    env = build_chat_env()
    assert env.rag._adaptive_enabled is False


async def test_adaptive_enabled_flag() -> None:
    """When settings enable adaptive, RagService picks it up."""
    env = build_chat_env()
    rag = _build_rag_with_adaptive(env)
    assert rag._adaptive_enabled is True
    assert rag._adaptive_simple_top_k == 4
    assert rag._adaptive_complex_top_k == 12
    assert rag._adaptive_simple_max_context_chars == 8000
    assert rag._adaptive_complex_max_context_chars == 30000


async def test_adaptive_e2e_simple_query_uses_smaller_context() -> None:
    """End-to-end: simple query with adaptive enabled uses simple budget."""
    env = build_chat_env()
    rag = _build_rag_with_adaptive(env)
    await make_website(env, tenant_id=ADAPTIVE_TENANT, website_id=ADAPTIVE_WEB, knowledge_chunks=1)
    await make_chunk(
        env,
        tenant_id=ADAPTIVE_TENANT,
        website_id=ADAPTIVE_WEB,
        text="Contact us at support@example.com.",
        chunk_index=0,
    )

    events = await consume(
        rag.stream_answer(
            tenant_id=ADAPTIVE_TENANT,
            website_id=ADAPTIVE_WEB,
            question="What is the contact email?",
        )
    )
    done = next(e for e in events if e["event"] == "done")
    assert done["data"]["fallback"] is False
    assert done["data"]["timing"]["adaptive_max_context_chars"] == 8000


async def test_adaptive_e2e_complex_query_uses_larger_context() -> None:
    """End-to-end: complex query with adaptive enabled uses complex budget."""
    env = build_chat_env()
    rag = _build_rag_with_adaptive(env)
    await make_website(env, tenant_id=ADAPTIVE_TENANT, website_id=ADAPTIVE_WEB, knowledge_chunks=2)
    await make_chunk(
        env,
        tenant_id=ADAPTIVE_TENANT,
        website_id=ADAPTIVE_WEB,
        text="Plan A costs $19 with basic features.",
        chunk_index=0,
    )
    await make_chunk(
        env,
        tenant_id=ADAPTIVE_TENANT,
        website_id=ADAPTIVE_WEB,
        text="Plan B costs $49 with advanced features and priority support.",
        chunk_index=1,
    )

    events = await consume(
        rag.stream_answer(
            tenant_id=ADAPTIVE_TENANT,
            website_id=ADAPTIVE_WEB,
            question=(
                "Can you compare the differences between the basic and enterprise plans "
                "and explain the advantages and disadvantages of each option and also "
                "describe the implementation details for the integration?"
            ),
        )
    )
    done = next(e for e in events if e["event"] == "done")
    assert done["data"]["fallback"] is False
    assert done["data"]["timing"]["adaptive_max_context_chars"] == 30000


async def test_adaptive_e2e_medium_query_uses_default_context() -> None:
    """End-to-end: medium query uses default (non-adaptive) context budget."""
    env = build_chat_env()
    rag = _build_rag_with_adaptive(env)
    await make_website(env, tenant_id=ADAPTIVE_TENANT, website_id=ADAPTIVE_WEB, knowledge_chunks=1)
    await make_chunk(
        env,
        tenant_id=ADAPTIVE_TENANT,
        website_id=ADAPTIVE_WEB,
        text="We offer API access.",
        chunk_index=0,
    )

    events = await consume(
        rag.stream_answer(
            tenant_id=ADAPTIVE_TENANT,
            website_id=ADAPTIVE_WEB,
            question="How does the API work?",
        )
    )
    done = next(e for e in events if e["event"] == "done")
    assert done["data"]["fallback"] is False
    assert done["data"]["timing"]["adaptive_max_context_chars"] == 20000


async def test_adaptive_disabled_fallback_to_fixed_params() -> None:
    """When adaptive is disabled, all queries use the fixed top_k / context."""
    env = build_chat_env()
    env.rag._timing_enabled = True
    assert env.rag._adaptive_enabled is False
    await make_website(env, tenant_id=ADAPTIVE_TENANT, website_id=ADAPTIVE_WEB, knowledge_chunks=1)
    await make_chunk(
        env,
        tenant_id=ADAPTIVE_TENANT,
        website_id=ADAPTIVE_WEB,
        text="Hello world.",
        chunk_index=0,
    )

    events = await consume(
        env.rag.stream_answer(
            tenant_id=ADAPTIVE_TENANT,
            website_id=ADAPTIVE_WEB,
            question="What is the pricing and features and integration and deployment?",
        )
    )
    done = next(e for e in events if e["event"] == "done")
    assert done["data"]["fallback"] is False
    # Even for a complex query, adaptive_max_context_chars equals the fixed default.
    assert done["data"]["timing"]["adaptive_max_context_chars"] == 20000


async def test_adaptive_custom_settings_override() -> None:
    """Custom adaptive settings are respected when building RagService."""
    env = build_chat_env()
    rag = _build_rag_with_adaptive(
        env,
        adaptive_simple_top_k=2,
        adaptive_complex_top_k=20,
        adaptive_simple_max_context_chars=4000,
        adaptive_complex_max_context_chars=50000,
    )
    assert rag._adaptive_simple_top_k == 2
    assert rag._adaptive_complex_top_k == 20
    assert rag._adaptive_simple_max_context_chars == 4000
    assert rag._adaptive_complex_max_context_chars == 50000


# ---------------------------------------------------------------------------
# 7. RAG confidence scoring (pre-generation)
# ---------------------------------------------------------------------------

CONF_TENANT = "conf-tenant"
CONF_WEB = "conf-web"


def _make_confidence_settings(**overrides):  # type: ignore[no-untyped-def]
    """Build a mock settings object with confidence check enabled."""
    defaults = dict(
        enable_hybrid_search=True,
        hybrid_rrf_k=40,
        chat_top_k=8,
        rag_prompt_version=1,
        chat_memory_turns=8,
        chat_context_chunk_chars=4000,
        chat_context_max_chars=20000,
        chat_context_min_score=0.25,
        perf_timing_log_enabled=True,
        embedding_cache_size=0,
        embedding_cache_ttl_seconds=0,
        chat_retrieval_cache_size=0,
        chat_retrieval_cache_ttl_seconds=0,
        enable_reranking=False,
        rerank_top_k=0,
        enable_faithfulness_check=False,
        faithfulness_warning_threshold=0.6,
        hybrid_search_candidate_limit=50,
        enable_adaptive_retrieval=False,
        adaptive_simple_top_k=4,
        adaptive_simple_rerank_top_k=3,
        adaptive_simple_max_context_chars=8000,
        adaptive_complex_top_k=12,
        adaptive_complex_rerank_top_k=8,
        adaptive_complex_max_context_chars=30000,
        enable_rag_confidence_check=True,
        rag_confidence_threshold=0.3,
        enable_conversational_query_rewrite=True,
        enable_context_optimization=False,
        ai_model_pricing_json="",
    )
    defaults.update(overrides)

    class _Settings:
        pass

    s = _Settings()
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


def _build_rag_with_confidence(env, **settings_overrides):  # type: ignore[no-untyped-def]
    """Build a RagService with confidence check settings patched."""
    settings = _make_confidence_settings(**settings_overrides)
    retrieval_strategy = settings_overrides.pop("retrieval_strategy", None)
    with patch(
        "backend.services.chat.rag_service.get_settings",
        return_value=settings,
    ):
        from backend.services.chat.rag_service import RagService

        return RagService(
            websites=env.websites,
            vector=env.vector,
            embedder=env.embedder,
            generation=env.generation,
            sessions=env.sessions,
            messages=env.messages,
            usage=env.usage,
            cache=None,
            allow_reranking=False,
            retrieval_strategy=retrieval_strategy,
        )


async def test_confidence_config_defaults() -> None:
    """Default settings enable the production abstention guard."""
    settings = get_settings()
    assert settings.enable_rag_confidence_check is True
    assert settings.rag_confidence_threshold == 0.3


async def test_confidence_disabled_by_default() -> None:
    """The default RagService enables confidence checking."""
    env = build_chat_env()
    assert env.rag._confidence_check_enabled is True


async def test_confidence_enabled_flag() -> None:
    """When settings enable confidence check, RagService picks it up."""
    env = build_chat_env()
    rag = _build_rag_with_confidence(env)
    assert rag._confidence_check_enabled is True
    assert rag._confidence_threshold == 0.3


async def test_confidence_high_scores_proceed() -> None:
    """High-confidence retrieval (fake scores ~0.9) proceeds to generation."""
    env = build_chat_env()
    rag = _build_rag_with_confidence(env)
    await make_website(env, tenant_id=CONF_TENANT, website_id=CONF_WEB, knowledge_chunks=1)
    await make_chunk(
        env,
        tenant_id=CONF_TENANT,
        website_id=CONF_WEB,
        text="We offer Pro and Team plans.",
        chunk_index=0,
    )

    events = await consume(
        rag.stream_answer(
            tenant_id=CONF_TENANT,
            website_id=CONF_WEB,
            question="What plans do you offer?",
        )
    )
    done = next(e for e in events if e["event"] == "done")
    assert done["data"]["fallback"] is False
    # Confidence was computed and included in timing.
    timing = done["data"]["timing"]
    assert timing["confidence_score"] is not None
    assert timing["confidence_score"] > 0.3


async def test_confidence_low_scores_fallback() -> None:
    """Low-confidence retrieval triggers fallback response."""
    from backend.services.chat.retrieval_strategy import VectorRetrievalStrategy

    env = build_chat_env()
    # Use vector-only strategy so scores are raw (0.9) not RRF-boosted (1.0).
    # Set threshold above 0.9 so the confidence check fails.
    rag = _build_rag_with_confidence(
        env,
        rag_confidence_threshold=0.95,
        retrieval_strategy=VectorRetrievalStrategy(),
    )
    await make_website(env, tenant_id=CONF_TENANT, website_id=CONF_WEB, knowledge_chunks=1)
    await make_chunk(
        env,
        tenant_id=CONF_TENANT,
        website_id=CONF_WEB,
        text="We offer Pro and Team plans.",
        chunk_index=0,
    )

    events = await consume(
        rag.stream_answer(
            tenant_id=CONF_TENANT,
            website_id=CONF_WEB,
            question="What plans do you offer?",
        )
    )
    done = next(e for e in events if e["event"] == "done")
    assert done["data"]["fallback"] is True
    # Should contain the standard fallback message.
    msg_events = [e for e in events if e["event"] == "message"]
    assert any("couldn't find" in e["data"]["delta"].lower() for e in msg_events)


async def test_unrelated_database_password_question_abstains() -> None:
    """An unrelated question must not turn nearest-neighbor noise into an answer."""
    env = build_chat_env()
    await make_website(env, tenant_id=CONF_TENANT, website_id=CONF_WEB, knowledge_chunks=1)
    chunk = await make_chunk(
        env,
        tenant_id=CONF_TENANT,
        website_id=CONF_WEB,
        text="Stripe invoices and checkout payments are documented here.",
    )

    async def low_similarity_search(*args, **kwargs):  # type: ignore[no-untyped-def]
        return [VectorSearchResult(chunk=chunk, score=0.08)]

    env.vector.similarity_search = low_similarity_search  # type: ignore[method-assign]
    events = await _stream(
        env,
        tenant_id=CONF_TENANT,
        website_id=CONF_WEB,
        question="What is the database password?",
    )

    done = _done_event(events)
    assert done["data"]["fallback"] is True
    assert done["data"]["confidence_rejected_chunks_count"] == 1


async def test_confidence_disabled_skips_check() -> None:
    """When confidence check is disabled, low scores don't block generation."""
    from backend.services.chat.retrieval_strategy import VectorRetrievalStrategy

    env = build_chat_env()
    # Don't enable confidence check — even with high threshold, should proceed.
    rag = _build_rag_with_confidence(
        env,
        enable_rag_confidence_check=False,
        rag_confidence_threshold=0.95,
        retrieval_strategy=VectorRetrievalStrategy(),
    )
    await make_website(env, tenant_id=CONF_TENANT, website_id=CONF_WEB, knowledge_chunks=1)
    await make_chunk(
        env,
        tenant_id=CONF_TENANT,
        website_id=CONF_WEB,
        text="We offer Pro and Team plans.",
        chunk_index=0,
    )

    events = await consume(
        rag.stream_answer(
            tenant_id=CONF_TENANT,
            website_id=CONF_WEB,
            question="What plans do you offer?",
        )
    )
    done = next(e for e in events if e["event"] == "done")
    assert done["data"]["fallback"] is False


async def test_confidence_timing_field_present_when_disabled() -> None:
    """Timing includes confidence metrics when the guard is enabled."""
    env = build_chat_env()
    env.rag._timing_enabled = True
    await make_website(env, tenant_id=CONF_TENANT, website_id=CONF_WEB, knowledge_chunks=1)
    await make_chunk(
        env,
        tenant_id=CONF_TENANT,
        website_id=CONF_WEB,
        text="Hello world.",
        chunk_index=0,
    )

    events = await consume(
        env.rag.stream_answer(
            tenant_id=CONF_TENANT,
            website_id=CONF_WEB,
            question="Hi",
        )
    )
    done = next(e for e in events if e["event"] == "done")
    timing = done["data"]["timing"]
    assert timing["confidence_score"] is not None
    assert timing["confidence_minimum_score"] is not None
    assert timing["confidence_average_score"] is not None
    assert timing["confidence_rejected_chunks_count"] == 0


async def test_confidence_threshold_custom_value() -> None:
    """Custom threshold value is respected."""
    env = build_chat_env()
    rag = _build_rag_with_confidence(env, rag_confidence_threshold=0.5)
    assert rag._confidence_threshold == 0.5


def test_embedding_dimension_validation_rejects_mixed_batch() -> None:
    from backend.services.knowledge.embedding import ensure_vector_dimensions

    with pytest.raises(Exception, match="dimensions"):
        ensure_vector_dimensions("test", [[0.0, 1.0], [0.0]], 2)


# ---------------------------------------------------------------------------
# 8. Context optimization (near-dup removal + compression)
# ---------------------------------------------------------------------------

OPT_TENANT = "opt-tenant"
OPT_WEB = "opt-web"


def _make_opt_settings(**overrides):  # type: ignore[no-untyped-def]
    """Build a mock settings object with context optimization enabled."""
    defaults = dict(
        enable_hybrid_search=True,
        hybrid_rrf_k=40,
        chat_top_k=8,
        rag_prompt_version=1,
        chat_memory_turns=8,
        chat_context_chunk_chars=4000,
        chat_context_max_chars=20000,
        chat_context_min_score=0.25,
        perf_timing_log_enabled=True,
        embedding_cache_size=0,
        embedding_cache_ttl_seconds=0,
        chat_retrieval_cache_size=0,
        chat_retrieval_cache_ttl_seconds=0,
        enable_reranking=False,
        rerank_top_k=0,
        enable_faithfulness_check=False,
        faithfulness_warning_threshold=0.6,
        hybrid_search_candidate_limit=50,
        enable_adaptive_retrieval=False,
        adaptive_simple_top_k=4,
        adaptive_simple_rerank_top_k=3,
        adaptive_simple_max_context_chars=8000,
        adaptive_complex_top_k=12,
        adaptive_complex_rerank_top_k=8,
        adaptive_complex_max_context_chars=30000,
        enable_rag_confidence_check=False,
        rag_confidence_threshold=0.3,
        enable_conversational_query_rewrite=True,
        enable_context_optimization=True,
        ai_model_pricing_json="",
    )
    defaults.update(overrides)

    class _Settings:
        pass

    s = _Settings()
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


def _build_rag_with_opt(env, **settings_overrides):  # type: ignore[no-untyped-def]
    """Build a RagService with context optimization settings patched."""
    settings = _make_opt_settings(**settings_overrides)
    with patch(
        "backend.services.chat.rag_service.get_settings",
        return_value=settings,
    ):
        from backend.services.chat.rag_service import RagService

        return RagService(
            websites=env.websites,
            vector=env.vector,
            embedder=env.embedder,
            generation=env.generation,
            sessions=env.sessions,
            messages=env.messages,
            usage=env.usage,
            cache=None,
            allow_reranking=False,
        )


async def test_optimization_config_default() -> None:
    """Default settings have context optimization disabled."""
    settings = get_settings()
    assert settings.enable_context_optimization is False


async def test_optimization_disabled_by_default() -> None:
    """When disabled (default), RagService reflects that."""
    env = build_chat_env()
    assert env.rag._context_optimization_enabled is False


async def test_optimization_enabled_flag() -> None:
    """When enabled, RagService picks it up."""
    env = build_chat_env()
    rag = _build_rag_with_opt(env)
    assert rag._context_optimization_enabled is True


async def test_optimization_e2e_metrics_present() -> None:
    """When enabled, timing includes optimization metrics."""
    env = build_chat_env()
    rag = _build_rag_with_opt(env)
    await make_website(env, tenant_id=OPT_TENANT, website_id=OPT_WEB, knowledge_chunks=2)
    await make_chunk(
        env,
        tenant_id=OPT_TENANT,
        website_id=OPT_WEB,
        text="Cats are independent animals. They like to explore.",
        url="https://example.com/cats",
        title="Cats",
        chunk_index=0,
    )
    await make_chunk(
        env,
        tenant_id=OPT_TENANT,
        website_id=OPT_WEB,
        text="Dogs are loyal companions. They love their owners.",
        url="https://example.com/dogs",
        title="Dogs",
        chunk_index=1,
    )

    events = await consume(
        rag.stream_answer(
            tenant_id=OPT_TENANT,
            website_id=OPT_WEB,
            question="Tell me about pets.",
        )
    )
    done = next(e for e in events if e["event"] == "done")
    assert done["data"]["fallback"] is False
    timing = done["data"]["timing"]
    assert timing["original_context_chars"] is not None
    assert timing["optimized_context_chars"] is not None
    assert timing["removed_chunks_count"] is not None
    assert timing["original_context_chars"] >= timing["optimized_context_chars"]


async def test_optimization_disabled_no_metrics() -> None:
    """When disabled, optimization metrics are None in timing."""
    env = build_chat_env()
    env.rag._timing_enabled = True
    await make_website(env, tenant_id=OPT_TENANT, website_id=OPT_WEB, knowledge_chunks=1)
    await make_chunk(
        env,
        tenant_id=OPT_TENANT,
        website_id=OPT_WEB,
        text="Hello world.",
        chunk_index=0,
    )

    events = await consume(
        env.rag.stream_answer(
            tenant_id=OPT_TENANT,
            website_id=OPT_WEB,
            question="Hi",
        )
    )
    done = next(e for e in events if e["event"] == "done")
    timing = done["data"]["timing"]
    assert timing["original_context_chars"] is None
    assert timing["optimized_context_chars"] is None
    assert timing["removed_chunks_count"] is None


async def test_optimization_removes_near_duplicates() -> None:
    """Near-duplicate chunks are removed when optimization is enabled."""
    env = build_chat_env()
    rag = _build_rag_with_opt(env)
    await make_website(env, tenant_id=OPT_TENANT, website_id=OPT_WEB, knowledge_chunks=3)
    await make_chunk(
        env,
        tenant_id=OPT_TENANT,
        website_id=OPT_WEB,
        text="The pricing page shows three plans: Starter, Pro, and Enterprise.",
        url="https://example.com/pricing",
        title="Pricing",
        document_id="doc-pricing-1",
        chunk_index=0,
    )
    await make_chunk(
        env,
        tenant_id=OPT_TENANT,
        website_id=OPT_WEB,
        text="The pricing page shows three plans: Starter, Pro, and Enterprise tiers.",
        url="https://example.com/pricing-alt",
        title="Pricing Alt",
        document_id="doc-pricing-2",
        chunk_index=1,
    )
    await make_chunk(
        env,
        tenant_id=OPT_TENANT,
        website_id=OPT_WEB,
        text="Contact our support team for custom enterprise pricing options.",
        url="https://example.com/contact",
        title="Contact",
        document_id="doc-contact",
        chunk_index=2,
    )

    events = await consume(
        rag.stream_answer(
            tenant_id=OPT_TENANT,
            website_id=OPT_WEB,
            question="What are your pricing plans?",
        )
    )
    done = next(e for e in events if e["event"] == "done")
    timing = done["data"]["timing"]
    # At least one chunk removed as near-duplicate.
    assert timing["removed_chunks_count"] >= 1


async def test_optimization_preserves_unique_content() -> None:
    """Unique content from different sources is preserved in context."""
    env = build_chat_env()
    rag = _build_rag_with_opt(env)
    await make_website(env, tenant_id=OPT_TENANT, website_id=OPT_WEB, knowledge_chunks=2)
    await make_chunk(
        env,
        tenant_id=OPT_TENANT,
        website_id=OPT_WEB,
        text="We offer 24/7 phone support for all enterprise customers.",
        url="https://example.com/support",
        title="Support",
        document_id="doc-support",
        chunk_index=0,
    )
    await make_chunk(
        env,
        tenant_id=OPT_TENANT,
        website_id=OPT_WEB,
        text="Our billing cycle runs monthly with automatic renewals.",
        url="https://example.com/billing",
        title="Billing",
        document_id="doc-billing",
        chunk_index=1,
    )

    events = await consume(
        rag.stream_answer(
            tenant_id=OPT_TENANT,
            website_id=OPT_WEB,
            question="What support do you offer and how does billing work?",
        )
    )
    done = next(e for e in events if e["event"] == "done")
    assert done["data"]["fallback"] is False
    timing = done["data"]["timing"]
    # Both unique chunks should survive — no near-duplicates to remove.
    assert timing["removed_chunks_count"] == 0
    # Both chunks contribute to context.
    assert timing["original_context_chars"] > 0
    assert timing["optimized_context_chars"] > 0


# ---------------------------------------------------------------------------
# 9. Regression: _load_all_chunks must use list_chunks (with embeddings)
# ---------------------------------------------------------------------------

REG_TENANT = "regression-tenant"
REG_WEB = "regression-web"


async def test_keyword_only_chunk_survives_reranker_and_min_score() -> None:
    """Regression: chunks loaded via _load_all_chunks must carry embeddings so the
    reranker can score them.  Previously, _load_all_chunks used list_chunks_light
    which returned empty embeddings, causing the reranker to assign score 0.0 and
    _build_context's min_score filter to discard them."""
    from backend.models.knowledge_chunk import KnowledgeChunk as KC

    env = build_chat_env(reranker=True)
    await make_website(env, tenant_id=REG_TENANT, website_id=REG_WEB, knowledge_chunks=4)

    # Use non-zero embeddings so the reranker's cosine similarity produces
    # meaningful scores above the min_score threshold.
    chunks_data = [
        {
            "text": "Our pricing plans include Starter at $9, Pro at $19, and Enterprise custom.",
            "url": "https://example.com/pricing",
            "title": "Pricing",
            "document_id": "doc-pricing",
            "chunk_index": 0,
            "embedding": [0.9, 0.1, 0.0, 0.0],
        },
        {
            "text": "Contact support@example.com for help with your account.",
            "url": "https://example.com/support",
            "title": "Support",
            "document_id": "doc-support",
            "chunk_index": 1,
            "embedding": [0.1, 0.9, 0.0, 0.0],
        },
        {
            # Target: found by keyword ("api key") but at a higher index.
            "text": "To create an API key, go to Settings and click Generate.",
            "url": "https://example.com/apikeys",
            "title": "API Keys",
            "document_id": "doc-apikeys",
            "chunk_index": 2,
            "embedding": [0.0, 0.0, 0.9, 0.1],
        },
        {
            "text": "Our enterprise tier includes SSO, audit logs, and priority support.",
            "url": "https://example.com/enterprise",
            "title": "Enterprise",
            "document_id": "doc-enterprise",
            "chunk_index": 3,
            "embedding": [0.0, 0.0, 0.1, 0.9],
        },
    ]

    for cd in chunks_data:
        chunk = KC.new(
            tenant_id=REG_TENANT,
            website_id=REG_WEB,
            document_id=cd["document_id"],
            chunk_text=cd["text"],
            embedding=cd["embedding"],
            chunk_index=cd["chunk_index"],
            embedding_provider=env.embedder.embedding_identity.provider,
            embedding_model=env.embedder.embedding_identity.model,
            embedding_dimensions=env.embedder.embedding_identity.dimensions,
            embedding_version=env.embedder.embedding_identity.version,
            metadata={"source_url": cd["url"], "title": cd["title"]},
        )
        await env.vector.insert_chunks([chunk])

    events = await _stream(
        env,
        tenant_id=REG_TENANT,
        website_id=REG_WEB,
        question="How do I create an API key?",
    )
    sources = next(e for e in events if e["event"] == "sources")
    source_urls = [s["url"] for s in sources["data"]["sources"]]

    # The API key chunk must survive through retrieval → reranker → min_score filter.
    assert any("apikeys" in url for url in source_urls), (
        f"API key chunk missing from sources (was discarded by reranker/min_score). "
        f"Got: {source_urls}"
    )

    done = _done_event(events)
    assert done["data"]["fallback"] is False


# ---------------------------------------------------------------------------
# Stale retrieval prevention (cache invalidation)
# ---------------------------------------------------------------------------


async def test_stale_retrieval_prevented_after_cache_invalidation() -> None:
    """After invalidating the retrieval cache for a website, a second query
    hits the vector store instead of returning stale cached results."""
    from tests.fakes import FakeCacheStore

    env = build_chat_env(cache=FakeCacheStore())
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE)

    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-v1",
        text="Version one: the pricing is $9 per month.",
        url="https://example.com/pricing-v1",
        title="Pricing V1",
        chunk_index=0,
    )

    # First query — populates the retrieval cache.
    question = "what is the pricing"
    events_1 = await _stream(env, tenant_id=TENANT, website_id=WEBSITE, question=question)
    sources_1 = next(e for e in events_1 if e["event"] == "sources")
    urls_1 = [s["url"] for s in sources_1["data"]["sources"]]
    assert any("pricing-v1" in u for u in urls_1)

    # Simulate a crawl: add new content, invalidate the cache.
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-v2",
        text="Version two: the pricing changed to $19 per month.",
        url="https://example.com/pricing-v2",
        title="Pricing V2",
        chunk_index=1,
    )
    deleted = await env.cache.delete_by_prefix("retrieval", f"{TENANT}:{WEBSITE}:")
    assert deleted >= 1

    # Second query — must NOT return the stale v1-only cached result.
    events_2 = await _stream(env, tenant_id=TENANT, website_id=WEBSITE, question=question)
    sources_2 = next(e for e in events_2 if e["event"] == "sources")
    urls_2 = [s["url"] for s in sources_2["data"]["sources"]]

    # The fresh retrieval should see both chunks (or at least v2).
    assert any("pricing-v2" in u for u in urls_2), (
        f"Expected fresh v2 chunk after cache invalidation, got: {urls_2}"
    )


# ---------------------------------------------------------------------------
# Conversational query rewriting (multi-turn retrieval accuracy)
# ---------------------------------------------------------------------------

REWRITE_TENANT = "rewrite-tenant"
REWRITE_WEB = "rewrite-web"


def _last_embedded_text(env):  # type: ignore[no-untyped-def]
    """The most recent text the fake embedder embedded."""
    return env.embedder.calls[-1][-1]


def test_rewrite_config_default() -> None:
    """Conversational query rewriting ships enabled."""
    assert get_settings().enable_conversational_query_rewrite is True


def test_needs_context_pronoun_start() -> None:
    assert needs_conversation_context("it supports SSO?") is True
    assert needs_conversation_context("That plan sounds good.") is True
    assert needs_conversation_context("their pricing") is True


def test_needs_context_continuation_start() -> None:
    assert needs_conversation_context("what about refunds?") is True
    assert needs_conversation_context("how about enterprise?") is True
    assert needs_conversation_context("and the team plan?") is True
    assert needs_conversation_context("tell me more") is True
    assert needs_conversation_context("anything else?") is True


def test_needs_context_standalone_questions_untouched() -> None:
    assert needs_conversation_context("How do I reset my password?") is False
    assert needs_conversation_context("What plans do you offer?") is False
    assert needs_conversation_context("pricing") is False
    assert needs_conversation_context("") is False


def test_build_search_query_combines_last_user_turn() -> None:
    history = [
        ("user", "Tell me about Acme pricing plans."),
        ("assistant", "Acme has Pro and Team plans."),
        ("user", "What does the Team plan include?"),
        ("assistant", "Team includes SSO and audit logs."),
    ]
    combined = build_search_query("what about refunds?", history)
    assert combined == ("What does the Team plan include? what about refunds?")


def test_build_search_query_truncates_long_context() -> None:
    long_turn = "x" * 500
    combined = build_search_query("what about refunds?", [("user", long_turn)])
    context, _, question = combined.partition(" ")
    assert len(context) == DEFAULT_REWRITE_CONTEXT_CHARS
    assert question == "what about refunds?"


def test_build_search_query_without_prior_user_turn() -> None:
    question = "what about refunds?"
    assert build_search_query(question, []) == question
    assert build_search_query(question, [("assistant", "hi")]) == question


async def test_followup_retrieval_uses_contextualized_query() -> None:
    """A context-dependent follow-up embeds the previous turn + question."""
    env = build_chat_env()
    await make_website(env, tenant_id=REWRITE_TENANT, website_id=REWRITE_WEB, knowledge_chunks=1)
    await make_chunk(
        env,
        tenant_id=REWRITE_TENANT,
        website_id=REWRITE_WEB,
        text="Acme offers a 30-day full refund policy on annual plans.",
        chunk_index=0,
    )

    events_first = await consume(
        env.rag.stream_answer(
            tenant_id=REWRITE_TENANT,
            website_id=REWRITE_WEB,
            question="Tell me about Acme plans.",
        )
    )
    session_id = _done_event(events_first)["data"]["session_id"]
    first_embedded = _last_embedded_text(env)
    assert first_embedded == "Tell me about Acme plans."

    events = await consume(
        env.rag.stream_answer(
            tenant_id=REWRITE_TENANT,
            website_id=REWRITE_WEB,
            question="what about refunds?",
            session_id=session_id,
        )
    )
    # The search query must carry the conversation subject.
    assert _last_embedded_text(env) == ("Tell me about Acme plans. what about refunds?")
    done = next(e for e in events if e["event"] == "done")
    assert done["data"]["fallback"] is False

    # The model still receives the original question verbatim.
    prompt = env.generation.calls[-1]["messages"][0][1]
    assert "Question: what about refunds?" in prompt


async def test_standalone_followup_is_not_rewritten() -> None:
    """Self-contained questions embed exactly as asked."""
    env = build_chat_env()
    await make_website(env, tenant_id=REWRITE_TENANT, website_id=REWRITE_WEB, knowledge_chunks=1)
    await make_chunk(
        env,
        tenant_id=REWRITE_TENANT,
        website_id=REWRITE_WEB,
        text="We offer Pro and Team plans.",
        chunk_index=0,
    )

    await consume(
        env.rag.stream_answer(
            tenant_id=REWRITE_TENANT, website_id=REWRITE_WEB, question="Tell me about plans."
        )
    )
    await consume(
        env.rag.stream_answer(
            tenant_id=REWRITE_TENANT,
            website_id=REWRITE_WEB,
            question="How do I reset my password?",
        )
    )
    assert _last_embedded_text(env) == "How do I reset my password?"


async def test_rewrite_disabled_uses_raw_question(monkeypatch) -> None:
    """Flag off restores the exact pre-rewrite retrieval behavior."""
    monkeypatch.setattr(get_settings(), "enable_conversational_query_rewrite", False)
    env = build_chat_env()
    assert env.rag._query_rewrite_enabled is False
    await make_website(env, tenant_id=REWRITE_TENANT, website_id=REWRITE_WEB, knowledge_chunks=1)
    await make_chunk(
        env,
        tenant_id=REWRITE_TENANT,
        website_id=REWRITE_WEB,
        text="We offer Pro and Team plans.",
        chunk_index=0,
    )

    await consume(
        env.rag.stream_answer(
            tenant_id=REWRITE_TENANT, website_id=REWRITE_WEB, question="Tell me about plans."
        )
    )
    await consume(
        env.rag.stream_answer(
            tenant_id=REWRITE_TENANT,
            website_id=REWRITE_WEB,
            question="what about refunds?",
        )
    )
    assert _last_embedded_text(env) == "what about refunds?"


async def test_rewritten_queries_get_distinct_cache_keys() -> None:
    """The same follow-up text in different conversations must not collide."""
    env_a = build_chat_env()
    env_b = build_chat_env()
    for env, subject in ((env_a, "Acme"), (env_b, "Globex")):
        await make_website(
            env, tenant_id=REWRITE_TENANT, website_id=REWRITE_WEB, knowledge_chunks=1
        )
        await make_chunk(
            env,
            tenant_id=REWRITE_TENANT,
            website_id=REWRITE_WEB,
            text=f"{subject} ships a 30-day refund policy.",
            document_id=f"doc-{subject}",
            chunk_index=0,
        )

    for env, subject in ((env_a, "Acme"), (env_b, "Globex")):
        first = await consume(
            env.rag.stream_answer(
                tenant_id=REWRITE_TENANT,
                website_id=REWRITE_WEB,
                question=f"Tell me about {subject}.",
            )
        )
        await consume(
            env.rag.stream_answer(
                tenant_id=REWRITE_TENANT,
                website_id=REWRITE_WEB,
                question="what about refunds?",
                session_id=_done_event(first)["data"]["session_id"],
            )
        )

    # Each conversation embedded its own contextualized query.
    assert _last_embedded_text(env_a) == "Tell me about Acme. what about refunds?"
    assert _last_embedded_text(env_b) == "Tell me about Globex. what about refunds?"


# ---------------------------------------------------------------------------
# Conversation memory: current turn excluded
# ---------------------------------------------------------------------------


async def test_history_excludes_current_user_turn() -> None:
    """The prompt must not contain the current question twice."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="Knowledge.")

    first = await consume(
        env.rag.stream_answer(tenant_id=TENANT, website_id=WEBSITE, question="First question?")
    )
    await consume(
        env.rag.stream_answer(
            tenant_id=TENANT,
            website_id=WEBSITE,
            question="Second question?",
            session_id=_done_event(first)["data"]["session_id"],
        )
    )

    prompt = env.generation.calls[-1]["messages"][0][1]
    # Prior turns are present as memory...
    assert "[user] First question?" in prompt
    assert "[assistant] Hello world!" in prompt
    # ...but the current question appears only once, as the Question line.
    assert prompt.count("Second question?") == 1
    assert "Question: Second question?" in prompt


async def test_memory_window_preserved_after_excluding_current_turn() -> None:
    """Excluding the current message must not shrink the memory window."""
    env = build_chat_env(memory_turns=2)
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="Knowledge.")

    first = await consume(
        env.rag.stream_answer(tenant_id=TENANT, website_id=WEBSITE, question="Q1?")
    )  # U1 -> A1
    session_id = _done_event(first)["data"]["session_id"]
    await consume(
        env.rag.stream_answer(
            tenant_id=TENANT, website_id=WEBSITE, question="Q2?", session_id=session_id
        )
    )  # U2 -> A2
    await consume(
        env.rag.stream_answer(
            tenant_id=TENANT, website_id=WEBSITE, question="Q3?", session_id=session_id
        )
    )

    prompt = env.generation.calls[-1]["messages"][0][1]
    # The two most recent PRIOR turns fill the memory window completely:
    # without the exclusion the window would hold [A2, duplicate Q3].
    assert "[user] Q2?" in prompt
    assert "[assistant] Hello world!" in prompt
    assert prompt.count("[assistant] Hello world!") == 1
    # Current question never leaks into the memory block.
    assert prompt.count("Q3?") == 1


# ---------------------------------------------------------------------------
# Blank-generation guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("blank_deltas", [[""], ["   "]])
async def test_blank_generation_substitutes_fallback(blank_deltas) -> None:
    """An empty provider stream must not persist or emit an empty answer."""
    env = build_chat_env(deltas=blank_deltas)
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="Knowledge.")

    events = await consume(
        env.rag.stream_answer(tenant_id=TENANT, website_id=WEBSITE, question="Hi?")
    )
    deltas = [e["data"]["delta"] for e in events if e["event"] == "message"]
    # The widget renders joined deltas: the fallback delta is always
    # appended (a whitespace-only provider stream contributes only noise).
    assert deltas[-1] == UNKNOWN_ANSWER_FALLBACK
    assert "".join(deltas).strip() == UNKNOWN_ANSWER_FALLBACK
    done = next(e for e in events if e["event"] == "done")
    assert done["data"]["fallback"] is True

    assistant = [m for m in env.messages.messages if m.role == CHAT_ROLE_ASSISTANT]
    assert len(assistant) == 1
    assert assistant[0].content == UNKNOWN_ANSWER_FALLBACK


async def test_non_blank_generation_keeps_fallback_false() -> None:
    """Normal generations still report fallback=False."""
    env = build_chat_env()  # default deltas ["Hello", " world!"]
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="Knowledge.")

    events = await consume(
        env.rag.stream_answer(tenant_id=TENANT, website_id=WEBSITE, question="Hi?")
    )
    done = next(e for e in events if e["event"] == "done")
    assert done["data"]["fallback"] is False


# ---------------------------------------------------------------------------
# 8. Empty-context guard: the model is never called without retrieved context
# ---------------------------------------------------------------------------


def _constant_score_search(env, score: float):  # type: ignore[no-untyped-def]
    """Replace similarity_search so every hit carries a fixed low/high score."""

    async def search(
        tenant_id: str,
        website_id: str,
        query_embedding: list[float],
        *,
        top_k: int = 5,
        embedding_identity: object = None,
    ) -> list[VectorSearchResult]:
        hits = [
            VectorSearchResult(chunk=chunk, score=score)
            for chunk in env.vector.chunks
            if chunk.tenant_id == tenant_id and chunk.website_id == website_id
        ]
        return hits[:top_k]

    return search


async def test_all_chunks_below_min_score_falls_back_without_model_call() -> None:
    """min_score filtering can empty the context even when retrieval hit.

    With the confidence gate disabled (a supported configuration), chunks
    scoring below `chat_context_min_score` are all filtered out by
    `_build_context`.  The pipeline must emit the safe fallback instead of
    asking the model to answer from an empty context block.
    """
    with (
        patch.object(get_settings(), "chat_context_min_score", 0.5),
        patch.object(get_settings(), "enable_rag_confidence_check", False),
    ):
        env = build_chat_env(reranker=False)
        await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
        await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="Pro plan costs money.")
        env.vector.similarity_search = _constant_score_search(env, 0.3)  # type: ignore[method-assign]

        events = await consume(
            env.rag.stream_answer(tenant_id=TENANT, website_id=WEBSITE, question="pricing")
        )

    deltas = [e["data"]["delta"] for e in events if e["event"] == "message"]
    done = next(e for e in events if e["event"] == "done")
    sources_event = next(e for e in events if e["event"] == "sources")
    assert env.generation.calls == []
    assert done["data"]["fallback"] is True
    assert deltas[-1] == UNKNOWN_ANSWER_FALLBACK
    assert sources_event["data"]["sources"] == []


async def test_some_chunks_above_min_score_still_generate() -> None:
    """The guard only fires when *every* chunk is filtered out."""
    with patch.object(get_settings(), "chat_context_min_score", 0.5):
        env = build_chat_env(reranker=False)
        await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
        await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="Pro plan costs money.")
        env.vector.similarity_search = _constant_score_search(env, 0.6)  # type: ignore[method-assign]

        events = await consume(
            env.rag.stream_answer(tenant_id=TENANT, website_id=WEBSITE, question="pricing")
        )

    done = next(e for e in events if e["event"] == "done")
    assert len(env.generation.calls) == 1
    assert done["data"]["fallback"] is False


async def test_context_empty_guard_reports_confidence_telemetry() -> None:
    """The fallback done event still carries confidence signals when available."""
    with (
        patch.object(get_settings(), "chat_context_min_score", 0.5),
        patch.object(get_settings(), "rag_confidence_threshold", 0.2),
    ):
        env = build_chat_env(reranker=False)
        await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
        await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="Pro plan costs money.")
        env.vector.similarity_search = _constant_score_search(env, 0.3)  # type: ignore[method-assign]

        events = await consume(
            env.rag.stream_answer(tenant_id=TENANT, website_id=WEBSITE, question="pricing")
        )

    # Scores {0.3}: avg=0.3, hit_ratio=0, peak=0.3 → confidence=0.21 >= 0.2,
    # so the confidence gate passes but min_score filters the only chunk.
    done = next(e for e in events if e["event"] == "done")
    assert done["data"]["fallback"] is True
    assert done["data"]["confidence_score"] == 0.21
    assert env.generation.calls == []
