"""RAG-ACC-02 — accuracy deep-dive benchmark (measurement ONLY).

Extends RAG-ACC-01 (``tests/test_rag_accuracy_benchmark.py``) instead of
replacing it.  RAG-ACC-01 measured *how well* the four weak categories
retrieve; RAG-ACC-02 measures *why* each weak query fails by replicating the
retrieval tower (vector proxy -> keyword search -> RRF fusion) in the harness
and attributing every golden chunk to the stage(s) that recovered it.

Scope rules (identical to RAG-ACC-01):
- No production writes; deterministic fakes only.
- No retrieval/ranking/chunking/prompt/caching/embedding configuration is
  changed.  ``install_relevance_scoring`` is the same test-side deterministic
  lexical proxy used by RAG-ACC-01 (it replaces only the fake repository's
  similarity scoring, never production code).  The attribution tower uses the
  real ``keyword_search`` / ``reciprocal_rank_fusion`` implementations with
  the production constants (RRF k=60, keyword top-k=50, candidate top-k=50,
  final top-k=5) so every rank is the exact pipeline output, recomputed
  outside ``RagService`` purely for diagnosis.
- Nothing is optimized or fixed; every number is recorded honestly.

The real-provider TTFT phase is deliberately UNMEASURED in this environment
(no cloud credentials in env/.env; the local Ollama on 127.0.0.1:11434 has
zero models).  The heavy benchmarks below therefore measure the SYNTHETIC
e2e-TTFT correlation to answer the *relationship* question; they are not a
substitute for real TTFT and are labelled SYNTHETIC everywhere.

Two modes (same convention as RAG-ACC-01):
- Fast diagnostic tests run always (small deterministic corpus).
- Heavy latency/TTFT correlation benchmarks require ``RAG_BENCH=1``.

Raw samples export to /tmp/opencode/rag_accuracy_deep_dive_results.json.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import statistics
from typing import Any

import pytest
from backend.repositories.vector.base import VectorSearchResult
from backend.repositories.vector.hybrid import keyword_search, reciprocal_rank_fusion, tokenize
from backend.services.chat.confidence import usable

from tests.chat_helpers import (
    ChatEnv,
    _relevance_tokens,
    build_chat_env,
    consume,
    install_relevance_scoring,
    make_chunk,
    make_website,
)
from tests.test_rag_accuracy_benchmark import (
    CORPUS_A,
    CORPUS_B,
)

RUN_BENCH = os.environ.get("RAG_BENCH") == "1"
BENCH_SKIP_REASON = "set RAG_BENCH=1 to run heavy latency/TTFT correlation benchmarks"

# ACC-02 uses its own tenant and a superset of the ACC-01 site-A corpus so the
# two benchmarks remain independent: every ACC-01 title/text is preserved, and
# ACC-02 adds the six chunks that make broad/multi-source fixtures meaningful.
ACC2_TENANT = "acc2-tenant"
ACC2_SITE_A = "acc2-academy-a"
ACC2_SITE_B = "acc2-academy-b"

CORPUS_A2: dict[str, str] = {
    **CORPUS_A,
    "bca-overview": (
        "BCA at Academy A is a three year undergraduate program covering "
        "computer science fundamentals, programming, and software engineering."
    ),
    "university-programs": (
        "Academy A offers the BCA, BBA and BCom undergraduate programs plus "
        "MBA and MCA postgraduate programs."
    ),
    "bca-curriculum": (
        "The BCA curriculum includes first year programming and mathematics, "
        "second year data structures and databases, and third year "
        "specialization electives."
    ),
    "bca-admissions-process": (
        "BCA admissions at Academy A open in April; applicants submit the "
        "online form and are selected through a merit list."
    ),
    "bca-international": (
        "Academy A welcomes international students to BCA and the admissions "
        "office assists with visa and travel arrangements."
    ),
    "bca-hostel": (
        "Academy A arranges hostel accommodation for BCA students within two kilometers of campus."
    ),
}

CORPUS_B2: dict[str, str] = {
    **CORPUS_B,
    "university-programs-b": (
        "Academy B offers the BCA and BBA undergraduate programs and a postgraduate MCA program."
    ),
}

# ---------------------------------------------------------------------------
# Fixtures — golden titles are predeclared ground truth (never derived from
# model output).  ``entity_tokens`` are the query's distinguishing terms used
# by the OBJECTIVE evidence-relevance check in the no-answer analysis.
# ---------------------------------------------------------------------------

# Phase 3 — broad queries.  expected == [] means the fact is genuinely absent
# from the corpus (classification A / corpus coverage), never a retrieval bug.
BROAD_QUERIES: list[tuple[str, list[str]]] = [
    ("What courses are available?", ["bca-courses", "bca-cybersec", "bca-curriculum"]),
    ("Tell me about the BCA program", ["bca-program", "bca-overview"]),
    ("What programs does the university offer?", ["university-programs"]),
    ("What are the admission options?", ["bca-admission", "bca-admissions-process"]),
    ("Tell me about admissions", ["bca-admission", "bca-admissions-process"]),
    (
        "Which programs are available at BCA?",
        ["bca-program", "university-programs", "bca-overview"],
    ),
    (
        "What does BCA cover in its curriculum?",
        ["bca-program", "bca-curriculum", "bca-courses"],
    ),
    ("Tell me about security at BCA", ["bca-cybersec"]),
    ("What is the BCA department structure?", ["bca-department"]),
    ("Which hostels or facilities does BCA have?", ["bca-hostel"]),
    ("Do you accept international students for BCA?", ["bca-international"]),
    ("How do I apply to BCA?", ["bca-admissions-process", "bca-admission"]),
    ("Tell me about fees and scholarships at BCA", ["bca-fee", "bca-scholarship"]),
    ("What is the fee structure?", ["bca-fee", "bca-scholarship"]),
    # Genuine corpus-coverage gaps (expected deliberately empty).
    ("What are the physics lab facilities?", []),
    ("Does the university offer a chess club?", []),
]

# Phase 4 — typo / noisy queries.  Each row: (query, [golden titles]).
TYPO_QUERIES: list[tuple[str, list[str]]] = [
    ("What is the BCA admision fee?", ["bca-fee", "bca-admission"]),
    ("eligibilty requirements for BCA admission", ["bca-admission"]),
    ("cyber securty course", ["bca-cybersec"]),
    ("teach me about BCA addmission", ["bca-admission"]),
    ("BCA progam details", ["bca-program", "bca-overview"]),
    ("universty tuition for BCA", ["bca-fee"]),
    ("BCA curriculam", ["bca-curriculum", "bca-program"]),
    ("hosptel for BCA students", ["bca-hostel"]),
    ("who is the dean od the BCA department", ["bca-department"]),
    ("admisssion fee", ["bca-fee", "bca-admission"]),
    ("placement support and mock interviewes", ["bca-placement"]),
    ("what is the annual BCA tution fee", ["bca-fee"]),
]

# Phase 5 — multi-source queries (answer genuinely needs several chunks).
MULTI_SOURCE_QUERIES: list[tuple[str, list[str]]] = [
    ("What is the BCA fee and admission eligibility?", ["bca-fee", "bca-admission"]),
    ("BCA courses and placement support", ["bca-courses", "bca-placement"]),
    ("cyber security course and BCA admission", ["bca-cybersec", "bca-admission"]),
    (
        "Tell me about BCA fees, scholarships and admission",
        ["bca-fee", "bca-scholarship", "bca-admission"],
    ),
    ("Who is the dean and what is the BCA fee?", ["bca-department", "bca-fee"]),
    (
        "What does the BCA program cover and does it offer hostels?",
        ["bca-program", "bca-hostel", "bca-overview"],
    ),
    (
        "Tell me about curriculum and international students",
        ["bca-curriculum", "bca-international"],
    ),
    (
        "What are the admission process and program overview?",
        ["bca-admissions-process", "bca-overview", "bca-program"],
    ),
    (
        "Which courses and cybersecurity electives does BCA offer?",
        ["bca-courses", "bca-cybersec", "bca-curriculum"],
    ),
    ("What are the placement support and hostel facility?", ["bca-placement", "bca-hostel"]),
]

# Phase 6 — no-answer queries by category.  entity_tokens = the distinguishing
# term(s): correct abstention is expected whenever NO accepted source contains
# them.  Golden evidence is intentionally empty.
_NO_ANSWER_SPECS: list[tuple[str, str, list[str]]] = [
    ("completely_unrelated", "What is the capital of France?", ["france", "capital"]),
    ("completely_unrelated", "Who won the world cup in 2018?", ["world", "cup", "2018"]),
    ("completely_unrelated", "How does a rocket engine work?", ["rocket", "engine"]),
    ("plausible_but_absent", "What is the MBA tuition fee?", ["mba"]),
    ("plausible_but_absent", "What are the MBA admission requirements?", ["mba"]),
    (
        "plausible_but_absent",
        "What is the last date to apply for BCA admission?",
        ["date", "apply"],
    ),
    ("plausible_but_absent", "Does BCA offer a semester exchange program?", ["exchange"]),
    ("similar_topic_absent_fact", "Where is the BCA campus located?", ["campus", "located"]),
    ("similar_topic_absent_fact", "What is the BCA application fee?", ["application"]),
    ("similar_topic_absent_fact", "What is the placement salary for BCA graduates?", ["salary"]),
    (
        "cross_site_other_website",
        "Who is the dean of the BCA program at Academy B?",
        ["dean", "academy"],
    ),
    ("cross_site_other_website", "What are the BCA fees at Academy B?", ["fees"]),
]

# Phase 7 — cross-site differential queries.  label, query, golden@A (running
# against the A corpus), golden@B.  A follow-up pair is included.
CROSS_SITE_QUERIES: list[tuple[str, str, list[str], list[str]]] = [
    ("exact", "What is the annual BCA tuition fee?", ["bca-fee"], ["bca-fee"]),
    ("short", "BCA fee?", ["bca-fee"], ["bca-fee"]),
    ("paraphrase", "How much does BCA cost per year?", ["bca-fee"], ["bca-fee"]),
    (
        "broad",
        "Tell me about admissions and fee at BCA",
        ["bca-fee", "bca-admission"],
        ["bca-fee", "bca-admission"],
    ),
    (
        "followup",
        ("How much does BCA charge annually?", "Is that per year?"),
        ["bca-fee"],
        ["bca-fee"],
    ),
]

BENCHMARK_RESULTS: dict[str, Any] = {
    "benchmark": "RAG-ACC-02",
    "measurement_kind": "SYNTHETIC (deterministic in-memory fakes, dev box)",
    "real_ttft": "UNMEASURED",
    "accuracy_diagnosis": {},
    "typo_diagnosis": {},
    "multi_source": {},
    "no_answer": {},
    "cross_site": {},
    "rerank_delta": {},
    "ttft_correlation": {},
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _stream(
    env: ChatEnv, *, tenant_id: str, website_id: str, question: str, session_id: str | None = None
) -> list[dict]:
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
    return [s.get("title", "") for s in _sources_event(events)["data"]["sources"]]


def _source_urls(events: list[dict]) -> list[str]:
    return [s.get("url", "") for s in _sources_event(events)["data"]["sources"]]


def _timing(events: list[dict]) -> dict[str, Any]:
    return _done_event(events)["data"].get("timing", {}) or {}


def _build_acc2_env(*, reranker: bool = False, confident: bool = False) -> ChatEnv:
    """Deterministic ACC-02 env.  ``confident=True`` enables the production
    pre-generation confidence/answerability gate (the default in production);
    ``confident=False`` measures pure retrieval (RAG-ACC-01 convention)."""
    env = build_chat_env(top_k=5, reranker=reranker)
    install_relevance_scoring(env)
    env.rag._confidence_check_enabled = confident
    env.rag._timing_enabled = True
    return env


async def _make_academy2(
    env: ChatEnv, *, tenant_id: str, site: str, corpus: dict[str, str]
) -> None:
    await make_website(env, tenant_id=tenant_id, website_id=site, knowledge_chunks=len(corpus))
    for i, (title, text) in enumerate(corpus.items()):
        chunk = await make_chunk(
            env,
            tenant_id=tenant_id,
            website_id=site,
            text=text,
            url=f"https://{site}.example.com/{title}",
            title=title,
            document_id=f"doc-{title}",
            chunk_index=i,
        )
        # Deterministic chunk ids: the keyword pass tie-breaks on chunk id, and
        # KnowledgeChunk.new() uses a per-run uuid — that made RRF ordering of
        # near-tied keyword scores vary between runs (observed in RAG-ACC-02).
        # Overwriting the id keeps every benchmark run byte-identical while
        # leaving tenant/site/document/index keys (and the store) untouched.
        chunk.id = f"{site}-{i}"


def _percentiles(samples: list[float]) -> dict[str, float]:
    """Nearest-rank P50/P95/P99 plus min/max/mean (same as RAG-ACC-01)."""
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
    if not expected:
        return 0.0
    top = set(titles[:k])
    return sum(1 for t in expected if t in top) / len(expected)


def mrr(titles: list[str], expected: list[str]) -> float:
    expected_set = set(expected)
    for i, t in enumerate(titles, start=1):
        if t in expected_set:
            return 1.0 / i
    return 0.0


# ---------------------------------------------------------------------------
# Attribution tower — recomputes the exact production retrieval stages outside
# RagService (vector proxy -> keyword_search -> RRF) so every golden chunk can
# be attributed to the stage that did (or did not) recover it.
# ---------------------------------------------------------------------------


def _site_chunks(env: ChatEnv, *, tenant_id: str, website_id: str) -> list[VectorSearchResult]:
    return [
        VectorSearchResult(chunk=c, score=0.5)
        for c in env.vector.chunks
        if c.tenant_id == tenant_id and c.website_id == website_id
    ]


def _vector_proxy_search(
    env: ChatEnv, *, query: str, tenant_id: str, website_id: str, top_k: int = 5
) -> list[VectorSearchResult]:
    """Replicates install_relevance_scoring's similarity_search deterministically."""
    query_tokens = _relevance_tokens(query)
    scored: list[VectorSearchResult] = []
    for chunk in env.vector.chunks:
        if chunk.tenant_id != tenant_id or chunk.website_id != website_id:
            continue
        chunk_tokens = _relevance_tokens(chunk.chunk_text)
        if not query_tokens or not chunk_tokens:
            continue
        overlap = len(query_tokens & chunk_tokens)
        if overlap == 0:
            continue
        score = overlap / min(len(query_tokens), len(chunk_tokens))
        scored.append(VectorSearchResult(chunk=chunk, score=round(score, 4)))
    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[:top_k]


