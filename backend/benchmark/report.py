"""Benchmark summary report and statistical helpers.

Pure functions that compute aggregate statistics from a list of
``BenchmarkRequest`` results.  No I/O, no side effects — easy to test.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from backend.benchmark.runner import BenchmarkRequest


@dataclass
class SummaryStats:
    """Single-metric summary (mean / median / p95 / min / max)."""

    mean: float = 0.0
    median: float = 0.0
    p95: float = 0.0
    min: float = 0.0
    max: float = 0.0


@dataclass
class BenchmarkReport:
    """Aggregated results from a benchmark run."""

    request_count: int = 0
    success_count: int = 0
    error_count: int = 0
    total_latency: SummaryStats = field(default_factory=SummaryStats)
    ttft: SummaryStats = field(default_factory=SummaryStats)
    generation_latency: SummaryStats = field(default_factory=SummaryStats)
    embedding_latency: SummaryStats = field(default_factory=SummaryStats)
    retrieval_latency: SummaryStats = field(default_factory=SummaryStats)
    provider_success_rate: float = 0.0
    fallback_rate: float = 0.0
    cache_hit_rate: float = 0.0
    fallback_attempts_total: int = 0
    estimated_tokens_total: int = 0
    provider_counts: dict[str, int] = field(default_factory=dict)
    per_request: list[BenchmarkRequest] = field(default_factory=list)
    # --- quality aggregates ---
    avg_relevance: SummaryStats = field(default_factory=SummaryStats)
    context_coverage: SummaryStats = field(default_factory=SummaryStats)
    response_length: SummaryStats = field(default_factory=SummaryStats)
    citation_count: SummaryStats = field(default_factory=SummaryStats)
    empty_rate: float = 0.0
    truncation_rate: float = 0.0
    context_usage_rate: float = 0.0
    avg_chunks_retrieved: SummaryStats = field(default_factory=SummaryStats)
    # --- golden dataset aggregates ---
    golden_overall: SummaryStats = field(default_factory=SummaryStats)
    golden_keyword: SummaryStats = field(default_factory=SummaryStats)
    golden_source: SummaryStats = field(default_factory=SummaryStats)
    golden_completeness: SummaryStats = field(default_factory=SummaryStats)
    golden_concept: SummaryStats = field(default_factory=SummaryStats)
    golden_case_count: int = 0


def _percentile(values: list[float], pct: float) -> float:
    """Compute the *pct*-th percentile (0-100) using nearest-rank."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = max(0, min(len(sorted_vals) - 1, int(round(pct / 100.0 * len(sorted_vals))) - 1))
    return sorted_vals[k]


def _stats_for(values: list[float]) -> SummaryStats:
    """Build ``SummaryStats`` from a list of non-negative floats."""
    if not values:
        return SummaryStats()
    return SummaryStats(
        mean=round(statistics.mean(values), 2),
        median=round(statistics.median(values), 2),
        p95=round(_percentile(values, 95), 2),
        min=round(min(values), 2),
        max=round(max(values), 2),
    )


def _collect(requests: list[BenchmarkRequest], attr: str) -> list[float]:
    """Collect non-None float values for *attr* across requests."""
    return [getattr(r, attr) for r in requests if getattr(r, attr) is not None]


def _collect_quality(
    requests: list[BenchmarkRequest],
    attr: str,
) -> list[float]:
    """Collect a numeric field from ``BenchmarkRequest.quality``."""
    return [getattr(r.quality, attr) for r in requests]


def compute_summary(requests: list[BenchmarkRequest]) -> BenchmarkReport:
    """Compute aggregate statistics from a list of benchmark results."""
    report = BenchmarkReport(per_request=requests)
    report.request_count = len(requests)
    report.error_count = sum(1 for r in requests if r.error is not None)
    report.success_count = report.request_count - report.error_count

    total_ms = [r.total_ms for r in requests if r.error is None]
    report.total_latency = _stats_for(total_ms)
    report.ttft = _stats_for(_collect(requests, "ttft_ms"))
    report.generation_latency = _stats_for(_collect(requests, "generation_ms"))
    report.embedding_latency = _stats_for(_collect(requests, "embedding_ms"))
    report.retrieval_latency = _stats_for(_collect(requests, "retrieval_ms"))

    ok_requests = [r for r in requests if r.error is None]
    report.provider_success_rate = (
        round(len(ok_requests) / report.request_count * 100, 1) if report.request_count else 0.0
    )
    report.fallback_rate = (
        round(sum(1 for r in ok_requests if r.fallback) / len(ok_requests) * 100, 1)
        if ok_requests
        else 0.0
    )
    report.fallback_attempts_total = sum(r.fallback_attempts for r in requests)
    report.estimated_tokens_total = sum(r.estimated_prompt_tokens for r in requests)

    embedding_hits = sum(1 for r in ok_requests if r.embedding_cache == "hit")
    report.cache_hit_rate = (
        round(embedding_hits / len(ok_requests) * 100, 1) if ok_requests else 0.0
    )

    provider_counts: dict[str, int] = {}
    for r in ok_requests:
        name = r.provider or "unknown"
        provider_counts[name] = provider_counts.get(name, 0) + 1
    report.provider_counts = provider_counts

    # --- quality aggregates ---
    report.avg_relevance = _stats_for(_collect_quality(ok_requests, "avg_relevance_score"))
    report.context_coverage = _stats_for(_collect_quality(ok_requests, "context_coverage"))
    report.response_length = _stats_for(_collect_quality(ok_requests, "response_length"))
    report.citation_count = _stats_for(_collect_quality(ok_requests, "citation_count"))
    report.avg_chunks_retrieved = _stats_for(_collect_quality(ok_requests, "retrieved_chunk_count"))
    if ok_requests:
        report.empty_rate = round(
            sum(1 for r in ok_requests if r.quality.is_empty) / len(ok_requests) * 100, 1
        )
        report.truncation_rate = round(
            sum(1 for r in ok_requests if r.quality.is_truncated) / len(ok_requests) * 100, 1
        )
        report.context_usage_rate = round(
            sum(1 for r in ok_requests if r.quality.context_used) / len(ok_requests) * 100, 1
        )

    # --- golden dataset aggregates ---
    golden_requests = [
        r
        for r in ok_requests
        if r.golden_metrics.overall_quality_score > 0 or r.golden_metrics.keyword_coverage_score > 0
    ]
    report.golden_case_count = len(golden_requests)
    if golden_requests:
        report.golden_overall = _stats_for(
            [r.golden_metrics.overall_quality_score for r in golden_requests]
        )
        report.golden_keyword = _stats_for(
            [r.golden_metrics.keyword_coverage_score for r in golden_requests]
        )
        report.golden_source = _stats_for(
            [r.golden_metrics.source_accuracy_score for r in golden_requests]
        )
        report.golden_completeness = _stats_for(
            [r.golden_metrics.answer_completeness_score for r in golden_requests]
        )
        report.golden_concept = _stats_for(
            [r.golden_metrics.concept_coverage_score for r in golden_requests]
        )

    return report


