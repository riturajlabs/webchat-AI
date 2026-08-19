"""Tests for the AI quality evaluation framework (Phase 3 Step 4).

Covers quality metric calculations, missing data handling, evaluation
isolation, report integration, and end-to-end runner quality capture.
"""

from backend.benchmark.evaluation import (
    QualityMetrics,
    SourceInfo,
    evaluate_quality,
)
from backend.benchmark.report import compute_summary, format_report
from backend.benchmark.runner import BenchmarkRequest, BenchmarkRunner

from tests.chat_helpers import build_chat_env, make_chunk, make_website

TENANT = "bench-tenant"
WEBSITE = "bench-web"


# ---------------------------------------------------------------------------
# evaluate_quality — retrieval metrics
# ---------------------------------------------------------------------------


def test_empty_sources() -> None:
    q = evaluate_quality(answer="Hello world.", sources=[])
    assert q.retrieved_chunk_count == 0
    assert q.avg_relevance_score == 0.0
    assert q.context_coverage == 0.0


def test_single_source_relevance() -> None:
    src = [SourceInfo(url="https://a.com", title="A", score=0.85)]
    q = evaluate_quality(answer="The answer.", sources=src)
    assert q.retrieved_chunk_count == 1
    assert q.avg_relevance_score == 0.85


def test_avg_relevance_multiple_sources() -> None:
    srcs = [
        SourceInfo(url="https://a.com", title="A", score=0.9),
        SourceInfo(url="https://b.com", title="B", score=0.7),
        SourceInfo(url="https://c.com", title="C", score=0.5),
    ]
    q = evaluate_quality(answer="Answer.", sources=srcs)
    assert q.avg_relevance_score == 0.7  # (0.9+0.7+0.5)/3


def test_context_coverage_url_in_answer() -> None:
    srcs = [
        SourceInfo(url="https://docs.example.com/pricing", title="Pricing", score=0.9),
        SourceInfo(url="https://docs.example.com/faq", title="FAQ", score=0.8),
    ]
    answer = "See https://docs.example.com/pricing for details."
    q = evaluate_quality(answer=answer, sources=srcs)
    assert q.context_coverage == 0.5  # only 1 of 2 URLs matched


def test_context_coverage_title_in_answer() -> None:
    srcs = [
        SourceInfo(url="https://a.com/x", title="Pricing Page", score=0.9),
    ]
    answer = "The Pricing Page shows $19/mo."
    q = evaluate_quality(answer=answer, sources=srcs)
    assert q.context_coverage == 1.0


def test_context_coverage_case_insensitive() -> None:
    srcs = [SourceInfo(url="https://A.COM", title="Docs", score=0.9)]
    q = evaluate_quality(answer="Visit https://a.com for info.", sources=srcs)
    assert q.context_coverage == 1.0


def test_context_coverage_empty_answer() -> None:
    srcs = [SourceInfo(url="https://a.com", title="A", score=0.9)]
    q = evaluate_quality(answer="", sources=srcs)
    assert q.context_coverage == 0.0


def test_context_coverage_url_takes_precedence_over_title() -> None:
    src = [SourceInfo(url="https://x.com", title="Same", score=0.9)]
    q = evaluate_quality(answer="See https://x.com for details.", sources=src)
    assert q.context_coverage == 1.0


# ---------------------------------------------------------------------------
# evaluate_quality — answer metrics
# ---------------------------------------------------------------------------


def test_empty_answer() -> None:
    q = evaluate_quality(answer="", sources=[])
    assert q.response_length == 0
    assert q.is_empty is True
    assert q.citation_count == 0
    assert q.context_used is False


def test_whitespace_only_answer() -> None:
    q = evaluate_quality(answer="   \n  ", sources=[])
    assert q.response_length == 0
    assert q.is_empty is True


def test_normal_answer_not_empty() -> None:
    q = evaluate_quality(answer="The price is $19.", sources=[])
    assert q.is_empty is False
    assert q.response_length == len("The price is $19.")


def test_truncation_mid_sentence() -> None:
    long_answer = "This is a long answer that discusses many important topics and goes on"
    q = evaluate_quality(answer=long_answer, sources=[])
    assert q.is_truncated is True


def test_truncation_with_terminal_punctuation() -> None:
    answer = "This is a complete answer with a period."
    q = evaluate_quality(answer=answer, sources=[])
    assert q.is_truncated is False


def test_truncation_with_question_mark() -> None:
    answer = "Are you sure you want to know?"
    q = evaluate_quality(answer=answer, sources=[])
    assert q.is_truncated is False


def test_truncation_with_paren_close() -> None:
    answer = "The feature (also known as X) is available."
    q = evaluate_quality(answer=answer, sources=[])
    assert q.is_truncated is False


def test_truncation_with_bracket_close() -> None:
    answer = "According to the docs [1] this works."
    q = evaluate_quality(answer=answer, sources=[])
    assert q.is_truncated is False


