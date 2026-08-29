"""Structured, environment-aware logging.

- Production: single-line JSON records to stdout (machine-parseable).
- Development: human-readable text output.
- Every record carries the current `request_id` (set by the request-ID
  middleware) so logs can be correlated across a request lifecycle.

Requirement: 00-AI-Development-Rules.md §17 (logging rules).
"""

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from backend.core.config import get_settings

# Populated by `RequestIDMiddleware` for the duration of each HTTP request.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    """Return the request ID associated with the current context."""
    return request_id_var.get()


# Standard `LogRecord` attributes; anything else on the record was attached via
# a logging call's `extra=` kwarg and is merged into the JSON payload.
_LOG_RECORD_ATTRS = frozenset(
    "name msg args levelname levelno pathname filename module exc_info "
    "exc_text stack_info lineno funcName created msecs relativeCreated "
    "thread threadName processName process taskName asctime message extra".split()
)


def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    """Non-standard attributes attached to `record` (the `extra=` payload)."""
    return {k: v for k, v in record.__dict__.items() if k not in _LOG_RECORD_ATTRS}


class JsonFormatter(logging.Formatter):
    """Format a log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id(),
            "environment": get_settings().environment,
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        extra = getattr(record, "extra", None)
        if isinstance(extra, dict):
            payload.update(extra)
        payload.update(_extra_fields(record))
        return json.dumps(payload, default=str)


class ReadableFormatter(logging.Formatter):
    """Human-readable format for local development."""

    def format(self, record: logging.LogRecord) -> str:
        base = f"[{record.levelname}] {record.name}: {record.getMessage()}"
        request_id = get_request_id()
        if request_id != "-":
            base = f"rid={request_id} {base}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def configure_logging(level: int | None = None) -> None:
    """Configure the root logger once.

    Environment-aware: JSON in non-development, readable in development.
    Safe to call multiple times; handlers are replaced on each call.
    """
    settings = get_settings()
    if level is not None:
        effective_level = level
    elif settings.debug:
        effective_level = logging.DEBUG
    else:
        effective_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(effective_level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    if settings.environment.lower() == "development":
        handler.setFormatter(ReadableFormatter())
    else:
        handler.setFormatter(JsonFormatter())
    root.addHandler(handler)


# Patterns that look like secrets, tokens, or API keys.
_SENSITIVE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization)\s*[=:]\s*\S+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"xox[bpsa]-[A-Za-z0-9\-]+"),
]

_MASKED = "[REDACTED]"


class SensitiveDataFilter(logging.Filter):
    """Scrub patterns that resemble secrets from log messages.

    Attached to the ``webchat_ai`` logger so all outgoing records are
    sanitised before they reach any handler.  The filter operates on the
    *rendered* message string — it catches both ``extra`` payloads merged by
    ``JsonFormatter`` and free-text log messages.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            msg = record.getMessage()
            for pattern in _SENSITIVE_PATTERNS:
                msg = pattern.sub(_MASKED, msg)
            record.msg = msg
            record.args = None
        except Exception:  # pragma: no cover — filter must never break logging
            pass
        return True


def attach_sensitive_data_filter(logger_name: str = "webchat_ai") -> None:
    """Idempotently attach the sensitive-data filter to the app logger."""
    target = logging.getLogger(logger_name)
    for existing in target.filters:
        if isinstance(existing, SensitiveDataFilter):
            return
    target.addFilter(SensitiveDataFilter())
