"""RAG-ACC-01 accuracy + TTFT measurement benchmark (measurement ONLY).

Scope rules honoured by every test in this file:
- No production writes.  No real provider/LLM calls (deterministic fakes only).
- No retrieval/ranking/chunking/prompt/caching/embedding configuration is
  changed.  ``install_relevance_scoring`` only swaps the fake repository's
  similarity scoring for a deterministic token-overlap proxy (as the other
  baseline RAG suites do) so ranking is reproducible instead of a constant.
- Nothing is optimized or refactored here; failures are measured and recorded,
  never fixed.

Two modes:
- Fast accuracy/isolation tests run always (deterministic, small).
- Heavy latency/TTFT/corpus-scale benchmarks are skipped unless
  ``RAG_BENCH=1`` so the ordinary suite stays quick.

All measured numbers are SYNTHETIC: they come from in-memory fakes on a dev
box and are NOT production latency.  Raw per-request samples are aggregated
(P50/P95/P99/min/max/mean) from the ``done`` timing frame, never from bucket
estimates.  Every benchmark writes its collected samples into the module-level
``BENCHMARK_RESULTS`` dict, which ``test_export_benchmark_results_json`` dumps
to ``/tmp/opencode/rag_accuracy_bench_results.json`` for the report step.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import statistics
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from backend.repositories.vector.base import VectorSearchResult
from backend.repositories.vector.hybrid import keyword_search

from tests.chat_helpers import (
    ChatEnv,
    build_chat_env,
    consume,
    install_relevance_scoring,
    make_chunk,
    make_website,
)

RUN_BENCH = os.environ.get("RAG_BENCH") == "1"
BENCH_SKIP_REASON = "set RAG_BENCH=1 to run heavy latency/scale/TTFT benchmarks"

ACC_TENANT = "acc-tenant"
OTHER_TENANT = "other-tenant"
SITE_A = "academy-a"
SITE_B = "academy-b"

CORPUS_A: dict[str, str] = {
    "bca-fee": "The BCA annual tuition fee is 80000 rupees for the first year.",
    "bca-admission": (
        "BCA admission eligibility requires a minimum of 50 percent marks "
        "in class 12 with mathematics."
    ),
    "bca-program": (
        "BCA is a three year undergraduate program covering programming, "
        "data structures, and software engineering."
    ),
    "bca-courses": (
        "BCA offers specialization electives in the third year including "
        "cybersecurity and cloud computing."
    ),
    "bca-cybersec": (
        "Cyber security course topics include network security, ethical "
        "hacking, and digital forensics."
    ),
    "bca-department": (
        "The BCA department chair is Professor Anil Kumar, who also serves "
        "as the dean of the school of information technology."
    ),
    "bca-placement": (
        "Placement support for BCA students includes a placement cell, "
        "resume workshops, and mock interviews."
    ),
    "bca-scholarship": (
        "BCA offers a merit scholarship covering 30 percent of the tuition fee for top performers."
    ),
}

CORPUS_B: dict[str, str] = {
    "bca-fee": "The BCA annual tuition fee is 65000 rupees for the first year.",
    "bca-admission": "BCA admission requires 55 percent marks in class 12.",
    "bca-dean": "The dean of the BCA program at Academy B is Professor Lakshmi Iyer.",
}

# Category -> list of (query, [golden titles]) .  Golden titles are the known
# relevant chunks by their fixed titles; they are NEVER derived from the model
# output (task rule: relevance labels are predeclared, not invented).
ACCURACY_QUERIES: dict[str, list[tuple[str, list[str]]]] = {
    "exact": [
        ("What is the annual BCA tuition fee?", ["bca-fee"]),
        ("What are the BCA admission eligibility requirements?", ["bca-admission"]),
        ("Who is the dean of the BCA department?", ["bca-department"]),
        ("Which specialization courses does BCA offer?", ["bca-courses"]),
    ],
    "short": [
        ("BCA fee?", ["bca-fee"]),
        ("Admission?", ["bca-admission"]),
        ("Dean?", ["bca-department"]),
    ],
    "broad": [
        ("Tell me about BCA", ["bca-program", "bca-courses", "bca-placement"]),
        ("What courses are available?", ["bca-courses", "bca-cybersec"]),
        ("Tell me about admissions and fee at BCA", ["bca-fee", "bca-admission"]),
    ],
    "paraphrase": [
        ("How much does BCA cost per year?", ["bca-fee"]),
        ("What is the yearly BCA tuition?", ["bca-fee"]),
        ("BCA fees?", ["bca-fee"]),
        ("What is the annual BCA fee?", ["bca-fee"]),
        ("What does BCA charge for tuition annually?", ["bca-fee"]),
    ],
    "typo": [
        ("What is the BCA admision fee?", ["bca-fee", "bca-admission"]),
        ("eligibilty requirements for BCA admission", ["bca-admission"]),
        ("cyber securty course", ["bca-cybersec"]),
        ("teach me about BCA addmission", ["bca-admission"]),
    ],
    "followup": [
        ("What is the BCA fee?", "Is that per year?", ["bca-fee"]),
        ("What is the BCA fee?", "and is that per year?", ["bca-fee"]),
        ("What is the BCA fee?", "That is per year, right?", ["bca-fee"]),
    ],
    "multi-source": [
        ("What is the BCA fee and admission eligibility?", ["bca-fee", "bca-admission"]),
        ("BCA courses and placement support", ["bca-courses", "bca-placement"]),
        ("cyber security course and BCA admission", ["bca-cybersec", "bca-admission"]),
    ],
    "no-answer": [
        ("What is the MBA tuition fee?", []),
        ("What are the MBA admission requirements?", []),
        ("What is the capital of France?", []),
    ],
}

BENCHMARK_RESULTS: dict[str, Any] = {
    "benchmark": "RAG-ACC-01",
    "measurement_kind": "SYNTHETIC (deterministic in-memory fakes, dev box)",
    "accuracy": {},
    "isolation": {},
    "cache": {},
    "scale": {},
    "rerank": {},
    "ttft": {},
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _stream(
    env: ChatEnv, *, tenant_id: str, website_id: str, question: str, session_id: str | None = None
) -> list[dict]:
    """Stream one question; returns all SSE events."""
    return await consume(
        env.rag.stream_answer(
            tenant_id=tenant_id, website_id=website_id, question=question, session_id=session_id
        )
    )


def _done_event(events: list[dict]) -> dict:
    return next(e for e in events if e["event"] == "done")


def _sources_event(events: list[dict]) -> dict:
    return next(e for e in events if e["event"] == "sources")


def _source_titles(events: list[dict]) -> list[str]:
    src = _sources_event(events)
    return [s.get("title", "") for s in src["data"]["sources"]]


def _source_urls(events: list[dict]) -> list[str]:
    src = _sources_event(events)
    return [s.get("url", "") for s in src["data"]["sources"]]


async def _make_academy(
    env: ChatEnv,
    *,
    tenant_id: str = ACC_TENANT,
    site: str = SITE_A,
    corpus: dict[str, str] | None = None,
) -> None:
    """Insert a website + its golden corpus with unique titles per chunk."""
    body = CORPUS_A if corpus is None else corpus
    await make_website(env, tenant_id=tenant_id, website_id=site, knowledge_chunks=len(body))
    for i, (title, text) in enumerate(body.items()):
        await make_chunk(
            env,
            tenant_id=tenant_id,
            website_id=site,
            text=text,
            url=f"https://{site}.example.com/{title}",
            title=title,
            document_id=f"doc-{title}",
            chunk_index=i,
        )


def _build_acc_env() -> ChatEnv:
    """Deterministic accuracy env: confidence gating disabled (pure retrieval)."""
    env = build_chat_env(top_k=5)
    install_relevance_scoring(env)
    env.rag._confidence_check_enabled = False
    env.rag._timing_enabled = True
    return env


def _percentiles(samples: list[float]) -> dict[str, float]:
    """Nearest-rank P50/P95/P99 plus min/max/mean of raw samples."""
    if not samples:
        return {"n": 0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "min": 0.0, "max": 0.0, "mean": 0.0}
    s = sorted(samples)
    n = len(s)

    def rank(p: float) -> float:
        idx = math.ceil(p / 100.0 * n) - 1
        return float(s[max(0, min(idx, n - 1))])

    return {
        "n": n,
        "p50": round(rank(50.0), 3),
        "p95": round(rank(95.0), 3),
        "p99": round(rank(99.0), 3),
        "min": round(float(min(s)), 3),
        "max": round(float(max(s)), 3),
        "mean": round(statistics.fmean(s), 3),
    }


def recall_at(titles: list[str], expected: list[str], k: int) -> float:
    """Standard IR recall: |expected found in top-k| / |expected|."""
    if not expected:
        return 0.0
    top_k = set(titles[:k])
    hits = sum(1 for t in expected if t in top_k)
    return hits / len(expected)


def mrr(titles: list[str], expected: list[str]) -> float:
    """Reciprocal rank of the highest-ranked expected title (0.0 if absent)."""
    expected_set = set(expected)
    for i, t in enumerate(titles, start=1):
        if t in expected_set:
            return 1.0 / i
    return 0.0


def _stage_summary(events: list[dict]) -> dict[str, float]:
    """Extract per-request stage timings (ms) from a done event's timing frame."""
    return _done_event(events)["data"].get("timing", {})


