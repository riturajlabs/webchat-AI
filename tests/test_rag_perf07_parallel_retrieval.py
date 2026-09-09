"""Regression tests for RAG-PERF-07: overlap the hybrid lexical corpus load
with the ``$vectorSearch`` round trip in ``RagService._retrieve``.

RAG-PERF-07 starts ``_load_all_chunks`` as a task before awaiting the vector
search, so the two independent reads run concurrently and the retrieval
strategy still receives the exact same inputs in the same order.

These tests prove, structurally and deterministically:

1. the lexical load actually overlaps the running vector search,
2. the returned results/metrics are identical to the sequential computation,
3. a vector-search failure cancels the overlapped load (no leaked task),
4. a corpus-load failure still propagates exactly as before,
5. empty corpus results (hybrid with zero chunks) still behave correctly.
"""

from __future__ import annotations

import asyncio

import pytest
from backend.repositories.vector import VectorSearchResult
from backend.services.chat.retrieval_strategy import HybridRetrievalStrategy

from tests.chat_helpers import build_chat_env, make_chunk

TENANT = "tenant-p07"
WEB = "web-p07"
VERSION = "v1"


def _make_hybrid_rag(env):
    """Build a hybrid-strategy ``RagService`` over the shared fakes."""
    return env.rag.__class__(
        websites=env.websites,
        vector=env.vector,
        embedder=env.embedder,
        generation=env.generation,
        sessions=env.sessions,
        messages=env.messages,
        usage=env.usage,
        cache=env.cache,
        top_k=5,
        retrieval_strategy=HybridRetrievalStrategy(rrf_k=60),
        allow_reranking=False,
    )


async def test_hybrid_load_overlaps_vector_search(monkeypatch) -> None:
    """The corpus load starts while the vector search is still in flight, and
    ``_retrieve`` returns the same results the sequential path would."""
    env = build_chat_env()
    rag = _make_hybrid_rag(env)
    await make_chunk(
        env, tenant_id=TENANT, website_id=WEB, text="BCA annual fee is 65000 rupees.", chunk_index=0
    )
    await make_chunk(
        env, tenant_id=TENANT, website_id=WEB, text="BCA accommodation is optional.", chunk_index=1
    )

    # Sequential baseline: compute what the strategy must produce.
    identity = env.embedder.embedding_identity
    query_vector = [0.0] * identity.dimensions
    vector_results = await env.vector.similarity_search(
        TENANT, WEB, query_vector, top_k=5, embedding_identity=identity
    )
    raw_corpus = await env.vector.list_chunks_light(TENANT, WEB)
    baseline_corpus = [VectorSearchResult(chunk=c, score=0.5) for c in raw_corpus]
    expected, expected_metrics = await rag._run_retrieval_strategy(
        query="What is the annual BCA fee?",
        vector_results=vector_results,
        all_chunks=baseline_corpus,
        top_k=5,
    )

    # Concurrency gates: the load signals it started; the search waits for
    # that signal (proving the load is in flight) and then releases it.
    load_started = asyncio.Event()
    load_release = asyncio.Event()
    orig_list = env.vector.list_chunks_light

    async def gated_list_chunks_light(tenant_id, website_id, *, limit=0):
        load_started.set()
        await asyncio.wait_for(load_release.wait(), 5.0)
        return await orig_list(tenant_id, website_id, limit=limit)

    orig_search = env.vector.similarity_search

    async def gated_search(tenant_id, website_id, query_embedding, **kwargs):
        await asyncio.wait_for(load_started.wait(), 2.0)
        load_release.set()
        return await orig_search(tenant_id, website_id, query_embedding, **kwargs)

    monkeypatch.setattr(env.vector, "list_chunks_light", gated_list_chunks_light)
    monkeypatch.setattr(env.vector, "similarity_search", gated_search)

    result = await rag._retrieve(
        tenant_id=TENANT,
        website_id=WEB,
        question="What is the annual BCA fee?",
        lexical_corpus_version=VERSION,
    )

    assert load_started.is_set()
    assert result.retrieval_cache_hit is False
    assert result.hybrid_candidate_count == 2
    assert [(r.chunk.id, r.score) for r in result.results] == [
        (r.chunk.id, r.score) for r in expected
    ]
    assert result.metrics.final_result_count == expected_metrics.final_result_count


async def test_vector_search_failure_cancels_overlapped_load(monkeypatch) -> None:
    """A vector-search failure cancels the in-flight corpus load and the
    original error surfaces (no leaked background task)."""
    env = build_chat_env()
    rag = _make_hybrid_rag(env)
    await make_chunk(env, tenant_id=TENANT, website_id=WEB, text="Fee is 65000.", chunk_index=0)

    load_started = asyncio.Event()
    cancelled: list[bool] = []

    async def cancellable_list(tenant_id, website_id, *, limit=0):
        load_started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise
        return []

    async def failing_search(*args, **kwargs):
        await load_started.wait()
        raise RuntimeError("vector boom")

    monkeypatch.setattr(env.vector, "list_chunks_light", cancellable_list)
    monkeypatch.setattr(env.vector, "similarity_search", failing_search)

    with pytest.raises(RuntimeError, match="vector boom"):
        await rag._retrieve(
            tenant_id=TENANT,
            website_id=WEB,
            question="What is the annual BCA fee?",
            lexical_corpus_version=VERSION,
        )
    assert load_started.is_set()
    assert cancelled == [True]


async def test_lexical_load_failure_propagates(monkeypatch) -> None:
    """A corpus-load failure still surfaces with the same error the sequential
    path would raise after the vector search completes."""
    env = build_chat_env()
    rag = _make_hybrid_rag(env)
    await make_chunk(env, tenant_id=TENANT, website_id=WEB, text="Fee is 65000.", chunk_index=0)

    async def failing_list(tenant_id, website_id, *, limit=0):
        raise RuntimeError("load boom")

    monkeypatch.setattr(env.vector, "list_chunks_light", failing_list)

    with pytest.raises(RuntimeError, match="load boom"):
        await rag._retrieve(
            tenant_id=TENANT,
            website_id=WEB,
            question="What is the annual BCA fee?",
            lexical_corpus_version=VERSION,
        )


async def test_hybrid_empty_corpus_returns_empty_results() -> None:
    """Hybrid retrieval on a website with zero chunks stays a clean no-hit
    (empty result set, not an error) exactly like the sequential path."""
    env = build_chat_env()
    rag = _make_hybrid_rag(env)
    result = await rag._retrieve(
        tenant_id=TENANT,
        website_id=WEB,
        question="What is the annual BCA fee?",
        lexical_corpus_version=VERSION,
    )
    assert result.results == []
    assert result.retrieval_cache_hit is False