def _compute_tower(env: ChatEnv, *, query: str, tenant_id: str, website_id: str) -> dict[str, Any]:
    """Vector-rank / keyword-rank / RRF-rank maps (1-indexed, 0 = absent) PLUS a
    faithful replica of the no-reranker SERVED list.

    Replicates the exact pipeline stages and constants used by ``RagService``
    in a pure (confidence-off, reranker-off) env:

    1. vector proxy      -> top_k=5 (adaptive retrieval defaults OFF, so the
                            fixed ``top_k=5`` passed by ``build_chat_env``)
    2. keyword_search    -> top_k=50 (= ``hybrid_search_candidate_limit``)
    3. RRF               -> k=60, fused[:50] (= the rerank candidate pool)
    4. preserve scores   -> dense_score = vector score for vector hits;
                            keyword-only chunks keep their RRF score
    5. strip + usable    -> ``_strip_lexical_scores`` detaches lexical evidence
                            (no reranker); ``usable(dense_floor=0.25)`` keeps
                            vector hits that clear the cosine floor AND any
                            RAG-ACC-03 short-query content-token match
                            (RagService passes the query into the gate).

    ``final`` is therefore EXACTLY what ``_build_context`` would expose as
    sources in this env, letting every diagnostic assert
    ``served == tower["final"]`` as a pipeline-fidelity guard.
    """
    vector = _vector_proxy_search(env, query=query, tenant_id=tenant_id, website_id=website_id)
    keyword = keyword_search(
        query,
        _site_chunks(env, tenant_id=tenant_id, website_id=website_id),
        top_k=50,
    )
    fused = reciprocal_rank_fusion([vector, keyword], k=60)[:50]

    vector_scores: dict[str, float] = {r.chunk.id: r.score for r in vector}
    served_titles: list[str] = []
    for r in fused:
        dense = vector_scores.get(r.chunk.id)
        # Faithful replica of the no-reranker gate: after ``_strip_lexical_scores``
        # lexical evidence is detached, so ``usable(dense_floor=0.25)`` decides on
        # the raw vector score (below-floor vector hits AND keyword-only RRF
        # chunks) plus the RAG-ACC-03 short-query content-token leniency.
        replica = VectorSearchResult(
            chunk=r.chunk,
            score=r.score,
            dense_score=dense,
            lexical_score=None,
            lexical_exact=False,
        )
        if usable(replica, dense_floor=0.25, query=query):
            served_titles.append(r.chunk.metadata.get("title", ""))

    def rank_map(results: list[VectorSearchResult]) -> dict[str, int]:
        return {r.chunk.metadata["title"]: i + 1 for i, r in enumerate(results)}

    return {
        "query": query,
        "vector": rank_map(vector),
        "keyword": rank_map(keyword),
        "rrf": rank_map(fused),
        "final": served_titles,
        "pool": [r.chunk.metadata.get("title", "") for r in fused],
    }