# ---------------------------------------------------------------------------
# Phase 2 & 3 — accuracy by category (Recall@1/3/5, MRR)
# ---------------------------------------------------------------------------


async def _score_query(
    env: ChatEnv,
    *,
    query: str,
    expected: list[str],
    session_id: str | None = None,
) -> dict[str, Any]:
    events = await _stream(
        env, tenant_id=ACC_TENANT, website_id=SITE_A, question=query, session_id=session_id
    )
    titles = _source_titles(events)
    done = _done_event(events)
    return {
        "query": query,
        "expected": expected,
        "titles": titles,
        "recall@1": recall_at(titles, expected, 1),
        "recall@3": recall_at(titles, expected, 3),
        "recall@5": recall_at(titles, expected, 5),
        "mrr": mrr(titles, expected),
        "fallback": done["data"].get("fallback", False),
    }


def _aggregate(category: str, rows: list[dict[str, Any]]) -> dict[str, float]:
    """Aggregate recall/MRR across queries in a category (unweighted mean)."""
    total = max(len(rows), 1)
    return {
        "category": category,
        "queries": len(rows),
        "recall@1": round(sum(r["recall@1"] for r in rows) / total, 3),
        "recall@3": round(sum(r["recall@3"] for r in rows) / total, 3),
        "recall@5": round(sum(r["recall@5"] for r in rows) / total, 3),
        "mrr": round(sum(r["mrr"] for r in rows) / total, 3),
    }


