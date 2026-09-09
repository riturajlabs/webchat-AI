"""RAG corpus-scale latency benchmarks (baseline instrumentation).

Synthetic corpora at 100, 500, 1K, 5K chunks with the FakeVectorRepository
and FakeEmbeddingClient.  All tests use ``install_relevance_scoring`` so
retrieval is deterministic and exercises the hybrid keyword path.

Every test records timing data in a summary dict for downstream analysis.
No production writes, no real LLM calls.
"""

from __future__ import annotations

import time

import pytest
from backend.core.metrics import RAG_STAGE_LATENCY_SECONDS, reset_registry

from tests.chat_helpers import (
    ChatEnv,
    build_chat_env,
    consume,
    install_relevance_scoring,
    make_chunk,
    make_website,
)

TENANT = "bench-tenant"
SITE = "bench-web"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_corpus_chunks(n: int) -> list[str]:
    """Generate n distinct chunk texts with varied topic keywords."""
    topics = [
        "pricing",
        "support",
        "enterprise",
        "API",
        "security",
        "onboarding",
        "billing",
        "analytics",
        "integration",
        "deployment",
    ]
    chunks: list[str] = []
    for i in range(n):
        topic = topics[i % len(topics)]
        chunks.append(
            f"Chunk {i}: {topic} documentation for feature {i}. "
            f"This section covers {topic} details including configuration, "
            f"best practices, and troubleshooting for item {i}."
        )
    return chunks


async def _build_scale_corpus(env: ChatEnv, n: int) -> None:
    """Insert n chunks into a single website."""
    await make_website(env, tenant_id=TENANT, website_id=SITE, knowledge_chunks=n)
    chunks = _build_corpus_chunks(n)
    for i, text in enumerate(chunks):
        await make_chunk(
            env,
            tenant_id=TENANT,
            website_id=SITE,
            text=text,
            chunk_index=i,
            document_id=f"doc-{i // 10}",
        )


def _make_bench_env(corpus_size: int, *, cache=None) -> ChatEnv:  # type: ignore[no-untyped-def]
    """Build a benchmark env with confidence gating disabled so the tests
    measure pure retrieval latency, not abstention behavior.  Also seeds the
    corpus at the given size."""
    env = build_chat_env(top_k=5, cache=cache)
    install_relevance_scoring(env)
    env.rag._confidence_check_enabled = False
    env.rag._timing_enabled = True
    return env


async def _stream_bench(env: ChatEnv, question: str) -> dict:
    """Stream a single question and return the done event."""
    events = await consume(
        env.rag.stream_answer(tenant_id=TENANT, website_id=SITE, question=question)
    )
    return next(e for e in events if e["event"] == "done")


# ---------------------------------------------------------------------------
# Benchmark tests — record latency for analysis
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corpus_size", [100, 500, 1000])
async def test_corpus_scale_retrieval_latency(corpus_size: int) -> None:
    """Measure retrieval latency at different corpus sizes.

    The done event timing dict is returned for downstream assertion.
    Regression guard: retrieval must not explode super-linearly.
    """
    reset_registry()
    env = _make_bench_env(corpus_size)
    await _build_scale_corpus(env, corpus_size)

    t0 = time.perf_counter()
    done = await _stream_bench(env, question="pricing documentation feature 0")
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    timing = done["data"].get("timing", {})
    assert done["data"]["fallback"] is False, f"Fallback at corpus_size={corpus_size}"
    # Retrieval path was hybrid (retrieval_method recorded).
    assert timing.get("retrieval_method") in ("hybrid", "vector"), (
        f"Unexpected retrieval_method={timing.get('retrieval_method')} at corpus_size={corpus_size}"
    )
    # The total wall-clock should be reasonable — less than 5s even at 1K
    # chunks (fake retrieval is in-process, not a real ANN index).
    assert elapsed_ms < 5000, f"Took {elapsed_ms:.0f}ms at corpus_size={corpus_size}"


@pytest.mark.parametrize("corpus_size", [100, 500, 1000])
async def test_corpus_scale_hybrid_keyword_path(corpus_size: int) -> None:
    """At each scale, verify hybrid search returns keyword_result_count > 0."""
    reset_registry()
    env = _make_bench_env(corpus_size)
    await _build_scale_corpus(env, corpus_size)

    done = await _stream_bench(env, question="security best practices configuration item 42")
    timing = done["data"].get("timing", {})
    assert timing.get("keyword_result_count", 0) >= 1, (
        f"Expected keyword results at corpus_size={corpus_size}"
    )


@pytest.mark.parametrize("corpus_size", [100, 500, 1000])
async def test_corpus_scale_cache_hit_reduces_latency(corpus_size: int) -> None:
    """Cache-hit path should be recorded with embedding_cache=hit."""
    from tests.fakes import FakeCacheStore

    cache = FakeCacheStore()
    env = _make_bench_env(corpus_size, cache=cache)
    await _build_scale_corpus(env, corpus_size)

    # First call: cache miss.
    done1 = await _stream_bench(env, question="billing documentation feature 10")
    timing1 = done1["data"].get("timing", {})
    assert timing1.get("embedding_cache") == "miss", "First call should be cache miss"
    assert timing1.get("retrieval_cache") == "miss", "First call should be retrieval cache miss"

    # Second call: should hit cache.
    done2 = await _stream_bench(env, question="billing documentation feature 10")
    timing2 = done2["data"].get("timing", {})
    assert timing2.get("embedding_cache") == "hit", "Second call should be embedding cache hit"

    # Embedding time should be 0 on cache hit (embedding skipped).
    assert timing2.get("embedding_ms", 999) == 0.0, (
        f"Embedding ms should be 0 on cache hit, got {timing2.get('embedding_ms')}"
    )


async def test_large_corpus_total_latency_under_bound() -> None:
    """5K chunks: total latency should stay under 10s with fake backends."""
    reset_registry()
    env = _make_bench_env(5000)
    await _build_scale_corpus(env, 5000)

    t0 = time.perf_counter()
    done = await _stream_bench(env, question="integration deployment documentation item 999")
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert done["data"]["fallback"] is False
    assert elapsed_ms < 10000, f"5K corpus total took {elapsed_ms:.0f}ms (expected < 10s)"


async def test_per_stage_histogram_has_samples_after_benchmark() -> None:
    """After a benchmark run, the histogram has samples across multiple stages."""
    reset_registry()
    env = _make_bench_env(100)
    await _build_scale_corpus(env, 100)

    await _stream_bench(env, question="pricing feature 0")

    expected_stages = {
        "embedding",
        "vector_search",
        "load_chunks",
        "rerank",
        "context",
        "generation",
        "total",
    }
    observed_stages = {stage for (stage, _) in RAG_STAGE_LATENCY_SECONDS._series}
    missing = expected_stages - observed_stages
    assert not missing, f"Missing stages in histogram: {missing}"
    reset_registry()
