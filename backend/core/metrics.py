"""Dependency-free Prometheus-compatible metrics (Phase 3).

A tiny in-process registry exposing the classic Prometheus text exposition
format (`text/plain; version=0.0.4`). Counters and histograms only — no
external `prometheus_client` dependency.

Design rules:
- Fixed label schemas only. Tenant/session/website identifiers are never
  used as label values, so series cardinality is bounded and tenant data
  never leaks into scrape output ("tenant-safe labels").
- Metrics are pure observation: every value is reused from an existing
  computation (SSE frame payloads, timing logs, ASGI scope) rather than
  recomputed.
- Observation must never break the observed path: all collectors swallow
  unexpected payload shapes instead of raising.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

__all__ = [
    "MetricsLogCollector",
    "attach_metrics_log_collector",
    "record_http_request",
    "record_chat_request",
    "record_chat_failure",
    "record_chat_latency",
    "record_llm_request",
    "record_llm_failure",
    "record_llm_latency",
    "record_llm_tokens",
    "record_rag_latency",
    "record_rag_empty",
    "record_crawl_started",
    "record_crawl_completed",
    "record_crawl_failed",
    "render_prometheus",
    "reset_registry",
]

_REGISTRY_LOCK = threading.Lock()
_REGISTRY: dict[str, _Metric] = {}

# Upper bound on distinct label-value combinations per metric. The fixed
# schemas below stay far under this; the cap is a guard against accidental
# high-cardinality additions (e.g. someone labeling by tenant id later).
_MAX_SERIES_PER_METRIC = 500


def _escape_label_value(value: str) -> str:
    """Escape a label value per the Prometheus text format rules."""
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


class _Series:
    """One labeled time series of a metric."""

    __slots__ = ("label_values",)

    def __init__(self, label_values: tuple[str, ...]) -> None:
        self.label_values = label_values


class _CounterSeries(_Series):
    __slots__ = ("value",)

    def __init__(self, label_values: tuple[str, ...]) -> None:
        super().__init__(label_values)
        self.value = 0.0


class _HistogramSeries(_Series):
    __slots__ = ("bucket_counts", "sum", "count")

    def __init__(self, label_values: tuple[str, ...], buckets: tuple[float, ...]) -> None:
        super().__init__(label_values)
        self.bucket_counts = [0] * len(buckets)
        self.sum = 0.0
        self.count = 0


class _Metric:
    """Base metric with a fixed label schema."""

    kind = "untyped"

    def __init__(
        self,
        name: str,
        documentation: str,
        label_names: tuple[str, ...] = (),
        *,
        buckets: tuple[float, ...] = (),
    ) -> None:
        self.name = name
        self.documentation = documentation
        self.label_names = label_names
        self.buckets = tuple(sorted(buckets))
        self._series: dict[tuple[str, ...], _Series] = {}
        with _REGISTRY_LOCK:
            if name in _REGISTRY:
                raise ValueError(f"metric {name!r} already registered")
            _REGISTRY[name] = self

    def _series_for(self, values: tuple[str, ...]) -> _Series:
        existing = self._series.get(values)
        if existing is not None:
            return existing
        if len(self._series) >= _MAX_SERIES_PER_METRIC:
            # Cardinality guard: drop observations beyond the cap rather than
            # growing without bound. Fixed schemas never hit this.
            return self._series[next(iter(self._series))]
        created = self._new_series(values)
        self._series[values] = created
        return created

    def _new_series(self, values: tuple[str, ...]) -> _Series:
        raise NotImplementedError

    def _label_sets(self) -> list[tuple[tuple[str, ...], str]]:
        """Sorted (values, rendered-labels) pairs for stable exposition."""
        result = []
        for values, _series in sorted(self._series.items()):
            pairs = [
                f'{name}="{_escape_label_value(value)}"'
                for name, value in zip(self.label_names, values, strict=True)
            ]
            result.append((values, ", ".join(pairs)))
        return result

    def render(self) -> list[str]:
        lines = [
            f"# HELP {self.name} {self.documentation}",
            f"# TYPE {self.name} {self.kind}",
        ]
        for values, labels in self._label_sets():
            suffix = f"{{{labels}}}" if labels else ""
            lines.extend(self._render_samples(self._series[values], values, suffix))
        return lines

    def _render_samples(self, series: _Series, values: tuple[str, ...], suffix: str) -> list[str]:
        raise NotImplementedError


class Counter(_Metric):
    """Monotonically increasing counter with optional labels."""

    kind = "counter"

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        if amount < 0:
            raise ValueError("counters can only increase")
        key = tuple(str(labels.get(name, "")) for name in self.label_names)
        assert isinstance((series := self._series_for(key)), _CounterSeries)
        series.value += amount

    def _new_series(self, values: tuple[str, ...]) -> _Series:
        return _CounterSeries(values)

    def _render_samples(self, series: _Series, values: tuple[str, ...], suffix: str) -> list[str]:
        assert isinstance(series, _CounterSeries)
        return [f"{self.name}{suffix} {_format_value(series.value)}"]


class Histogram(_Metric):
    """Cumulative-bucket histogram (`*_bucket`, `*_sum`, `*_count`)."""

    kind = "histogram"

    def observe(self, amount: float, **labels: str) -> None:
        key = tuple(str(labels.get(name, "")) for name in self.label_names)
        assert isinstance((series := self._series_for(key)), _HistogramSeries)
        for index, bound in enumerate(self.buckets):
            if amount <= bound:
                series.bucket_counts[index] += 1
        series.sum += amount
        series.count += 1

    def _new_series(self, values: tuple[str, ...]) -> _Series:
        return _HistogramSeries(values, self.buckets)

    def _render_samples(self, series: _Series, values: tuple[str, ...], suffix: str) -> list[str]:
        assert isinstance(series, _HistogramSeries)
        pairs = [
            f'{name}="{_escape_label_value(value)}"'
            for name, value in zip(self.label_names, values, strict=True)
        ]
        lines: list[str] = []
        for bound, count in zip(self.buckets, series.bucket_counts, strict=True):
            bucket_labels = ", ".join([*pairs, f'le="{_format_bound(bound)}"'])
            lines.append(f"{self.name}_bucket{{{bucket_labels}}} {count}")
        inf_labels = ", ".join([*pairs, 'le="+Inf"'])
        lines.append(f"{self.name}_bucket{{{inf_labels}}} {series.count}")
        lines.append(f"{self.name}_sum{suffix} {_format_value(series.sum)}")
        lines.append(f"{self.name}_count{suffix} {series.count}")
        return lines


def _format_value(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return repr(round(float(value), 6))


def _format_bound(bound: float) -> str:
    if float(bound).is_integer():
        return str(int(bound))
    return repr(bound)


# ---------------------------------------------------------------------------
# Application metrics (Phase 3). Label schemas are fixed on purpose.
# ---------------------------------------------------------------------------

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests handled.",
    ("method", "path", "status"),
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ("method", "path"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

RAG_RETRIEVAL_SUCCESS_TOTAL = Counter(
    "rag_retrieval_total",
    "Chat turns whose retrieval produced at least one source.",
    ("result",),
)
RAG_SOURCES_COUNT = Histogram(
    "rag_sources_count",
    "Number of sources returned per chat turn.",
    buckets=(0, 1, 2, 3, 5, 8, 10, 15, 20),
)
RAG_FALLBACK_TOTAL = Counter(
    "rag_fallback_total",
    "No-context fallback turns by reason (knowledge_empty, retrieval_empty,"
    " confidence_low, context_empty).",
    ("reason",),
)
RAG_CONFIDENCE_SCORE = Histogram(
    "rag_confidence_score",
    "Answer confidence score per completed chat turn.",
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)

AI_GENERATION_TOTAL = Counter(
    "ai_generation_total",
    "Completed AI generations observed at the SSE layer.",
)
AI_FALLBACK_TOTAL = Counter(
    "ai_fallback_total",
    "Turns answered with the safe fallback answer.",
)
AI_PROVIDER_FAILURES_TOTAL = Counter(
    "ai_provider_failures_total",
    "Generation/provider failures surfaced as SSE error frames, by code.",
    ("code",),
)
AI_TOKENS_TOTAL = Counter(
    "ai_tokens_total",
    "Token usage reported on completed turns, split by kind.",
    ("kind",),
)
AI_TTFT_SECONDS = Histogram(
    "ai_ttft_seconds",
    "Time to first streamed token in seconds (from sse_transport logs).",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
)

CACHE_OPERATIONS_TOTAL = Counter(
    "cache_operations_total",
    "Retrieval/embedding cache outcomes (populated when timing is enabled).",
    ("cache", "result"),
)

SSE_ERRORS_TOTAL = Counter(
    "sse_errors_total",
    "Terminal SSE error frames by error code.",
    ("code",),
)

CHAT_REQUESTS_TOTAL = Counter(
    "chat_requests_total",
    "Total chat requests received.",
)
CHAT_FAILURES_TOTAL = Counter(
    "chat_failures_total",
    "Chat requests that resulted in an error or fallback.",
    ("reason",),
)
CHAT_LATENCY_SECONDS = Histogram(
    "chat_latency_seconds",
    "End-to-end chat request latency in seconds.",
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0),
)

LLM_REQUESTS_TOTAL = Counter(
    "llm_requests_total",
    "Total LLM generation requests.",
    ("provider",),
)
LLM_FAILURES_TOTAL = Counter(
    "llm_failures_total",
    "LLM generation failures by error code.",
    ("code",),
)
LLM_LATENCY_SECONDS = Histogram(
    "llm_latency_seconds",
    "LLM generation latency in seconds.",
    ("provider",),
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0),
)
LLM_TOKENS_USED = Counter(
    "llm_tokens_used",
    "LLM tokens consumed by kind.",
    ("kind",),
)
LLM_QUOTA_EXCEEDED_TOTAL = Counter(
    "llm_quota_exceeded_total",
    "LLM generation requests rejected by the per-tenant AI quota, by window.",
    ("window",),
)

RAG_LATENCY_SECONDS = Histogram(
    "rag_latency_seconds",
    "RAG retrieval latency in seconds.",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
)
RAG_EMPTY_RESULTS_TOTAL = Counter(
    "rag_empty_results_total",
    "RAG retrievals that returned zero chunks.",
)

CRAWL_STARTED_TOTAL = Counter(
    "crawl_started_total",
    "Crawl jobs started.",
)
CRAWL_COMPLETED_TOTAL = Counter(
    "crawl_completed_total",
    "Crawl jobs completed successfully.",
)
CRAWL_FAILED_TOTAL = Counter(
    "crawl_failed_total",
    "Crawl jobs that failed.",
    ("reason",),
)


def record_http_request(*, method: str, path: str, status: str, duration_seconds: float) -> None:
    """Observe one finished HTTP request (called by MetricsMiddleware)."""
    HTTP_REQUESTS_TOTAL.inc(method=method, path=path, status=status)
    HTTP_REQUEST_DURATION_SECONDS.observe(duration_seconds, method=method, path=path)


def observe_sources(count: int) -> None:
    """Record retrieval outcome + source count from a `sources` frame."""
    RAG_SOURCES_COUNT.observe(count)
    RAG_RETRIEVAL_SUCCESS_TOTAL.inc(result="success" if count > 0 else "empty")


def observe_done(data: dict[str, Any]) -> None:
    """Record AI/RAG counters from a successful terminal `done` frame."""
    AI_GENERATION_TOTAL.inc()
    input_tokens = data.get("input_tokens")
    output_tokens = data.get("output_tokens")
    if isinstance(input_tokens, (int, float)) and input_tokens >= 0:
        AI_TOKENS_TOTAL.inc(input_tokens, kind="input")
    if isinstance(output_tokens, (int, float)) and output_tokens >= 0:
        AI_TOKENS_TOTAL.inc(output_tokens, kind="output")
    confidence = data.get("confidence_score")
    if isinstance(confidence, (int, float)) and 0.0 <= confidence <= 1.0:
        RAG_CONFIDENCE_SCORE.observe(confidence)
    if data.get("fallback"):
        AI_FALLBACK_TOTAL.inc()
    timing = data.get("timing")
    if isinstance(timing, dict):
        for cache_key, cache_name in (
            ("embedding_cache", "embedding"),
            ("retrieval_cache", "retrieval"),
        ):
            outcome = timing.get(cache_key)
            if outcome in ("hit", "miss"):
                CACHE_OPERATIONS_TOTAL.inc(cache=cache_name, result=outcome)


_GENERATION_FAILURE_PREFIXES = ("GENERATION", "AI_", "EMBEDDING")


def observe_sse_error(code: str) -> None:
    """Record an SSE error frame code; generation failures counted separately."""
    SSE_ERRORS_TOTAL.inc(code=code)
    if code.startswith(_GENERATION_FAILURE_PREFIXES):
        AI_PROVIDER_FAILURES_TOTAL.inc(code=code)


def record_chat_request() -> None:
    """Record that a chat request was received."""
    CHAT_REQUESTS_TOTAL.inc()


def record_chat_failure(reason: str) -> None:
    """Record a chat request failure."""
    CHAT_FAILURES_TOTAL.inc(reason=reason)


def record_chat_latency(duration_seconds: float) -> None:
    """Record end-to-end chat latency."""
    CHAT_LATENCY_SECONDS.observe(duration_seconds)


def record_llm_request(provider: str) -> None:
    """Record an LLM generation request."""
    LLM_REQUESTS_TOTAL.inc(provider=provider)


def record_llm_failure(code: str) -> None:
    """Record an LLM generation failure."""
    LLM_FAILURES_TOTAL.inc(code=code)


def record_llm_latency(provider: str, duration_seconds: float) -> None:
    """Record LLM generation latency."""
    LLM_LATENCY_SECONDS.observe(duration_seconds, provider=provider)


def record_llm_tokens(kind: str, count: float) -> None:
    """Record LLM token usage."""
    LLM_TOKENS_USED.inc(count, kind=kind)


def record_llm_quota_exceeded(window: str) -> None:
    """Record a per-tenant AI quota rejection (window: daily/monthly/request)."""
    LLM_QUOTA_EXCEEDED_TOTAL.inc(window=window)


def record_rag_latency(duration_seconds: float) -> None:
    """Record RAG retrieval latency."""
    RAG_LATENCY_SECONDS.observe(duration_seconds)


def record_rag_empty() -> None:
    """Record an empty RAG retrieval result."""
    RAG_EMPTY_RESULTS_TOTAL.inc()


def record_crawl_started() -> None:
    """Record a crawl job start."""
    CRAWL_STARTED_TOTAL.inc()


def record_crawl_completed() -> None:
    """Record a crawl job completion."""
    CRAWL_COMPLETED_TOTAL.inc()


def record_crawl_failed(reason: str) -> None:
    """Record a crawl job failure."""
    CRAWL_FAILED_TOTAL.inc(reason=reason)


def render_prometheus() -> str:
    """Render the full registry in Prometheus text exposition format."""
    with _REGISTRY_LOCK:
        metrics = list(_REGISTRY.values())
    lines: list[str] = []
    for metric in metrics:
        rendered = metric.render()
        if len(rendered) > 2:  # skip metrics with no samples yet
            lines.extend(rendered)
    return "\n".join(lines) + ("\n" if lines else "")


def reset_registry() -> None:
    """Clear all recorded samples (tests only; metric definitions remain)."""
    with _REGISTRY_LOCK:
        for metric in _REGISTRY.values():
            metric._series.clear()


class MetricsLogCollector(logging.Filter):
    """Derive metrics from structured log events the services already emit.

    Attached to the `webchat_ai` logger so no service call site changes:
    - `rag_retrieval_zero_context` warnings carry the fallback reason as the
      4th positional arg (always-on WARNING, one per no-context turn).
    - `sse_transport` info records carry `first_token_ms` (one per streamed
      turn), used as the always-on TTFT source.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            message = record.msg
            if not isinstance(message, str):
                return True
            if message.startswith("rag_retrieval_zero_context"):
                args = record.args
                reason = str(args[3]) if isinstance(args, tuple) and len(args) > 3 else "unknown"
                RAG_FALLBACK_TOTAL.inc(reason=reason)
            elif message == "sse_transport":
                first_token_ms = getattr(record, "first_token_ms", None)
                if isinstance(first_token_ms, (int, float)) and first_token_ms >= 0:
                    AI_TTFT_SECONDS.observe(first_token_ms / 1000.0)
        except Exception:  # pragma: no cover - observation must never log-break
            pass
        return True


def attach_metrics_log_collector(logger_name: str = "webchat_ai") -> None:
    """Idempotently attach the collector filter to the app logger."""
    target = logging.getLogger(logger_name)
    for existing in target.filters:
        if isinstance(existing, MetricsLogCollector):
            return
    target.addFilter(MetricsLogCollector())
