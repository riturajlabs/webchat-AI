"""Tests for structured logging, sensitive data filtering, and LOG_LEVEL (Phase 14.7)."""

from __future__ import annotations

import json
import logging

from backend.core.logging import (
    JsonFormatter,
    ReadableFormatter,
    SensitiveDataFilter,
    configure_logging,
    get_request_id,
    get_tenant_id,
    request_id_var,
    tenant_id_var,
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
            msg="authorization: Bearer FAKE.JWT.FOR.REDACTION.TEST.this.is.not.a.real.token",
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

    def test_masks_url_token_parameter(self) -> None:
        filt = SensitiveDataFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="redirect to https://app.example.com/verify-email?token=eyJhbGciOiJIUzI1NiJ9.payload.signature",
            args=(),
            exc_info=None,
        )
        filt.filter(record)
        assert "REDACTED" in record.msg
        assert "eyJhbGciOiJIUzI1NiJ9" not in record.msg

    def test_masks_url_refresh_token_parameter(self) -> None:
        filt = SensitiveDataFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="callback?refresh_token=abc123secret&state=xyz",
            args=(),
            exc_info=None,
        )
        filt.filter(record)
        assert "REDACTED" in record.msg
        assert "abc123secret" not in record.msg

    def test_masks_url_access_token_parameter(self) -> None:
        filt = SensitiveDataFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="redirect?access_token=ghp_abcdefghij1234567890&scope=read",
            args=(),
            exc_info=None,
        )
        filt.filter(record)
        assert "REDACTED" in record.msg
        assert "ghp_" not in record.msg

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


class TestTenantContext:
    """Tenant ID context is carried into structured/man-readable logs (OBS-01)."""

    def _record(self) -> logging.LogRecord:
        return logging.LogRecord(
            name="webchat_ai",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="chat_request",
            args=(),
            exc_info=None,
        )

    def test_default_tenant_id(self) -> None:
        token = tenant_id_var.set("-")
        try:
            assert get_tenant_id() == "-"
        finally:
            tenant_id_var.reset(token)

    def test_json_formatter_includes_tenant_id(self) -> None:
        token = tenant_id_var.set("tenant-abc")
        try:
            payload = json.loads(JsonFormatter().format(self._record()))
        finally:
            tenant_id_var.reset(token)
        assert payload["tenant_id"] == "tenant-abc"

    def test_json_formatter_defaults_tenant_id_to_dash(self) -> None:
        token = tenant_id_var.set("-")
        try:
            payload = json.loads(JsonFormatter().format(self._record()))
        finally:
            tenant_id_var.reset(token)
        assert payload["tenant_id"] == "-"

    def test_readable_formatter_renders_tenant_prefix(self) -> None:
        token = tenant_id_var.set("tenant-xyz")
        try:
            rendered = ReadableFormatter().format(self._record())
        finally:
            tenant_id_var.reset(token)
        assert "tenant=tenant-xyz" in rendered

    def test_readable_formatter_omits_tenant_prefix_by_default(self) -> None:
        token = tenant_id_var.set("-")
        try:
            rendered = ReadableFormatter().format(self._record())
        finally:
            tenant_id_var.reset(token)
        assert "tenant=" not in rendered


class TestJsonFormatterScrubsExtras:
    """Structured `extra=` payloads are scrubbed like messages (OBS-06)."""

    def _format(self, *, extra: dict[str, object] | None = None, **attrs: object) -> dict:
        record = logging.LogRecord(
            name="webchat_ai",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="request",
            args=(),
            exc_info=None,
        )
        for key, value in attrs.items():
            setattr(record, key, value)  # simulates `extra={...}` kwargs
        if extra is not None:
            record.extra = extra
        payload = json.loads(JsonFormatter().format(record))
        return payload

    def test_api_key_in_extra_is_redacted(self) -> None:
        payload = self._format(api_key="sk-abcdefghijklmnopqrstuvwxyz123")
        assert payload["api_key"] == "[REDACTED]"
        assert "sk-abcdefghijklmnopqrstuvwxyz123" not in payload["api_key"]

    def test_password_in_record_extra_dict_is_redacted(self) -> None:
        payload = self._format(extra={"log": "login failed password=SuperSecret123!"})
        assert payload["log"] == "login failed [REDACTED]"

    def test_nested_dict_value_is_redacted(self) -> None:
        payload = self._format(
            extra={"credentials": {"api": "api_key=sk-abcdefghijklmnopqrstuvwxyz123"}}
        )
        assert payload["credentials"]["api"] == "[REDACTED]"

    def test_non_sensitive_extra_is_preserved(self) -> None:
        payload = self._format(tenant_id="t-1", status=200, duration_ms=12.5)
        assert payload["tenant_id"] == "t-1"
        assert payload["status"] == 200
        assert payload["duration_ms"] == 12.5

    def test_url_token_in_extra_is_redacted(self) -> None:
        payload = self._format(url="https://app.example.com/cb?access_token=secret-value&a=1")
        assert "[REDACTED]" in payload["url"]
        assert "secret-value" not in payload["url"]
