"""Regression tests for RAG-PERF-02: cache the final retrieval result.

The retrieval cache previously stored only the pre-strategy, pre-rerank raw
vector results, so a warm (valid) cache hit still reloaded the full lexical
corpus and re-ran keyword/RRF hybrid retrieval plus reranking. This is the
largest warm / cache-hit latency cost in the RAG pipeline.

F-02 fix: the cache now stores the FINAL post-strategy, post-rerank result
(schema 2) plus the metrics/diagnostic fields. A valid schema-2 cache hit
returns that result directly, skipping the lexical-corpus load, keyword/RRF
pass and reranking entirely. Reranking is deterministic given (query vector,
stored chunk embeddings, query tokens, top_k) — all fixed per (search query,
corpus version) — so the cached output is exactly what a repeat miss path
would have computed.

These tests verify the short-circuit with structural call-count assertions and
the isolation guarantees (tenant + website + query + corpus version).
"""

from __future__ import annotations

import json
from datetime import timedelta

from backend.core.config import get_settings

from tests.chat_helpers import build_chat_env, consume, make_chunk, make_website

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
WEB_1 = "web-1"
WEB_2 = "web-2"


def _done(events):
    return next(event for event in events if event["event"] == "done")


async def _stream(env, **kwargs):
    return await consume(env.rag.stream_answer(**kwargs))


def _cache_entry(env, namespace: str, prefix: str) -> dict | None:
    """Return the first cached JSON entry in `namespace` whose key starts with `prefix`."""
    needle = f"{namespace}:{prefix}"
    for key, value in env.cache._data.items():
        if key.startswith(needle):
            return json.loads(value)
    return None


async def _corpus_key(env, question: str) -> str:
    website = await env.websites.find_by_id(TENANT_A, WEB_1)
    assert website is not None
    return f"{TENANT_A}:{WEB_1}:{website.updated_at.isoformat()}:{question.strip().lower()}"


# ---------------------------------------------------------------------------
# Structural: a valid cache hit skips lexical load + keyword/RRF + rerank
# ---------------------------------------------------------------------------


async def test_cache_hit_skips_lexical_load_keyword_and_rerank(monkeypatch) -> None:
    """On a warm schema-2 cache hit, the lexical corpus, keyword/RRF pass and
    reranker are all skipped: the final cached result is returned directly."""
    monkeypatch.setattr(get_settings(), "enable_hybrid_search", True)
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=1)
    await make_chunk(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        text="Pro plans include priority support and onboarding.",
    )

    question = "What support comes with Pro plans?"
    # Cold call -> miss: full pipeline runs.
    first = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question=question)
    assert _done(first)["data"]["fallback"] is False

    assert env.vector.search_calls == 1
    assert env.embedder.calls

    # Instrument the expensive stages before the warm call.
    load_chunks_calls: list = []
    strategy_calls: list = []
    rerank_calls: list = []

    original_load = env.rag._load_all_chunks
    original_strategy = env.rag._run_retrieval_strategy
    original_rerank = env.rag._reranker.rerank if env.rag._reranker is not None else None

    async def _spy_load(*args, **kwargs):
        load_chunks_calls.append((args, kwargs))
        return await original_load(*args, **kwargs)

    async def _spy_strategy(*args, **kwargs):
        strategy_calls.append((args, kwargs))
        return await original_strategy(*args, **kwargs)

    monkeypatch.setattr(env.rag, "_load_all_chunks", _spy_load)
    monkeypatch.setattr(env.rag, "_run_retrieval_strategy", _spy_strategy)
    if original_rerank is not None:
        rerank_bind = env.rag._reranker

        async def _spy_rerank(*args, **kwargs):
            rerank_calls.append((args, kwargs))
            return await original_rerank(*args, **kwargs)

        monkeypatch.setattr(rerank_bind, "rerank", _spy_rerank)

    second = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question=question)
    assert _done(second)["data"]["fallback"] is False

    # The warm call must not re-run any of the expensive stages.
    assert load_chunks_calls == [], "cache hit must NOT reload the lexical corpus"
    assert strategy_calls == [], "cache hit must NOT re-run keyword/RRF retrieval"
    assert rerank_calls == [], "cache hit must NOT re-run the reranker"
    # And no second embed or vector search either.
    assert env.vector.search_calls == 1
    assert len(env.embedder.calls) == 1