async def test_accuracy_by_category() -> None:
    """Measure retrieval accuracy for every category with golden titles."""
    env = _build_acc_env()
    await _make_academy(env)
    BENCHMARK_RESULTS["accuracy"] = {}

    for category, specs in ACCURACY_QUERIES.items():
        rows: list[dict[str, Any]] = []
        for spec in specs:
            if category == "followup":
                first, second, expected = spec[0], spec[1], spec[2]
                events1 = await _stream(
                    env,
                    tenant_id=ACC_TENANT,
                    website_id=SITE_A,
                    question=first,
                )
                session_id = _done_event(events1)["data"]["session_id"]
                row = await _score_query(
                    env, query=second, expected=expected, session_id=session_id
                )
                row["first_query"] = first
            else:
                query, expected = spec[0], spec[1]
                row = await _score_query(env, query=query, expected=expected)
            rows.append(row)
        BENCHMARK_RESULTS["accuracy"][category] = {
            "aggregate": _aggregate(category, rows),
            "queries": rows,
        }

    acc = BENCHMARK_RESULTS["accuracy"]
    # Regression guards derived from deterministic measurement; the exact
    # figures are reported honestly above (including the weak paraphrase/no-
    # answer rows).  Floors are intentionally far below the measured values so
    # a genuine gross regression (not scoring quirks) is what fails.
    for category, min_mrr in (("exact", 0.9), ("short", 0.7), ("multi-source", 0.6)):
        agg = acc[category]["aggregate"]
        assert agg["mrr"] >= min_mrr, f"{category} MRR {agg['mrr']} < floor {min_mrr}"
    # Broad + paraphrase must at least surface *something* relevant at k=5.
    assert acc["broad"]["aggregate"]["recall@5"] >= 0.3
    assert acc["paraphrase"]["aggregate"]["recall@3"] >= 0.4
    # Typo: hybrid vocabulary normalization should recover at least one golden
    # chunk for the majority of typo queries.
    assert acc["typo"]["aggregate"]["recall@3"] >= 0.5
    # No-answer is informational: no score floor, just confirm measurements
    # were recorded for each query.
    for row in acc["no-answer"]["queries"]:
        assert "titles" in row and "fallback" in row


