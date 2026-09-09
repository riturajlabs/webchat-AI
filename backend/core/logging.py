"""Structured, environment-aware logging.

- Production: single-line JSON records to stdout (machine-parseable).
- Development: human-readable text output.
- Every record carries the current `request_id` (set by the request-ID
  middleware) and, when known, the authenticated `tenant_id` (set by the
  auth dependencies) so logs can be correlated across a request lifecycle
  and sliced per tenant.

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

# Populated by the auth-resolving dependencies once a principal's tenant is
# known (and by worker jobs from the job document). Anonymous requests keep
# the "-" default so tenant context is never inferred from unauthenticated
# input.
tenant_id_var: ContextVar[str] = ContextVar("tenant_id", default="-")


def get_request_id() -> str:
    """Return the request ID associated with the current context."""
    return request_id_var.get()


def get_tenant_id() -> str:
    """Return the tenant ID associated with the current context ("-" if none)."""
    return tenant_id_var.get()


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
            "tenant_id": get_tenant_id(),
            "environment": get_settings().environment,
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        extra = getattr(record, "extra", None)
        if isinstance(extra, dict):
            payload.update(extra)
        payload.update(_extra_fields(record))
        # OBS-06: the `extra=` dict and %-args merge into the payload above and
        # bypass the message-level SensitiveDataFilter, so every non-scalar
        # value is scrubbed here before serialization.
        return json.dumps(_scrub_sensitive(payload), default=str)


class ReadableFormatter(logging.Formatter):
    """Human-readable format for local development."""

    def format(self, record: logging.LogRecord) -> str:
        base = f"[{record.levelname}] {record.name}: {record.getMessage()}"
        request_id = get_request_id()
        if request_id != "-":
            base = f"rid={request_id} {base}"
        tenant_id = get_tenant_id()
        if tenant_id != "-":
            base = f"tenant={tenant_id} {base}"
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
    # URL query parameters containing tokens (e.g. ?token=<JWT>).  JWTs
    # contain dots and slashes that the generic `token=\S+` pattern misses.
    re.compile(r"(?i)[?&](?:token|access_token|refresh_token)=[^&\s]+"),
]

_MASKED = "[REDACTED]"


def _scrub_sensitive(value: Any) -> Any:
    """Recursively redact values that resemble secrets.

    The message-level ``SensitiveDataFilter`` only touches ``record.msg``;
    structured ``extra=`` payloads reach the JSON formatter as raw attribute
    values. Scrub strings and recurse through dicts/lists so secrets nested in
    structured logs are masked exactly like free-text messages (OBS-06).
    """
    if isinstance(value, str):
        for pattern in _SENSITIVE_PATTERNS:
            value = pattern.sub(_MASKED, value)
        return value
    if isinstance(value, dict):
        return {key: _scrub_sensitive(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_scrub_sensitive(item) for item in value)
    return value


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