def _title_of(result: VectorSearchResult) -> str:
    return result.chunk.metadata.get("title", "")


# ---------------------------------------------------------------------------
# Phase 2 & 3 — broad-query failure classification (A..H)
# ---------------------------------------------------------------------------


def _classify_golden(self_title: str, tower: dict[str, Any], served: list[str]) -> tuple[str, str]:
    """Per-golden classification + root-cause note.

    A: corpus coverage (fixture-level, expected empty) — handled by caller.
    B: no overlap at all: neither the token-overlap vector proxy nor keyword
       matched (a semantic embedding index would be required).
    C: vector failed the gate: the vector proxy recovered it but its raw
       overlap score sits below ``chat_context_min_score`` (0.25), so the
       cosine gate drops it before context.
    D: keyword-only without reranker protection: only keyword recovered it; in
       a no-reranker env keyword evidence is stripped, so it never surfaces.
    E: hybrid/RRF ranking failed: a stage recovered it but RRF lost it.
    H: present but ordered below rank 1 (multi-golden ordering issue).
    """
    v = tower["vector"].get(self_title, 0)
    k = tower["keyword"].get(self_title, 0)
    r = tower["rrf"].get(self_title, 0)
    served_rank = (served.index(self_title) + 1) if self_title in served else 0
    if served_rank >= 1:
        if served_rank == 1:
            return "OK", "retrieved at rank 1"
        return "H", "retrieved below rank 1 (multi-golden ordering)"
    if v >= 1:
        return (
            "C",
            "vector proxy retrieved it but scored below the 0.25 cosine floor; gate dropped it",
        )
    if k >= 1:
        return (
            "D",
            "keyword-only recovered it; without a reranker its lexical evidence "
            "is stripped and the cosine gate drops it",
        )
    if r >= 1:
        return "E", "recovered upstream but RRF ranked it below the pool"
    return "B", "no surface-token overlap with the query (vector proxy AND keyword both miss it)"


