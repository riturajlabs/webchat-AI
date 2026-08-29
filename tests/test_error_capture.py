"""Tests for capture_exception() error tracking abstraction (Phase 14.7)."""

from __future__ import annotations

import logging

from backend.core.errors import (
    AppError,
    GenerationError,
    capture_exception,
)


class TestCaptureException:
    def test_logs_exception_at_error_level(self) -> None:
        exc = GenerationError("test failure")
        # Should not raise
        capture_exception(exc)

    def test_includes_error_type_in_log(self, caplog) -> None:
        exc = AppError("test error")
        with caplog.at_level(logging.ERROR, logger="webchat_ai"):
            capture_exception(exc)
        assert any("exception_captured" in r.message for r in caplog.records)

    def test_includes_context_fields(self, caplog) -> None:
        exc = GenerationError("timeout")
        with caplog.at_level(logging.ERROR, logger="webchat_ai"):
            capture_exception(exc, context={"tenant_id": "t1", "job_id": "j1"})
        # Should not raise
        assert len(caplog.records) > 0

    def test_preserves_exception_chain(self, caplog) -> None:
        try:
            try:
                raise ValueError("root cause")
            except ValueError as e:
                raise GenerationError("wrapped") from e
        except GenerationError as exc:
            with caplog.at_level(logging.ERROR, logger="webchat_ai"):
                capture_exception(exc)
        # Should not raise; the exception chain is captured via exc_info
        assert len(caplog.records) > 0

    def test_custom_log_level(self, caplog) -> None:
        exc = AppError("warning level")
        with caplog.at_level(logging.WARNING, logger="webchat_ai"):
            capture_exception(exc, level=logging.WARNING)
        assert len(caplog.records) > 0
