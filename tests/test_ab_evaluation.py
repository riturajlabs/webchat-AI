"""Tests for Hybrid Search A/B evaluation framework.

Covers QueryABResult data flow, ABReport aggregation, improvement
percentages, recommendation logic, formatted report output, and
end-to-end run_ab_evaluation with seeded in-memory data. All in-memory
— no I/O, no MongoDB.
"""

from backend.benchmark.ab_evaluation import (
    ABReport,
    QueryABResult,
    compute_ab_report,
    format_ab_report,
    run_ab_evaluation,
)
from backend.benchmark.evaluation import SourceInfo
from backend.benchmark.golden import GoldenCase
from backend.benchmark.golden_eval import GoldenMetrics
from backend.benchmark.retrieval_metrics import RetrievalMetrics

from tests.chat_helpers import build_chat_env, make_chunk, make_website

TENANT = "ab-tenant"
WEBSITE = "ab-web"


# ---------------------------------------------------------------------------
# QueryABResult (frozen dataclass)
# ---------------------------------------------------------------------------


def _make_query_result(
    *,
    label: str = "test_q",
    v_precision: float = 0.5,
    v_accuracy: float = 0.5,
    v_score: float = 0.7,
    v_sources: int = 2,
    v_unique: int = 2,
    v_golden_overall: float = 0.4,
    v_golden_kw: float = 0.5,
    v_golden_src: float = 0.5,
    v_latency: float = 10.0,
    h_precision: float = 0.7,
    h_accuracy: float = 0.7,
    h_score: float = 0.8,
    h_sources: int = 2,
    h_unique: int = 3,
    h_golden_overall: float = 0.6,
    h_golden_kw: float = 0.7,
    h_golden_src: float = 0.7,
    h_latency: float = 12.0,
) -> QueryABResult:
    return QueryABResult(
        query=f"question for {label}",
        label=label,
        vector_retrieval=RetrievalMetrics(
            precision_at_k=v_precision,
            source_accuracy=v_accuracy,
            total_chunks_retrieved=v_sources,
            unique_sources_retrieved=v_unique,
            avg_score=v_score,
        ),
        vector_answer="The Pro plan costs $19 per month.",
        vector_sources=[SourceInfo(url="https://example.com/pricing", title="Pricing", score=0.9)],
        vector_golden=GoldenMetrics(
            keyword_coverage_score=v_golden_kw,
            source_accuracy_score=v_golden_src,
            answer_completeness_score=1.0,
            concept_coverage_score=1.0,
            overall_quality_score=v_golden_overall,
        ),
        vector_latency_ms=v_latency,
        hybrid_retrieval=RetrievalMetrics(
            precision_at_k=h_precision,
            source_accuracy=h_accuracy,
            total_chunks_retrieved=h_sources,
            unique_sources_retrieved=h_unique,
            avg_score=h_score,
        ),
        hybrid_answer="The Pro plan costs $19 per month.",
        hybrid_sources=[SourceInfo(url="https://example.com/pricing", title="Pricing", score=0.9)],
        hybrid_golden=GoldenMetrics(
            keyword_coverage_score=h_golden_kw,
            source_accuracy_score=h_golden_src,
            answer_completeness_score=1.0,
            concept_coverage_score=1.0,
            overall_quality_score=h_golden_overall,
        ),
        hybrid_latency_ms=h_latency,
    )


# ---------------------------------------------------------------------------
# compute_ab_report — pure function tests
# ---------------------------------------------------------------------------


def test_ab_report_empty() -> None:
    report = compute_ab_report([])
    assert report.query_count == 0
    assert report.recommendation == "No queries evaluated."


def test_ab_report_single_result() -> None:
    r = _make_query_result(label="q1", v_precision=0.5, h_precision=0.8)
    report = compute_ab_report([r])
    assert report.query_count == 1
    assert report.vector_precision_mean == 0.5
    assert report.hybrid_precision_mean == 0.8
    assert report.precision_improvement_pct == 60.0


def test_ab_report_multiple_results() -> None:
    r1 = _make_query_result(label="q1", v_precision=0.4, h_precision=0.7)
    r2 = _make_query_result(label="q2", v_precision=0.6, h_precision=0.9)
    report = compute_ab_report([r1, r2])
    assert report.query_count == 2
    assert report.vector_precision_mean == 0.5
    assert report.hybrid_precision_mean == 0.8
    assert report.precision_improvement_pct == 60.0