async def test_cached_entry_contains_final_results() -> None:
    """Schema-2 entries persist the final post-strategy results and metrics."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=1)
    await make_chunk(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        text="Our pro plan is priced at $80,000 per year.",
    )

    await _stream(
        env, tenant_id=TENANT_A, website_id=WEB_1, question="What does the pro plan cost?"
    )

    entry = _cache_entry(env, "retrieval", f"{TENANT_A}:{WEB_1}:")
    assert entry is not None
    assert entry["schema"] == 2
    assert "vector" in entry
    assert "embedding_identity" in entry
    assert "results" in entry and entry["results"]
    assert "metrics" in entry
    result = entry["results"][0]
    assert "chunk" in result and "chunk_text" in result["chunk"]
    assert "score" in result


# ---------------------------------------------------------------------------
# Isolation: tenant + website + query stay strictly partitioned on cache hits
# ---------------------------------------------------------------------------


async def test_cross_site_isolation_on_cache_hit() -> None:
    """Two websites with query-overlapping but distinct-price chunks, when
    each is asked the same question, only ever see their OWN chunk — even
    across the retrieval-cache hit path."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=1)
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_2, knowledge_chunks=1)
    await make_chunk(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        text="Site A BCA fee is ₹80,000 per year.",
        url="https://a.example/bca",
    )
    await make_chunk(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_2,
        text="Site B BCA fee is ₹65,000 per year.",
        url="https://b.example/bca",
    )

    question = "What is the BCA fee?"
    for website_id in (WEB_1, WEB_2):
        await _stream(env, tenant_id=TENANT_A, website_id=website_id, question=question)

    entry_a = _cache_entry(env, "retrieval", f"{TENANT_A}:{WEB_1}:")
    entry_b = _cache_entry(env, "retrieval", f"{TENANT_A}:{WEB_2}:")
    assert entry_a is not None and entry_b is not None
    text_a = entry_a["results"][0]["chunk"]["chunk_text"]
    text_b = entry_b["results"][0]["chunk"]["chunk_text"]
    assert "₹80,000" in text_a and "₹80,000" not in text_b
    assert "₹65,000" in text_b and "₹65,000" not in text_a


async def test_tenant_isolation_within_website_on_cache_hit() -> None:
    """The same website id under different tenants is isolated by the cache key:
    a tenant-a cache lookup can never be satisfied by a tenant-b entry."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=1)
    chunk_a = await make_chunk(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        text="Tenant A proprietary document about alpha.",
    )
    chunk_b = await make_chunk(
        env,
        tenant_id=TENANT_B,
        website_id=WEB_1,
        text="Tenant B proprietary document about beta.",
    )

    question = "Summarize the proprietary document."
    q = question.strip().lower()
    corpus = (await _corpus_key(env, question)).split(f"{TENANT_A}:{WEB_1}:")[1].split(":")[0]

    def _payload(chunk) -> dict:
        return {
            "schema": 2,
            "vector": [0.0, 0.0, 0.0, 0.0],
            "embedding_identity": env.embedder.embedding_identity.as_dict(),
            "results": [
                {
                    "chunk": chunk.model_dump(mode="json"),
                    "score": 0.9,
                }
            ],
            "metrics": None,
            "cached_at": 0.0,
        }

    # Seed identical-query entries for the two tenants (same website id).
    env.cache._data[f"retrieval:{TENANT_A}:{WEB_1}:{corpus}:{q}"] = json.dumps(_payload(chunk_a))
    env.cache._data[f"retrieval:{TENANT_B}:{WEB_1}:{corpus}:{q}"] = json.dumps(_payload(chunk_b))

    events = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question=question)
    done = _done(events)
    assert done["data"]["fallback"] is False
    # The tenant-a lookup returned tenant-a's own cached chunk, never tenant-b's.
    sources = next(
        (e for e in events if e["event"] == "sources"),
        {"data": {"sources": []}},
    )
    source_ids = [s["chunk_id"] for s in sources["data"]["sources"]]
    assert chunk_a.id in source_ids, "tenant-a hit must serve tenant-a's own cached chunk"
    assert chunk_b.id not in source_ids, "tenant-a must never serve tenant-b's cached chunk"


async def test_cache_hit_scoped_per_query() -> None:
    """Different questions get different cache entries (no cross-query bleed)."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=1)
    await make_chunk(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        text="Pro plan is $80,000. Team plan has onboarding.",
    )

    await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question="What is the pro plan cost?")
    await _stream(
        env, tenant_id=TENANT_A, website_id=WEB_1, question="Does the team plan have onboarding?"
    )

    prefixes = [k.split(":", 3)[3] for k in env.cache._data if k.startswith("retrieval:")]
    assert len(prefixes) == 2, "each distinct query keeps its own cache entry"


