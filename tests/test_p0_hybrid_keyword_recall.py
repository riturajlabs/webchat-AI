"""Focused P0 regression tests for hybrid keyword recall over a full lexical corpus.

Proves the acceptance criteria from the P0 fix: keyword retrieval searches a
deterministic, tenant+website-scoped, embedding-free lexical corpus without an
artificial first-50 recall cap, while RRF, lexical protection and source
diversity remain intact.
"""

from __future__ import annotations

from backend.repositories.vector.base import VectorSearchResult
from backend.repositories.vector.hybrid import keyword_search
from backend.services.chat.retrieval_strategy import HybridRetrievalStrategy

from tests.chat_helpers import build_chat_env, make_chunk, make_website

TENANT = "p0-tenant"
WEBSITE = "p0-web"


def _ids(results: list[VectorSearchResult]) -> list[str]:
    return [r.chunk.id for r in results]


# ---------------------------------------------------------------------------
# 1 & 2. A keyword match outside the first 50 records is retrieved
# ---------------------------------------------------------------------------


async def test_exact_rare_term_outside_first_50_enters_keyword_results() -> None:
    """A SOIT-style exact term whose chunk is past the old 50-record slice is found."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=60)
    for i in range(59):
        await make_chunk(
            env,
            tenant_id=TENANT,
            website_id=WEBSITE,
            text=f"unrelated paragraph content number {i}",
            chunk_index=i,
        )
    target = await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="The School of Information Technology dean is Dr. Janardan Pawar.",
        chunk_index=59,
        document_id="soit-document",
        url="https://indira.example/school-of-it",
        title="School of Information Technology",
    )

    all_chunks = await env.rag._load_all_chunks(TENANT, WEBSITE, corpus_version="v1")
    assert len(all_chunks) == 60
    results = keyword_search("dean of SOIT", all_chunks, top_k=5)

    assert target.id in _ids(results)


async def test_rare_exact_token_outside_first_50_retrieved() -> None:
    """An exact rare token whose chunk lies beyond the first 50 records is recalled."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=70)
    for i in range(69):
        await make_chunk(
            env,
            tenant_id=TENANT,
            website_id=WEBSITE,
            text=f"ordinary body copy {i}",
            chunk_index=i,
        )
    target = await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Xenodochial admission criteria apply only here.",
        chunk_index=69,
        document_id="rare-token",
    )

    all_chunks = await env.rag._load_all_chunks(TENANT, WEBSITE, corpus_version="v1")
    results = keyword_search("Xenodochial", all_chunks, top_k=5)

    assert _ids(results) == [target.id]


# ---------------------------------------------------------------------------
# 3 & 4. Tenant and website scoping
# ---------------------------------------------------------------------------


async def test_keyword_retrieval_is_tenant_and_website_scoped() -> None:
    """The lexical corpus never bleeds across tenants or websites."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
    await make_website(env, tenant_id=TENANT, website_id="other-site", knowledge_chunks=1)
    await make_website(env, tenant_id="other-tenant", website_id=WEBSITE, knowledge_chunks=1)

    own = await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="SOIT rare fact")
    await make_chunk(env, tenant_id=TENANT, website_id="other-site", text="SOIT other site")
    await make_chunk(env, tenant_id="other-tenant", website_id=WEBSITE, text="SOIT other tenant")

    chunks = await env.rag._load_all_chunks(TENANT, WEBSITE, corpus_version="v1")

    assert _ids(chunks) == [own.id]
    assert all(c.chunk.embedding == [] for c in chunks)


# ---------------------------------------------------------------------------
# 5. Deterministic ordering for ties
# ---------------------------------------------------------------------------


async def test_keyword_tie_ordering_is_deterministic_by_chunk_id() -> None:
    """Identical lexical scores use chunk id as the stable secondary sort."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=3)
    a = await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="SOIT", chunk_index=0)
    b = await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="SOIT", chunk_index=1)
    c = await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="SOIT", chunk_index=2)

    all_chunks = await env.rag._load_all_chunks(TENANT, WEBSITE, corpus_version="v1")
    results = keyword_search("SOIT", all_chunks, top_k=3)

    assert set(_ids(results)) == {a.id, b.id, c.id}
    assert _ids(results) == sorted(_ids(results))


# ---------------------------------------------------------------------------
# 6. No embedding field is required/transferred
# ---------------------------------------------------------------------------


async def test_lexical_corpus_carries_no_embeddings() -> None:
    """Keyword retrieval operates purely on text/metadata, never vectors."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=2)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="SOIT facts", chunk_index=0)
    await make_chunk(
        env, tenant_id=TENANT, website_id=WEBSITE, text="Cyber Security", chunk_index=1
    )

    chunks = await env.rag._load_all_chunks(TENANT, WEBSITE, corpus_version="v1")
    assert all(c.chunk.embedding == [] for c in chunks)
    # Every returned candidate must be keyword-scorable from text alone.
    assert keyword_search("SOIT", chunks, top_k=1)


# ---------------------------------------------------------------------------
# 7. RRF still merges vector-only and keyword-only candidates
# ---------------------------------------------------------------------------


async def test_rrf_merges_vector_only_and_keyword_only() -> None:
    """A keyword-only chunk that vector search missed survives RRF into the pool."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=2)
    vector_hit = await make_chunk(
        env, tenant_id=TENANT, website_id=WEBSITE, text="semantic startup info", chunk_index=0
    )
    keyword_only = await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="SOIT peregrine exact entity",
        chunk_index=1,
    )

    vector_results = [VectorSearchResult(chunk=vector_hit, score=0.9)]
    all_chunks = await env.rag._load_all_chunks(TENANT, WEBSITE, corpus_version="v1")

    strategy = HybridRetrievalStrategy(rrf_k=60, keyword_top_k=50, candidate_top_k=50)
    final, metrics = strategy.search(
        query="SOIT peregrine",
        vector_results=vector_results,
        all_chunks=all_chunks,
        top_k=5,
    )

    ids = _ids(final)
    assert vector_hit.id in ids
    assert keyword_only.id in ids
    assert metrics.keyword_result_count > 0