def test_ab_report_latency_delta() -> None:
    r1 = _make_query_result(v_latency=10.0, h_latency=15.0)
    r2 = _make_query_result(v_latency=20.0, h_latency=25.0)
    report = compute_ab_report([r1, r2])
    assert report.vector_latency_mean == 15.0
    assert report.hybrid_latency_mean == 20.0
    assert report.latency_delta_ms == 5.0


def test_ab_report_regression() -> None:
    r = _make_query_result(
        v_precision=0.9,
        h_precision=0.5,
        v_accuracy=0.9,
        h_accuracy=0.5,
        v_golden_overall=0.9,
        h_golden_overall=0.5,
    )
    report = compute_ab_report([r])
    assert report.precision_improvement_pct < 0
    assert report.source_accuracy_improvement_pct < 0
    assert report.golden_overall_improvement_pct < 0
    assert "DO NOT ENABLE" in report.recommendation


def test_ab_report_neutral() -> None:
    r = _make_query_result(
        v_precision=0.5,
        h_precision=0.5,
        v_accuracy=0.5,
        h_accuracy=0.5,
        v_golden_overall=0.5,
        h_golden_overall=0.5,
    )
    report = compute_ab_report([r])
    assert report.precision_improvement_pct == 0.0
    assert report.source_accuracy_improvement_pct == 0.0
    assert report.golden_overall_improvement_pct == 0.0
    assert "NEUTRAL" in report.recommendation


def test_ab_report_mixed() -> None:
    r = _make_query_result(
        v_precision=0.5,
        h_precision=0.8,  # improvement
        v_accuracy=0.8,
        h_accuracy=0.5,  # regression
        v_golden_overall=0.5,
        h_golden_overall=0.5,
    )
    report = compute_ab_report([r])
    assert "MIXED" in report.recommendation
    assert "improved" in report.recommendation
    assert "regressed" in report.recommendation


def test_ab_report_recommendation_latency_significant() -> None:
    r1 = _make_query_result(v_latency=10.0, h_latency=100.0)
    r2 = _make_query_result(v_latency=10.0, h_latency=100.0)
    report = compute_ab_report([r1, r2])
    assert "significant" in report.recommendation.lower()


def test_ab_report_recommendation_latency_ok() -> None:
    r1 = _make_query_result(v_latency=10.0, h_latency=12.0)
    r2 = _make_query_result(v_latency=10.0, h_latency=12.0)
    report = compute_ab_report([r1, r2])
    assert "minimal" in report.recommendation.lower()


def test_ab_report_per_query_breakdown() -> None:
    r1 = _make_query_result(label="q1")
    r2 = _make_query_result(label="q2")
    report = compute_ab_report([r1, r2])
    assert len(report.per_query) == 2
    assert report.per_query[0].label == "q1"
    assert report.per_query[1].label == "q2"


# ---------------------------------------------------------------------------
# format_ab_report — string output tests
# ---------------------------------------------------------------------------


def test_format_ab_report_empty() -> None:
    report = compute_ab_report([])
    text = format_ab_report(report)
    assert "Hybrid Search A/B Evaluation Report" in text
    assert "No queries evaluated" in text


def test_format_ab_report_structure() -> None:
    r = _make_query_result(label="pricing_q")
    report = compute_ab_report([r])
    text = format_ab_report(report)
    assert "Retrieval Quality" in text
    assert "Golden Quality" in text
    assert "Latency" in text
    assert "Per-Query Breakdown" in text
    assert "Recommendation" in text
    assert "pricing_q" in text


def test_format_ab_report_recommendation_recommends() -> None:
    r = _make_query_result(
        v_precision=0.5,
        h_precision=0.8,
        v_accuracy=0.5,
        h_accuracy=0.8,
        v_golden_overall=0.5,
        h_golden_overall=0.8,
    )
    report = compute_ab_report([r])
    text = format_ab_report(report)
    assert "RECOMMEND" in text


def test_format_ab_report_recommendation_do_not_enable() -> None:
    r = _make_query_result(
        v_precision=0.9,
        h_precision=0.5,
        v_accuracy=0.9,
        h_accuracy=0.5,
        v_golden_overall=0.9,
        h_golden_overall=0.5,
    )
    report = compute_ab_report([r])
    text = format_ab_report(report)
    assert "DO NOT ENABLE" in text