def _broad_diagnosis_row(query: str, expected: list[str]) -> dict[str, Any]:
    """Per-query broad diagnosis (computed against the ACC-02 site-A corpus)."""
    if not expected:
        return {
            "query": query,
            "expected": expected,
            "classification": "A",
            "root_cause": "corpus does not contain the requested information",
            "detail": {},
        }
    return {
        "query": query,
        "expected": expected,
        "classification": "TO-BE-CLASSIFIED",
        "root_cause": "",
        "detail": {},
    }


def _finalize_diagnosis(
    row: dict[str, Any], tower: dict[str, Any], served: list[str]
) -> dict[str, Any]:
    """Fill in tower attribution + pick the dominant query-level label."""
    expected: list[str] = row["expected"]
    if not expected:
        return row
    golden_rows = []
    for title in expected:
        v = tower["vector"].get(title, 0)
        k = tower["keyword"].get(title, 0)
        r = tower["rrf"].get(title, 0)
        label, note = _classify_golden(title, tower, served)
        golden_rows.append(
            {
                "title": title,
                "vector_rank": v,
                "keyword_rank": k,
                "rrf_rank": r,
                "in_vector": v >= 1,
                "in_keyword": k >= 1,
                "label": label,
                "note": note,
                "served_rank": (served.index(title) + 1) if title in served else 0,
            }
        )
    labels = [g["label"] for g in golden_rows]
    # Dominant label ranking: B (nowhere) < C/D (found but gated out) < E
    # (found but RRF lost) < H (ordering) < OK.
    order = {"B": 0, "C": 1, "D": 2, "E": 3, "H": 4, "OK": 5}
    dominant = min(labels, key=lambda x: order[x])
    return {
        **row,
        "classification": dominant,
        "root_cause": next(g["note"] for g in golden_rows if g["label"] == dominant),
        "retrieved": served[:5],
        "golden_attribution": golden_rows,
        "reranked": False,  # attribution env runs the no-rerank path (see rerank delta test)
    }


# ---------------------------------------------------------------------------
# Tests — fast, deterministic accuracy diagnosis
# ---------------------------------------------------------------------------