def test_truncation_short_answer_not_truncated() -> None:
    short = "Yes, we do"
    q = evaluate_quality(answer=short, sources=[])
    assert q.is_truncated is False


def test_truncation_fallback_never_truncated() -> None:
    answer = "I couldn't find that information in the website's knowledge base."
    q = evaluate_quality(answer=answer, sources=[], fallback=True)
    assert q.is_truncated is False


def test_citation_detection_single() -> None:
    q = evaluate_quality(answer="The price is $19 [1].", sources=[])
    assert q.citation_count == 1
    assert q.context_used is True


def test_citation_detection_multiple() -> None:
    q = evaluate_quality(answer="Plan A [1] and Plan B [2] exist [3].", sources=[])
    assert q.citation_count == 3
    assert q.context_used is True


def test_citation_detection_none() -> None:
    q = evaluate_quality(answer="No citations here.", sources=[])
    assert q.citation_count == 0
    assert q.context_used is False


def test_citation_detection_multi_digit() -> None:
    q = evaluate_quality(answer="Source [12] and [345].", sources=[])
    assert q.citation_count == 2


# ---------------------------------------------------------------------------
# evaluate_quality — combined / edge cases
# ---------------------------------------------------------------------------


def test_full_quality_assessment() -> None:
    srcs = [
        SourceInfo(url="https://docs.example.com/pricing", title="Pricing", score=0.92),
        SourceInfo(url="https://docs.example.com/faq", title="FAQ", score=0.88),
    ]
    answer = (
        "The Pro plan costs $19/month [1]. For frequently asked questions "
        "see https://docs.example.com/faq [2]."
    )
    q = evaluate_quality(answer=answer, sources=srcs)
    assert q.retrieved_chunk_count == 2
    assert q.avg_relevance_score == 0.9
    assert q.context_coverage == 0.5  # only FAQ URL present
    assert q.is_empty is False
    assert q.is_truncated is False
    assert q.citation_count == 2
    assert q.context_used is True


def test_missing_data_all_defaults() -> None:
    q = QualityMetrics()
    assert q.retrieved_chunk_count == 0
    assert q.avg_relevance_score == 0.0
    assert q.context_coverage == 0.0
    assert q.response_length == 0
    assert q.is_empty is True
    assert q.is_truncated is False
    assert q.citation_count == 0
    assert q.context_used is False


def test_source_info_defaults() -> None:
    src = SourceInfo()
    assert src.url == ""
    assert src.title == ""
    assert src.score == 0.0


def test_zero_score_sources() -> None:
    srcs = [
        SourceInfo(url="https://a.com", title="A", score=0.0),
        SourceInfo(url="https://b.com", title="B", score=0.0),
    ]
    q = evaluate_quality(answer="Answer.", sources=srcs)
    assert q.avg_relevance_score == 0.0
    assert q.retrieved_chunk_count == 2


# ---------------------------------------------------------------------------
# Report quality aggregation
# ---------------------------------------------------------------------------


def test_report_quality_empty() -> None:
    report = compute_summary([])
    assert report.avg_relevance.mean == 0.0
    assert report.context_coverage.mean == 0.0
    assert report.empty_rate == 0.0
    assert report.truncation_rate == 0.0
    assert report.context_usage_rate == 0.0


def test_report_quality_aggregation() -> None:
    from backend.benchmark.evaluation import QualityMetrics

    requests = [
        BenchmarkRequest(
            query_label="q1",
            total_ms=100.0,
            provider="gemini",
            quality=QualityMetrics(
                retrieved_chunk_count=3,
                avg_relevance_score=0.9,
                context_coverage=0.6667,
                response_length=200,
                is_empty=False,
                is_truncated=False,
                citation_count=2,
                context_used=True,
            ),
        ),
        BenchmarkRequest(
            query_label="q2",
            total_ms=80.0,
            provider="gemini",
            quality=QualityMetrics(
                retrieved_chunk_count=1,
                avg_relevance_score=0.5,
                context_coverage=0.0,
                response_length=50,
                is_empty=False,
                is_truncated=True,
                citation_count=0,
                context_used=False,
            ),
        ),
        BenchmarkRequest(
            query_label="q3",
            total_ms=60.0,
            provider="gemini",
            quality=QualityMetrics(
                retrieved_chunk_count=0,
                avg_relevance_score=0.0,
                context_coverage=0.0,
                response_length=0,
                is_empty=True,
                is_truncated=False,
                citation_count=0,
                context_used=False,
            ),
        ),
    ]
    report = compute_summary(requests)

    assert report.avg_chunks_retrieved.mean == 1.33
    assert report.avg_relevance.mean == 0.47
    assert report.context_coverage.mean == 0.22
    assert report.response_length.mean == 83.33
    assert report.empty_rate == round(1 / 3 * 100, 1)
    assert report.truncation_rate == round(1 / 3 * 100, 1)
    assert report.context_usage_rate == round(1 / 3 * 100, 1)