# ---------------------------------------------------------------------------
# _improvement_pct edge cases
# ---------------------------------------------------------------------------


def test_improvement_pct_zero_baseline() -> None:
    from backend.benchmark.ab_evaluation import _improvement_pct

    assert _improvement_pct(0.0, 0.5) == 0.0


def test_improvement_pct_both_zero() -> None:
    from backend.benchmark.ab_evaluation import _improvement_pct

    assert _improvement_pct(0.0, 0.0) == 0.0


def test_improvement_pct_negative() -> None:
    from backend.benchmark.ab_evaluation import _improvement_pct

    result = _improvement_pct(1.0, 0.5)
    assert result == -50.0


def test_improvement_pct_positive() -> None:
    from backend.benchmark.ab_evaluation import _improvement_pct

    result = _improvement_pct(0.5, 1.0)
    assert result == 100.0


# ---------------------------------------------------------------------------
# _mean edge cases
# ---------------------------------------------------------------------------


def test_mean_empty() -> None:
    from backend.benchmark.ab_evaluation import _mean

    assert _mean([]) == 0.0


def test_mean_single() -> None:
    from backend.benchmark.ab_evaluation import _mean

    assert _mean([3.14]) == 3.14


def test_mean_multiple() -> None:
    from backend.benchmark.ab_evaluation import _mean

    assert _mean([1.0, 2.0, 3.0]) == 2.0


# ---------------------------------------------------------------------------
# End-to-end: run_ab_evaluation with seeded data
# ---------------------------------------------------------------------------


async def test_run_ab_evaluation_basic() -> None:
    env = build_chat_env(deltas=["The", " pricing", " plan", " is", " $19", " per", " month."])
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=2)
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Pro plan costs $19 per month with 10GB storage.",
        url="https://example.com/pricing",
        title="Pricing",
        chunk_index=0,
    )
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Enterprise plan includes SSO and audit logs.",
        url="https://example.com/enterprise",
        title="Enterprise",
        chunk_index=1,
    )

    case = GoldenCase(
        question="What pricing plans do you offer?",
        label="pricing_plans",
        expected_keywords=["plan", "price"],
        expected_sources=["/pricing"],
        min_answer_length=10,
        expected_concepts=["pricing", "plans"],
    )

    result = await run_ab_evaluation(
        env=env,
        golden_case=case,
        tenant_id=TENANT,
        website_id=WEBSITE,
        question="What pricing plans do you offer?",
        top_k=2,
    )

    assert result.label == "pricing_plans"
    assert result.query == "What pricing plans do you offer?"
    assert result.vector_retrieval.total_chunks_retrieved >= 1
    assert result.hybrid_retrieval.total_chunks_retrieved >= 1
    assert result.vector_latency_ms > 0
    assert result.hybrid_latency_ms > 0
    assert result.vector_answer != "" or result.vector_answer == result.hybrid_answer