# ---------------------------------------------------------------------------
# Phase 4 — cross-site / tenant / corpus-version isolation (REQUIRED)
# ---------------------------------------------------------------------------


async def test_cross_site_isolation_accuracy() -> None:
    """Same query against two websites must return only that website's chunks."""
    env = _build_acc_env()
    await _make_academy(env, site=SITE_A, corpus=CORPUS_A)
    await _make_academy(env, site=SITE_B, corpus=CORPUS_B)

    events_a = await _stream(
        env, tenant_id=ACC_TENANT, website_id=SITE_A, question="What is the annual BCA tuition fee?"
    )
    events_b = await _stream(
        env, tenant_id=ACC_TENANT, website_id=SITE_B, question="What is the annual BCA tuition fee?"
    )

    urls_a = _source_urls(events_a)
    urls_b = _source_urls(events_b)
    assert urls_a, "Site A returned no sources"
    assert urls_b, "Site B returned no sources"
    leaked_a_to_b = [u for u in urls_b if SITE_A in u]
    leaked_b_to_a = [u for u in urls_a if SITE_B in u]
    BENCHMARK_RESULTS["isolation"]["cross_site"] = {
        "query": "What is the annual BCA tuition fee?",
        "site_a_sources": urls_a,
        "site_b_sources": urls_b,
        "leak_b_to_a": leaked_b_to_a,
        "leak_a_to_b": leaked_a_to_b,
    }
    assert not leaked_a_to_b, f"CRITICAL: site A chunk leaked into site B results: {leaked_a_to_b}"
    assert not leaked_b_to_a, f"CRITICAL: site B chunk leaked into site A results: {leaked_b_to_a}"
    # Grounding must be correct per site: A reports 80000, B reports 65000.
    titles_a = _source_titles(events_a)
    titles_b = _source_titles(events_b)
    assert "bca-fee" in titles_a
    assert "bca-fee" in titles_b


async def test_tenant_isolation_same_website_id() -> None:
    """Tenant-scoped retrieval: an identical query cached under tenant A must
    never serve tenant B, and B's evidence must come from B's corpus.

    Note on the fixture: ``Website.id`` is the global Mongo ``_id``, so two
    tenants can never own the same website id in production, and the fake
    repository keys websites by ``id`` alone (it cannot hold equal ids).  The
    tenant isolation contract that IS testable here is the chunk namespace
    (tenant_id, website_id) plus the retrieval-cache key prefix
    (``{tenant_id}:{website_id}:...``); both are asserted below.
    """
    env = _build_acc_env()
    await _make_academy(env, tenant_id=ACC_TENANT, site=SITE_A, corpus=CORPUS_A)
    await _make_academy(env, tenant_id=OTHER_TENANT, site=SITE_B, corpus=CORPUS_B)

    question = "What is the annual BCA tuition fee?"
    events_t1 = await _stream(env, tenant_id=ACC_TENANT, website_id=SITE_A, question=question)
    urls_t1 = _source_urls(events_t1)
    assert all(SITE_A in u for u in urls_t1), f"tenant A served foreign sources: {urls_t1}"

    # Identical query under tenant B must NOT reuse tenant A's cached result
    # (tenant-scoped retrieval-cache keys) and must produce B's own evidence.
    events_t2 = await _stream(env, tenant_id=OTHER_TENANT, website_id=SITE_B, question=question)
    urls_t2 = _source_urls(events_t2)
    timing2 = _stage_summary(events_t2)

    BENCHMARK_RESULTS["isolation"]["tenant"] = {
        "tenant_a_sources": urls_t1,
        "tenant_b_sources": urls_t2,
        "tenant_b_retrieval_cache": timing2.get("retrieval_cache"),
    }
    assert all(SITE_B in u for u in urls_t2), f"tenant B served foreign sources: {urls_t2}"
    assert timing2.get("retrieval_cache") == "miss", (
        "retrieval cache is not tenant-scoped; tenant B served tenant A's cached results"
    )


