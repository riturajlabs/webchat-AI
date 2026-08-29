"""Tests for Prometheus-compatible metrics (Phase 14.7)."""

from __future__ import annotations

import pytest
from backend.core.metrics import (
    record_chat_failure,
    record_chat_latency,
    record_chat_request,
    record_crawl_completed,
    record_crawl_failed,
    record_crawl_started,
    record_llm_failure,
    record_llm_latency,
    record_llm_request,
    record_llm_tokens,
    record_rag_empty,
    record_rag_latency,
    render_prometheus,
    reset_registry,
)


@pytest.fixture(autouse=True)
def _clean_metrics():
    """Reset all metric samples before each test."""
    reset_registry()
    yield
    reset_registry()


class TestChatMetrics:
    def test_chat_request_increments(self) -> None:
        record_chat_request()
        record_chat_request()
        record_chat_request()
        output = render_prometheus()
        assert "chat_requests_total 3" in output

    def test_chat_failure_records_reason(self) -> None:
        record_chat_failure(reason="knowledge_empty")
        record_chat_failure(reason="retrieval_empty")
        output = render_prometheus()
        assert 'chat_failures_total{reason="knowledge_empty"} 1' in output
        assert 'chat_failures_total{reason="retrieval_empty"} 1' in output

    def test_chat_latency_observes_value(self) -> None:
        record_chat_latency(2.5)
        record_chat_latency(5.0)
        output = render_prometheus()
        assert "chat_latency_seconds_sum 7.5" in output
        assert "chat_latency_seconds_count 2" in output


class TestLLMMetrics:
    def test_llm_request_records_provider(self) -> None:
        record_llm_request(provider="gemini")
        record_llm_request(provider="gemini")
        output = render_prometheus()
        assert 'llm_requests_total{provider="gemini"} 2' in output

    def test_llm_failure_records_code(self) -> None:
        record_llm_failure(code="GENERATION_FAILED")
        output = render_prometheus()
        assert 'llm_failures_total{code="GENERATION_FAILED"} 1' in output

    def test_llm_latency_records_provider(self) -> None:
        record_llm_latency(provider="gemini", duration_seconds=3.5)
        output = render_prometheus()
        assert 'llm_latency_seconds_sum{provider="gemini"} 3.5' in output
        assert 'llm_latency_seconds_count{provider="gemini"} 1' in output

    def test_llm_tokens_records_kind(self) -> None:
        record_llm_tokens(kind="input", count=150)
        record_llm_tokens(kind="output", count=50)
        output = render_prometheus()
        assert 'llm_tokens_used{kind="input"} 150' in output
        assert 'llm_tokens_used{kind="output"} 50' in output


class TestRAGMetrics:
    def test_rag_latency_observes(self) -> None:
        record_rag_latency(0.25)
        record_rag_latency(1.0)
        output = render_prometheus()
        assert "rag_latency_seconds_sum 1.25" in output
        assert "rag_latency_seconds_count 2" in output

    def test_rag_empty_increments(self) -> None:
        record_rag_empty()
        output = render_prometheus()
        assert "rag_empty_results_total 1" in output


class TestCrawlMetrics:
    def test_crawl_started_increments(self) -> None:
        record_crawl_started()
        output = render_prometheus()
        assert "crawl_started_total 1" in output

    def test_crawl_completed_increments(self) -> None:
        record_crawl_completed()
        output = render_prometheus()
        assert "crawl_completed_total 1" in output

    def test_crawl_failed_records_reason(self) -> None:
        record_crawl_failed(reason="invalid_url")
        record_crawl_failed(reason="exception")
        output = render_prometheus()
        assert 'crawl_failed_total{reason="invalid_url"} 1' in output
        assert 'crawl_failed_total{reason="exception"} 1' in output


class TestRenderPrometheus:
    def test_empty_registry_renders_empty(self) -> None:
        output = render_prometheus()
        assert output == ""

    def test_rendered_output_is_valid_text_format(self) -> None:
        record_chat_request()
        output = render_prometheus()
        assert "# HELP chat_requests_total" in output
        assert "# TYPE chat_requests_total counter" in output
