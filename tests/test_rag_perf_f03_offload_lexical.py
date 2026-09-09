"""Regression tests for RAG-PERF-03 (F-01): lexical-corpus offload.

``RagService._load_all_chunks`` hydrates the compact lexical corpus from the
Redis ``lexical`` namespace by running ``json.loads`` + ``KnowledgeChunk(...)``
construction + ``VectorSearchResult`` wrapping. That deserialization is CPU-
bound and previously ran on the asyncio event loop (blocking the whole loop
for the corpus size, ~2k chunks per website).

F-01 fix: the hydration runs inside ``_parse_lexical_corpus`` through
``asyncio.to_thread`` — async Redis/DB I/O unchanged, CPU penny-pushing
moved off the loop. These tests prove the offload structurally (no timing),
that the returned chunks are byte-for-byte the same as before, that malformed
cache data still degrades safely to the DB path, and that tenant/website/
corpus-version isolation is untouched.
"""

from __future__ import annotations

import json

import backend.services.chat.rag_service as rag_module

from tests.chat_helpers import build_chat_env, make_chunk, make_website

TENANT_A = "tenant-a"
WEB_A = "web-a"
WEB_B = "web-b"
CORPUS_VERSION = "v1"
# Identity key when `_load_all_chunks` is called with embedding_identity=None.
LEXICAL_KEY_A = f"{TENANT_A}:{WEB_A}:{CORPUS_VERSION}:unlocked"
LEXICAL_KEY_B = f"{TENANT_A}:{WEB_B}:{CORPUS_VERSION}:unlocked"


def _serialize(chunks) -> str:
    return json.dumps(
        {"chunks": [chunk.model_dump(mode="json", exclude={"embedding"}) for chunk in chunks]}
    )


# ---------------------------------------------------------------------------
# Phase 5: event-loop offload proof (structural, deterministic)
# ---------------------------------------------------------------------------


async def test_lexical_hydration_offloaded_via_to_thread(monkeypatch) -> None:
    """The warm lexical-cache read resolves the corpus through
    ``asyncio.to_thread(_parse_lexical_corpus, raw)`` — not on the loop — and
    returns the identical chunks the DB path produced on the cold call."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_A, knowledge_chunks=2)
    chunk_a = await make_chunk(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_A,
        text="Pro plans include priority support.",
        chunk_index=0,
    )
    chunk_b = await make_chunk(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_A,
        text="Team plans include onboarding.",
        chunk_index=1,
    )

    # Spy: anything that goes through asyncio.to_thread is recorded.
    spied: list[tuple] = []
    real_to_thread = rag_module.asyncio.to_thread

    async def _fake_to_thread(func, *args, **kwargs):
        spied.append((func, args, kwargs))
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(rag_module.asyncio, "to_thread", _fake_to_thread)

    # Cold call -> DB path (cache miss): must NOT hydrate via to_thread.
    cold = await env.rag._load_all_chunks(TENANT_A, WEB_A, corpus_version=CORPUS_VERSION)
    assert cold[0].chunk.id == chunk_a.id
    assert all(c.chunk.embedding == [] for c in cold)
    assert [c[0] for c in spied if c[0] is rag_module._parse_lexical_corpus] == []

    # Warm call -> lexical-cache hit: hydration runs through the worker thread.
    spied.clear()
    warm = await env.rag._load_all_chunks(TENANT_A, WEB_A, corpus_version=CORPUS_VERSION)

    parse_calls = [c for c in spied if c[0] is rag_module._parse_lexical_corpus]
    assert len(parse_calls) == 1, "lexical hydration must run inside asyncio.to_thread"
    # The raw Redis payload is handed to the worker-thread parser.
    assert parse_calls[0][1][0] == _serialize([chunk_a, chunk_b])

    # Semantically identical to the DB path: same ids, score, order.
    assert [c.chunk.id for c in warm] == [c.chunk.id for c in cold]
    assert [c.score for c in warm] == [c.score for c in cold]
    assert all(
        wa.chunk.chunk_text == co.chunk.chunk_text
        and wa.chunk.metadata == co.chunk.metadata
        and wa.chunk.embedding == co.chunk.embedding
        for wa, co in zip(warm, cold, strict=True)
    )


async def test_redis_and_db_io_remain_async(monkeypatch) -> None:
    """The Redis read is still awaited async I/O and the DB light load still
    runs via the repository's async method (only deserialization is offloaded)."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_A, knowledge_chunks=1)
    await make_chunk(
        env, tenant_id=TENANT_A, website_id=WEB_A, text="Knowledge content.", chunk_index=0
    )
    # Capture the chunk payload BEFORE spying so the seeding read is not counted.
    seeded = await env.vector.list_chunks_light(TENANT_A, WEB_A, limit=0)

    light_calls: list = []
    original_light = env.vector.list_chunks_light

    async def _spy_light(tenant_id: str, website_id: str, *, limit: int = 0):
        light_calls.append((tenant_id, website_id, limit))
        return await original_light(tenant_id, website_id, limit=limit)

    monkeypatch.setattr(env.vector, "list_chunks_light", _spy_light)

    # 1) Cache-too-thread path: seed the lexical cache, no DB read at all.
    await env.cache.set("lexical", LEXICAL_KEY_A, _serialize(seeded))
    cached = await env.rag._load_all_chunks(TENANT_A, WEB_A, corpus_version=CORPUS_VERSION)
    assert [c.chunk.id for c in cached] == [seeded[0].id]
    assert light_calls == [], "warm cache path must skip the DB light load"

    # 2) DB path still uses the (async) repository method on a cache miss.
    await env.cache.delete("lexical", LEXICAL_KEY_A)
    db = await env.rag._load_all_chunks(TENANT_A, WEB_A, corpus_version=CORPUS_VERSION)
    assert db and light_calls[-1][:2] == (TENANT_A, WEB_A)


