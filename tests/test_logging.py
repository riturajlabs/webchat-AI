"""Structured logging tests: JSON output, request-ID correlation, env awareness."""

import json
import logging

from backend.core.config import Settings
from backend.core.logging import (
    JsonFormatter,
    ReadableFormatter,
    configure_logging,
    request_id_var,
)


def _record(message: str = "hello world") -> logging.LogRecord:
    return logging.LogRecord("test.logger", logging.INFO, __file__, 1, message, (), None)


def test_json_formatter_emits_structured_record() -> None:
    token = request_id_var.set("req-123")
    try:
        line = JsonFormatter().format(_record())
    finally:
        request_id_var.reset(token)

    payload = json.loads(line)
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"
    assert payload["request_id"] == "req-123"
    assert "environment" in payload
    assert "ts" in payload


def test_json_formatter_includes_exception_details() -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record = _record()
        record.exc_info = logging.sys.exc_info()

    line = JsonFormatter().format(record)
    payload = json.loads(line)
    assert "boom" in payload["exc_info"]


def test_json_formatter_merges_extra_fields() -> None:
    record = _record()
    record.command = "find"
    record.duration_ms = 12.5

    line = JsonFormatter().format(record)
    payload = json.loads(line)
    assert payload["command"] == "find"
    assert payload["duration_ms"] == 12.5


def test_readable_formatter_carries_request_id() -> None:
    token = request_id_var.set("req-abc")
    try:
        out = ReadableFormatter().format(_record())
    finally:
        request_id_var.reset(token)
    assert "rid=req-abc" in out
    assert out.endswith("hello world")


def test_configure_logging_is_environment_aware(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.core.logging.get_settings",
        lambda: Settings(environment="production", jwt_secret="a" * 32),
    )
    configure_logging()
    assert isinstance(logging.getLogger().handlers[-1].formatter, JsonFormatter)

    monkeypatch.setattr(
        "backend.core.logging.get_settings",
        lambda: Settings(environment="development"),
    )
    configure_logging()
    assert isinstance(logging.getLogger().handlers[-1].formatter, ReadableFormatter)