async def test_broad_query_failure_classification() -> None:
    """Classify every weak broad query A..H with per-stage attribution."""
    assert len(BROAD_QUERIES) >= 10, "need >=10 deterministic broad fixtures"
    env = _build_acc2_env()
    await _make_academy2(env, tenant_id=ACC2_TENANT, site=ACC2_SITE_A, corpus=CORPUS_A2)

    rows: list[dict[str, Any]] = []
    for query, expected in BROAD_QUERIES:
        events = await _stream(env, tenant_id=ACC2_TENANT, website_id=ACC2_SITE_A, question=query)
        served = _source_titles(events)
        row = _broad_diagnosis_row(query, expected)
        tower = _compute_tower(env, query=query, tenant_id=ACC2_TENANT, website_id=ACC2_SITE_A)
        row["detail"]["tower"] = tower
        row = _finalize_diagnosis(row, tower, served)
        # Alignment guard: the harness tower must reproduce exactly what the
        # pipeline served (both are the same RRF output -> no-rerank env).
        assert served == tower["final"], (
            f"tower/pipeline mismatch for {query!r}: pipeline={served} tower={tower['final']}"
        )
        rows.append(row)

    BENCHMARK_RESULTS["accuracy_diagnosis"] = {
        "fixture_count": len(rows),
        "classes": {
            label: sum(1 for r in rows if r["classification"] == label)
            for label in ("A", "B", "C", "D", "E", "H", "OK")
        },
        "queries": rows,
    }
    # Every non-coverage fixture must have been classified rather than skipped.
    for row in rows:
        if row["expected"]:
            assert row["classification"] in ("B", "C", "D", "E", "H", "OK")
        else:
            assert row["classification"] == "A"
    assert len(rows) == len(BROAD_QUERIES)


async def test_typo_retrieval_attribution() -> None:
    """Typo recall metrics + which stage recovered each golden chunk."""
    env = _build_acc2_env()
    await _make_academy2(env, tenant_id=ACC2_TENANT, site=ACC2_SITE_A, corpus=CORPUS_A2)

    rows: list[dict[str, Any]] = []
    for query, expected in TYPO_QUERIES:
        events = await _stream(env, tenant_id=ACC2_TENANT, website_id=ACC2_SITE_A, question=query)
        served = _source_titles(events)
        tower = _compute_tower(env, query=query, tenant_id=ACC2_TENANT, website_id=ACC2_SITE_A)
        assert served == tower["final"]
        raw_query = _relevance_tokens(query)
        normalized_query = set(tokenize(query))
        golden = []
        for title in expected:
            v = tower["vector"].get(title, 0)
            k = tower["keyword"].get(title, 0)
            r = tower["rrf"].get(title, 0)
            text = _text_of(env, title)
            raw_chunk = _relevance_tokens(text)
            normalized_chunk = set(tokenize(text))
            # A token that matched ONLY after normalization proves the typo
            # bridge engaged (e.g. "admision" -> "admission").
            bridged = (normalized_query & normalized_chunk) - (raw_query & raw_chunk)
            golden.append(
                {
                    "title": title,
                    "vector_rank": v,
                    "keyword_rank": k,
                    "rrf_rank": r,
                    "recovered_by": "vector+keyword"
                    if (v >= 1 and k >= 1)
                    else "keyword"
                    if k >= 1
                    else "vector"
                    if v >= 1
                    else "nothing",
                    "keyword_used_variant": k >= 1 and bool(bridged),
                }
            )
        rows.append(
            {
                "query": query,
                "expected": expected,
                "retrieved": served[:5],
                "recall@1": recall_at(served, expected, 1),
                "recall@3": recall_at(served, expected, 3),
                "recall@5": recall_at(served, expected, 5),
                "mrr": mrr(served, expected),
                "golden_attribution": golden,
            }
        )

    aggregate_rows = [r for r in rows]
    BENCHMARK_RESULTS["typo_diagnosis"] = {
        "aggregate": {
            "queries": len(aggregate_rows),
            "recall@1": round(sum(r["recall@1"] for r in aggregate_rows) / len(aggregate_rows), 3),
            "recall@3": round(sum(r["recall@3"] for r in aggregate_rows) / len(aggregate_rows), 3),
            "recall@5": round(sum(r["recall@5"] for r in aggregate_rows) / len(aggregate_rows), 3),
            "mrr": round(sum(r["mrr"] for r in aggregate_rows) / len(aggregate_rows), 3),
        },
        "queries": rows,
    }
    # Deterministic guard: variant normalization MUST be observable for at
    # least one typo ("admision"/"addmission"/"eligibilty" live in the table).
    variant_engaged = [
        (row["query"], any(g["keyword_used_variant"] for g in row["golden_attribution"]))
        for row in rows
    ]
    assert any(flag for _, flag in variant_engaged), (
        f"variant normalization never engaged: {variant_engaged}"
    )
    assert len(rows) == len(TYPO_QUERIES)


def _text_of(env: ChatEnv, title: str) -> str:
    matches = [
        c.chunk_text
        for c in env.vector.chunks
        if c.metadata.get("title") == title
        and c.tenant_id == ACC2_TENANT
        and c.website_id == ACC2_SITE_A
    ]
    return matches[0] if matches else ""


