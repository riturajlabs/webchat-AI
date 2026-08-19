"""Tests for the AI latency benchmark system (Phase 3 Step 3).

Exercises the statistical helpers, report generation, and the full runner
pipeline using in-memory fakes — no network, no MongoDB.
"""

from backend.benchmark.report import _percentile, _stats_for, compute_summary, format_report
from backend.benchmark.runner import BenchmarkRequest, BenchmarkRunner

from tests.chat_helpers import build_chat_env, make_chunk, make_website

TENANT = "bench-tenant"
WEBSITE = "bench-web"


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------


def test_percentile_empty() -> None:
    assert _percentile([], 95) == 0.0


def test_percentile_single() -> None:
    assert _percentile([42.0], 95) == 42.0


def test_percentile_even_count() -> None:
    values = [1.0, 2.0, 3.0, 4.0]
    p50 = _percentile(values, 50)
    assert p50 == 2.0


def test_percentile_odd_count() -> None:
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    p95 = _percentile(values, 95)
    assert p95 == 50.0


def test_percentile_high_values() -> None:
    values = list(range(1, 101))
    p95 = _percentile([float(v) for v in values], 95)
    assert p95 == 95.0


def test_stats_for_empty() -> None:
    stats = _stats_for([])
    assert stats.mean == 0.0
    assert stats.median == 0.0
    assert stats.p95 == 0.0
    assert stats.min == 0.0
    assert stats.max == 0.0


def test_stats_for_values() -> None:
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    stats = _stats_for(values)
    assert stats.mean == 30.0
    assert stats.median == 30.0
    assert stats.min == 10.0
    assert stats.max == 50.0


# ---------------------------------------------------------------------------
# compute_summary
# ---------------------------------------------------------------------------


def test_summary_empty() -> None:
    report = compute_summary([])
    assert report.request_count == 0
    assert report.success_count == 0
    assert report.error_count == 0
    assert report.provider_success_rate == 0.0
    assert report.fallback_rate == 0.0
    assert report.cache_hit_rate == 0.0


def test_summary_all_successful() -> None:
    requests = [
        BenchmarkRequest(
            query_label="q1",
            total_ms=100.0,
            ttft_ms=30.0,
            generation_ms=60.0,
            embedding_ms=5.0,
            retrieval_ms=5.0,
            provider="gemini",
            fallback=False,
            embedding_cache="miss",
            estimated_prompt_tokens=150,
        ),
        BenchmarkRequest(
            query_label="q2",
            total_ms=200.0,
            ttft_ms=50.0,
            generation_ms=130.0,
            embedding_ms=10.0,
            retrieval_ms=10.0,
            provider="gemini",
            fallback=False,
            embedding_cache="hit",
            estimated_prompt_tokens=200,
        ),
        BenchmarkRequest(
            query_label="q3",
            total_ms=150.0,
            ttft_ms=40.0,
            generation_ms=90.0,
            embedding_ms=7.0,
            retrieval_ms=8.0,
            provider="gemini",
            fallback=True,
            embedding_cache="miss",
            estimated_prompt_tokens=180,
        ),
    ]
    report = compute_summary(requests)

    assert report.request_count == 3
    assert report.success_count == 3
    assert report.error_count == 0
    assert report.total_latency.mean == 150.0
    assert report.total_latency.min == 100.0
    assert report.total_latency.max == 200.0
    assert report.provider_success_rate == 100.0
    assert report.fallback_rate == round(1 / 3 * 100, 1)
    assert report.cache_hit_rate == round(1 / 3 * 100, 1)
    assert report.fallback_attempts_total == 0
    assert report.estimated_tokens_total == 530
    assert report.provider_counts == {"gemini": 3}
    assert len(report.per_request) == 3


def test_summary_with_errors() -> None:
    requests = [
        BenchmarkRequest(query_label="ok", total_ms=100.0, provider="gemini"),
        BenchmarkRequest(query_label="err", total_ms=50.0, error="Timeout"),
    ]
    report = compute_summary(requests)

    assert report.request_count == 2
    assert report.success_count == 1
    assert report.error_count == 1
    assert report.total_latency.mean == 100.0
    assert report.provider_success_rate == 50.0
    assert report.fallback_rate == 0.0