async def test_run_ab_evaluation_fallback() -> None:
    """When the website has no chunks, vector pipeline falls back."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=0)

    case = GoldenCase(
        question="test?",
        label="fallback_q",
        expected_keywords=[],
        expected_sources=[],
        min_answer_length=0,
        expected_concepts=[],
    )

    result = await run_ab_evaluation(
        env=env,
        golden_case=case,
        tenant_id=TENANT,
        website_id=WEBSITE,
        question="test?",
        top_k=3,
    )

    assert result.vector_retrieval.total_chunks_retrieved == 0
    assert result.vector_latency_ms > 0


async def test_run_ab_evaluation_full_report() -> None:
    """Seed data, run A/B evaluation, and compute + format the full report."""
    env = build_chat_env(deltas=["The", " plan", " is", " great."])
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=3)
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Pro plan costs $19 per month.",
        url="https://example.com/pricing",
        title="Pricing",
        chunk_index=0,
    )
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Enterprise includes SSO.",
        url="https://example.com/enterprise",
        title="Enterprise",
        chunk_index=1,
    )
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Free trial gives 14 days.",
        url="https://example.com/trial",
        title="Trial",
        chunk_index=2,
    )

    case = GoldenCase(
        question="Tell me about plans",
        label="plans_q",
        expected_keywords=["plan"],
        expected_sources=["/pricing"],
        min_answer_length=10,
        expected_concepts=["plan"],
    )

    result = await run_ab_evaluation(
        env=env,
        golden_case=case,
        tenant_id=TENANT,
        website_id=WEBSITE,
        question="Tell me about plans",
        top_k=3,
    )

    report = compute_ab_report([result])
    assert report.query_count == 1
    assert report.vector_latency_mean > 0
    assert report.hybrid_latency_mean > 0

    text = format_ab_report(report)
    assert "Retrieval Quality" in text
    assert "Golden Quality" in text
    assert "Latency" in text
    assert "plans_q" in text


# ---------------------------------------------------------------------------
# QueryABResult frozen
# ---------------------------------------------------------------------------


def test_query_ab_result_frozen() -> None:
    r = _make_query_result(label="frozen_q")
    assert r.label == "frozen_q"
    assert r.query == "question for frozen_q"
    assert r.vector_retrieval.precision_at_k == 0.5
    assert r.hybrid_retrieval.precision_at_k == 0.7
    assert r.vector_golden.overall_quality_score == 0.4
    assert r.hybrid_golden.overall_quality_score == 0.6


# ---------------------------------------------------------------------------
# ABReport dataclass defaults
# ---------------------------------------------------------------------------


def test_ab_report_defaults() -> None:
    r = ABReport()
    assert r.query_count == 0
    assert r.vector_precision_mean == 0.0
    assert r.hybrid_precision_mean == 0.0
    assert r.per_query == []
    assert r.recommendation == ""


# ---------------------------------------------------------------------------
# Golden metrics aggregation
# ---------------------------------------------------------------------------


def test_ab_report_golden_aggregation() -> None:
    r1 = _make_query_result(
        v_golden_overall=0.6,
        h_golden_overall=0.8,
        v_golden_kw=0.5,
        h_golden_kw=0.7,
        v_golden_src=0.4,
        h_golden_src=0.9,
    )
    r2 = _make_query_result(
        v_golden_overall=0.4,
        h_golden_overall=0.6,
        v_golden_kw=0.3,
        h_golden_kw=0.5,
        v_golden_src=0.6,
        h_golden_src=0.8,
    )
    report = compute_ab_report([r1, r2])
    assert report.vector_golden_overall_mean == 0.5
    assert report.hybrid_golden_overall_mean == 0.7
    assert report.vector_keyword_coverage_mean == 0.4
    assert report.hybrid_keyword_coverage_mean == 0.6
    assert report.vector_context_coverage_mean == 0.5
    assert report.hybrid_context_coverage_mean == 0.85
    assert report.golden_overall_improvement_pct == 40.0


def test_ab_report_retrieval_aggregation() -> None:
    r1 = _make_query_result(
        v_precision=0.6,
        h_precision=0.9,
        v_accuracy=0.5,
        h_accuracy=0.8,
        v_score=0.7,
        h_score=0.85,
        v_unique=2,
        h_unique=3,
    )
    r2 = _make_query_result(
        v_precision=0.4,
        h_precision=0.7,
        v_accuracy=0.6,
        h_accuracy=0.9,
        v_score=0.6,
        h_score=0.8,
        v_unique=1,
        h_unique=4,
    )
    report = compute_ab_report([r1, r2])
    assert report.vector_precision_mean == 0.5
    assert report.hybrid_precision_mean == 0.8
    assert report.vector_source_accuracy_mean == 0.55
    assert report.hybrid_source_accuracy_mean == 0.85
    assert report.vector_avg_score_mean == 0.65
    assert report.hybrid_avg_score_mean == 0.825
    assert report.vector_unique_sources_mean == 1.5
    assert report.hybrid_unique_sources_mean == 3.5


# ---------------------------------------------------------------------------
# __all__ exports
# ---------------------------------------------------------------------------


def test_module_all() -> None:
    from backend.benchmark import ab_evaluation as mod

    assert hasattr(mod, "ABReport")
    assert hasattr(mod, "QueryABResult")
    assert hasattr(mod, "compute_ab_report")
    assert hasattr(mod, "format_ab_report")
    assert hasattr(mod, "run_ab_evaluation")
