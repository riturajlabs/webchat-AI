"""Hybrid Search A/B evaluation: vector-only vs hybrid retrieval.

Runs each golden dataset query through the existing vector pipeline and
through hybrid (vector + keyword RRF) retrieval, collecting per-query
retrieval, quality, and performance metrics.  Produces a comparison report
with improvement percentages and a recommendation.

All operations are in-memory using fake repositories — no network, no
MongoDB, no production state mutation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from backend.benchmark.evaluation import SourceInfo
from backend.benchmark.golden import GoldenCase
from backend.benchmark.golden_eval import GoldenMetrics, evaluate_golden
from backend.benchmark.retrieval_metrics import RetrievalMetrics, compute_retrieval_metrics
from backend.repositories.vector.base import VectorSearchResult
from backend.repositories.vector.hybrid import HybridSearcher


@dataclass(frozen=True)
class QueryABResult:
    """A/B comparison for a single query."""

    query: str
    label: str
    # Vector-only metrics
    vector_retrieval: RetrievalMetrics
    vector_answer: str
    vector_sources: list[SourceInfo]
    vector_golden: GoldenMetrics
    vector_latency_ms: float
    # Hybrid metrics
    hybrid_retrieval: RetrievalMetrics
    hybrid_answer: str
    hybrid_sources: list[SourceInfo]
    hybrid_golden: GoldenMetrics
    hybrid_latency_ms: float


@dataclass
class ABReport:
    """Aggregated A/B comparison across all queries."""

    query_count: int = 0
    # Retrieval metrics (mean)
    vector_precision_mean: float = 0.0
    hybrid_precision_mean: float = 0.0
    vector_source_accuracy_mean: float = 0.0
    hybrid_source_accuracy_mean: float = 0.0
    vector_avg_score_mean: float = 0.0
    hybrid_avg_score_mean: float = 0.0
    vector_unique_sources_mean: float = 0.0
    hybrid_unique_sources_mean: float = 0.0
    # Golden quality metrics (mean)
    vector_golden_overall_mean: float = 0.0
    hybrid_golden_overall_mean: float = 0.0
    vector_keyword_coverage_mean: float = 0.0
    hybrid_keyword_coverage_mean: float = 0.0
    vector_context_coverage_mean: float = 0.0
    hybrid_context_coverage_mean: float = 0.0
    # Latency (mean ms)
    vector_latency_mean: float = 0.0
    hybrid_latency_mean: float = 0.0
    latency_delta_ms: float = 0.0
    # Improvement percentages
    precision_improvement_pct: float = 0.0
    source_accuracy_improvement_pct: float = 0.0
    golden_overall_improvement_pct: float = 0.0
    # Per-query details
    per_query: list[QueryABResult] = field(default_factory=list)
    # Recommendation
    recommendation: str = ""


async def run_ab_evaluation(
    *,
    env: object,
    golden_case: GoldenCase,
    tenant_id: str,
    website_id: str,
    question: str,
    top_k: int = 5,
    rrf_k: int = 60,
) -> QueryABResult:
    """Run A/B evaluation for a single query against a golden case.

    1. Runs the vector pipeline (RagService.stream_answer) to get the
       vector-only answer, sources, and timing.
    2. Uses the same vector results + keyword search via RRF to build
       hybrid results, then evaluates retrieval and golden quality.

    Parameters
    ----------
    env:
        Pre-built ChatEnv with seeded website/chunks.
    golden_case:
        The golden case providing expected keywords/sources/concepts.
    tenant_id / website_id:
        Tenant and website scope for the pipeline.
    question:
        The user question text.
    top_k:
        Maximum retrieval results per method.
    rrf_k:
        RRF constant for hybrid fusion.
    """
    from tests.chat_helpers import consume

    rag = env.rag  # type: ignore[attr-defined]
    rag._timing_enabled = True  # noqa: SLF001

    # --- Vector-only path (full pipeline) ---
    v_started = time.perf_counter()
    v_answer_parts: list[str] = []
    v_sources: list[SourceInfo] = []

    try:
        stream = rag.stream_answer(
            tenant_id=tenant_id,
            website_id=website_id,
            question=question,
        )
        events = await consume(stream)
        for event in events:
            ev = event.get("event")
            if ev == "error":
                break
            if ev == "sources":
                for src in event["data"].get("sources", []):
                    v_sources.append(
                        SourceInfo(
                            url=src.get("url", ""),
                            title=src.get("title", ""),
                            score=src.get("score", 0.0),
                        )
                    )
            elif ev == "message":
                v_answer_parts.append(event["data"].get("delta", ""))
            elif ev == "done":
                break
    except Exception:
        pass

    v_latency_ms = (time.perf_counter() - v_started) * 1000.0
    v_answer = "".join(v_answer_parts)
    v_golden = evaluate_golden(answer=v_answer, sources=v_sources, case=golden_case)

    # --- Build vector results for hybrid via public API ---
    vector = env.vector  # type: ignore[attr-defined]
    query_embedding = [0.0, 0.0, 0.0, 0.0]
    vector_results = await vector.similarity_search(
        tenant_id, website_id, query_embedding, top_k=top_k
    )

    all_chunks = [
        VectorSearchResult(chunk=c, score=0.5)
        for c in vector.chunks
        if c.tenant_id == tenant_id and c.website_id == website_id
    ]

    # --- Hybrid path (retrieval-only, no LLM call) ---
    h_started = time.perf_counter()
    searcher = HybridSearcher(rrf_k=rrf_k)
    hybrid_raw = searcher.search(question, vector_results, all_chunks, top_k=top_k)
    h_latency_ms = (time.perf_counter() - h_started) * 1000.0

    hybrid_chunks = [hr.chunk for hr in hybrid_raw]

    h_sources = [
        SourceInfo(
            url=r.chunk.metadata.get("source_url", ""),
            title=r.chunk.metadata.get("title", ""),
            score=r.score,
        )
        for r in hybrid_chunks
        if r.chunk.metadata
    ]

    # Golden evaluation on hybrid sources (same answer — comparing retrieval)
    h_golden = evaluate_golden(answer=v_answer, sources=h_sources, case=golden_case)

    # Retrieval metrics against golden expected sources
    v_retrieval = compute_retrieval_metrics(
        vector_results, golden_case.expected_sources, top_k=top_k
    )
    h_retrieval = compute_retrieval_metrics(
        hybrid_chunks, golden_case.expected_sources, top_k=top_k
    )

    return QueryABResult(
        query=question,
        label=golden_case.short_label,
        vector_retrieval=v_retrieval,
        vector_answer=v_answer,
        vector_sources=v_sources,
        vector_golden=v_golden,
        vector_latency_ms=round(v_latency_ms, 2),
        hybrid_retrieval=h_retrieval,
        hybrid_answer=v_answer,
        hybrid_sources=h_sources,
        hybrid_golden=h_golden,
        hybrid_latency_ms=round(h_latency_ms, 2),
    )


def compute_ab_report(results: list[QueryABResult]) -> ABReport:
    """Aggregate per-query A/B results into a summary report."""
    if not results:
        return ABReport(recommendation="No queries evaluated.")

    n = len(results)
    report = ABReport(query_count=n, per_query=results)

    report.vector_precision_mean = _mean(
        [r.vector_retrieval.precision_at_k for r in results]
    )
    report.hybrid_precision_mean = _mean(
        [r.hybrid_retrieval.precision_at_k for r in results]
    )
    report.vector_source_accuracy_mean = _mean(
        [r.vector_retrieval.source_accuracy for r in results]
    )
    report.hybrid_source_accuracy_mean = _mean(
        [r.hybrid_retrieval.source_accuracy for r in results]
    )
    report.vector_avg_score_mean = _mean(
        [r.vector_retrieval.avg_score for r in results]
    )
    report.hybrid_avg_score_mean = _mean(
        [r.hybrid_retrieval.avg_score for r in results]
    )
    report.vector_unique_sources_mean = _mean(
        [float(r.vector_retrieval.unique_sources_retrieved) for r in results]
    )
    report.hybrid_unique_sources_mean = _mean(
        [float(r.hybrid_retrieval.unique_sources_retrieved) for r in results]
    )

    report.vector_golden_overall_mean = _mean(
        [r.vector_golden.overall_quality_score for r in results]
    )
    report.hybrid_golden_overall_mean = _mean(
        [r.hybrid_golden.overall_quality_score for r in results]
    )
    report.vector_keyword_coverage_mean = _mean(
        [r.vector_golden.keyword_coverage_score for r in results]
    )
    report.hybrid_keyword_coverage_mean = _mean(
        [r.hybrid_golden.keyword_coverage_score for r in results]
    )
    report.vector_context_coverage_mean = _mean(
        [r.vector_golden.source_accuracy_score for r in results]
    )
    report.hybrid_context_coverage_mean = _mean(
        [r.hybrid_golden.source_accuracy_score for r in results]
    )

    report.vector_latency_mean = _mean([r.vector_latency_ms for r in results])
    report.hybrid_latency_mean = _mean([r.hybrid_latency_ms for r in results])
    report.latency_delta_ms = round(
        report.hybrid_latency_mean - report.vector_latency_mean, 2
    )

    report.precision_improvement_pct = _improvement_pct(
        report.vector_precision_mean, report.hybrid_precision_mean
    )
    report.source_accuracy_improvement_pct = _improvement_pct(
        report.vector_source_accuracy_mean, report.hybrid_source_accuracy_mean
    )
    report.golden_overall_improvement_pct = _improvement_pct(
        report.vector_golden_overall_mean, report.hybrid_golden_overall_mean
    )

    report.recommendation = _generate_recommendation(report)
    return report


def format_ab_report(report: ABReport) -> str:
    """Render a human-readable A/B comparison report."""
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("  Hybrid Search A/B Evaluation Report")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"  Queries evaluated: {report.query_count}")
    lines.append("")

    lines.append("  --- Retrieval Quality ---")
    lines.append(
        f"  {'Metric':<24s} {'Vector':>10s} {'Hybrid':>10s} {'Delta':>10s}"
    )
    lines.append("  " + "-" * 56)
    lines.append(
        f"  {'Precision@k':<24s} {report.vector_precision_mean:>10.3f} "
        f"{report.hybrid_precision_mean:>10.3f} "
        f"{report.precision_improvement_pct:>+9.1f}%"
    )
    lines.append(
        f"  {'Source accuracy':<24s} {report.vector_source_accuracy_mean:>10.3f} "
        f"{report.hybrid_source_accuracy_mean:>10.3f} "
        f"{report.source_accuracy_improvement_pct:>+9.1f}%"
    )
    lines.append(
        f"  {'Avg relevance score':<24s} {report.vector_avg_score_mean:>10.3f} "
        f"{report.hybrid_avg_score_mean:>10.3f} "
        f"{'':>10s}"
    )
    lines.append(
        f"  {'Unique sources':<24s} {report.vector_unique_sources_mean:>10.1f} "
        f"{report.hybrid_unique_sources_mean:>10.1f} "
        f"{'':>10s}"
    )
    lines.append("")

    lines.append("  --- Golden Quality ---")
    lines.append(
        f"  {'Metric':<24s} {'Vector':>10s} {'Hybrid':>10s} {'Delta':>10s}"
    )
    lines.append("  " + "-" * 56)
    lines.append(
        f"  {'Overall score':<24s} {report.vector_golden_overall_mean:>10.3f} "
        f"{report.hybrid_golden_overall_mean:>10.3f} "
        f"{report.golden_overall_improvement_pct:>+9.1f}%"
    )
    lines.append(
        f"  {'Keyword coverage':<24s} {report.vector_keyword_coverage_mean:>10.3f} "
        f"{report.hybrid_keyword_coverage_mean:>10.3f} "
        f"{'':>10s}"
    )
    lines.append(
        f"  {'Context coverage':<24s} {report.vector_context_coverage_mean:>10.3f} "
        f"{report.hybrid_context_coverage_mean:>10.3f} "
        f"{'':>10s}"
    )
    lines.append("")

    lines.append("  --- Latency ---")
    lines.append(f"  Vector latency:     {report.vector_latency_mean:>8.2f} ms")
    lines.append(f"  Hybrid latency:     {report.hybrid_latency_mean:>8.2f} ms")
    sign = "+" if report.latency_delta_ms >= 0 else ""
    lines.append(f"  Delta:              {sign}{report.latency_delta_ms:>7.2f} ms")
    lines.append("")

    lines.append("  --- Per-Query Breakdown ---")
    for qr in report.per_query:
        v_acc = qr.vector_retrieval.source_accuracy
        h_acc = qr.hybrid_retrieval.source_accuracy
        delta = h_acc - v_acc
        sign = "+" if delta >= 0 else ""
        lines.append(
            f"  {qr.label:<20s}  vector={v_acc:.3f}  hybrid={h_acc:.3f}  "
            f"delta={sign}{delta:.3f}"
        )
    lines.append("")

    lines.append("  --- Recommendation ---")
    for line in report.recommendation.split("\n"):
        lines.append(f"  {line}")
    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _improvement_pct(baseline: float, treatment: float) -> float:
    if baseline <= 0:
        return 0.0
    return round((treatment - baseline) / baseline * 100, 1)


def _generate_recommendation(report: ABReport) -> str:
    improvements: list[str] = []
    regressions: list[str] = []

    if report.precision_improvement_pct > 0:
        improvements.append(
            f"Precision@k improved by {report.precision_improvement_pct:+.1f}%"
        )
    elif report.precision_improvement_pct < 0:
        regressions.append(
            f"Precision@k regressed by {report.precision_improvement_pct:.1f}%"
        )

    if report.source_accuracy_improvement_pct > 0:
        improvements.append(
            f"Source accuracy improved by "
            f"{report.source_accuracy_improvement_pct:+.1f}%"
        )
    elif report.source_accuracy_improvement_pct < 0:
        regressions.append(
            f"Source accuracy regressed by "
            f"{report.source_accuracy_improvement_pct:.1f}%"
        )

    if report.golden_overall_improvement_pct > 0:
        improvements.append(
            f"Golden overall score improved by "
            f"{report.golden_overall_improvement_pct:+.1f}%"
        )
    elif report.golden_overall_improvement_pct < 0:
        regressions.append(
            f"Golden overall score regressed by "
            f"{report.golden_overall_improvement_pct:.1f}%"
        )

    latency_ok = abs(report.latency_delta_ms) < 50.0

    parts: list[str] = []
    if improvements:
        parts.append("Strengths: " + "; ".join(improvements) + ".")
    if regressions:
        parts.append("Concerns: " + "; ".join(regressions) + ".")
    if latency_ok:
        parts.append(
            f"Latency impact is minimal ({report.latency_delta_ms:+.1f}ms)."
        )
    else:
        parts.append(
            f"Latency increase is significant ({report.latency_delta_ms:+.1f}ms) "
            "— optimize before production."
        )

    has_improvement = any(
        v > 0
        for v in [
            report.precision_improvement_pct,
            report.source_accuracy_improvement_pct,
            report.golden_overall_improvement_pct,
        ]
    )
    has_regression = any(
        v < 0
        for v in [
            report.precision_improvement_pct,
            report.source_accuracy_improvement_pct,
            report.golden_overall_improvement_pct,
        ]
    )

    if has_improvement and not has_regression:
        verdict = "RECOMMEND: Enable hybrid retrieval in production."
    elif has_regression and not has_improvement:
        verdict = "DO NOT ENABLE: Hybrid shows regressions. Investigate."
    elif has_improvement and has_regression:
        verdict = (
            "MIXED: Hybrid shows both improvements and regressions. "
            "Run larger evaluation before deciding."
        )
    else:
        verdict = "NEUTRAL: No meaningful difference detected."

    parts.append(verdict)
    return "\n".join(parts)


__all__ = [
    "ABReport",
    "QueryABResult",
    "compute_ab_report",
    "format_ab_report",
    "run_ab_evaluation",
]