def test_summary_with_fallback_attempts() -> None:
    requests = [
        BenchmarkRequest(query_label="q1", total_ms=100.0, fallback_attempts=2),
        BenchmarkRequest(query_label="q2", total_ms=120.0, fallback_attempts=1),
    ]
    report = compute_summary(requests)
    assert report.fallback_attempts_total == 3


def test_summary_provider_counts() -> None:
    requests = [
        BenchmarkRequest(query_label="q1", provider="gemini"),
        BenchmarkRequest(query_label="q2", provider="groq"),
        BenchmarkRequest(query_label="q3", provider="gemini"),
        BenchmarkRequest(query_label="q4", provider="unknown"),
    ]
    report = compute_summary(requests)
    assert report.provider_counts == {"gemini": 2, "groq": 1, "unknown": 1}


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------


def test_format_report_contains_sections() -> None:
    report = compute_summary(
        [
            BenchmarkRequest(
                query_label="q1",
                total_ms=100.0,
                provider="gemini",
            ),
        ]
    )
    text = format_report(report)
    assert "AI Benchmark Report" in text
    assert "Requests:" in text
    assert "Latency (ms)" in text
    assert "Rates" in text
    assert "Providers" in text


def test_format_report_empty() -> None:
    text = format_report(compute_summary([]))
    assert "Requests:" in text
    assert "0" in text


# ---------------------------------------------------------------------------
# BenchmarkRunner
# ---------------------------------------------------------------------------


async def test_runner_executes_queries() -> None:
    from backend.benchmark.queries import BenchmarkQuery

    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="Pro plan costs $19/mo.")

    runner = BenchmarkRunner(
        queries=[
            BenchmarkQuery(text="What is the price?", label="price"),
            BenchmarkQuery(text="Do you have a trial?", label="trial"),
        ],
        tenant_id=TENANT,
        website_id=WEBSITE,
    )
    results = await runner.run(env=env)

    assert len(results) == 2
    assert results[0].query_label == "price"
    assert results[1].query_label == "trial"
    assert results[0].total_ms >= 0
    assert results[0].provider is not None
    assert results[0].fallback is False


async def test_runner_multiple_rounds() -> None:
    from backend.benchmark.queries import BenchmarkQuery

    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="Knowledge.")

    runner = BenchmarkRunner(
        queries=[BenchmarkQuery(text="Question?", label="q")],
        rounds=3,
        tenant_id=TENANT,
        website_id=WEBSITE,
    )
    results = await runner.run(env=env)

    assert len(results) == 3


async def test_runner_creates_env_when_none() -> None:
    from backend.benchmark.queries import BenchmarkQuery

    runner = BenchmarkRunner(
        queries=[BenchmarkQuery(text="test", label="t")],
        tenant_id=TENANT,
        website_id=WEBSITE,
    )
    # Without a pre-seeded env, the website lookup fails -> error captured
    results = await runner.run(env=None)
    assert len(results) == 1
    # The request errors because the website doesn't exist
    assert results[0].error is not None


async def test_runner_captures_timing_breakdown() -> None:
    from backend.benchmark.queries import BenchmarkQuery

    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="Knowledge data.")

    runner = BenchmarkRunner(
        queries=[BenchmarkQuery(text="What data?", label="data")],
        tenant_id=TENANT,
        website_id=WEBSITE,
    )
    results = await runner.run(env=env)

    assert len(results) == 1
    r = results[0]
    assert r.total_ms > 0
    assert r.ttft_ms is not None and r.ttft_ms >= 0
    assert r.generation_ms is not None and r.generation_ms >= 0
    assert r.embedding_ms is not None and r.embedding_ms >= 0
    assert r.retrieval_ms is not None and r.retrieval_ms >= 0
    assert r.provider is not None
    assert r.estimated_prompt_tokens >= 0


async def test_runner_does_not_modify_production_state() -> None:
    """The benchmark runner must not leave any side effects in the fakes
    beyond what a normal chat request would produce."""
    from backend.benchmark.queries import BenchmarkQuery

    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT, website_id=WEBSITE, text="Knowledge.")

    runner = BenchmarkRunner(
        queries=[BenchmarkQuery(text="Test?", label="t")],
        tenant_id=TENANT,
        website_id=WEBSITE,
    )
    messages_before = len(env.messages.messages)
    await runner.run(env=env)
    # Each request creates 1 user + 1 assistant message
    assert len(env.messages.messages) == messages_before + 2