# ---------------------------------------------------------------------------
# Phase 3: malformed data must degrade to the established DB fallback
# ---------------------------------------------------------------------------


async def test_lexical_cache_invalid_json_falls_back_to_db(caplog) -> None:
    """Invalid JSON in the lexical cache logs `lexical_corpus_cache_invalid`
    and returns the DB corpus (established miss semantics, not an error)."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_A, knowledge_chunks=1)
    chunk = await make_chunk(
        env, tenant_id=TENANT_A, website_id=WEB_A, text="Knowledge content.", chunk_index=0
    )

    await env.cache.set("lexical", LEXICAL_KEY_A, "not-json{{{")

    with caplog.at_level("WARNING", logger="webchat_ai"):
        chunks = await env.rag._load_all_chunks(TENANT_A, WEB_A, corpus_version=CORPUS_VERSION)

    assert [c.chunk.id for c in chunks] == [chunk.id]
    assert any(r.getMessage().startswith("lexical_corpus_cache_invalid") for r in caplog.records)


async def test_lexical_cache_broken_chunk_payload_falls_back_to_db(caplog) -> None:
    """A JSON-valid payload whose chunk dict fails KnowledgeChunk validation
    (pydantic ValidationError -> ValueError) must also degrade to the DB path."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_A, knowledge_chunks=1)
    chunk = await make_chunk(
        env, tenant_id=TENANT_A, website_id=WEB_A, text="Knowledge content.", chunk_index=0
    )

    broken = json.dumps({"chunks": [{"chunk_text": 12345}]})
    await env.cache.set("lexical", LEXICAL_KEY_A, broken)

    with caplog.at_level("WARNING", logger="webchat_ai"):
        chunks = await env.rag._load_all_chunks(TENANT_A, WEB_A, corpus_version=CORPUS_VERSION)

    assert [c.chunk.id for c in chunks] == [chunk.id]
    assert any(r.getMessage().startswith("lexical_corpus_cache_invalid") for r in caplog.records)


# ---------------------------------------------------------------------------
# Phase 4: tenant / website / corpus-version isolation preserved
# ---------------------------------------------------------------------------


async def test_cross_site_isolation_same_query() -> None:
    """Website A ('BCA fee ₹80,000') and Website B ('BCA fee ₹65,000'), asked
    with the same question/corpus version, each retrieve ONLY their own corpus."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_A, knowledge_chunks=1)
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_B, knowledge_chunks=1)
    chunk_a = await make_chunk(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_A,
        text="BCA annual tuition fee is ₹80,000.",
        chunk_index=0,
    )
    chunk_b = await make_chunk(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_B,
        text="BCA annual tuition fee is ₹65,000.",
        chunk_index=0,
    )

    corpus_a = await env.rag._load_all_chunks(TENANT_A, WEB_A, corpus_version=CORPUS_VERSION)
    corpus_b = await env.rag._load_all_chunks(TENANT_A, WEB_B, corpus_version=CORPUS_VERSION)

    assert [c.chunk.id for c in corpus_a] == [chunk_a.id]
    assert [c.chunk.id for c in corpus_b] == [chunk_b.id]
    assert "₹80,000" in corpus_a[0].chunk.chunk_text
    assert "₹65,000" in corpus_b[0].chunk.chunk_text
    assert "₹65,000" not in corpus_a[0].chunk.chunk_text
    assert "₹80,000" not in corpus_b[0].chunk.chunk_text


async def test_lexical_cache_is_scoped_per_website_and_version() -> None:
    """different website ids / corpus versions never share lexical cache keys."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_A, knowledge_chunks=2)
    chunk_v1 = await make_chunk(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_A,
        text="corpus v1 content",
        chunk_index=0,
    )

    # Seed a WRONG-version and a WRONG-website entry; neither may serve WEB_A v1.
    await env.cache.set("lexical", f"{TENANT_A}:{WEB_A}:v9:unlocked", _serialize([]))
    await env.cache.set("lexical", f"{TENANT_A}:{WEB_B}:{CORPUS_VERSION}:unlocked", _serialize([]))

    chunks = await env.rag._load_all_chunks(TENANT_A, WEB_A, corpus_version=CORPUS_VERSION)
    assert [c.chunk.id for c in chunks] == [chunk_v1.id]