# ---------------------------------------------------------------------------
# Corpus-version invalidation (RAG-07) preserved for schema-2
# ---------------------------------------------------------------------------


async def test_corpus_version_bump_forces_cache_miss(monkeypatch) -> None:
    """A knowledge reprocessing bumping `website.updated_at` invalidates the
    schema-2 retrieval cache: the same question re-runs the full pipeline."""
    monkeypatch.setattr(get_settings(), "chat_retrieval_cache_ttl_seconds", 100)
    env = build_chat_env()
    website = await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT_A, website_id=WEB_1, text="Knowledge content.")

    question = "What is the price?"
    await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question=question)
    assert env.vector.search_calls == 1

    website.updated_at = website.updated_at + timedelta(seconds=5)
    await env.websites.update(website)

    await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question=question)
    assert env.vector.search_calls == 2  # stale cache invalidated by corpus version


# ---------------------------------------------------------------------------
# Fail-open: malformed / schema-1 / legacy entries never short-circuit wrongly
# ---------------------------------------------------------------------------


async def test_legacy_schema1_entry_treated_as_miss(monkeypatch) -> None:
    """A pre-existing schema-1 entry (raw vector results only) must NOT be
    treated as a final-result cache hit; F-02 degrades it to a normal miss."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT_A, website_id=WEB_1, text="Knowledge content.")

    question = "What is the price?"
    legacy_raw = {
        "vector": [0.0, 0.0, 0.0, 0.0],
        "embedding_identity": {
            "provider": "fake",
            "model": "fake",
            "dimensions": 4,
            "version": "1",
        },
        "results": [],
        "cached_at": 0.0,
    }
    prekey = await _corpus_key(env, question)
    await env.cache.set("retrieval", prekey, json.dumps(legacy_raw))

    # Instrument stages to confirm the warm call is treated as a miss.
    load_chunks_calls: list = []
    original_load = env.rag._load_all_chunks

    async def _spy_load(*args, **kwargs):
        load_chunks_calls.append((args, kwargs))
        return await original_load(*args, **kwargs)

    monkeypatch.setattr(env.rag, "_load_all_chunks", _spy_load)

    events = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question=question)
    assert _done(events)["data"]["fallback"] is False
    # A legacy schema-1 entry must be a miss: the pipeline re-ran and rewrote
    # the cache as schema-2.
    rewritten = _cache_entry(env, "retrieval", f"{TENANT_A}:{WEB_1}:")
    assert rewritten is not None and rewritten.get("schema") == 2


async def test_malformed_cache_entry_fails_open_to_miss() -> None:
    """A corrupt cache value must not crash or wrongly short-circuit retrieval."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT_A, website_id=WEB_1, text="Knowledge content.")

    question = "What is the price?"
    prekey = await _corpus_key(env, question)
    env.cache._data[f"retrieval:{prekey}"] = "not-json{{{"

    events = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question=question)
    assert _done(events)["data"]["fallback"] is False
    assert env.vector.search_calls == 1