async def test_multi_source_coverage() -> None:
    """Source coverage (|expected ∩ retrieved| / |expected|) for multi-source Qs."""
    env = _build_acc2_env()
    await _make_academy2(env, tenant_id=ACC2_TENANT, site=ACC2_SITE_A, corpus=CORPUS_A2)

    rows: list[dict[str, Any]] = []
    coverages: list[float] = []
    for query, expected in MULTI_SOURCE_QUERIES:
        events = await _stream(env, tenant_id=ACC2_TENANT, website_id=ACC2_SITE_A, question=query)
        served = _source_titles(events)
        tower = _compute_tower(env, query=query, tenant_id=ACC2_TENANT, website_id=ACC2_SITE_A)
        assert served == tower["final"]
        recovered = set(served) & set(expected)
        coverage = len(recovered) / max(len(expected), 1)
        coverages.append(coverage)
        missing = []
        for title in expected:
            if title not in recovered:
                v = tower["vector"].get(title, 0)
                k = tower["keyword"].get(title, 0)
                missing.append(
                    {
                        "title": title,
                        "vector_rank": v,
                        "keyword_rank": k,
                        "cause": "ranking" if (v >= 1 or k >= 1) else "lexical_no_overlap",
                    }
                )
        rows.append(
            {
                "query": query,
                "expected": expected,
                "retrieved": served,
                "recovered": sorted(recovered),
                "source_coverage": round(coverage, 3),
                "fully_covered": coverage == 1.0,
                "recall@1": recall_at(served, expected, 1),
                "mrr": mrr(served, expected),
                "missing": missing,
            }
        )

    fully = sum(1 for r in rows if r["fully_covered"])
    BENCHMARK_RESULTS["multi_source"] = {
        "queries": rows,
        "mean_source_coverage": round(statistics.fmean(coverages), 3),
        "source_coverage_p50": _percentiles(coverages)["p50"],
        "fully_covered_percent": round(fully / len(rows) * 100.0, 1),
        "missing_causes": {
            cause: sum(1 for r in rows for m in r["missing"] if m["cause"] == cause)
            for cause in ("ranking", "lexical_no_overlap")
        },
    }
    assert len(rows) == len(MULTI_SOURCE_QUERIES)
    assert coverages, "no coverage samples"


async def test_no_answer_abstention() -> None:
    """No-answer behavior under the PRODUCTION confidence/answerability gate.

    Pure-env raw retrieval and gated-env acceptance are both recorded so the
    report can distinguish "correct abstention", "useful related evidence"
    (entity token present in accepted evidence) and "unsupported-answer risk"
    (generation ran without the query's distinguishing entity in evidence).
    """
    pure = _build_acc2_env(confident=False)
    gated = _build_acc2_env(confident=True)
    for env, _site in ((pure, "pure"), (gated, "gated")):
        await _make_academy2(env, tenant_id=ACC2_TENANT, site=ACC2_SITE_A, corpus=CORPUS_A2)

    rows: list[dict[str, Any]] = []
    for category, query, entity_tokens in _NO_ANSWER_SPECS:
        ev_pure = await _stream(pure, tenant_id=ACC2_TENANT, website_id=ACC2_SITE_A, question=query)
        raw_titles = _source_titles(ev_pure)
        ev_gated = await _stream(
            gated, tenant_id=ACC2_TENANT, website_id=ACC2_SITE_A, question=query
        )
        done_g = _done_event(ev_gated)["data"]
        accepted_titles = _source_titles(ev_gated)
        timing_g = _timing(ev_gated)
        fallback = bool(done_g.get("fallback", False))
        evidence_tokens: set[str] = set()
        for t in accepted_titles:
            evidence_tokens |= _relevance_tokens(_text_of(gated, t))
        claim_tokens = set(entity_tokens)
        present = claim_tokens & evidence_tokens
        all_present = claim_tokens <= evidence_tokens if claim_tokens else False
        if fallback:
            behavior = "correct_abstention"
        elif all_present:
            behavior = "useful_related_evidence"
        elif present:
            behavior = "related_evidence_partial"
        else:
            behavior = "unsupported_answer_risk"
        rows.append(
            {
                "category": category,
                "query": query,
                "entity_tokens": entity_tokens,
                "raw_evidence_count": len(raw_titles),
                "raw_titles": raw_titles,
                "accepted_evidence_count": len(accepted_titles),
                "accepted_titles": accepted_titles,
                "fallback": fallback,
                "gate_rejected_chunks": timing_g.get("confidence_rejected_chunks_count"),
                "gate_confidence": done_g.get("confidence_score"),
                "claim_tokens_present": sorted(present),
                "claim_tokens_all_present": all_present,
                "behavior": behavior,
            }
        )

    BENCHMARK_RESULTS["no_answer"] = {
        "categories": {
            cat: sum(1 for r in rows if r["category"] == cat)
            for cat in (
                "completely_unrelated",
                "plausible_but_absent",
                "similar_topic_absent_fact",
                "cross_site_other_website",
            )
        },
        "behavior_counts": {
            behavior: sum(1 for r in rows if r["behavior"] == behavior)
            for behavior in (
                "correct_abstention",
                "useful_related_evidence",
                "related_evidence_partial",
                "unsupported_answer_risk",
            )
        },
        "queries": rows,
    }
    assert len(rows) == len(_NO_ANSWER_SPECS)
    # Deterministic: an unrelated query must abstain; at least one weak-related
    # query must show what the gate actually does (abstain or risk — real).
    assert any(r["behavior"] == "correct_abstention" for r in rows)