async def test_corpus_version_isolation() -> None:
    """A corpus bump invalidates the retrieval cache for a website (no stale
    cross-version evidence served)."""
    env = _build_acc_env()
    await _make_academy(env, tenant_id=ACC_TENANT, site=SITE_A, corpus=CORPUS_A)

    question = "What is the annual BCA tuition fee?"
    events1 = await _stream(env, tenant_id=ACC_TENANT, website_id=SITE_A, question=question)
    timing1 = _stage_summary(events1)
    assert timing1.get("retrieval_cache") == "miss"

    website = env.websites.websites[SITE_A]
    website.updated_at = datetime.now(UTC) + timedelta(days=1)

    events2 = await _stream(env, tenant_id=ACC_TENANT, website_id=SITE_A, question=question)
    timing2 = _stage_summary(events2)
    BENCHMARK_RESULTS["isolation"]["corpus_version"] = {
        "cache_after_bump": timing2.get("retrieval_cache"),
        "sources_after_bump": _source_urls(events2),
    }
    assert timing2.get("retrieval_cache") == "miss", (
        f"corpus bump did not invalidate retrieval cache: {timing2.get('retrieval_cache')}"
    )
    # Grounding stays correct after the bump.
    assert all("academy-a" in u for u in _source_urls(events2))


# ---------------------------------------------------------------------------
# Phase 5/6/7/9 — latency, cache, TTFT, corpus scale (heavy, RAG_BENCH=1)
# ---------------------------------------------------------------------------


def _topic_corpus_chunks(n: int) -> list[str]:
    """Deterministic topic-document corpus at n chunks (mirrors the existing
    baseline benchmark corpus generator)."""
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


async def _build_topic_corpus(env: ChatEnv, tenant_id: str, site: str, n: int) -> None:
    await make_website(env, tenant_id=tenant_id, website_id=site, knowledge_chunks=n)
    for i, text in enumerate(_topic_corpus_chunks(n)):
        await make_chunk(
            env,
            tenant_id=tenant_id,
            website_id=site,
            text=text,
            chunk_index=i,
            document_id=f"doc-{i // 10}",
        )


def _bench_env(*, cache: Any = None) -> ChatEnv:
    env = build_chat_env(top_k=5, cache=cache)
    install_relevance_scoring(env)
    env.rag._confidence_check_enabled = False
    env.rag._timing_enabled = True
    return env


def _summary_from_done(done: dict[str, Any]) -> dict[str, float]:
    timing = done["data"].get("timing", {})
    return {
        "embedding_ms": float(timing.get("embedding_ms", 0) or 0),
        "retrieval_ms": float(timing.get("retrieval_ms", 0) or 0),
        "load_chunks_ms": float(timing.get("load_chunks_ms", 0) or 0),
        "rerank_ms": float(timing.get("rerank_ms", 0) or 0),
        "context_ms": float(timing.get("context_ms", 0) or 0),
        "ttft_ms": float(timing.get("ttft_ms", 0) or 0),
        "total_ms": float(timing.get("total_ms", 0) or 0),
        "embedding_cache": str(timing.get("embedding_cache", "miss")),
        "retrieval_cache": str(timing.get("retrieval_cache", "miss")),
    }


def _retrieval_total_ms(stage: dict[str, float]) -> float:
    """Retrieval pipeline total (embed + vector search + lexical load + rerank)."""
    return (
        stage["embedding_ms"] + stage["retrieval_ms"] + stage["load_chunks_ms"] + stage["rerank_ms"]
    )


def _keyword_kernel_ms(env: ChatEnv, query: str, *, top_k: int = 50) -> float:
    """Time the keyword-search CPU kernel (tokenize + IDF/UFF scoring + top-k)
    over the env's full corpus.  ``RagService`` does not separately instrument
    the keyword/RRF pass, so this measures the same code path directly."""
    chunks = [VectorSearchResult(chunk=c, score=0.5) for c in env.vector.chunks]
    t0 = time.perf_counter()
    keyword_search(query, chunks, top_k=top_k)
    return (time.perf_counter() - t0) * 1000.0


