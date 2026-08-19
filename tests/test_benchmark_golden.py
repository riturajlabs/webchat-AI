"""Tests for the RAG golden dataset evaluation framework (Phase 3 Step 5).

Covers golden metric calculations, dataset loading, report integration,
and end-to-end runner golden capture.
"""

from backend.benchmark.evaluation import SourceInfo
from backend.benchmark.golden import GoldenCase, GoldenDataset
from backend.benchmark.golden_eval import GoldenMetrics, evaluate_golden
from backend.benchmark.report import compute_summary, format_report
from backend.benchmark.runner import BenchmarkRequest, BenchmarkRunner

from tests.chat_helpers import build_chat_env, make_chunk, make_website

TENANT = "bench-tenant"
WEBSITE = "bench-web"


# ---------------------------------------------------------------------------
# GoldenCase / GoldenDataset
# ---------------------------------------------------------------------------


def test_golden_case_defaults() -> None:
    case = GoldenCase(question="Hello?")
    assert case.label == ""
    assert case.expected_keywords == []
    assert case.expected_sources == []
    assert case.min_answer_length == 10
    assert case.expected_concepts == []
    assert case.short_label == "Hello?"


def test_golden_case_short_label() -> None:
    case = GoldenCase(question="Long question text", label="ql")
    assert case.short_label == "ql"


def test_golden_dataset_load_default() -> None:
    ds = GoldenDataset.load_default()
    assert len(ds) == 6
    labels = [c.label for c in ds]
    assert "pricing_plans" in labels
    assert "free_trial" in labels


def test_golden_dataset_iter() -> None:
    ds = GoldenDataset(cases=[GoldenCase(question="A"), GoldenCase(question="B")])
    collected: list[GoldenCase] = list(ds)
    assert len(collected) == 2


# ---------------------------------------------------------------------------
# evaluate_golden — keyword coverage
# ---------------------------------------------------------------------------


def test_keyword_coverage_all_found() -> None:
    case = GoldenCase(question="q", expected_keywords=["price", "plan"])
    m = evaluate_golden(answer="The price plan is $19.", sources=[], case=case)
    assert m.keyword_coverage_score == 1.0


def test_keyword_coverage_partial() -> None:
    case = GoldenCase(question="q", expected_keywords=["price", "plan", "trial"])
    m = evaluate_golden(answer="The price is $19.", sources=[], case=case)
    assert abs(m.keyword_coverage_score - 1 / 3) < 0.01


def test_keyword_coverage_none_found() -> None:
    case = GoldenCase(question="q", expected_keywords=["price", "plan"])
    m = evaluate_golden(answer="No relevant info.", sources=[], case=case)
    assert m.keyword_coverage_score == 0.0


def test_keyword_coverage_empty_answer() -> None:
    case = GoldenCase(question="q", expected_keywords=["price"])
    m = evaluate_golden(answer="", sources=[], case=case)
    assert m.keyword_coverage_score == 0.0


def test_keyword_coverage_no_expected() -> None:
    case = GoldenCase(question="q", expected_keywords=[])
    m = evaluate_golden(answer="Anything.", sources=[], case=case)
    assert m.keyword_coverage_score == 1.0


def test_keyword_coverage_case_insensitive() -> None:
    case = GoldenCase(question="q", expected_keywords=["PRICE"])
    m = evaluate_golden(answer="the price is $19.", sources=[], case=case)
    assert m.keyword_coverage_score == 1.0


# ---------------------------------------------------------------------------
# evaluate_golden — source accuracy
# ---------------------------------------------------------------------------


def test_source_accuracy_all_found() -> None:
    case = GoldenCase(question="q", expected_sources=["/pricing", "/faq"])
    srcs = [
        SourceInfo(url="https://example.com/pricing", title="Pricing"),
        SourceInfo(url="https://example.com/faq", title="FAQ"),
    ]
    m = evaluate_golden(answer="Answer.", sources=srcs, case=case)
    assert m.source_accuracy_score == 1.0