async def test_schema2_entry_with_invalid_chunk_fails_open_to_miss() -> None:
    """A schema-2 entry whose chunk payload fails KnowledgeChunk validation
    (pydantic ValidationError) must be treated as a miss, never a crash."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT_A, website_id=WEB_1, text="Knowledge content.")

    question = "What is the price?"
    prekey = await _corpus_key(env, question)
    broken = {
        "schema": 2,
        "vector": [0.0, 0.0, 0.0, 0.0],
        "embedding_identity": env.embedder.embedding_identity.as_dict(),
        "results": [{"chunk": {"chunk_text": 12345, "id": "x"}, "score": 0.9}],
        "metrics": None,
        "cached_at": 0.0,
    }
    env.cache._data[f"retrieval:{prekey}"] = json.dumps(broken)

    events = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question=question)
    assert _done(events)["data"]["fallback"] is False
    assert env.vector.search_calls == 1  # failed open to a real miss


# ---------------------------------------------------------------------------
# Deterministic equivalence: a cache hit serves EXACTLY the miss-path result
# ---------------------------------------------------------------------------


async def test_cache_hit_results_match_miss_path_exactly(monkeypatch) -> None:
    """The schema-2 cache hit must return the identical final ranked result
    (same chunk ids, order, scores, lexical/dense/rerank evidence) that the
    cold miss path computed — including with hybrid + reranking enabled."""
    monkeypatch.setattr(get_settings(), "enable_hybrid_search", True)
    env = build_chat_env(reranker=True)
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=3)
    await make_chunk(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        text="Pro plans include priority support and onboarding.",
    )
    await make_chunk(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        text="The BCA fee is ₹80,000 per year.",
        chunk_index=1,
    )
    await make_chunk(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        text="Team plans include onboarding for new hires.",
        chunk_index=2,
    )

    question = "What support comes with Pro plans?"
    corpus_version = "v1"

    miss = await env.rag._retrieve(
        tenant_id=TENANT_A,
        website_id=WEB_1,
        question=question,
        embedding_identity=env.embedder.embedding_identity,
        lexical_corpus_version=corpus_version,
    )
    assert miss.retrieval_cache_hit is False

    # A fresh RagService instance sharing the same cache store simulates a new
    # process request: the retrieval cache (schema-2) must serve the hit.
    from backend.services.chat.rag_service import RagService

    hit_rag = RagService(
        websites=env.websites,
        vector=env.vector,
        embedder=env.embedder,
        generation=env.generation,
        sessions=env.sessions,
        messages=env.messages,
        usage=env.usage,
        cache=env.cache,
        top_k=env.rag._top_k,
        memory_turns=env.rag._memory_turns,
        allow_reranking=True,
    )
    hit = await hit_rag._retrieve(
        tenant_id=TENANT_A,
        website_id=WEB_1,
        question=question,
        embedding_identity=env.embedder.embedding_identity,
        lexical_corpus_version=corpus_version,
    )
    assert hit.retrieval_cache_hit is True
    assert hit.load_chunks_ms == 0.0
    assert hit.rerank_ms == 0.0
    assert hit.rerank_input_count == 0

    assert len(hit.results) == len(miss.results)
    for hit_result, miss_result in zip(hit.results, miss.results, strict=True):
        assert hit_result.chunk.id == miss_result.chunk.id
        assert hit_result.score == miss_result.score
        assert hit_result.lexical_score == miss_result.lexical_score
        assert hit_result.dense_score == miss_result.dense_score
        assert hit_result.lexical_exact == miss_result.lexical_exact