@pytest.mark.skipif(not RUN_BENCH, reason=BENCH_SKIP_REASON)
@pytest.mark.timeout(300)
async def test_retrieval_stage_latency_and_ttft() -> None:
    """N>=30 distinct miss queries: per-stage retrieval latency and synthetic
    end-to-end TTFT percentiles (fake generation client -> SYNTHETIC TTFT)."""
    env = _bench_env()
    await _build_topic_corpus(env, ACC_TENANT, SITE_A, 100)

    stages: dict[str, list[float]] = {
        "embedding_ms": [],
        "retrieval_ms": [],
        "load_chunks_ms": [],
        "context_ms": [],
        "ttft_ms": [],
        "total_ms": [],
        "retrieval_total_ms": [],
        "keyword_hybrid_ms": [],
    }
    for i in range(30):
        events = await _stream(
            env,
            tenant_id=ACC_TENANT,
            website_id=SITE_A,
            question=f"pricing documentation feature {i}",
        )
        st = _summary_from_done(_done_event(events))
        ret_tot = _retrieval_total_ms(st)
        stages["embedding_ms"].append(st["embedding_ms"])
        stages["retrieval_ms"].append(st["retrieval_ms"])
        stages["load_chunks_ms"].append(st["load_chunks_ms"])
        stages["context_ms"].append(st["context_ms"])
        stages["ttft_ms"].append(st["ttft_ms"])
        stages["total_ms"].append(st["total_ms"])
        stages["retrieval_total_ms"].append(ret_tot)
        stages["keyword_hybrid_ms"].append(
            _keyword_kernel_ms(env, f"pricing documentation feature {i}")
        )

    summary = {
        "embedding": _percentiles(stages["embedding_ms"]),
        "vector_search": _percentiles(stages["retrieval_ms"]),
        "lexical_load": _percentiles(stages["load_chunks_ms"]),
        "keyword_hybrid": _percentiles(stages["keyword_hybrid_ms"]),
        "context": _percentiles(stages["context_ms"]),
        "retrieval_total": _percentiles(stages["retrieval_total_ms"]),
        "e2e_total": _percentiles(stages["total_ms"]),
        "ttft_synthetic": _percentiles(stages["ttft_ms"]),
    }
    BENCHMARK_RESULTS["latency_miss"] = summary
    BENCHMARK_RESULTS["ttft"]["miss_synthetic"] = summary["ttft_synthetic"]
    assert stages["ttft_ms"][0] >= 0, "ttft sample missing"
    assert stages["total_ms"][-1] > 0, "total_ms sample missing"
    assert summary["e2e_total"]["n"] == 30


@pytest.mark.skipif(not RUN_BENCH, reason=BENCH_SKIP_REASON)
@pytest.mark.timeout(300)
async def test_cache_hit_vs_miss_latency() -> None:
    """F-02 retrieval-cache hit vs miss: per-stage delta and improvement."""
    env = _bench_env()
    await _build_topic_corpus(env, ACC_TENANT, SITE_A, 100)

    # Miss sample set: distinct queries (each a retrieval-cache miss).
    miss_stages: dict[str, list[float]] = {
        "retrieval_total": [],
        "embedding": [],
        "vector_search": [],
        "lexical_load": [],
        "e2e_total": [],
        "ttft": [],
    }
    for i in range(30):
        events = await _stream(
            env,
            tenant_id=ACC_TENANT,
            website_id=SITE_A,
            question=f"security documentation feature {i}",
        )
        st = _summary_from_done(_done_event(events))
        assert st["retrieval_cache"] == "miss"
        miss_stages["retrieval_total"].append(_retrieval_total_ms(st))
        miss_stages["embedding"].append(st["embedding_ms"])
        miss_stages["vector_search"].append(st["retrieval_ms"])
        miss_stages["lexical_load"].append(st["load_chunks_ms"])
        miss_stages["e2e_total"].append(st["total_ms"])
        miss_stages["ttft"].append(st["ttft_ms"])

    # Warm sample set: repeat the SAME query; first run seeds/evicts nothing in
    # F-02 (fresh env), the following N runs are retrieval-cache hits.
    seed = await _stream(
        env, tenant_id=ACC_TENANT, website_id=SITE_A, question="billing documentation feature 10"
    )
    assert _summary_from_done(_done_event(seed))["retrieval_cache"] == "miss"
    hit_stages: dict[str, list[float]] = {
        "retrieval_total": [],
        "embedding": [],
        "vector_search": [],
        "lexical_load": [],
        "e2e_total": [],
        "ttft": [],
    }
    for _ in range(30):
        events = await _stream(
            env,
            tenant_id=ACC_TENANT,
            website_id=SITE_A,
            question="billing documentation feature 10",
        )
        st = _summary_from_done(_done_event(events))
        assert st["retrieval_cache"] == "hit", "expected F-02 cache hit"
        assert st["embedding_ms"] == 0 and st["retrieval_ms"] == 0 and st["load_chunks_ms"] == 0
        hit_stages["retrieval_total"].append(_retrieval_total_ms(st))
        hit_stages["embedding"].append(st["embedding_ms"])
        hit_stages["vector_search"].append(st["retrieval_ms"])
        hit_stages["lexical_load"].append(st["load_chunks_ms"])
        hit_stages["e2e_total"].append(st["total_ms"])
        hit_stages["ttft"].append(st["ttft_ms"])

    miss = {k: _percentiles(v) for k, v in miss_stages.items()}
    hit = {k: _percentiles(v) for k, v in hit_stages.items()}
    BENCHMARK_RESULTS["cache"] = {"miss": miss, "hit": hit}
    BENCHMARK_RESULTS["ttft"]["hit_synthetic"] = hit["ttft"]
    assert hit["retrieval_total"]["n"] == 30 and miss["retrieval_total"]["n"] == 30