def test_source_accuracy_partial() -> None:
    case = GoldenCase(question="q", expected_sources=["/pricing", "/faq", "/teams"])
    srcs = [SourceInfo(url="https://example.com/pricing", title="Pricing")]
    m = evaluate_golden(answer="Answer.", sources=srcs, case=case)
    assert abs(m.source_accuracy_score - 1 / 3) < 0.01


def test_source_accuracy_no_sources() -> None:
    case = GoldenCase(question="q", expected_sources=["/pricing"])
    m = evaluate_golden(answer="Answer.", sources=[], case=case)
    assert m.source_accuracy_score == 0.0


def test_source_accuracy_no_expected() -> None:
    case = GoldenCase(question="q", expected_sources=[])
    m = evaluate_golden(answer="Answer.", sources=[], case=case)
    assert m.source_accuracy_score == 1.0


def test_source_accuracy_case_insensitive() -> None:
    case = GoldenCase(question="q", expected_sources=["/Pricing"])
    srcs = [SourceInfo(url="https://example.com/pricing")]
    m = evaluate_golden(answer="Answer.", sources=srcs, case=case)
    assert m.source_accuracy_score == 1.0


# ---------------------------------------------------------------------------
# evaluate_golden — answer completeness
# ---------------------------------------------------------------------------


def test_completeness_met() -> None:
    case = GoldenCase(question="q", min_answer_length=10)
    m = evaluate_golden(answer="This is a long enough answer.", sources=[], case=case)
    assert m.answer_completeness_score == 1.0


def test_completeness_not_met() -> None:
    case = GoldenCase(question="q", min_answer_length=50)
    m = evaluate_golden(answer="Short.", sources=[], case=case)
    assert m.answer_completeness_score == 0.0


def test_completeness_exact_boundary() -> None:
    case = GoldenCase(question="q", min_answer_length=5)
    m = evaluate_golden(answer="12345", sources=[], case=case)
    assert m.answer_completeness_score == 1.0


def test_completeness_zero_min() -> None:
    case = GoldenCase(question="q", min_answer_length=0)
    m = evaluate_golden(answer="", sources=[], case=case)
    assert m.answer_completeness_score == 1.0


# ---------------------------------------------------------------------------
# evaluate_golden — concept coverage
# ---------------------------------------------------------------------------


def test_concept_coverage_all() -> None:
    case = GoldenCase(question="q", expected_concepts=["pricing", "plan"])
    m = evaluate_golden(answer="Our pricing plan starts at $19.", sources=[], case=case)
    assert m.concept_coverage_score == 1.0


def test_concept_coverage_partial() -> None:
    case = GoldenCase(question="q", expected_concepts=["pricing", "plan", "trial"])
    m = evaluate_golden(answer="Our pricing is competitive.", sources=[], case=case)
    assert abs(m.concept_coverage_score - 1 / 3) < 0.01


def test_concept_coverage_none() -> None:
    case = GoldenCase(question="q", expected_concepts=["pricing"])
    m = evaluate_golden(answer="Nothing relevant.", sources=[], case=case)
    assert m.concept_coverage_score == 0.0


def test_concept_coverage_no_expected() -> None:
    case = GoldenCase(question="q", expected_concepts=[])
    m = evaluate_golden(answer="Anything.", sources=[], case=case)
    assert m.concept_coverage_score == 1.0


# ---------------------------------------------------------------------------
# evaluate_golden — overall score
# ---------------------------------------------------------------------------


def test_overall_score_perfect() -> None:
    case = GoldenCase(
        question="q",
        expected_keywords=["price"],
        expected_sources=["/pricing"],
        min_answer_length=5,
        expected_concepts=["price"],
    )
    srcs = [SourceInfo(url="https://example.com/pricing")]
    m = evaluate_golden(answer="The price is $19 per month.", sources=srcs, case=case)
    # All sub-scores = 1.0, so overall = 1.0
    assert m.overall_quality_score == 1.0


