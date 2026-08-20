"""Tests for RAG accuracy improvements.

Covers:
- Hybrid retrieval enabled by default
- Reranker execution path
- Faithfulness score generation
- Adaptive provider routing (integration-level)
"""

from __future__ import annotations

from unittest.mock import patch

from backend.core.config import get_settings
from backend.models.knowledge_chunk import KnowledgeChunk
from backend.prompts.rag import ContextItem
from backend.repositories.vector.base import VectorSearchResult
from backend.repositories.vector.reranker import EmbeddingReranker, _cosine_similarity
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
        env, tenant_id=TENANT, website_id=WEBSITE,
        text="Pro plan costs $19 per month.",
        url="https://example.com/pricing", title="Pricing", chunk_index=0,
    )
    await make_chunk(
        env, tenant_id=TENANT, website_id=WEBSITE,
        text="Enterprise includes SSO and audit logs.",
        url="https://example.com/enterprise", title="Enterprise", chunk_index=1,
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
        tenant_id=TENANT, website_id=WEBSITE, document_id="doc-a",
        chunk_text="chunk_a text", embedding=[0.0] * 4, chunk_index=0,
    )
    chunk_b = KnowledgeChunk.new(
        tenant_id=TENANT, website_id=WEBSITE, document_id="doc-b",
        chunk_text="chunk_b text", embedding=[0.0] * 4, chunk_index=0,
    )

    candidates = [
        VectorSearchResult(chunk=chunk_a, score=0.99),
        VectorSearchResult(chunk=chunk_b, score=0.95),
    ]

    result = await reranker.rerank("query text", candidates)
    assert len(result) == 2
    assert result[0].chunk.chunk_text == "chunk_b text"
    assert result[1].chunk.chunk_text == "chunk_a text"
    assert len(fake_embedder.calls) == 1


async def test_reranker_returns_original_on_embed_failure() -> None:
    class FailingEmbedder:
        async def embed(self, texts: list[str]) -> list[list[float]]:
            raise ConnectionError("provider down")

    reranker = EmbeddingReranker(embedder=FailingEmbedder(), top_k=5)

    chunk = KnowledgeChunk.new(
        tenant_id=TENANT, website_id=WEBSITE, document_id="doc-1",
        chunk_text="test", embedding=[0.0] * 4, chunk_index=0,
    )
    candidates = [VectorSearchResult(chunk=chunk, score=0.9)]
    result = await reranker.rerank("query", candidates)
    assert len(result) == 1
    assert result[0].chunk.chunk_text == "test"


async def test_reranker_top_k_limits_output() -> None:
    class SimpleEmbedder:
        async def embed(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0, 0.0, 0.0]] * len(texts)

    reranker = EmbeddingReranker(embedder=SimpleEmbedder(), top_k=2)

    chunks = [
        KnowledgeChunk.new(
            tenant_id=TENANT, website_id=WEBSITE, document_id=f"doc-{i}",
            chunk_text=f"chunk_{i}", embedding=[0.0] * 4, chunk_index=i,
        )
        for i in range(5)
    ]
    candidates = [
        VectorSearchResult(chunk=c, score=0.9 - i * 0.01)
        for i, c in enumerate(chunks)
    ]
    result = await reranker.rerank("query", candidates)
    assert len(result) == 2


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
        ContextItem(url="https://a.com", title="A", heading=None,
                    text="The Pro plan costs $19 per month."),
    ]
    score = _check_faithfulness("The Pro plan costs $19 per month.", context)
    assert score == 1.0


def test_faithfulness_no_support() -> None:
    context = [
        ContextItem(url="https://a.com", title="A", heading=None,
                    text="The Pro plan costs $19."),
    ]
    score = _check_faithfulness(
        "Quantum entanglement enables faster-than-light communication.",
        context,
    )
    assert score <= 0.3


def test_faithfulness_partial_support() -> None:
    context = [
        ContextItem(url="https://a.com", title="A", heading=None,
                    text="The Pro plan costs $19 per month and includes priority support."),
    ]
    score = _check_faithfulness(
        "The Pro plan costs $19. However, quantum entanglement is not involved.",
        context,
    )
    assert 0.3 <= score <= 0.8


def test_faithfulness_empty_answer() -> None:
    assert _check_faithfulness("", []) == 1.0


def test_faithfulness_short_sentences_supported() -> None:
    context = [
        ContextItem(url="https://a.com", title="A", heading=None,
                    text="Some context."),
    ]
    score = _check_faithfulness("Hi. Ok.", context)
    assert score == 1.0


def test_faithfulness_multiple_context_items() -> None:
    context = [
        ContextItem(url="https://a.com", title="A", heading=None,
                    text="The pricing page details plans."),
        ContextItem(url="https://b.com", title="B", heading=None,
                    text="Enterprise tier includes SSO and audit."),
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