@pytest.mark.skipif(not RUN_BENCH, reason=BENCH_SKIP_REASON)
@pytest.mark.timeout(300)
async def test_rerank_latency_when_enabled() -> None:
    """Reranking latency (deployment default enable_reranking=True) measured
    with the deterministic embedding reranker (stored embeddings, no API)."""
    # Rebuild RagService with allow_reranking=True (build_chat_env helper
    # passes reranker=False by default; production enables reranking) and
    # insert the corpus into that env's own repositories.
    rerank_env = build_chat_env(top_k=5, reranker=True)
    install_relevance_scoring(rerank_env)
    rerank_env.rag._confidence_check_enabled = False
    rerank_env.rag._timing_enabled = True
    await _build_topic_corpus(rerank_env, ACC_TENANT, SITE_A, 100)

    rerank_ms: list[float] = []
    for i in range(30):
        events = await _stream(
            rerank_env,
            tenant_id=ACC_TENANT,
            website_id=SITE_A,
            question=f"analytics documentation feature {i}",
        )
        st = _summary_from_done(_done_event(events))
        rerank_ms.append(st["rerank_ms"])
    BENCHMARK_RESULTS["rerank"] = {
        "config": "allow_reranking=True (embedding stored, fake embedder)",
        "rerank_ms": _percentiles(rerank_ms),
        "note": "SYNTHETIC: stored chunk embeddings are zero vectors; real "
        "provider embeddings would change absolute values.",
    }
    assert len(rerank_ms) == 30


@pytest.mark.skipif(not RUN_BENCH, reason=BENCH_SKIP_REASON)
@pytest.mark.timeout(600)
async def test_corpus_scale_retrieval_latency() -> None:
    """Retrieval latency across corpus sizes (100/500/1K/5K), N samples each."""
    sizes = [100, 500, 1000, 5000]
    for size in sizes:
        env = _bench_env()
        await _build_topic_corpus(env, ACC_TENANT, SITE_A, size)
        load_ms: list[float] = []
        ret_total: list[float] = []
        e2e_total: list[float] = []
        keyword_ms: list[float] = []
        for i in range(30):
            events = await _stream(
                env,
                tenant_id=ACC_TENANT,
                website_id=SITE_A,
                question=f"integration deployment documentation feature {i}",
            )
            st = _summary_from_done(_done_event(events))
            load_ms.append(st["load_chunks_ms"])
            ret_total.append(_retrieval_total_ms(st))
            e2e_total.append(st["total_ms"])
            keyword_ms.append(
                _keyword_kernel_ms(env, query=f"integration deployment documentation feature {i}")
            )
        BENCHMARK_RESULTS["scale"][str(size)] = {
            "lexical_load": _percentiles(load_ms),
            "keyword_hybrid": _percentiles(keyword_ms),
            "retrieval_total": _percentiles(ret_total),
            "e2e_total": _percentiles(e2e_total),
        }


async def test_export_benchmark_results_json() -> None:
    """Dump collected benchmark samples for the report step (no production
    writes; artifact lands in /tmp/opencode)."""
    path = "/tmp/opencode/rag_accuracy_bench_results.json"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    handle = await asyncio.get_running_loop().run_in_executor(
        None,
        lambda: open(path, "w", encoding="utf-8"),  # noqa: ASYNC230
    )
    with handle:
        json.dump(BENCHMARK_RESULTS, handle, indent=2, sort_keys=True)