def test_overall_score_zero() -> None:
    case = GoldenCase(
        question="q",
        expected_keywords=["price", "plan"],
        expected_sources=["/pricing"],
        min_answer_length=50,
        expected_concepts=["pricing"],
    )
    m = evaluate_golden(answer="No.", sources=[], case=case)
    # All sub-scores = 0.0, so overall = 0.0
    assert m.overall_quality_score == 0.0


def test_overall_score_weighted() -> None:
    case = GoldenCase(
        question="q",
        expected_keywords=["price"],
        expected_sources=["/pricing"],
        min_answer_length=5,
        expected_concepts=["price"],
    )
    # Only keyword matched (1.0), source missing (0.0), long enough (1.0), concept matched (1.0)
    m = evaluate_golden(answer="The price is great.", sources=[], case=case)
    expected = 0.35 * 1.0 + 0.30 * 0.0 + 0.20 * 1.0 + 0.15 * 1.0
    assert abs(m.overall_quality_score - round(expected, 4)) < 0.01


# ---------------------------------------------------------------------------
# GoldenMetrics defaults
# ---------------------------------------------------------------------------


def test_golden_metrics_defaults() -> None:
    m = GoldenMetrics()
    assert m.keyword_coverage_score == 0.0
    assert m.source_accuracy_score == 0.0
    assert m.answer_completeness_score == 0.0
    assert m.concept_coverage_score == 0.0
    assert m.overall_quality_score == 0.0


# ---------------------------------------------------------------------------
# Report golden aggregation
# ---------------------------------------------------------------------------


def test_report_golden_empty() -> None:
    report = compute_summary([])
    assert report.golden_case_count == 0
    assert report.golden_overall.mean == 0.0


def test_report_golden_aggregation() -> None:
    requests = [
        BenchmarkRequest(
            query_label="q1",
            total_ms=100.0,
            provider="gemini",
            golden_metrics=GoldenMetrics(
                keyword_coverage_score=1.0,
                source_accuracy_score=0.8,
                answer_completeness_score=1.0,
                concept_coverage_score=0.9,
                overall_quality_score=0.92,
            ),
        ),
        BenchmarkRequest(
            query_label="q2",
            total_ms=80.0,
            provider="gemini",
            golden_metrics=GoldenMetrics(
                keyword_coverage_score=0.5,
                source_accuracy_score=0.0,
                answer_completeness_score=0.0,
                concept_coverage_score=0.5,
                overall_quality_score=0.30,
            ),
        ),
    ]
    report = compute_summary(requests)
    assert report.golden_case_count == 2
    assert report.golden_overall.mean == 0.61
    assert report.golden_keyword.mean == 0.75
    assert report.golden_source.mean == 0.4
    assert report.golden_completeness.mean == 0.5
    assert report.golden_concept.mean == 0.7


def test_report_golden_with_errors() -> None:
    """Errors are excluded from golden aggregation."""
    requests = [
        BenchmarkRequest(
            query_label="ok",
            provider="gemini",
            golden_metrics=GoldenMetrics(overall_quality_score=0.9),
        ),
        BenchmarkRequest(
            query_label="err",
            error="Timeout",
            golden_metrics=GoldenMetrics(overall_quality_score=0.5),
        ),
    ]
    report = compute_summary(requests)
    assert report.golden_case_count == 1
    assert report.golden_overall.mean == 0.9


# ---------------------------------------------------------------------------
# format_report — golden section
# ---------------------------------------------------------------------------


def test_format_report_contains_golden_section() -> None:
    requests = [
        BenchmarkRequest(
            query_label="q1",
            total_ms=100.0,
            provider="gemini",
            golden_metrics=GoldenMetrics(
                keyword_coverage_score=0.9,
                source_accuracy_score=0.8,
                overall_quality_score=0.85,
                answer_completeness_score=1.0,
                concept_coverage_score=0.7,
            ),
        ),
    ]
    text = format_report(compute_summary(requests))
    assert "Golden Dataset" in text
    assert "Cases evaluated" in text
    assert "Overall score" in text
    assert "Keyword coverage" in text
    assert "Source accuracy" in text
    assert "Completeness" in text
    assert "Concept coverage" in text