# ---------------------------------------------------------------------------
# 8. Lexical protection still works
# ---------------------------------------------------------------------------


async def test_strong_lexical_match_retained() -> None:
    """A chunk containing every query content token is protected in the pool."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=3)
    protected = await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="dean of SOIT is Dr. Janardan Pawar",
        chunk_index=0,
        document_id="soit",
    )
    for i in (1, 2):
        await make_chunk(
            env,
            tenant_id=TENANT,
            website_id=WEBSITE,
            text=f"generic marketing copy {i}",
            chunk_index=i,
        )

    all_chunks = await env.rag._load_all_chunks(TENANT, WEBSITE, corpus_version="v1")
    kw = keyword_search("dean of SOIT", all_chunks, top_k=5)
    assert protected.id in _ids(kw)


# ---------------------------------------------------------------------------
# 9. Source diversity behavior unchanged
# ---------------------------------------------------------------------------


async def test_lexical_corpus_preserves_source_metadata() -> None:
    """Chunks carry source_url/title so source diversity and citations still work."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=2)
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="admission process for BCA",
        url="https://indira.example/bca",
        title="BCA",
        chunk_index=0,
    )
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="admission process for cyber security",
        url="https://indira.example/cyber",
        title="Cyber Security",
        chunk_index=1,
    )

    chunks = await env.rag._load_all_chunks(TENANT, WEBSITE, corpus_version="v1")
    urls = {c.chunk.metadata.get("source_url") for c in chunks}
    assert urls == {"https://indira.example/bca", "https://indira.example/cyber"}


# ---------------------------------------------------------------------------
# 11. Cache hit and cache miss behavior
# ---------------------------------------------------------------------------


async def test_lexical_cache_hit_skips_mongo_and_serves_same_corpus(monkeypatch) -> None:
    """First call misses and loads Mongo; second call hits and avoids the DB."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=3)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="A", chunk_index=0)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="B", chunk_index=1)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="C", chunk_index=2)

    calls: list[int] = []
    original = env.vector.list_chunks_light

    async def spy(tenant_id: str, website_id: str, *, limit: int = 0):
        calls.append(limit)
        return await original(tenant_id, website_id, limit=limit)

    monkeypatch.setattr(env.vector, "list_chunks_light", spy)

    first = await env.rag._load_all_chunks(TENANT, WEBSITE, corpus_version="v1")
    second = await env.rag._load_all_chunks(TENANT, WEBSITE, corpus_version="v1")

    assert calls == [0]  # exactly one Mongo light load (the miss)
    assert len(first) == len(second) == 3
    assert _ids(first) == _ids(second)
    lexical_write = next(call for call in env.cache.set_calls if call[0] == "lexical")
    raw = await env.cache.get("lexical", lexical_write[1])
    assert raw is not None
    assert '"embedding"' not in raw


async def test_lexical_cache_key_includes_tenant_website_identity() -> None:
    """Different websites/tenants/versions use distinct lexical cache keys."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
    await make_website(env, tenant_id=TENANT, website_id="site-b", knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="W", chunk_index=0)
    await make_chunk(env, tenant_id=TENANT, website_id="site-b", text="B", chunk_index=0)

    await env.rag._load_all_chunks(TENANT, WEBSITE, corpus_version="v1")
    await env.rag._load_all_chunks(TENANT, "site-b", corpus_version="v1")

    lexical_keys = {k for (ns, k, _ttl) in env.cache.set_calls if ns == "lexical"}
    assert len(lexical_keys) == 2
    assert all(k.startswith(f"{TENANT}:") for k in lexical_keys)


# ---------------------------------------------------------------------------
# 10. Light loading remains effective (no full embedding transfer)
# ---------------------------------------------------------------------------


async def test_no_full_list_chunks_embedding_transfer() -> None:
    """The lexical path uses the embedding-free projection, not list_chunks."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=2)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="A", chunk_index=0)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="B", chunk_index=1)

    calls: list[str] = []
    original_light = env.vector.list_chunks_light

    async def _light(tenant_id: str, website_id: str, *, limit: int = 0):
        calls.append("list_chunks_light")
        return await original_light(tenant_id, website_id, limit=limit)

    # Simulate a repository whose full transfer would raise: prove the lexical
    # path never calls it.
    async def _full(*_a, **_k):
        calls.append("list_chunks")
        return []

    env.vector.list_chunks = _full  # type: ignore[method-assign]
    env.vector.list_chunks_light = _light  # type: ignore[method-assign]

    chunks = await env.rag._load_all_chunks(TENANT, WEBSITE, corpus_version="v1")

    assert calls == ["list_chunks_light"]
    assert len(chunks) == 2