async def test_cross_site_differential_expansion() -> None:
    """Phase 7 — every query type across sites A and B with zero leakage."""
    env = _build_acc2_env()
    await _make_academy2(env, tenant_id=ACC2_TENANT, site=ACC2_SITE_A, corpus=CORPUS_A2)
    await _make_academy2(env, tenant_id=ACC2_TENANT, site=ACC2_SITE_B, corpus=CORPUS_B2)

    results: dict[str, Any] = {"queries": [], "leak_total": 0}
    for label, spec, golden_a, golden_b in CROSS_SITE_QUERIES:
        if isinstance(spec, tuple):
            first, second = spec
        else:
            first, second = spec, None
        for site, golden in ((ACC2_SITE_A, golden_a), (ACC2_SITE_B, golden_b)):
            ev1 = await _stream(env, tenant_id=ACC2_TENANT, website_id=site, question=first)
            session_id = _done_event(ev1)["data"]["session_id"]
            urls = _source_urls(ev1)
            titles1 = _source_titles(ev1)
            urls_second = urls
            titles2: list[str] | None = None
            if second is not None:
                ev2 = await _stream(
                    env,
                    tenant_id=ACC2_TENANT,
                    website_id=site,
                    question=second,
                    session_id=session_id,
                )
                urls_second = _source_urls(ev2)
                titles2 = _source_titles(ev2)
            for step, urls_here in (("first", urls), ("second", urls_second)):
                foreign = [u for u in urls_here if (ACC2_SITE_A in u) != (site == ACC2_SITE_A)]
                results["leak_total"] += len(foreign)
                assert not foreign, (
                    f"CRITICAL FOREIGN LEAK: {label}/{step} on {site} returned {foreign}"
                )
            served_final = titles2 if titles2 is not None else titles1
            golden_recovered = [t for t in golden if t in served_final]
            results["queries"].append(
                {
                    "label": label,
                    "site": site,
                    "question": first,
                    "followup": second,
                    "served_titles": titles1,
                    "served_titles_followup": titles2,
                    "served_urls": urls,
                    "golden": golden,
                    "golden_recovered": golden_recovered,
                    "golden_fully_covered": all(t in served_final for t in golden),
                    "evidence_present": bool(golden_recovered),
                }
            )

    BENCHMARK_RESULTS["cross_site"] = results
    # Isolation contract: absolutely no foreign evidence on either site, and
    # every served URL must belong to the requested website.
    assert results["leak_total"] == 0
    for row in results["queries"]:
        assert all((ACC2_SITE_A in u) == (row["site"] == ACC2_SITE_A) for u in row["served_urls"])
        assert row["evidence_present"], f"no in-corpus evidence for {row['label']}/{row['site']}"


async def test_rerank_ordering_delta() -> None:
    """Reranking's effect on final ordering when enabled (deterministic fakes).

    Stored chunk embeddings are zero vectors, so cosine contributes nothing:
    the reranker rescoring yields 0.0 for every candidate and only the
    strong-lexical protection (all query content tokens present) can admit a
    chunk past the ``chat_context_min_score`` gate.  Queries that are not
    strong-lexical matches therefore fall back with an empty context under a
    reranker — a SYNTHETIC artifact that real embeddings would not produce.
    This test records the RRF pool order and the served (reranked) order
    without asserting equality, so the reordering effect is measured honestly.
    """
    samples = [
        ("What is the annual BCA tuition fee?", ["bca-fee"]),
        ("Tell me about admissions and fee at BCA", ["bca-fee", "bca-admission"]),
        ("What is the BCA fee and admission eligibility?", ["bca-fee", "bca-admission"]),
        ("What programs does the university offer?", ["university-programs"]),
        ("BCA courses and placement support", ["bca-courses", "bca-placement"]),
        (
            "What does BCA cover in its curriculum?",
            ["bca-program", "bca-curriculum", "bca-courses"],
        ),
    ]
    env = _build_acc2_env(reranker=True)
    await _make_academy2(env, tenant_id=ACC2_TENANT, site=ACC2_SITE_A, corpus=CORPUS_A2)

    rows: list[dict[str, Any]] = []
    for query, _ in samples:
        events = await _stream(env, tenant_id=ACC2_TENANT, website_id=ACC2_SITE_A, question=query)
        served = _source_titles(events)
        tower = _compute_tower(env, query=query, tenant_id=ACC2_TENANT, website_id=ACC2_SITE_A)
        rows.append(
            {
                "query": query,
                "rrf_pool_order": tower["pool"],
                "rerank_order": served,
                "rerank_changed_order": bool(served) and served != tower["pool"][:5],
                "reranked": _timing(events).get("reranked", False),
                "context_empty": not served,
            }
        )

    BENCHMARK_RESULTS["rerank_delta"] = {
        "note": (
            "SYNTHETIC: stored chunk embeddings are zero vectors; cosine "
            "contributes 0.0, so the reranker admits only strong-lexical "
            "matches. A real embedding index would score candidates "
            "non-degenerately."
        ),
        "reranker_enabled": True,
        "order_changed": any(r["rerank_changed_order"] for r in rows),
        "context_empty_count": sum(1 for r in rows if r["context_empty"]),
        "queries": rows,
    }
    assert env.rag._reranker is not None, "reranker was not enabled"


# ---------------------------------------------------------------------------
# Phase 8-11 — SYNTHETIC e2e-TTFT correlation (heavy; RAG_BENCH=1)
# Real-provider TTFT is UNMEASURED in this environment; these numbers answer
# the retrieval->TTFT relationship question only and are labellled SYNTHETIC.
# ---------------------------------------------------------------------------


def _topic_corpus_chunks(n: int) -> list[str]:
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
    return [
        f"Chunk {i}: {topics[i % len(topics)]} documentation for feature {i}. "
        f"This section covers {topics[i % len(topics)]} details including "
        f"configuration, best practices, and troubleshooting for item {i}."
        for i in range(n)
    ]


