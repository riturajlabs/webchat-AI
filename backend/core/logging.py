"""Structured, environment-aware logging.

- Production: single-line JSON records to stdout (machine-parseable).
- Development: human-readable text output.
- Every record carries the current `request_id` (set by the request-ID
  middleware) so logs can be correlated across a request lifecycle.

Requirement: 00-AI-Development-Rules.md §17 (logging rules).
"""

import json
import logging
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
    effective_level = level or (logging.DEBUG if settings.debug else logging.INFO)

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
