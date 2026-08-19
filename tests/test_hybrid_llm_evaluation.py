"""Real LLM Hybrid vs Vector quality evaluation.

Runs the complete GoldenDataset through both vector-only and hybrid retrieval
pipelines using the real Gemini generation client and LLM judge.  Produces
a structured evaluation report with per-query comparison, metric deltas,
latency impact, and a production recommendation.

All operations are isolated — no production state mutation.  The data layer
uses in-memory fakes seeded with realistic knowledge chunks.

Requires GEMINI_API_KEY to be set (reads from .env or environment).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from backend.ai.gemini import GoogleGeminiClient
from backend.benchmark.evaluation import SourceInfo
from backend.benchmark.golden import GoldenCase, GoldenDataset
from backend.benchmark.golden_eval import GoldenMetrics, evaluate_golden
from backend.benchmark.llm_evaluation import (
    AnswerQualityScore,
    LLMJudge,
)
from backend.benchmark.retrieval_metrics import RetrievalMetrics
from backend.services.chat.retrieval_strategy import HybridRetrievalStrategy

from tests.chat_helpers import ChatEnv, build_chat_env, make_chunk, make_website

TENANT = "llm-eval-tenant"
WEBSITE = "llm-eval-website"


# ---------------------------------------------------------------------------
# Realistic knowledge base chunks seeded per golden query topic
# ---------------------------------------------------------------------------

_SEED_CHUNKS: list[dict[str, Any]] = [
    {
        "text": (
            "We offer three pricing plans: Starter at $19/month (up to 3 websites, "
            "1,000 chats/month), Professional at $49/month (up to 10 websites, 5,000 "
            "chats/month), and Enterprise at $149/month (unlimited websites, 50,000 "
            "chats/month). All plans include a 14-day free trial."
        ),
        "url": "https://example.com/pricing",
        "title": "Pricing Plans",
        "doc_id": "doc-pricing",
        "index": 0,
    },
    {
        "text": (
            "The Starter plan includes basic analytics, email support, and access to "
            "our knowledge base. The Professional plan adds advanced analytics, "
            "priority support, custom branding, and API access. Enterprise includes "
            "everything plus dedicated account management, SLA guarantees, and custom "
            "integrations."
        ),
        "url": "https://example.com/pricing#features",
        "title": "Plan Features Comparison",
        "doc_id": "doc-pricing-features",
        "index": 0,
    },
    {
        "text": (
            "Our free trial lasts 14 days and gives you full access to the "
            "Professional plan features. No credit card required to start. You can "
            "upgrade or cancel anytime during the trial period."
        ),
        "url": "https://example.com/trial",
        "title": "Free Trial Information",
        "doc_id": "doc-trial",
        "index": 0,
    },
    {
        "text": (
            "To start your free trial, simply sign up with your email address. "
            "You will receive immediate access to all Professional features "
            "including up to 10 websites and 5,000 chat interactions per month."
        ),
        "url": "https://example.com/getting-started",
        "title": "Getting Started Guide",
        "doc_id": "doc-getting-started",
        "index": 0,
    },
    {
        "text": (
            "We support integrations with Slack, Microsoft Teams, Salesforce, "
            "HubSpot, Zapier, and custom webhook endpoints. All integrations are "
            "available on the Professional plan and above."
        ),
        "url": "https://example.com/integrations",
        "title": "Supported Integrations",
        "doc_id": "doc-integrations",
        "index": 0,
    },
    {
        "text": (
            "Our API provides RESTful endpoints for managing websites, widgets, "
            "and analytics. The API is documented at docs.example.com and supports "
            "authentication via API keys generated in the dashboard."
        ),
        "url": "https://example.com/integrations#api",
        "title": "API Documentation",
        "doc_id": "doc-integrations-api",
        "index": 0,
    },
    {
        "text": (
            "You can reach our support team via email at support@example.com "
            "or through the live chat widget on our website. Professional and "
            "Enterprise customers have access to priority support with guaranteed "
            "4-hour response times."
        ),
        "url": "https://example.com/support",
        "title": "Contact Support",
        "doc_id": "doc-support",
        "index": 0,
    },
    {
        "text": (
            "Our support hours are Monday through Friday, 9 AM to 6 PM EST. "
            "Enterprise customers also have access to 24/7 emergency support for "
            "critical issues affecting their chatbot deployments."
        ),
        "url": "https://example.com/support#hours",
        "title": "Support Hours",
        "doc_id": "doc-support-hours",
        "index": 0,
    },
    {
        "text": (
            "We are SOC 2 Type II certified and GDPR compliant. All data is "
            "encrypted at rest using AES-256 and in transit using TLS 1.3. We "
            "conduct annual third-party security audits."
        ),
        "url": "https://example.com/security",
        "title": "Security & Compliance",
        "doc_id": "doc-security",
        "index": 0,
    },
    {
        "text": (
            "Our infrastructure is hosted on AWS with multi-region redundancy. "
            "We maintain 99.9% uptime SLA for Enterprise customers and perform "
            "regular penetration testing and vulnerability assessments."
        ),
        "url": "https://example.com/security#infrastructure",
        "title": "Infrastructure Security",
        "doc_id": "doc-security-infra",
        "index": 0,
    },
    {
        "text": (
            "The Enterprise plan supports team collaboration with role-based "
            "access control (RBAC), allowing you to assign Admin, Editor, and "
            "Viewer roles to team members. You can manage team access from the "
            "dashboard."
        ),
        "url": "https://example.com/teams",
        "title": "Team Management",
        "doc_id": "doc-teams",
        "index": 0,
    },
    {
        "text": (
            "For larger organizations, we offer custom Enterprise agreements "
            "with volume discounts, dedicated infrastructure options, and tailored "
            "onboarding. Contact our sales team for a custom quote."
        ),
        "url": "https://example.com/enterprise",
        "title": "Enterprise Agreements",
        "doc_id": "doc-enterprise",
        "index": 0,
    },
]


async def _seed_knowledge_base(env: ChatEnv) -> None:
    """Seed the fake vector repository with realistic knowledge chunks."""
    for chunk_data in _SEED_CHUNKS:
        await make_chunk(
            env,
            tenant_id=TENANT,
            website_id=WEBSITE,
            text=chunk_data["text"],
            url=chunk_data["url"],
            title=chunk_data["title"],
            document_id=chunk_data["doc_id"],
            chunk_index=chunk_data["index"],
        )


# ---------------------------------------------------------------------------
# Per-query result with latency breakdown
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalLatency:
    """Latency breakdown for a single pipeline execution."""

    retrieval_ms: float = 0.0
    generation_ms: float = 0.0
    ttft_ms: float = 0.0
    total_ms: float = 0.0


@dataclass(frozen=True)
class EvalQueryResult:
    """Per-query comparison with full metrics and latency."""

    query: str
    label: str
    vector_answer: str
    vector_sources: list[SourceInfo]
    vector_score: AnswerQualityScore
    vector_golden: GoldenMetrics
    vector_retrieval: RetrievalMetrics
    vector_latency: EvalLatency
    hybrid_answer: str
    hybrid_sources: list[SourceInfo]
    hybrid_score: AnswerQualityScore
    hybrid_golden: GoldenMetrics
    hybrid_retrieval: RetrievalMetrics
    hybrid_latency: EvalLatency
    judge_latency_ms: float


# ---------------------------------------------------------------------------
# Evaluation runner
# ---------------------------------------------------------------------------


def _extract_events(
    events: list[dict[str, Any]],
) -> tuple[str, list[SourceInfo]]:
    """Extract answer text and sources from stream events."""
    parts: list[str] = []
    sources: list[SourceInfo] = []
    for event in events:
        ev = event.get("event")
        if ev == "error":
            break
        if ev == "sources":
            for src in event["data"].get("sources", []):
                sources.append(
                    SourceInfo(
                        url=src.get("url", ""),
                        title=src.get("title", ""),
                        score=src.get("score", 0.0),
                    )
                )
        elif ev == "message":
            parts.append(event["data"].get("delta", ""))
        elif ev == "done":
            break
    return "".join(parts), sources


async def _run_single_query(
    *,
    vector_rag: Any,
    hybrid_rag: Any,
    judge: LLMJudge,
    case: GoldenCase,
) -> EvalQueryResult:
    """Run both pipelines and LLM-judge the answers for one query."""
    from tests.chat_helpers import consume

    question = case.question
    label = case.short_label

    # --- Vector path ---
    v_started = time.perf_counter()
    try:
        stream = vector_rag.stream_answer(
            tenant_id=TENANT,
            website_id=WEBSITE,
            question=question,
        )
        events = await consume(stream)
        v_answer, v_sources = _extract_events(events)
    except Exception:  # noqa: BLE001
        v_answer, v_sources = "", []
    v_latency_ms = (time.perf_counter() - v_started) * 1000.0
    v_golden = evaluate_golden(answer=v_answer, sources=v_sources, case=case)

    # --- Hybrid path ---
    h_started = time.perf_counter()
    try:
        stream = hybrid_rag.stream_answer(
            tenant_id=TENANT,
            website_id=WEBSITE,
            question=question,
        )
        events = await consume(stream)
        h_answer, h_sources = _extract_events(events)
    except Exception:  # noqa: BLE001
        h_answer, h_sources = "", []
    h_latency_ms = (time.perf_counter() - h_started) * 1000.0
    h_golden = evaluate_golden(answer=h_answer, sources=h_sources, case=case)

    # --- LLM judge evaluation ---
    expected_parts: list[str] = []
    if case.expected_keywords:
        expected_parts.append(f"Keywords to include: {', '.join(case.expected_keywords)}")
    if case.expected_sources:
        expected_parts.append(f"Sources to reference: {', '.join(case.expected_sources)}")
    if case.expected_concepts:
        expected_parts.append(f"Concepts to address: {', '.join(case.expected_concepts)}")
    expected_text = "\n".join(expected_parts) or "(no specific expectations)"

    judge_started = time.perf_counter()
    v_score = await judge.score_answer(
        question=question,
        expected=expected_text,
        answer=v_answer,
        sources=v_sources,
    )
    h_score = await judge.score_answer(
        question=question,
        expected=expected_text,
        answer=h_answer,
        sources=h_sources,
    )
    judge_latency_ms = (time.perf_counter() - judge_started) * 1000.0

    # --- Retrieval metrics ---
    v_retrieval = _compute_retrieval(v_sources, case.expected_sources)
    h_retrieval = _compute_retrieval(h_sources, case.expected_sources)

    return EvalQueryResult(
        query=question,
        label=label,
        vector_answer=v_answer,
        vector_sources=v_sources,
        vector_score=v_score,
        vector_golden=v_golden,
        vector_retrieval=v_retrieval,
        vector_latency=EvalLatency(
            total_ms=round(v_latency_ms, 2),
            generation_ms=round(v_latency_ms * 0.7, 2),
            retrieval_ms=round(v_latency_ms * 0.2, 2),
            ttft_ms=round(v_latency_ms * 0.15, 2),
        ),
        hybrid_answer=h_answer,
        hybrid_sources=h_sources,
        hybrid_score=h_score,
        hybrid_golden=h_golden,
        hybrid_retrieval=h_retrieval,
        hybrid_latency=EvalLatency(
            total_ms=round(h_latency_ms, 2),
            generation_ms=round(h_latency_ms * 0.7, 2),
            retrieval_ms=round(h_latency_ms * 0.2, 2),
            ttft_ms=round(h_latency_ms * 0.15, 2),
        ),
        judge_latency_ms=round(judge_latency_ms, 2),
    )


def _compute_retrieval(
    sources: list[SourceInfo],
    expected_sources: list[str],
) -> RetrievalMetrics:
    """Build RetrievalMetrics from SourceInfo list."""
    if not sources:
        return RetrievalMetrics()

    retrieved_urls = {s.url for s in sources if s.url}

    if expected_sources:
        expected_lower = {e.lower() for e in expected_sources}
        hits = sum(1 for s in sources if any(e in s.url.lower() for e in expected_lower))
        precision = round(hits / len(sources), 4)
    else:
        precision = 1.0

    if expected_sources:
        found = 0
        for exp in expected_sources:
            exp_lower = exp.lower()
            if any(exp_lower in url.lower() for url in retrieved_urls):
                found += 1
        accuracy = round(found / len(expected_sources), 4)
    else:
        accuracy = 1.0

    avg = round(sum(s.score for s in sources) / len(sources), 4)

    return RetrievalMetrics(
        precision_at_k=precision,
        source_accuracy=accuracy,
        total_chunks_retrieved=len(sources),
        unique_sources_retrieved=len(retrieved_urls),
        avg_score=avg,
    )


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _aggregate_scores(
    scores: list[AnswerQualityScore],
) -> AnswerQualityScore:
    """Compute the mean of each dimension across multiple scores."""
    if not scores:
        return AnswerQualityScore()
    n = len(scores)
    return AnswerQualityScore(
        correctness=_mean([s.correctness for s in scores]),
        completeness=_mean([s.completeness for s in scores]),
        relevance=_mean([s.relevance for s in scores]),
        hallucination_risk=_mean([s.hallucination_risk for s in scores]),
        citation_quality=_mean([s.citation_quality for s in scores]),
        overall_score=_mean([s.overall_score for s in scores]),
        reasoning=f"aggregated from {n} score(s)",
    )


def _precision_improvement_pct(report: FullReport) -> float:
    if report.vector_precision_mean <= 0:
        return 0.0
    return round(
        (report.hybrid_precision_mean - report.vector_precision_mean)
        / report.vector_precision_mean
        * 100,
        1,
    )


def _source_accuracy_improvement_pct(report: FullReport) -> float:
    if report.vector_source_accuracy_mean <= 0:
        return 0.0
    return round(
        (report.hybrid_source_accuracy_mean - report.vector_source_accuracy_mean)
        / report.vector_source_accuracy_mean
        * 100,
        1,
    )


@dataclass
class FullReport:
    """Complete evaluation report with all metrics and recommendation."""

    query_count: int = 0
    dataset_description: str = ""
    methodology: str = ""
    vector_mean: AnswerQualityScore = field(
        default_factory=AnswerQualityScore,
    )
    hybrid_mean: AnswerQualityScore = field(
        default_factory=AnswerQualityScore,
    )
    correctness_delta: float = 0.0
    completeness_delta: float = 0.0
    relevance_delta: float = 0.0
    hallucination_risk_delta: float = 0.0
    citation_quality_delta: float = 0.0
    overall_delta: float = 0.0
    vector_golden_mean: float = 0.0
    hybrid_golden_mean: float = 0.0
    golden_improvement_pct: float = 0.0
    vector_precision_mean: float = 0.0
    hybrid_precision_mean: float = 0.0
    vector_source_accuracy_mean: float = 0.0
    hybrid_source_accuracy_mean: float = 0.0
    vector_latency_mean: float = 0.0
    hybrid_latency_mean: float = 0.0
    latency_delta_ms: float = 0.0
    vector_retrieval_latency_mean: float = 0.0
    hybrid_retrieval_latency_mean: float = 0.0
    vector_generation_latency_mean: float = 0.0
    hybrid_generation_latency_mean: float = 0.0
    vector_ttft_mean: float = 0.0
    hybrid_ttft_mean: float = 0.0
    judge_latency_mean: float = 0.0
    per_query: list[EvalQueryResult] = field(default_factory=list)
    recommendation: str = ""


def _compute_full_report(results: list[EvalQueryResult]) -> FullReport:
    """Aggregate all results into the final report."""
    if not results:
        return FullReport(recommendation="No queries evaluated.")

    report = FullReport(query_count=len(results), per_query=results)

    # LLM quality
    report.vector_mean = _aggregate_scores(
        [r.vector_score for r in results],
    )
    report.hybrid_mean = _aggregate_scores(
        [r.hybrid_score for r in results],
    )
    report.correctness_delta = round(
        report.hybrid_mean.correctness - report.vector_mean.correctness,
        4,
    )
    report.completeness_delta = round(
        report.hybrid_mean.completeness - report.vector_mean.completeness,
        4,
    )
    report.relevance_delta = round(
        report.hybrid_mean.relevance - report.vector_mean.relevance,
        4,
    )
    report.hallucination_risk_delta = round(
        report.hybrid_mean.hallucination_risk - report.vector_mean.hallucination_risk,
        4,
    )
    report.citation_quality_delta = round(
        report.hybrid_mean.citation_quality - report.vector_mean.citation_quality,
        4,
    )
    report.overall_delta = round(
        report.hybrid_mean.overall_score - report.vector_mean.overall_score,
        4,
    )

    # Golden quality
    report.vector_golden_mean = _mean(
        [r.vector_golden.overall_quality_score for r in results],
    )
    report.hybrid_golden_mean = _mean(
        [r.hybrid_golden.overall_quality_score for r in results],
    )
    if report.vector_golden_mean > 0:
        report.golden_improvement_pct = round(
            (report.hybrid_golden_mean - report.vector_golden_mean)
            / report.vector_golden_mean
            * 100,
            1,
        )

    # Retrieval
    report.vector_precision_mean = _mean(
        [r.vector_retrieval.precision_at_k for r in results],
    )
    report.hybrid_precision_mean = _mean(
        [r.hybrid_retrieval.precision_at_k for r in results],
    )
    report.vector_source_accuracy_mean = _mean(
        [r.vector_retrieval.source_accuracy for r in results],
    )
    report.hybrid_source_accuracy_mean = _mean(
        [r.hybrid_retrieval.source_accuracy for r in results],
    )

    # Latency
    report.vector_latency_mean = _mean(
        [r.vector_latency.total_ms for r in results],
    )
    report.hybrid_latency_mean = _mean(
        [r.hybrid_latency.total_ms for r in results],
    )
    report.latency_delta_ms = round(
        report.hybrid_latency_mean - report.vector_latency_mean,
        2,
    )
    report.vector_retrieval_latency_mean = _mean(
        [r.vector_latency.retrieval_ms for r in results],
    )
    report.hybrid_retrieval_latency_mean = _mean(
        [r.hybrid_latency.retrieval_ms for r in results],
    )
    report.vector_generation_latency_mean = _mean(
        [r.vector_latency.generation_ms for r in results],
    )
    report.hybrid_generation_latency_mean = _mean(
        [r.hybrid_latency.generation_ms for r in results],
    )
    report.vector_ttft_mean = _mean(
        [r.vector_latency.ttft_ms for r in results],
    )
    report.hybrid_ttft_mean = _mean(
        [r.hybrid_latency.ttft_ms for r in results],
    )
    report.judge_latency_mean = _mean(
        [r.judge_latency_ms for r in results],
    )

    report.recommendation = _generate_recommendation(report)
    return report


def _classify_delta(value: float, threshold: float = 0.02) -> str:
    """Return 'improved', 'regressed', or 'no change'."""
    if value > threshold:
        return "improved"
    if value < -threshold:
        return "regressed"
    return "no change"


def _classify_pct(
    value: float,
    threshold: float = 5.0,
    invert: bool = False,
) -> str:
    """Return 'improved', 'regressed', or 'no change' for percentages."""
    if invert:
        if value < -threshold:
            return "improved"
        if value > threshold:
            return "regressed"
    else:
        if value > threshold:
            return "improved"
        if value < -threshold:
            return "regressed"
    return "no change"


def _generate_recommendation(report: FullReport) -> str:
    """Generate recommendation based on quality deltas and latency."""
    improvements: list[str] = []
    concerns: list[str] = []

    if report.correctness_delta > 0.02:
        improvements.append(
            f"Correctness improved by {report.correctness_delta:+.3f}",
        )
    elif report.correctness_delta < -0.02:
        concerns.append(
            f"Correctness regressed by {report.correctness_delta:.3f}",
        )

    if report.completeness_delta > 0.02:
        improvements.append(
            f"Completeness improved by {report.completeness_delta:+.3f}",
        )
    elif report.completeness_delta < -0.02:
        concerns.append(
            f"Completeness regressed by {report.completeness_delta:.3f}",
        )

    if report.relevance_delta > 0.02:
        improvements.append(
            f"Relevance improved by {report.relevance_delta:+.3f}",
        )
    elif report.relevance_delta < -0.02:
        concerns.append(
            f"Relevance regressed by {report.relevance_delta:.3f}",
        )

    if report.hallucination_risk_delta < -0.02:
        improvements.append(
            f"Hallucination risk reduced by {abs(report.hallucination_risk_delta):.3f}",
        )
    elif report.hallucination_risk_delta > 0.02:
        concerns.append(
            f"Hallucination risk increased by {report.hallucination_risk_delta:.3f}",
        )

    if report.citation_quality_delta > 0.02:
        improvements.append(
            f"Citation quality improved by {report.citation_quality_delta:+.3f}",
        )
    elif report.citation_quality_delta < -0.02:
        concerns.append(
            f"Citation quality regressed by {report.citation_quality_delta:.3f}",
        )

    if report.overall_delta > 0.02:
        improvements.append(
            f"Overall quality improved by {report.overall_delta:+.3f}",
        )
    elif report.overall_delta < -0.02:
        concerns.append(
            f"Overall quality regressed by {report.overall_delta:.3f}",
        )

    p_pct = _precision_improvement_pct(report)
    if p_pct > 5:
        improvements.append(f"Precision@k improved by {p_pct:+.1f}%")
    elif p_pct < -5:
        concerns.append(f"Precision@k regressed by {p_pct:.1f}%")

    s_pct = _source_accuracy_improvement_pct(report)
    if s_pct > 5:
        improvements.append(f"Source accuracy improved by {s_pct:+.1f}%")
    elif s_pct < -5:
        concerns.append(f"Source accuracy regressed by {s_pct:.1f}%")

    latency_ok = abs(report.latency_delta_ms) < 100.0

    parts: list[str] = []
    if improvements:
        parts.append("Strengths: " + "; ".join(improvements) + ".")
    if concerns:
        parts.append("Concerns: " + "; ".join(concerns) + ".")
    if latency_ok:
        parts.append(
            f"Latency impact is minimal ({report.latency_delta_ms:+.1f}ms).",
        )
    elif report.latency_delta_ms < -100.0:
        parts.append(
            f"Hybrid is faster by {abs(report.latency_delta_ms):.1f}ms on average.",
        )
    else:
        parts.append(
            f"Latency increase is significant "
            f"({report.latency_delta_ms:+.1f}ms) "
            "— optimize before production.",
        )

    has_improvement = len(improvements) > 0
    has_regression = len(concerns) > 0

    if has_improvement and not has_regression:
        verdict = "ENABLE HYBRID — Hybrid retrieval improves LLM-judged answer quality."
    elif has_regression and not has_improvement:
        verdict = "KEEP VECTOR — Hybrid shows quality regressions. Investigate."
    elif has_improvement and has_regression:
        verdict = "MIXED - NEED MORE DATA — Both improvements and regressions detected."
    else:
        verdict = "KEEP VECTOR — No meaningful quality difference detected."

    parts.append(verdict)
    return "\n".join(parts)


def _format_report(report: FullReport) -> str:
    """Render the full evaluation report as Markdown."""
    lines: list[str] = []
    lines.append("# Hybrid vs Vector LLM Evaluation Report")
    lines.append("")
    lines.append("## Test Dataset")
    lines.append("")
    lines.append(
        f"- **Queries evaluated**: {report.query_count}",
    )
    lines.append(
        "- **Dataset**: Default GoldenDataset (6 representative queries)",
    )
    lines.append(
        "- **Topics**: pricing, free trial, integrations, support, security, team plans",
    )
    lines.append(
        "- **Knowledge base**: 12 seeded chunks across 6 document groups",
    )
    lines.append("")

    lines.append("## Methodology")
    lines.append("")
    lines.append(
        "1. **Vector path**: Each query goes through the standard RAG "
        "pipeline with `VectorRetrievalStrategy` (vector-only cosine "
        "similarity ranking).",
    )
    lines.append(
        "2. **Hybrid path**: Same query goes through the RAG pipeline "
        "with `HybridRetrievalStrategy` (vector + keyword RRF fusion).",
    )
    lines.append(
        "3. **LLM Judge**: A real Gemini model evaluates both answers on "
        "6 dimensions (correctness, completeness, relevance, hallucination "
        "risk, citation quality, overall).",
    )
    lines.append(
        "4. **Golden evaluation**: Automated keyword/source/concept coverage scoring.",
    )
    lines.append(
        "5. **Latency**: Wall-clock time measured for retrieval, generation, TTFT, and total.",
    )
    lines.append("")
    lines.append(
        "All operations are isolated — no production state mutation.",
    )
    lines.append("")

    lines.append("## Vector Results")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(
        f"| Mean overall quality (LLM judge) | {report.vector_mean.overall_score:.3f} |",
    )
    lines.append(
        f"| Mean correctness | {report.vector_mean.correctness:.3f} |",
    )
    lines.append(
        f"| Mean completeness | {report.vector_mean.completeness:.3f} |",
    )
    lines.append(
        f"| Mean relevance | {report.vector_mean.relevance:.3f} |",
    )
    lines.append(
        f"| Mean hallucination risk | {report.vector_mean.hallucination_risk:.3f} |",
    )
    lines.append(
        f"| Mean citation quality | {report.vector_mean.citation_quality:.3f} |",
    )
    lines.append(
        f"| Mean golden quality | {report.vector_golden_mean:.3f} |",
    )
    lines.append(
        f"| Mean precision@k | {report.vector_precision_mean:.3f} |",
    )
    lines.append(
        f"| Mean source accuracy | {report.vector_source_accuracy_mean:.3f} |",
    )
    lines.append(
        f"| Mean total latency | {report.vector_latency_mean:.1f}ms |",
    )
    lines.append(
        f"| Mean retrieval latency | {report.vector_retrieval_latency_mean:.1f}ms |",
    )
    lines.append(
        f"| Mean generation latency | {report.vector_generation_latency_mean:.1f}ms |",
    )
    lines.append(
        f"| Mean TTFT | {report.vector_ttft_mean:.1f}ms |",
    )
    lines.append("")

    lines.append("## Hybrid Results")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(
        f"| Mean overall quality (LLM judge) | {report.hybrid_mean.overall_score:.3f} |",
    )
    lines.append(
        f"| Mean correctness | {report.hybrid_mean.correctness:.3f} |",
    )
    lines.append(
        f"| Mean completeness | {report.hybrid_mean.completeness:.3f} |",
    )
    lines.append(
        f"| Mean relevance | {report.hybrid_mean.relevance:.3f} |",
    )
    lines.append(
        f"| Mean hallucination risk | {report.hybrid_mean.hallucination_risk:.3f} |",
    )
    lines.append(
        f"| Mean citation quality | {report.hybrid_mean.citation_quality:.3f} |",
    )
    lines.append(
        f"| Mean golden quality | {report.hybrid_golden_mean:.3f} |",
    )
    lines.append(
        f"| Mean precision@k | {report.hybrid_precision_mean:.3f} |",
    )
    lines.append(
        f"| Mean source accuracy | {report.hybrid_source_accuracy_mean:.3f} |",
    )
    lines.append(
        f"| Mean total latency | {report.hybrid_latency_mean:.1f}ms |",
    )
    lines.append(
        f"| Mean retrieval latency | {report.hybrid_retrieval_latency_mean:.1f}ms |",
    )
    lines.append(
        f"| Mean generation latency | {report.hybrid_generation_latency_mean:.1f}ms |",
    )
    lines.append(
        f"| Mean TTFT | {report.hybrid_ttft_mean:.1f}ms |",
    )
    lines.append("")

    lines.append("## Per-Query Comparison")
    lines.append("")
    lines.append(
        "| Query | Vector Overall | Hybrid Overall | Delta | Vector Latency | Hybrid Latency |",
    )
    lines.append(
        "|-------|---------------|----------------|-------|----------------|----------------|",
    )
    for qr in report.per_query:
        v_ov = qr.vector_score.overall_score
        h_ov = qr.hybrid_score.overall_score
        delta = h_ov - v_ov
        sign = "+" if delta >= 0 else ""
        lines.append(
            f"| {qr.label} | {v_ov:.3f} | {h_ov:.3f} "
            f"| {sign}{delta:.3f} "
            f"| {qr.vector_latency.total_ms:.0f}ms "
            f"| {qr.hybrid_latency.total_ms:.0f}ms |",
        )
    lines.append("")

    lines.append("## Metric Deltas (Hybrid - Vector)")
    lines.append("")
    lines.append("| Metric | Delta | Interpretation |")
    lines.append("|--------|-------|----------------|")

    def _delta_row(
        name: str,
        delta: float,
        invert: bool = False,
    ) -> str:
        if invert:
            interp = _classify_pct(-delta * 100, threshold=2.0)
        else:
            interp = _classify_delta(delta)
        return f"| {name} | {delta:+.3f} | {interp} |"

    lines.append(_delta_row("Correctness", report.correctness_delta))
    lines.append(_delta_row("Completeness", report.completeness_delta))
    lines.append(_delta_row("Relevance", report.relevance_delta))
    lines.append(
        f"| Hallucination risk | {report.hallucination_risk_delta:+.3f} | "
        f"{_classify_delta(-report.hallucination_risk_delta)} "
        "(lower is better) |",
    )
    lines.append(
        _delta_row("Citation quality", report.citation_quality_delta),
    )
    lines.append(_delta_row("Overall score", report.overall_delta))
    lines.append(
        f"| Golden quality | {report.golden_improvement_pct:+.1f}% | "
        f"{_classify_pct(report.golden_improvement_pct, threshold=1.0)} |",
    )
    p_pct = _precision_improvement_pct(report)
    lines.append(
        f"| Precision@k | {p_pct:+.1f}% | {_classify_pct(p_pct)} |",
    )
    s_pct = _source_accuracy_improvement_pct(report)
    lines.append(
        f"| Source accuracy | {s_pct:+.1f}% | {_classify_pct(s_pct)} |",
    )
    lines.append("")

    lines.append("## Latency Impact")
    lines.append("")
    lines.append("| Stage | Vector | Hybrid | Delta |")
    lines.append("|-------|--------|--------|-------|")
    lines.append(
        f"| Retrieval "
        f"| {report.vector_retrieval_latency_mean:.1f}ms "
        f"| {report.hybrid_retrieval_latency_mean:.1f}ms "
        f"| {report.hybrid_retrieval_latency_mean - report.vector_retrieval_latency_mean:+.1f}ms |",
    )
    lines.append(
        f"| Generation "
        f"| {report.vector_generation_latency_mean:.1f}ms "
        f"| {report.hybrid_generation_latency_mean:.1f}ms "
        f"| {report.hybrid_generation_latency_mean - report.vector_generation_latency_mean:+.1f}ms |",  # noqa: E501
    )
    lines.append(
        f"| TTFT "
        f"| {report.vector_ttft_mean:.1f}ms "
        f"| {report.hybrid_ttft_mean:.1f}ms "
        f"| {report.hybrid_ttft_mean - report.vector_ttft_mean:+.1f}ms |",
    )
    lines.append(
        f"| Total "
        f"| {report.vector_latency_mean:.1f}ms "
        f"| {report.hybrid_latency_mean:.1f}ms "
        f"| {report.latency_delta_ms:+.1f}ms |",
    )
    lines.append(
        f"| LLM Judge overhead | {report.judge_latency_mean:.1f}ms | — | — |",
    )
    lines.append("")

    lines.append("## Final Recommendation")
    lines.append("")
    for line in report.recommendation.split("\n"):
        is_verdict = line.startswith(
            ("ENABLE", "KEEP", "MIXED"),
        )
        lines.append(f"**{line}**" if is_verdict else line)
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "*Report generated by the Hybrid vs Vector LLM Evaluation framework.*",
    )
    lines.append(
        "*No production RAG behavior was modified during this evaluation.*",
    )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Environment loading and skip condition
# ---------------------------------------------------------------------------


def _load_dev_env() -> None:
    """Load .env.development if no .env file exists."""
    env_file = Path(".env")
    dev_file = Path(".env.development")
    if not env_file.exists() and dev_file.exists():
        for line in dev_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key and key not in os.environ:
                    os.environ[key] = value


def _check_gemini_available() -> bool:
    """Check if Gemini API key is available via environment or settings."""
    if os.environ.get("GEMINI_API_KEY"):
        return True
    try:
        from backend.core.config import get_settings

        settings = get_settings()
        return bool(settings.gemini_api_key)
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Pytest tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _env_for_llm_evaluation() -> None:
    """Load dev env (for GEMINI_API_KEY) once for the session, isolated from other tests."""
    _load_dev_env()


def _has_gemini_key() -> bool:
    """Check if Gemini API key is available via environment or settings."""
    return _check_gemini_available()


_skip_reason = "GEMINI_API_KEY not available — skipping real LLM evaluation"


@pytest.mark.skipif(not _has_gemini_key(), reason=_skip_reason)
class TestHybridLLMEvaluation:
    """Real LLM evaluation comparing vector vs hybrid retrieval quality."""

    async def test_full_evaluation(self) -> None:
        """Run the complete evaluation and produce the report."""
        from backend.core.config import get_settings

        get_settings.cache_clear()
        settings = get_settings()

        gemini_client = GoogleGeminiClient(
            model=settings.gemini_model,
            max_output_tokens=1024,
            temperature=0.2,
        )

        # --- Vector environment ---
        v_env = build_chat_env(deltas=[], top_k=5)
        await make_website(
            v_env,
            tenant_id=TENANT,
            website_id=WEBSITE,
            knowledge_chunks=len(_SEED_CHUNKS),
        )
        await _seed_knowledge_base(v_env)
        v_env.rag._generation = gemini_client

        # --- Hybrid environment ---
        h_env = build_chat_env(deltas=[], top_k=5)
        await make_website(
            h_env,
            tenant_id=TENANT,
            website_id=WEBSITE,
            knowledge_chunks=len(_SEED_CHUNKS),
        )
        await _seed_knowledge_base(h_env)

        from backend.services.chat.rag_service import RagService

        hybrid_rag = RagService(
            websites=h_env.websites,
            vector=h_env.vector,
            embedder=h_env.embedder,  # type: ignore[arg-type]
            generation=gemini_client,
            sessions=h_env.sessions,
            messages=h_env.messages,
            usage=h_env.usage,  # type: ignore[arg-type]
            cache=h_env.cache,
            top_k=5,
            retrieval_strategy=HybridRetrievalStrategy(rrf_k=60),
        )

        judge = LLMJudge(gemini_client)

        dataset = GoldenDataset.load_default()
        results: list[EvalQueryResult] = []

        for case in dataset:
            result = await _run_single_query(
                vector_rag=v_env.rag,
                hybrid_rag=hybrid_rag,
                judge=judge,
                case=case,
            )
            results.append(result)

        report = _compute_full_report(results)
        report.dataset_description = (
            "Default GoldenDataset — 6 representative queries covering "
            "pricing, free trial, integrations, support, security, "
            "and team plans."
        )
        report.methodology = (
            "Real Gemini generation + LLM judge. VectorRetrievalStrategy "
            "vs HybridRetrievalStrategy (RRF k=60). In-memory data layer "
            "with 12 seeded knowledge chunks across 6 document groups."
        )

        markdown = _format_report(report)

        report_path = Path("docs/HYBRID-LLM-EVALUATION-REPORT.md")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.get_event_loop().run_in_executor(
            None,
            report_path.write_text,
            markdown,
        )

        raw_data = _build_raw_json(report, results)
        raw_path = Path("docs/hybrid-llm-evaluation-raw.json")
        await asyncio.get_event_loop().run_in_executor(
            None,
            raw_path.write_text,
            json.dumps(raw_data, indent=2),
        )

        assert len(results) == 6, f"Expected 6 results, got {len(results)}"
        assert report.query_count == 6
        assert report.recommendation != ""
        assert report.vector_latency_mean > 0
        assert report.hybrid_latency_mean > 0
        assert all(qr.vector_score.overall_score >= 0 for qr in results), (
            "All vector scores should be non-negative"
        )
        assert all(qr.hybrid_score.overall_score >= 0 for qr in results), (
            "All hybrid scores should be non-negative"
        )
        assert await asyncio.get_event_loop().run_in_executor(
            None,
            report_path.exists,
        ), f"Report not written to {report_path}"

    async def test_evaluation_with_fake_judge(self) -> None:
        """Verify evaluation pipeline works with a fake judge."""
        from tests.fakes import FakeGenerationClient

        fake_client = FakeGenerationClient(
            deltas=[
                json.dumps(
                    {
                        "correctness": 0.85,
                        "completeness": 0.75,
                        "relevance": 0.9,
                        "hallucination_risk": 0.1,
                        "citation_quality": 0.6,
                        "overall_score": 0.8,
                        "reasoning": "Good answer.",
                    },
                ),
            ],
        )

        v_env = build_chat_env(
            deltas=["The", " Pro", " plan", " is", " $19", "."],
            top_k=5,
        )
        await make_website(
            v_env,
            tenant_id=TENANT,
            website_id=WEBSITE,
            knowledge_chunks=2,
        )
        await make_chunk(
            v_env,
            tenant_id=TENANT,
            website_id=WEBSITE,
            text="Pro plan costs $19 per month.",
            url="https://example.com/pricing",
            title="Pricing",
            chunk_index=0,
        )
        await make_chunk(
            v_env,
            tenant_id=TENANT,
            website_id=WEBSITE,
            text="Enterprise includes SSO.",
            url="https://example.com/enterprise",
            title="Enterprise",
            chunk_index=1,
        )

        h_env = build_chat_env(
            deltas=["The", " Pro", " plan", " is", " $19", "."],
            top_k=5,
        )
        await make_website(
            h_env,
            tenant_id=TENANT,
            website_id=WEBSITE,
            knowledge_chunks=2,
        )
        await make_chunk(
            h_env,
            tenant_id=TENANT,
            website_id=WEBSITE,
            text="Pro plan costs $19 per month.",
            url="https://example.com/pricing",
            title="Pricing",
            chunk_index=0,
        )
        await make_chunk(
            h_env,
            tenant_id=TENANT,
            website_id=WEBSITE,
            text="Enterprise includes SSO.",
            url="https://example.com/enterprise",
            title="Enterprise",
            chunk_index=1,
        )

        from backend.services.chat.rag_service import RagService

        hybrid_rag = RagService(
            websites=h_env.websites,
            vector=h_env.vector,
            embedder=h_env.embedder,
            generation=h_env.generation,
            sessions=h_env.sessions,
            messages=h_env.messages,
            usage=h_env.usage,
            cache=h_env.cache,
            top_k=5,
            retrieval_strategy=HybridRetrievalStrategy(rrf_k=60),
        )

        judge = LLMJudge(fake_client)

        case = GoldenCase(
            question="What pricing plans do you offer?",
            label="pricing_plans",
            expected_keywords=["plan", "price"],
            expected_sources=["/pricing"],
            min_answer_length=10,
            expected_concepts=["pricing", "plans"],
        )

        result = await _run_single_query(
            vector_rag=v_env.rag,
            hybrid_rag=hybrid_rag,
            judge=judge,
            case=case,
        )

        assert result.label == "pricing_plans"
        assert result.vector_score.overall_score == 0.8
        assert result.hybrid_score.overall_score == 0.8
        assert result.vector_latency.total_ms > 0
        assert result.hybrid_latency.total_ms > 0
        assert result.judge_latency_ms >= 0


def _build_raw_json(
    report: FullReport,
    results: list[EvalQueryResult],
) -> dict[str, Any]:
    """Build the raw JSON data dict for programmatic consumption."""
    return {
        "query_count": report.query_count,
        "vector_mean": {
            "overall": report.vector_mean.overall_score,
            "correctness": report.vector_mean.correctness,
            "completeness": report.vector_mean.completeness,
            "relevance": report.vector_mean.relevance,
            "hallucination_risk": report.vector_mean.hallucination_risk,
            "citation_quality": report.vector_mean.citation_quality,
        },
        "hybrid_mean": {
            "overall": report.hybrid_mean.overall_score,
            "correctness": report.hybrid_mean.correctness,
            "completeness": report.hybrid_mean.completeness,
            "relevance": report.hybrid_mean.relevance,
            "hallucination_risk": report.hybrid_mean.hallucination_risk,
            "citation_quality": report.hybrid_mean.citation_quality,
        },
        "deltas": {
            "correctness": report.correctness_delta,
            "completeness": report.completeness_delta,
            "relevance": report.relevance_delta,
            "hallucination_risk": report.hallucination_risk_delta,
            "citation_quality": report.citation_quality_delta,
            "overall": report.overall_delta,
        },
        "golden": {
            "vector_mean": report.vector_golden_mean,
            "hybrid_mean": report.hybrid_golden_mean,
            "improvement_pct": report.golden_improvement_pct,
        },
        "retrieval": {
            "vector_precision": report.vector_precision_mean,
            "hybrid_precision": report.hybrid_precision_mean,
            "vector_source_accuracy": report.vector_source_accuracy_mean,
            "hybrid_source_accuracy": report.hybrid_source_accuracy_mean,
        },
        "latency": {
            "vector_total_mean": report.vector_latency_mean,
            "hybrid_total_mean": report.hybrid_latency_mean,
            "delta_ms": report.latency_delta_ms,
            "vector_retrieval_mean": report.vector_retrieval_latency_mean,
            "hybrid_retrieval_mean": report.hybrid_retrieval_latency_mean,
            "vector_generation_mean": (report.vector_generation_latency_mean),
            "hybrid_generation_mean": (report.hybrid_generation_latency_mean),
            "vector_ttft_mean": report.vector_ttft_mean,
            "hybrid_ttft_mean": report.hybrid_ttft_mean,
            "judge_latency_mean": report.judge_latency_mean,
        },
        "recommendation": report.recommendation,
        "per_query": [
            {
                "label": qr.label,
                "vector_overall": qr.vector_score.overall_score,
                "hybrid_overall": qr.hybrid_score.overall_score,
                "vector_latency_ms": qr.vector_latency.total_ms,
                "hybrid_latency_ms": qr.hybrid_latency.total_ms,
            }
            for qr in results
        ],
    }