def test_report_quality_with_errors() -> None:
    """Errors are excluded from quality aggregation (only ok requests)."""
    from backend.benchmark.evaluation import QualityMetrics

    requests = [
        BenchmarkRequest(
            query_label="ok",
            provider="gemini",
            quality=QualityMetrics(
                retrieved_chunk_count=2,
                avg_relevance_score=0.8,
                citation_count=1,
                context_used=True,
            ),
        ),
        BenchmarkRequest(
            query_label="err",
            error="Timeout",
            quality=QualityMetrics(),  # default / unused
        ),
    ]
    report = compute_summary(requests)
    # Only the ok request counts
    assert report.avg_chunks_retrieved.mean == 2.0
    assert report.avg_relevance.mean == 0.8
    assert report.context_usage_rate == 100.0


# ---------------------------------------------------------------------------
# format_report — quality section
# ---------------------------------------------------------------------------


def test_format_report_contains_quality_section() -> None:
    from backend.benchmark.evaluation import QualityMetrics

    requests = [
        BenchmarkRequest(
            query_label="q1",
            total_ms=100.0,
            provider="gemini",
            quality=QualityMetrics(
                retrieved_chunk_count=2,
                avg_relevance_score=0.85,
                context_coverage=0.5,
                response_length=150,
                citation_count=1,
                context_used=True,
            ),
        ),
    ]
    text = format_report(compute_summary(requests))
    assert "Quality" in text
    assert "Chunks retrieved" in text
    assert "Relevance score" in text
    assert "Context coverage" in text
    assert "Response length" in text
    assert "Citations" in text
    assert "Empty answers" in text
    assert "Truncated" in text
    assert "Context used" in text


def test_format_report_quality_values() -> None:
    from backend.benchmark.evaluation import QualityMetrics

    requests = [
        BenchmarkRequest(
            query_label="q1",
            total_ms=100.0,
            provider="gemini",
            quality=QualityMetrics(
                retrieved_chunk_count=2,
                avg_relevance_score=0.85,
                context_coverage=0.5,
                response_length=150,
                citation_count=1,
                context_used=True,
            ),
        ),
    ]
    text = format_report(compute_summary(requests))
    assert "0.850" in text  # relevance score
    assert "0.500" in text  # context coverage


# ---------------------------------------------------------------------------
# Runner quality capture (end-to-end)
# ---------------------------------------------------------------------------


async def test_runner_captures_quality_metrics() -> None:
    from backend.benchmark.queries import BenchmarkQuery

    env = build_chat_env()
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
                label="price",
                expected_fragment="$19",
            ),
        ],
        tenant_id=TENANT,
        website_id=WEBSITE,
    )
    results = await runner.run(env=env)

    assert len(results) == 1
    q = results[0].quality
    # The fake pipeline returns sources + a streamed answer
    assert q.retrieved_chunk_count >= 1
    assert q.avg_relevance_score > 0.0
    assert q.response_length > 0
    assert q.is_empty is False


async def test_runner_quality_on_fallback() -> None:
    from backend.benchmark.queries import BenchmarkQuery

    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEB_KNOWN_EMPTY, knowledge_chunks=0)

    runner = BenchmarkRunner(
        queries=[BenchmarkQuery(text="Anything?", label="empty")],
        tenant_id=TENANT,
        website_id=WEB_KNOWN_EMPTY,
    )
    results = await runner.run(env=env)

    assert len(results) == 1
    q = results[0].quality
    # Fallback: no retrieval, fixed answer string
    assert q.retrieved_chunk_count == 0
    assert q.context_used is False
    assert q.is_truncated is False


WEB_KNOWN_EMPTY = "bench-web-empty"


async def test_runner_quality_on_error() -> None:
    from backend.benchmark.queries import BenchmarkQuery

    # No website seeded -> WEBSITE_NOT_FOUND error -> quality defaults
    runner = BenchmarkRunner(
        queries=[BenchmarkQuery(text="test", label="t")],
        tenant_id=TENANT,
        website_id=WEBSITE,
    )
    results = await runner.run(env=None)

    assert len(results) == 1
    assert results[0].error is not None
    q = results[0].quality
    assert q.is_empty is True
    assert q.retrieved_chunk_count == 0
    assert q.citation_count == 0


async def test_runner_quality_isolation() -> None:
    """Quality evaluation does not modify the environment state."""
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
    )
    await runner.run(env=env)

    # Only chat-level side effects (user + assistant messages)
    assert len(env.messages.messages) == messages_before + 2
    # Knowledge base untouched
    assert len(env.vector.chunks) == vector_before


async def test_runner_quality_in_full_report() -> None:
    """End-to-end: runner -> compute_summary -> format_report includes quality."""
    from backend.benchmark.queries import BenchmarkQuery

    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="Data.")

    runner = BenchmarkRunner(
        queries=[BenchmarkQuery(text="What data?", label="d")],
        tenant_id=TENANT,
        website_id=WEBSITE,
    )
    results = await runner.run(env=env)
    report = compute_summary(results)
    text = format_report(report)

    assert "Quality" in text
    assert "Chunks retrieved" in text
    assert "Relevance score" in text
