"""Tests for structured logging, sensitive data filtering, and LOG_LEVEL (Phase 14.7)."""

from __future__ import annotations

import logging

from backend.core.logging import (
    JsonFormatter,
    SensitiveDataFilter,
    configure_logging,
    get_request_id,
    request_id_var,
)


class TestSensitiveDataFilter:
    """SensitiveDataFilter scrubs secrets from log records."""

    def test_masks_api_key_in_message(self) -> None:
        filt = SensitiveDataFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="api_key=sk-abc123def456ghi789jkl0mno",
            args=(),
            exc_info=None,
        )
        filt.filter(record)
        assert "REDACTED" in record.msg
        assert "sk-" not in record.msg

    def test_masks_bearer_token(self) -> None:
        filt = SensitiveDataFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="authorization: Bearer eyJhbGciOiJIUzI1NiJ9.test.signature",
            args=(),
            exc_info=None,
        )
        filt.filter(record)
        assert "REDACTED" in record.msg

    def test_masks_password_assignment(self) -> None:
        filt = SensitiveDataFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="password=SuperSecret123!",
            args=(),
            exc_info=None,
        )
        filt.filter(record)
        assert "REDACTED" in record.msg
        assert "SuperSecret123" not in record.msg

    def test_masks_github_token(self) -> None:
        filt = SensitiveDataFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="using ghp_abcdefghij1234567890abcdefghij1234 for auth",
            args=(),
            exc_info=None,
        )
        filt.filter(record)
        assert "REDACTED" in record.msg
        assert "ghp_" not in record.msg

    def test_masks_slack_token(self) -> None:
        filt = SensitiveDataFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="token xoxb-1234567890-1234567890123-abcdef",
            args=(),
            exc_info=None,
        )
        filt.filter(record)
        assert "REDACTED" in record.msg
        assert "xoxb-" not in record.msg

    def test_preserves_normal_message(self) -> None:
        filt = SensitiveDataFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="chat_request tenant=t1 website=w1",
            args=(),
            exc_info=None,
        )
        filt.filter(record)
        assert record.msg == "chat_request tenant=t1 website=w1"

    def test_always_returns_true(self) -> None:
        filt = SensitiveDataFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="normal",
            args=(),
            exc_info=None,
        )
        assert filt.filter(record) is True

    def test_clears_args_after_formatting(self) -> None:
        filt = SensitiveDataFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="api_key=%s",
            args=("sk-abc123def456ghi789jkl0",),
            exc_info=None,
        )
        filt.filter(record)
        assert record.args is None


class TestConfigureLogging:
    """configure_logging respects LOG_LEVEL and debug settings."""

    def test_default_level_is_info(self) -> None:
        root = logging.getLogger()
        old_level = root.level
        try:
            configure_logging()
            assert root.level <= logging.INFO
        finally:
            root.level = old_level

    def test_explicit_level_override(self) -> None:
        root = logging.getLogger()
        old_level = root.level
        try:
            configure_logging(level=logging.WARNING)
            assert root.level == logging.WARNING
        finally:
            root.level = old_level

    def test_json_formatter_in_production(self) -> None:
        from backend.core.config import get_settings

        settings = get_settings()
        old_env = settings.environment
        try:
            settings.environment = "production"
            root = logging.getLogger()
            old_handlers = root.handlers[:]
            try:
                configure_logging()
                assert any(isinstance(h.formatter, JsonFormatter) for h in root.handlers)
            finally:
                root.handlers = old_handlers
        finally:
            settings.environment = old_env


class TestRequestId:
    """Request ID context variable works correctly."""

    def test_default_request_id(self) -> None:
        token = request_id_var.set("-")
        try:
            assert get_request_id() == "-"
        finally:
            request_id_var.reset(token)

    def test_custom_request_id(self) -> None:
        token = request_id_var.set("test-req-123")
        try:
            assert get_request_id() == "test-req-123"
        finally:
            request_id_var.reset(token)
