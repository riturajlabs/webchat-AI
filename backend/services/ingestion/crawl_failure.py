"""Structured crawl failure classification (production egress hardening).

The crawler must distinguish "the target rejected our egress" from "the worker
is broken" so operators can diagnose target-specific blocking (e.g. a WAF
answering HTTP 403 to Railway's outbound IPs) without leaking internals to the
dashboard. This module owns the classification vocabulary, the HTTP-status
mapping, retryability rules, and secret-safe URL decomposition used by the
fetch path and the worker.

Design rules (docs/CRAWL_EGRESS_HARDENING.md):

- Classifications are a fixed enum, never free-form strings, so metrics
  (`crawl_fetch_failures_total`) and `record_crawl_failed` stay low-cardinality.
- `user_facing_reason` is the only place a failure is translated for end users;
  it never mentions Railway, IPs, proxy infrastructure or internal hostnames.
- `safe_url_parts` is the logging primitive for blocked targets: hostname plus
  a normalized path with query strings and fragments removed, so URL tokens
  never reach structured logs (the `SensitiveDataFilter` is a second layer).
"""

from __future__ import annotations

from enum import StrEnum
from urllib.parse import urlparse


class CrawlFailureClassification(StrEnum):
    """Canonical outcome of a page fetch / crawl run.

    Values are intentionally stable strings (stored in ``CrawlJobError`` and
    used as metric labels), so renaming a label ships only here.
    """

    SUCCESS = "success"
    RETRYABLE_NETWORK_ERROR = "retryable_network_error"
    TARGET_RATE_LIMITED = "target_rate_limited"
    TARGET_BLOCKED = "target_blocked"
    TARGET_SERVER_ERROR = "target_server_error"
    TARGET_NOT_FOUND = "target_not_found"
    UNSUPPORTED_CONTENT = "unsupported_content"
    SSRF_BLOCKED = "ssrf_blocked"
    INVALID_URL = "invalid_url"
    BROWSER_LAUNCH_FAILURE = "browser_launch_failure"
    CRAWL_TIMEOUT = "crawl_timeout"
    UNKNOWN_FAILURE = "unknown_failure"


# HTTP statuses the HTTP-first path treats as recoverable (bounded retry /
# browser fallback). 404/410 are deliberately absent: retrying cannot fix a
# missing page (Phase 3, TRD).
_RECOVERABLE_STATUS_CODES = frozenset({403, 429, 500, 502, 503, 504})

# Statuses that get a BOUNDED http retry BEFORE the browser fallback. 403 is
# not here: the spec says a 403 may fall back to the browser once and, if the
# browser is also rejected, stop (no retry storm).
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def classify_http_status(status_code: int) -> CrawlFailureClassification:
    """Map an HTTP status to its crawl classification (unknown stays generic)."""
    if status_code in (401, 403):
        return CrawlFailureClassification.TARGET_BLOCKED
    if status_code == 429:
        return CrawlFailureClassification.TARGET_RATE_LIMITED
    if status_code in (404, 410):
        return CrawlFailureClassification.TARGET_NOT_FOUND
    if status_code in (500, 502, 503, 504):
        return CrawlFailureClassification.TARGET_SERVER_ERROR
    return CrawlFailureClassification.UNKNOWN_FAILURE


def classify_network_error(exception: Exception) -> CrawlFailureClassification:
    """Classify a transport-level exception raised during a fetch attempt."""
    name = type(exception).__name__
    if "Timeout" in name or "Timeout" in str(exception):
        return CrawlFailureClassification.CRAWL_TIMEOUT
    return CrawlFailureClassification.RETRYABLE_NETWORK_ERROR


def is_http_recoverable(status_code: int) -> bool:
    """True when the crawler may fall back to the browser for this status."""
    return status_code in _RECOVERABLE_STATUS_CODES


def is_http_retryable(status_code: int) -> bool:
    """True when this status may be retried over HTTP (bounded) first."""
    return status_code in _RETRYABLE_STATUS_CODES


def user_facing_reason(classification: CrawlFailureClassification | None) -> str | None:
    """Safe, user-visible sentence for a zero-page crawl failure.

    Returns ``None`` when there is no specific safe message (the worker keeps
    its generic "No pages were fetched."). Never exposes network/egress internals.
    """
    if classification is CrawlFailureClassification.TARGET_BLOCKED:
        return "The website rejected automated crawling (HTTP 403)."
    if classification is CrawlFailureClassification.TARGET_RATE_LIMITED:
        return "The website is rate-limiting automated requests."
    return None


def safe_url_parts(url: str) -> tuple[str, str]:
    """Return ``(hostname, path)`` with secrets-bearing parts removed.

    Query strings and fragments can carry tokens/access keys (e.g.
    ``?token=...``) and are never logged; only the bare hostname and path are
    returned so operators can still identify the page without internal
    hostnames, ports, or credentials.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "/").rstrip("/") or "/"
    return host, path