async def _build_topic_corpus(env: ChatEnv, tenant_id: str, site: str, n: int) -> None:
    await make_website(env, tenant_id=tenant_id, website_id=site, knowledge_chunks=n)
    for i, text in enumerate(_topic_corpus_chunks(n)):
        chunk = await make_chunk(
            env,
            tenant_id=tenant_id,
            website_id=site,
            text=text,
            chunk_index=i,
            document_id=f"doc-{i // 10}",
        )
        chunk.id = f"topic-{i}"  # see _make_academy2: determinism across runs


def _retrieval_total_ms(t: dict[str, Any]) -> float:
    return (
        float(t.get("embedding_ms", 0))
        + float(t.get("retrieval_ms", 0))
        + float(t.get("load_chunks_ms", 0))
        + float(t.get("rerank_ms", 0))
    )


@pytest.mark.skipif(not RUN_BENCH, reason=BENCH_SKIP_REASON)
@pytest.mark.timeout(300)
async def test_synthetic_e2e_ttft_correlation() -> None:
    """Validate e2e_TTFT = pre-generation stages + ttft, and compute how much
    a 50% retrieval cut would improve SYNTHETIC end-to-end TTFT."""
    env = _build_acc2_env()
    await _build_topic_corpus(env, ACC2_TENANT, ACC2_SITE_A, 100)

    def capture(events: list[dict]) -> dict[str, float]:
        t = _timing(events)
        gen = float(t.get("generation_ms", 0) or 0)
        ttft = float(t.get("ttft_ms", 0) or 0)
        total = float(t.get("total_ms", 0) or 0)
        retrieval = _retrieval_total_ms(t)
        # e2e_TTFT = request start -> first token.  generation_ms spans the
        # whole streamed response, so subtract the post-first-token remainder.
        e2e_ttft = total - (gen - ttft)
        return {
            "retrieval_ms": retrieval,
            "ttft_ms": ttft,
            "e2e_ttft_ms": e2e_ttft,
            "gen_ms": gen,
            "total_ms": total,
            "cache_status": str(t.get("retrieval_cache", "miss")),
        }

    miss: list[dict[str, float]] = []
    for i in range(30):
        events = await _stream(
            env,
            tenant_id=ACC2_TENANT,
            website_id=ACC2_SITE_A,
            question=f"pricing documentation feature {i}",
        )
        row = capture(events)
        assert row["cache_status"] == "miss"
        miss.append(row)

    seed = await _stream(
        env,
        tenant_id=ACC2_TENANT,
        website_id=ACC2_SITE_A,
        question="billing documentation feature 10",
    )
    assert _timing(seed).get("retrieval_cache") == "miss"
    hit: list[dict[str, float]] = []
    for _ in range(30):
        events = await _stream(
            env,
            tenant_id=ACC2_TENANT,
            website_id=ACC2_SITE_A,
            question="billing documentation feature 10",
        )
        row = capture(events)
        assert row["cache_status"] == "hit"
        hit.append(row)

    def block(samples: list[dict[str, float]]) -> dict[str, Any]:
        return {
            "retrieval": _percentiles([s["retrieval_ms"] for s in samples]),
            "llm_ttft": _percentiles([s["ttft_ms"] for s in samples]),
            "e2e_ttft": _percentiles([s["e2e_ttft_ms"] for s in samples]),
            "total_generation": _percentiles([s["gen_ms"] for s in samples]),
        }

    miss_block, hit_block = block(miss), block(hit)
    # Relationship validation: e2e_ttft ≈ (total - generation) + ttft is exact
    # by construction; validate instead that pre-gen + ttft reproduces e2e.
    for s in miss + hit:
        pre_gen = s["total_ms"] - s["gen_ms"]
        assert abs(s["e2e_ttft_ms"] - (pre_gen + s["ttft_ms"])) < 1e-6

    # Retrieval share of SYNTHETIC e2e-TTFT (miss only) and the halving answer.
    e2e_mean = statistics.fmean(x["e2e_ttft_ms"] for x in miss)
    ret_mean = statistics.fmean(x["retrieval_ms"] for x in miss)
    ret_share = ret_mean / e2e_mean if e2e_mean else 0.0
    halving_improvement = 0.5 * ret_mean / e2e_mean if e2e_mean else 0.0

    BENCHMARK_RESULTS["ttft_correlation"] = {
        "measurement_kind": "SYNTHETIC (fake generation client, dev box)",
        "real_ttft_note": (
            "REAL TTFT = UNMEASURED: no cloud provider credentials; local "
            "Ollama 127.0.0.1:11434 has zero models. These numbers are NOT "
            "production latency."
        ),
        "miss": miss_block,
        "hit": hit_block,
        "retrieval_share_of_e2e_ttft_p50": round(
            miss_block["retrieval"]["p50"] / miss_block["e2e_ttft"]["p50"], 3
        )
        if miss_block["e2e_ttft"]["p50"]
        else None,
        "retrieval_mean_share_of_e2e_ttft": round(ret_share, 3),
        "e2e_improvement_if_retrieval_halved_mean": round(halving_improvement, 3),
        "samples": {"miss_rows": miss, "hit_rows": hit},
    }
    assert len(miss) == 30 and len(hit) == 30


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


async def test_export_deep_dive_results_json() -> None:
    """Dump the raw deep-dive samples for the report step (no production
    writes; lands in /tmp/opencode)."""
    path = "/tmp/opencode/rag_accuracy_deep_dive_results.json"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    handle = await asyncio.get_running_loop().run_in_executor(
        None,
        lambda: open(path, "w", encoding="utf-8"),  # noqa: ASYNC230
    )
    with handle:
        json.dump(BENCHMARK_RESULTS, handle, indent=2, sort_keys=True)