def format_report(report: BenchmarkReport) -> str:
    """Render a human-readable text report."""
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("  AI Benchmark Report (Latency + Quality)")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"  Requests:          {report.request_count}")
    lines.append(f"  Successes:         {report.success_count}")
    lines.append(f"  Errors:            {report.error_count}")
    lines.append("")
    lines.append("  --- Latency (ms) ---")
    for label, stats in [
        ("Total", report.total_latency),
        ("TTFT", report.ttft),
        ("Generation", report.generation_latency),
        ("Embedding", report.embedding_latency),
        ("Retrieval", report.retrieval_latency),
    ]:
        if stats.mean > 0 or stats.median > 0:
            lines.append(
                f"  {label:<14s}  mean={stats.mean:>8.1f}  median={stats.median:>8.1f}  "
                f"p95={stats.p95:>8.1f}  min={stats.min:>8.1f}  max={stats.max:>8.1f}"
            )
    lines.append("")
    lines.append("  --- Rates ---")
    lines.append(f"  Provider success: {report.provider_success_rate:.1f}%")
    lines.append(f"  Fallback rate:    {report.fallback_rate:.1f}%")
    lines.append(f"  Cache hit rate:   {report.cache_hit_rate:.1f}%")
    lines.append(f"  Fallback attempts:{report.fallback_attempts_total}")
    lines.append(f"  Est. tokens:      {report.estimated_tokens_total}")
    lines.append("")
    lines.append("  --- Quality ---")
    lines.append(
        f"  Chunks retrieved: mean={report.avg_chunks_retrieved.mean:.1f}  "
        f"median={report.avg_chunks_retrieved.median:.1f}  "
        f"max={report.avg_chunks_retrieved.max:.0f}"
    )
    lines.append(
        f"  Relevance score:  mean={report.avg_relevance.mean:.3f}  "
        f"median={report.avg_relevance.median:.3f}  "
        f"p95={report.avg_relevance.p95:.3f}"
    )
    lines.append(
        f"  Context coverage: mean={report.context_coverage.mean:.3f}  "
        f"median={report.context_coverage.median:.3f}  "
        f"p95={report.context_coverage.p95:.3f}"
    )
    lines.append(
        f"  Response length:  mean={report.response_length.mean:.0f}  "
        f"median={report.response_length.median:.0f}  "
        f"p95={report.response_length.p95:.0f} chars"
    )
    lines.append(
        f"  Citations:        mean={report.citation_count.mean:.1f}  "
        f"median={report.citation_count.median:.1f}  "
        f"p95={report.citation_count.p95:.1f}"
    )
    lines.append(f"  Empty answers:    {report.empty_rate:.1f}%")
    lines.append(f"  Truncated:        {report.truncation_rate:.1f}%")
    lines.append(f"  Context used:     {report.context_usage_rate:.1f}%")
    lines.append("")
    if report.golden_case_count > 0:
        lines.append("  --- Golden Dataset ---")
        lines.append(f"  Cases evaluated:  {report.golden_case_count}")
        lines.append(
            f"  Overall score:    mean={report.golden_overall.mean:.3f}  "
            f"median={report.golden_overall.median:.3f}  "
            f"p95={report.golden_overall.p95:.3f}"
        )
        lines.append(
            f"  Keyword coverage: mean={report.golden_keyword.mean:.3f}  "
            f"median={report.golden_keyword.median:.3f}  "
            f"p95={report.golden_keyword.p95:.3f}"
        )
        lines.append(
            f"  Source accuracy:  mean={report.golden_source.mean:.3f}  "
            f"median={report.golden_source.median:.3f}  "
            f"p95={report.golden_source.p95:.3f}"
        )
        lines.append(
            f"  Completeness:     mean={report.golden_completeness.mean:.3f}  "
            f"median={report.golden_completeness.median:.3f}  "
            f"p95={report.golden_completeness.p95:.3f}"
        )
        lines.append(
            f"  Concept coverage: mean={report.golden_concept.mean:.3f}  "
            f"median={report.golden_concept.median:.3f}  "
            f"p95={report.golden_concept.p95:.3f}"
        )
        lines.append("")
    if report.provider_counts:
        lines.append("  --- Providers ---")
        for name, count in sorted(report.provider_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {name:<20s} {count}")
        lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)
