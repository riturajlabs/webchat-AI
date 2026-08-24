"""Phase 3 production-metrics tests.

Covers the four required guarantees:
- `/metrics` serves Prometheus text exposition with HTTP 200;
- counters increment (HTTP, RAG, AI, cache) from existing timing/log data;
- histograms record buckets/sum/count;
- labels are tenant-safe: identifiers (tenant/session/website ids, dynamic
  path segments) never appear in the scrape output.
"""

import logging

import pytest
from backend.core.metrics import (
    MetricsLogCollector,
    attach_metrics_log_collector,
    observe_done,
    observe_sources,
    observe_sse_error,
    record_http_request,
    render_prometheus,
    reset_registry,
)
from backend.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clean_registry():
    """Isolate metric samples per test; metric definitions persist."""
    reset_registry()
    yield
    reset_registry()


def _log_record(
    msg: str,
    *args: object,
    level: int = logging.WARNING,
    **extra: object,
) -> logging.LogRecord:
    """Build a LogRecord shaped like the ones services emit."""
    record = logging.LogRecord("webchat_ai", level, __file__, 1, msg, args, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


def test_metrics_endpoint_returns_200_prometheus_format() -> None:
    client = TestClient(create_app())
    # Warm the registry first: the middleware records a finished request
    # *after* its response is sent, so a cold scrape of /metrics itself is
    # legitimately empty (the very first scrape observes nothing yet).
    assert client.get("/api/health/live").status_code == 200
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "version=0.0.4" in response.headers["content-type"]
    body = response.text
    assert "# HELP http_requests_total" in body
    assert "# TYPE http_requests_total counter" in body


def test_metrics_endpoint_exposes_live_http_counters() -> None:
    client = TestClient(create_app())
    assert client.get("/api/health/live").status_code == 200
    body = client.get("/metrics").text
    # Path label = matched route template (router-relative on this FastAPI
    # version); dynamic segments can never enter it.
    assert 'http_requests_total{method="GET", path="/health/live", status="200"} 1' in body


# ---------------------------------------------------------------------------
# HTTP metrics
# ---------------------------------------------------------------------------


def test_http_counter_increments_per_label_set() -> None:
    record_http_request(method="GET", path="/api/health", status="200", duration_seconds=0.01)
    record_http_request(method="GET", path="/api/health", status="200", duration_seconds=0.02)
    record_http_request(method="POST", path="/api/chat/stream", status="500", duration_seconds=0.5)
    body = render_prometheus()
    assert 'http_requests_total{method="GET", path="/api/health", status="200"} 2' in body
    assert 'http_requests_total{method="POST", path="/api/chat/stream", status="500"} 1' in body


def test_error_status_recorded_for_unmatched_route() -> None:
    client = TestClient(create_app())
    assert client.get("/api/does-not-exist").status_code == 404
    body = render_prometheus()
    # Unmatched requests collapse to a "-" path label (bounded cardinality).
    assert 'http_requests_total{method="GET", path="-", status="404"} 1' in body


def test_request_latency_histogram_records_buckets_sum_count() -> None:
    record_http_request(method="GET", path="/x", status="200", duration_seconds=0.02)
    record_http_request(method="GET", path="/x", status="200", duration_seconds=0.3)
    body = render_prometheus()
    assert 'http_request_duration_seconds_bucket{method="GET", path="/x", le="0.05"} 1' in body
    assert 'http_request_duration_seconds_bucket{method="GET", path="/x", le="+Inf"} 2' in body
    assert 'http_request_duration_seconds_count{method="GET", path="/x"} 2' in body
    assert "# TYPE http_request_duration_seconds histogram" in body


# ---------------------------------------------------------------------------
# RAG / AI / cache observations from SSE frames and log events
# ---------------------------------------------------------------------------


def test_retrieval_success_empty_and_average_sources_count() -> None:
    observe_sources(3)
    observe_sources(0)
    body = render_prometheus()
    assert 'rag_retrieval_total{result="success"} 1' in body
    assert 'rag_retrieval_total{result="empty"} 1' in body
    # Average sources = sum/count of the sources histogram.
    assert "rag_sources_count_sum 3" in body
    assert "rag_sources_count_count 2" in body


def test_done_frame_updates_confidence_tokens_and_generation_counters() -> None:
    observe_done(
        {
            "input_tokens": 12,
            "output_tokens": 34,
            "confidence_score": 0.85,
            "fallback": False,
        }
    )
    body = render_prometheus()
    assert "ai_generation_total 1" in body
    assert 'ai_tokens_total{kind="input"} 12' in body
    assert 'ai_tokens_total{kind="output"} 34' in body
    assert 'rag_confidence_score_bucket{le="0.9"} 1' in body
    assert "ai_fallback_total" not in body


def test_fallback_turn_counted_with_zero_token_usage() -> None:
    observe_done({"fallback": True, "input_tokens": 0, "output_tokens": 0})
    body = render_prometheus()
    assert "ai_fallback_total 1" in body
    # Fallback turns never call the model: token counters stay at zero.
    assert 'ai_tokens_total{kind="input"} 0' in body
    assert 'ai_tokens_total{kind="output"} 0' in body


def test_cache_hit_miss_from_done_timing_block() -> None:
    observe_done(
        {"timing": {"embedding_cache": "hit", "retrieval_cache": "miss"}},
    )
    observe_done({"timing": {"embedding_cache": "hit"}})
    body = render_prometheus()
    assert 'cache_operations_total{cache="embedding", result="hit"} 2' in body
    assert 'cache_operations_total{cache="retrieval", result="miss"} 1' in body


def test_provider_failures_separated_from_other_sse_errors() -> None:
    observe_sse_error("GENERATION_TIMEOUT")
    observe_sse_error("LIMIT_REACHED")
    body = render_prometheus()
    assert 'sse_errors_total{code="GENERATION_TIMEOUT"} 1' in body
    assert 'sse_errors_total{code="LIMIT_REACHED"} 1' in body
    assert 'ai_provider_failures_total{code="GENERATION_TIMEOUT"} 1' in body
    assert "LIMIT_REACHED" not in body.split("sse_errors_total")[0]


def test_ttft_observed_from_sse_transport_log_event() -> None:
    collector = MetricsLogCollector()
    collector.filter(_log_record("sse_transport", level=logging.INFO, first_token_ms=250))
    body = render_prometheus()
    assert 'ai_ttft_seconds_bucket{le="0.1"} 0' in body
    assert 'ai_ttft_seconds_bucket{le="0.25"} 1' in body
    assert "ai_ttft_seconds_count 1" in body


def test_ttft_ignores_missing_or_negative_first_token() -> None:
    collector = MetricsLogCollector()
    collector.filter(_log_record("sse_transport", level=logging.INFO))
    collector.filter(_log_record("sse_transport", level=logging.INFO, first_token_ms=-5))
    assert "ai_ttft_seconds" not in render_prometheus()


@pytest.mark.parametrize(
    "reason",
    ["knowledge_empty", "retrieval_empty", "confidence_low", "context_empty"],
)
def test_all_fallback_reasons_recorded_from_log_events(reason: str) -> None:
    collector = MetricsLogCollector()
    collector.filter(
        _log_record(
            "rag_retrieval_zero_context tenant=%s website=%s session=%s reason=%s "
            "vector_queries=%s top_k=%s scores=%s query_hash=%s query_length=%d",
            "tenant-1",
            "site-1",
            "sess-1",
            reason,
            2,
            6,
            [],
            "abc",
            12,
        )
    )
    body = render_prometheus()
    assert f'rag_fallback_total{{reason="{reason}"}} 1' in body


# ---------------------------------------------------------------------------
# Tenant-safe labels
# ---------------------------------------------------------------------------


def test_log_identifiers_never_leak_into_exposition() -> None:
    tenant_id = "tenant-9f2c8e6a-secret"
    session_id = "sess-4f7a-secret"
    website_id = "site-b1o2-secret"

    client = TestClient(create_app())  # create_app attaches the log collector.
    logging.getLogger("webchat_ai").warning(
        "rag_retrieval_zero_context tenant=%s website=%s session=%s reason=%s",
        tenant_id,
        website_id,
        session_id,
        "confidence_low",
    )

    body = client.get("/metrics").text
    assert 'rag_fallback_total{reason="confidence_low"} 1' in body
    assert tenant_id not in body
    assert website_id not in body
    assert session_id not in body


def test_dynamic_path_segments_do_not_enter_labels() -> None:
    secret_segment = "tenant-9f2c8e6a-private-id"
    client = TestClient(create_app())
    response = client.get(f"/api/{secret_segment}")
    assert response.status_code == 404

    body = client.get("/metrics").text
    assert secret_segment not in body
    assert 'path="-"' in body


def test_collector_attachment_is_idempotent() -> None:
    attach_metrics_log_collector()
    attach_metrics_log_collector()
    filters = [
        f for f in logging.getLogger("webchat_ai").filters if isinstance(f, MetricsLogCollector)
    ]
    assert len(filters) == 1


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


def test_observe_done_never_raises_on_malformed_payloads() -> None:
    observe_done(
        {
            "confidence_score": "high",
            "input_tokens": -5,
            "output_tokens": None,
            "timing": "junk",
        }
    )
    body = render_prometheus()
    assert "ai_generation_total 1" in body
    assert "ai_tokens_total" not in body
    assert "rag_confidence_score" not in body


def test_reset_registry_clears_samples_but_keeps_definitions() -> None:
    observe_sources(3)
    reset_registry()
    assert "rag_sources_count" not in render_prometheus()
    # The definition is still live and accepts new observations.
    observe_sources(2)
    assert "rag_sources_count_count 1" in render_prometheus()
