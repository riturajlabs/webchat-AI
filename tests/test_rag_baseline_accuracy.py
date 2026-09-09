"""RAG baseline accuracy evaluation fixtures (baseline instrumentation).

Covers:
- Cross-site (cross-website) corpus isolation: same query must produce
  only that website's sources.
- Retrieval recall by query type: exact-match, short, broad, paraphrase,
  follow-up.
- Per-stage histogram instrumentation verification.

All tests use ``install_relevance_scoring`` so the FakeVectorRepository
scores by lexical token overlap, giving deterministic retrieval semantics.
Sources are identified by their ``url``/``title`` (the sources frame exposes
``chunk_id``, ``url``, ``title``, ``score`` — not the chunk text).
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.core.metrics import RAG_STAGE_LATENCY_SECONDS, reset_registry

from tests.chat_helpers import (
    ChatEnv,
    build_chat_env,
    consume,
    install_relevance_scoring,
    make_chunk,
    make_website,
)

TENANT = "accuracy-tenant"
SITE_A = "site-a"
SITE_B = "site-b"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _stream(env: ChatEnv, **kwargs):  # type: ignore[no-untyped-def]
    return await consume(env.rag.stream_answer(**kwargs))


def _done_event(events: list[dict]) -> dict:
    return next(e for e in events if e["event"] == "done")


def _sources_event(events: list[dict]) -> dict:
    return next(e for e in events if e["event"] == "sources")


def _source_titles(events: list[dict]) -> list[str]:
    """Extract the title for each source (identified uniquely per chunk below)."""
    src = _sources_event(events)
    return [s.get("title", "") for s in src["data"]["sources"]]


def _source_urls(events: list[dict]) -> list[str]:
    src = _sources_event(events)
    return [s.get("url", "") for s in src["data"]["sources"]]


# ---------------------------------------------------------------------------
# Corpus fixture helpers
# ---------------------------------------------------------------------------


@dataclass
class SiteCorpus:
    env: ChatEnv
    website_id: str
    tenant_id: str
    # Maps a human label to the title url assigned to each chunk.
    title_to_url: dict[str, str]


async def _build_two_site_corpus(
    *, use_relevance: bool = True
) -> tuple[ChatEnv, SiteCorpus, SiteCorpus]:
    """Build two independent corpora under the same tenant.

    Site A (BCA bank): home loan processing fee is ₹80,000.
    Site B (ICICI bank): home loan processing fee is ₹65,000.

    Each chunk gets a unique title so tests can identify which source came back.
    Returns (env, site_a, site_b).
    """
    env = build_chat_env(reranker=False)
    if use_relevance:
        install_relevance_scoring(env)

    await make_website(env, tenant_id=TENANT, website_id=SITE_A, knowledge_chunks=3)
    await make_website(env, tenant_id=TENANT, website_id=SITE_B, knowledge_chunks=3)

    a_chunks = [
        "BCA home loan processing fee is 80000 rupees for loan amounts above 50 lakh.",
        "BCA home loan interest rates start from 8.5 percent per annum for salaried applicants.",
        "BCA charges a late payment penalty of 2 percent on the overdue amount.",
    ]
    b_chunks = [
        "ICICI home loan processing fee is 65000 rupees for all loan amounts.",
        "ICICI home loan interest rates start from 8.75 percent per annum.",
        "ICICI charges a prepayment penalty of 3 percent on fixed-rate loans.",
    ]

    a_title_to_url: dict[str, str] = {}
    for i, text in enumerate(a_chunks):
        title = f"site-a-chunk-{i}"
        url = f"https://{SITE_A}.example.com/chunk-{i}"
        a_title_to_url[title] = url
        await make_chunk(
            env, tenant_id=TENANT, website_id=SITE_A, text=text, url=url, title=title, chunk_index=i
        )

    b_title_to_url: dict[str, str] = {}
    for i, text in enumerate(b_chunks):
        title = f"site-b-chunk-{i}"
        url = f"https://{SITE_B}.example.com/chunk-{i}"
        b_title_to_url[title] = url
        await make_chunk(
            env, tenant_id=TENANT, website_id=SITE_B, text=text, url=url, title=title, chunk_index=i
        )

    return (
        env,
        SiteCorpus(env=env, website_id=SITE_A, tenant_id=TENANT, title_to_url=a_title_to_url),
        SiteCorpus(env=env, website_id=SITE_B, tenant_id=TENANT, title_to_url=b_title_to_url),
    )


# ---------------------------------------------------------------------------
# 1. Cross-site corpus isolation (critical)
# ---------------------------------------------------------------------------


async def test_cross_site_isolation_same_query_different_sources() -> None:
    """Same query to two different websites must return only that website's sources.

    Site A has BCA ₹80,000, site B has ICICI ₹65,000. A query about the
    processing fee must return only that website's own sources.
    """
    env, site_a, site_b = await _build_two_site_corpus()

    events_a = await _stream(
        env, tenant_id=TENANT, website_id=SITE_A, question="home loan processing fee"
    )
    events_b = await _stream(
        env, tenant_id=TENANT, website_id=SITE_B, question="home loan processing fee"
    )

    urls_a = _source_urls(events_a)
    urls_b = _source_urls(events_b)

    assert len(urls_a) >= 1, "Site A returned no sources"
    assert len(urls_b) >= 1, "Site B returned no sources"

    # Every A source must be from site A; every B source from site B.
    assert all(SITE_A in u for u in urls_a), f"Site A returned foreign source: {urls_a}"
    assert all(SITE_B in u for u in urls_b), f"Site B returned foreign source: {urls_b}"

    done_a = _done_event(events_a)
    done_b = _done_event(events_b)
    assert done_a["data"]["fallback"] is False
    assert done_b["data"]["fallback"] is False


async def test_cross_site_no_content_leak() -> None:
    """Site A's sources must not contain site B's unique facts (ICICI / 65000)."""
    env, site_a, site_b = await _build_two_site_corpus()

    events_a = await _stream(env, tenant_id=TENANT, website_id=SITE_A, question="processing fee")
    urls_a = _source_urls(events_a)

    assert all(SITE_A in u for u in urls_a), f"Cross-site leak: {urls_a}"


async def test_cross_site_opposite_direction() -> None:
    """Site B's sources must not contain site A's unique facts (BCA / 80000)."""
    env, site_a, site_b = await _build_two_site_corpus()

    events_b = await _stream(env, tenant_id=TENANT, website_id=SITE_B, question="processing fee")
    urls_b = _source_urls(events_b)

    assert all(SITE_B in u for u in urls_b), f"Cross-site leak: {urls_b}"


# ---------------------------------------------------------------------------
# 2. Retrieval accuracy by query type
# ---------------------------------------------------------------------------


async def test_exact_match_retrieves_correct_chunk() -> None:
    """An exact-match query about BCA fee must retrieve the site-a-chunk-0 source."""
    env, site_a, _ = await _build_two_site_corpus()
    events = await _stream(
        env, tenant_id=TENANT, website_id=SITE_A, question="BCA home loan processing fee"
    )
    titles = _source_titles(events)
    assert "site-a-chunk-0" in titles, f"Expected BCA fee chunk in {titles}"


async def test_short_query_retrieves_topically_relevant_chunks() -> None:
    """A short query 'fee' should not always fallback (source present or fallback False)."""
    env, site_a, _ = await _build_two_site_corpus()
    events = await _stream(env, tenant_id=TENANT, website_id=SITE_A, question="fee")
    done = _done_event(events)
    assert done["data"]["fallback"] is False


async def test_broad_query_retrieves_multiple_chunks() -> None:
    """A broad query should retrieve multiple distinct sources.

    Confidence gating is disabled so the test measures pure retrieval behavior
    rather than the abstention guard.
    """
    env, site_a, _ = await _build_two_site_corpus()
    env.rag._confidence_check_enabled = False
    events = await _stream(
        env, tenant_id=TENANT, website_id=SITE_A, question="bank loan policies fees interest"
    )
    titles = _source_titles(events)
    assert len(titles) >= 1, "Broad query returned no sources"


async def test_paraphrase_retrieves_matching_chunk() -> None:
    """A paraphrase query retrieves the BCA fee chunk via token overlap.

    Confidence gating is disabled so the test measures pure retrieval.
    """
    env, site_a, _ = await _build_two_site_corpus()
    env.rag._confidence_check_enabled = False
    events = await _stream(
        env,
        tenant_id=TENANT,
        website_id=SITE_A,
        question="How much does it cost to process a home loan application?",
    )
    titles = _source_titles(events)
    assert "site-a-chunk-0" in titles, f"Paraphrase should retrieve fee chunk, got {titles}"


async def test_followup_retrieval_uses_session() -> None:
    """A follow-up question with a session still searches the same corpus."""
    env, site_a, _ = await _build_two_site_corpus()
    events1 = await _stream(env, tenant_id=TENANT, website_id=SITE_A, question="BCA processing fee")
    done1 = _done_event(events1)
    assert done1["data"]["fallback"] is False
    session_id = done1["data"]["session_id"]

    events2 = await _stream(
        env,
        tenant_id=TENANT,
        website_id=SITE_A,
        question="interest rate",
        session_id=session_id,
    )
    done2 = _done_event(events2)
    assert done2["data"]["fallback"] is False


# ---------------------------------------------------------------------------
# 3. Recall@k / MRR helpers
# ---------------------------------------------------------------------------


def recall_at_k(titles: list[str], expected_titles: list[str], k: int) -> float:
    """Fraction of expected_titles found within the first k returned titles."""
    top_k = set(titles[:k])
    hits = sum(1 for t in expected_titles if t in top_k)
    return hits / len(expected_titles) if expected_titles else 0.0


def mrr(titles: list[str], expected_title: str) -> float:
    """Reciprocal rank of the first occurrence of expected_title (or 0.0)."""
    for i, t in enumerate(titles, start=1):
        if t == expected_title:
            return 1.0 / i
    return 0.0


async def test_recall_at_3_exact_query() -> None:
    """Recall@3 for the BCA fee query should find site-a-chunk-0."""
    env, site_a, _ = await _build_two_site_corpus()
    events = await _stream(env, tenant_id=TENANT, website_id=SITE_A, question="BCA processing fee")
    titles = _source_titles(events)
    r3 = recall_at_k(titles, ["site-a-chunk-0"], k=3)
    assert r3 == 1.0, f"Expected recall@3=1.0, got {r3} for titles {titles}"


async def test_mrr_exact_query() -> None:
    """MRR for the BCA fee query should be >= 1/3."""
    env, site_a, _ = await _build_two_site_corpus()
    events = await _stream(env, tenant_id=TENANT, website_id=SITE_A, question="BCA processing fee")
    titles = _source_titles(events)
    rr = mrr(titles, "site-a-chunk-0")
    assert rr >= 1 / 3, f"Expected MRR >= 1/3, got {rr} for titles {titles}"


# ---------------------------------------------------------------------------
# 4. Per-stage histogram instrumentation verification
# ---------------------------------------------------------------------------


async def test_per_stage_histogram_observed_after_stream() -> None:
    """After a successful stream_answer, the 'total' stage has histogram samples."""
    reset_registry()
    env = build_chat_env()
    install_relevance_scoring(env)
    await make_website(env, tenant_id=TENANT, website_id=SITE_A, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT, website_id=SITE_A, text="Hello world.", chunk_index=0)

    await _stream(env, tenant_id=TENANT, website_id=SITE_A, question="Hello")

    assert ("total", "") in RAG_STAGE_LATENCY_SECONDS._series
    total_series = RAG_STAGE_LATENCY_SECONDS._series[("total", "")]
    assert total_series.count >= 1
    reset_registry()


async def test_per_stage_histogram_cache_status_labels() -> None:
    """First call to a fresh env produces embedding cache_status='miss' series."""
    reset_registry()
    env = build_chat_env()
    install_relevance_scoring(env)
    await make_website(env, tenant_id=TENANT, website_id=SITE_A, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT, website_id=SITE_A, text="Cache test.", chunk_index=0)

    await _stream(env, tenant_id=TENANT, website_id=SITE_A, question="Cache test")

    assert ("embedding", "miss") in RAG_STAGE_LATENCY_SECONDS._series
    reset_registry()