def test_format_report_no_golden_section_when_empty() -> None:
    requests = [
        BenchmarkRequest(
            query_label="q1",
            total_ms=100.0,
            provider="gemini",
        ),
    ]
    text = format_report(compute_summary(requests))
    assert "Golden Dataset" not in text


# ---------------------------------------------------------------------------
# Runner golden capture (end-to-end)
# ---------------------------------------------------------------------------


async def test_runner_captures_golden_metrics() -> None:
    from backend.benchmark.queries import BenchmarkQuery

    env = build_chat_env(deltas=["The ", "price ", "is $19."])
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Pro plan costs $19/mo.",
        url="https://example.com/pricing",
        title="Pricing",
    )

    runner = BenchmarkRunner(
        queries=[
            BenchmarkQuery(
                text="What is the price?",
                label="pricing",
                expected_fragment="$19",
            ),
        ],
        tenant_id=TENANT,
        website_id=WEBSITE,
        golden_cases=[
            GoldenCase(
                question="What is the price?",
                label="pricing",
                expected_keywords=["price"],
                expected_sources=["/pricing"],
                min_answer_length=10,
            ),
        ],
    )
    results = await runner.run(env=env)

    assert len(results) == 1
    gm = results[0].golden_metrics
    assert gm.keyword_coverage_score > 0.0
    assert gm.overall_quality_score > 0.0
    assert gm.answer_completeness_score == 1.0


async def test_runner_no_golden_when_not_provided() -> None:
    from backend.benchmark.queries import BenchmarkQuery

    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="Data.")

    runner = BenchmarkRunner(
        queries=[BenchmarkQuery(text="What data?", label="data")],
        tenant_id=TENANT,
        website_id=WEBSITE,
    )
    results = await runner.run(env=env)

    assert len(results) == 1
    gm = results[0].golden_metrics
    assert gm.overall_quality_score == 0.0


async def test_runner_golden_label_mismatch() -> None:
    """Golden case with non-matching label is not applied."""
    from backend.benchmark.queries import BenchmarkQuery

    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="Data.")

    runner = BenchmarkRunner(
        queries=[BenchmarkQuery(text="What data?", label="data")],
        tenant_id=TENANT,
        website_id=WEBSITE,
        golden_cases=[
            GoldenCase(
                question="Other question",
                label="other",
                expected_keywords=["xyz"],
            ),
        ],
    )
    results = await runner.run(env=env)

    assert len(results) == 1
    assert results[0].golden_metrics.overall_quality_score == 0.0


async def test_runner_golden_isolation() -> None:
    """Golden evaluation does not modify the environment state."""
    from backend.benchmark.queries import BenchmarkQuery

    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="Knowledge.")

    messages_before = len(env.messages.messages)
    vector_before = len(env.vector.chunks)

    runner = BenchmarkRunner(
        queries=[BenchmarkQuery(text="Test?", label="t")],
        tenant_id=TENANT,
        website_id=WEBSITE,
        golden_cases=[
            GoldenCase(
                question="Test?",
                label="t",
                expected_keywords=["knowledge"],
                expected_sources=["/page"],
            ),
        ],
    )
    await runner.run(env=env)

    assert len(env.messages.messages) == messages_before + 2
    assert len(env.vector.chunks) == vector_before


async def test_runner_golden_in_full_report() -> None:
    """End-to-end: runner -> compute_summary -> format_report includes golden."""
    from backend.benchmark.queries import BenchmarkQuery

    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="Data.")

    runner = BenchmarkRunner(
        queries=[BenchmarkQuery(text="What data?", label="d")],
        tenant_id=TENANT,
        website_id=WEBSITE,
        golden_cases=[
            GoldenCase(
                question="What data?",
                label="d",
                expected_keywords=["data"],
                min_answer_length=5,
            ),
        ],
    )
    results = await runner.run(env=env)
    report = compute_summary(results)
    text = format_report(report)

    assert "Golden Dataset" in text
    assert "Cases evaluated:  1" in text
