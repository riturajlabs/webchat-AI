"""Focused FIND-03 worker-logging-audit tests (OBS-01/OBS-02, SEV-01).

Covers: worker bootstrap, job log context, crawler URL sanitisation, email
PII masking, and the log-context adapter. All tests run with the in-memory
fakes already in place (no external services started).
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest
from backend.core.logging import get_request_id, get_tenant_id, tenant_id_var

# ---------------------------------------------------------------------------
# Worker bootstrap
# ---------------------------------------------------------------------------


async def test_worker_startup_configures_shared_logging_and_filter(monkeypatch) -> None:
    """startup() installs shared structured logging and the sensitive-data
    filter before any other initialisation."""
    from backend.workers import app

    calls: list[str] = []
    monkeypatch.setattr(app, "configure_logging", lambda: calls.append("configure_logging"))
    monkeypatch.setattr(app, "attach_sensitive_data_filter", lambda: calls.append("attach_filter"))
    # Prevent real Redis/Google-SDK connections during startup.
    monkeypatch.setattr(app, "build_ingestion_embedding_client", lambda: object())
    monkeypatch.setattr(app, "ProviderHealthStore", lambda _redis: object())
    monkeypatch.setattr(app, "get_redis", lambda: object())

    ctx: dict[str, Any] = {}
    await app.startup(ctx)

    assert ctx["app_name"] == app._settings.app_name
    assert calls == ["configure_logging", "attach_filter"]


# ---------------------------------------------------------------------------
# Tiny log-context adapter
# ---------------------------------------------------------------------------


def test_job_request_id_returns_job_prefix() -> None:
    from backend.workers.jobs.log_context import job_request_id

    assert job_request_id({"job_id": "abc"}) == "job:abc"
    assert job_request_id({}) == "job:unknown"


def test_request_context_preserves_outer_values_and_resets() -> None:
    """request/tenant context is bound for the job and restored afterwards,
    preserving any outer tenant value."""
    from backend.workers.jobs.log_context import request_context, reset_context

    outer = tenant_id_var.set("outer-tenant")
    try:
        req_tok, ten_tok = request_context({"job_id": "42"})
        try:
            assert get_request_id() == "job:42"
            assert get_tenant_id() == "outer-tenant"
        finally:
            reset_context(req_tok, ten_tok)
        assert get_request_id() == "-"
        assert get_tenant_id() == "outer-tenant"
    finally:
        tenant_id_var.reset(outer)


# ---------------------------------------------------------------------------
# Knowledge job context
# ---------------------------------------------------------------------------


async def test_process_document_carry_job_request_context(monkeypatch) -> None:
    """request_id is set to job:{id} for the lifetime of the worker call."""
    from backend.workers.jobs import knowledge

    observed: dict[str, str] = {}

    class _FakeProcessor:
        async def process_document(
            self, document_id: str, *, on_retry: Any = None, run_id: Any = None
        ) -> dict[str, str]:
            observed["request_id"] = get_request_id()
            observed["tenant_id"] = get_tenant_id()
            return {"status": "ok"}

    monkeypatch.setattr(knowledge, "_embedder", lambda ctx: object())
    monkeypatch.setattr(knowledge, "_processor", lambda ctx, embed: _FakeProcessor())

    result = await knowledge.process_document({"job_id": "j7"}, "doc-a")
    assert result == {"status": "ok"}
    assert observed["request_id"] == "job:j7"
    assert get_request_id() == "-"


async def test_process_website_documents_carry_job_request_context(monkeypatch) -> None:
    """request_id and tenant_id are bound for the fan-out and reset afterwards."""
    from backend.workers.jobs import knowledge

    observed: dict[str, str] = {}

    class _FakeProcessor:
        async def process_website_documents(
            self, website_id: str, *, enqueue: Any = None
        ) -> dict[str, str]:
            observed["request_id"] = get_request_id()
            observed["tenant_id"] = get_tenant_id()
            return {"status": "ok"}

    monkeypatch.setattr(knowledge, "_embedder", lambda ctx: object())
    monkeypatch.setattr(knowledge, "_processor", lambda ctx, embed: _FakeProcessor())

    result = await knowledge.process_website_documents({"job_id": "ws-1"}, "ws-abc")
    assert result == {"status": "ok"}
    assert observed["request_id"] == "job:ws-1"
    assert get_request_id() == "-"
    assert get_tenant_id() == "-"


# ---------------------------------------------------------------------------
# Email PII masking + context
# ---------------------------------------------------------------------------


async def test_send_email_masks_recipient_subject_and_resets_context(monkeypatch, caplog) -> None:
    """Failed email logs mask the address, hash the subject, and reset context."""
    from backend.workers.jobs import email as email_mod

    caplog.set_level(logging.ERROR, logger="webchat_ai")

    class _FailingMailService:
        async def send(self, msg: Any) -> None:  # noqa: ARG002
            raise RuntimeError("SMTP down")

    monkeypatch.setattr(email_mod, "get_mail_service", lambda: _FailingMailService())

    with pytest.raises(RuntimeError, match="SMTP down"):
        await email_mod.send_email(
            {"job_id": "e1"},
            {
                "to": "alice@app.example.com",
                "subject": "Your billing statement",
                "text": "hi",
                "html": "<p>hi</p>",
            },
        )

    text = caplog.text
    assert "al***@app.example.com" in text
    assert "alice@app.example.com" not in text
    assert "Your billing statement" not in text
    assert "subject_hash=" in text
    assert get_request_id() == "-"
    assert get_tenant_id() == "-"


async def test_send_email_success_does_not_leak_address(monkeypatch, caplog) -> None:
    """Successful email delivery must not leak the recipient into logs."""
    from backend.workers.jobs import email as email_mod

    caplog.set_level(logging.DEBUG, logger="webchat_ai")

    class _StubMailService:
        async def send(self, msg: Any) -> None:  # noqa: ARG002
            pass

    monkeypatch.setattr(email_mod, "get_mail_service", lambda: _StubMailService())

    await email_mod.send_email(
        {"job_id": "e2"},
        {
            "to": "bob@corp.example.com",
            "subject": "Welcome!",
            "text": "hello",
            "html": "<p>hello</p>",
        },
    )

    assert "bob@corp.example.com" not in caplog.text
    assert get_request_id() == "-"


# ---------------------------------------------------------------------------
# Mailpit provider PII masking
# ---------------------------------------------------------------------------


def test_mailpit_provider_masks_recipient_and_omits_api_url(monkeypatch, caplog) -> None:
    """Mailpit log lines mask the address and never include the API URL."""
    import urllib.request as _urllib_request

    from backend.services.mail.providers import MailpitProvider

    caplog.set_level(logging.INFO, logger="webchat_ai")

    def _fail(*_a: Any, **_kw: Any) -> None:
        raise RuntimeError("no network")

    monkeypatch.setattr(_urllib_request, "urlopen", _fail)

    provider = MailpitProvider("http://secret-host:8025")
    payload: dict[str, Any] = {
        "To": [{"Email": "bob@corp.example.com"}],
        "Subject": "Hi",
        "Text": "body",
        "HTML": "<p>body</p>",
    }

    with pytest.raises(RuntimeError, match="no network"):
        provider._post(payload)

    text = caplog.text
    assert "bo***@corp.example.com" in text
    assert "bob@corp.example.com" not in text
    assert "secret-host" not in text
    assert "api_url" not in text


# ---------------------------------------------------------------------------
# Crawler browser URL sanitisation
# ---------------------------------------------------------------------------


async def test_browser_fetch_start_logs_safe_url_with_token(monkeypatch, caplog) -> None:
    """crawl_browser_fetch_start logs hostname/path without query tokens."""
    from backend.services.ingestion.browser import BrowserPageFetcher
    from backend.services.ingestion.crawler import FetchError

    caplog.set_level(logging.INFO, logger="webchat_ai")

    async def _launch_boom(self: Any) -> Any:  # noqa: ARG002, ANN401
        raise FetchError(
            "abort",
            classification="browser_launch_failure",
            method="browser",
        )

    monkeypatch.setattr(BrowserPageFetcher, "_ensure_context", _launch_boom)

    class _OKGuard:
        async def validate_async(self, url: str) -> None:  # noqa: ARG002
            pass

    fetcher = BrowserPageFetcher(guard=_OKGuard())  # type: ignore[arg-type]

    with pytest.raises(FetchError, match="abort"):
        await fetcher.fetch("https://example.com/secret?token=SHOULD_NOT_APPEAR")

    text = caplog.text
    assert "crawl_browser_fetch_start hostname=example.com path=/secret" in text
    assert "SHOULD_NOT_APPEAR" not in text
    assert "token=" not in text


async def test_browser_launch_failed_omits_full_url_and_exception_message(
    monkeypatch, caplog
) -> None:
    """crawl_browser_launch_failed logs only the error type, not the URL or
    exception message which may embed the URL."""
    from backend.services.ingestion.browser import BrowserPageFetcher
    from backend.services.ingestion.crawler import FetchError

    caplog.set_level(logging.WARNING, logger="webchat_ai")

    async def _boom(self: Any) -> Any:  # noqa: ARG002, ANN401
        raise RuntimeError("Chromium launch failed for https://bad.example.com/?token=X")

    monkeypatch.setattr(BrowserPageFetcher, "_ensure_context", _boom)

    class _OKGuard:
        async def validate_async(self, url: str) -> None:  # noqa: ARG002
            pass

    fetcher = BrowserPageFetcher(guard=_OKGuard())  # type: ignore[arg-type]

    with pytest.raises(FetchError) as excinfo:
        await fetcher.fetch("https://bad.example.com/page?q=tok")
    assert excinfo.value.classification == "browser_launch_failure"

    text = caplog.text
    assert "crawl_browser_launch_failed hostname=bad.example.com path=/page" in text
    assert "error_type=RuntimeError" in text
    assert "bad.example.com/page?q=tok" not in text


async def test_browser_failure_logs_safe_url_not_raw_exception(monkeypatch, caplog) -> None:
    """crawl_browser_failure logs error type + safe hostname/path; exception
    messages that embed user:password@ credentials are never emitted."""
    from backend.services.ingestion.browser import BrowserPageFetcher
    from backend.services.ingestion.crawler import FetchError

    caplog.set_level(logging.WARNING, logger="webchat_ai")

    class _FakePage:
        async def route(self, *a: Any, **kw: Any) -> None:  # noqa: ARG002, ANN401
            pass

        async def goto(self, url: str, **kw: Any) -> None:  # noqa: ARG002, ANN401
            raise RuntimeError(
                "Timeout https://user:pass@secrets.example.org/y?token=ABC navigating"
            )

        async def close(self) -> None:
            pass

    class _FakeCtx:
        async def new_page(self) -> _FakePage:
            return _FakePage()

    async def _ok_ctx(self: Any) -> _FakeCtx:  # noqa: ARG002, ANN401
        return _FakeCtx()

    monkeypatch.setattr(BrowserPageFetcher, "_ensure_context", _ok_ctx)

    class _OKGuard:
        async def validate_async(self, url: str) -> None:  # noqa: ARG002
            pass

    fetcher = BrowserPageFetcher(guard=_OKGuard())  # type: ignore[arg-type]

    with pytest.raises(FetchError):
        await fetcher.fetch("https://user:pass@secrets.example.org/y?token=ABC")

    text = caplog.text
    assert "crawl_browser_failure hostname=secrets.example.org path=/y" in text
    assert "error_type=RuntimeError" in text
    assert "user:pass@" not in text
    assert "token=ABC" not in text


# ---------------------------------------------------------------------------
# Knowledge processor failure records: host/path only, never the raw URL
# ---------------------------------------------------------------------------


def test_knowledge_failure_record_emits_host_path_not_raw_url(caplog) -> None:
    """`_log_failure` structured records carry url_host/url_path instead of a
    full URL (which may contain query tokens or credentials)."""
    from types import SimpleNamespace

    from backend.services.knowledge.processor import KnowledgeProcessor

    caplog.set_level(logging.WARNING, logger="webchat_ai")
    document = SimpleNamespace(
        id="doc-1",
        website_id="ws-1",
        tenant_id="tenant-a",
        url="https://vip.example.com/secret?token=LEAKME",
        knowledge_retry_count=2,
    )

    KnowledgeProcessor._log_failure(  # type: ignore[call-arg]
        document,  # type: ignore[arg-type]
        stage="chunk",
        error_type="InsufficientContent",
        error_message="Too short to embed",
    )

    record = caplog.records[-1]
    assert record.url_host == "vip.example.com"
    assert record.url_path == "/secret"
    assert not hasattr(record, "url")
    assert "LEAKME" not in caplog.text


# ---------------------------------------------------------------------------
# Browser success site: safe URL fields while preserving the internal URL
# ---------------------------------------------------------------------------


async def test_browser_success_logs_safe_url_not_full_url(monkeypatch, caplog) -> None:
    """crawl_browser_success logs only sanitised host/path fields, never the
    raw URL with query tokens nor the navigation's final_url."""
    from backend.services.ingestion.browser import BrowserPageFetcher

    caplog.set_level(logging.INFO, logger="webchat_ai")

    class _FakePage:
        url = "https://example.com/result?q=secret"

        async def route(self, *a: Any, **kw: Any) -> None:  # noqa: ARG002, ANN401
            pass

        async def goto(self, url: str, **kw: Any) -> Any:  # noqa: ARG002, ANN401
            return SimpleNamespace(status=200)

        async def content(self) -> str:
            return "<html>ok</html>"

        async def close(self) -> None:
            pass

    class _FakeCtx:
        async def new_page(self) -> _FakePage:
            return _FakePage()

    async def _ok_ctx(self: Any) -> _FakeCtx:  # noqa: ARG002, ANN401
        return _FakeCtx()

    monkeypatch.setattr(BrowserPageFetcher, "_ensure_context", _ok_ctx)

    class _OKGuard:
        async def validate_async(self, url: str) -> None:  # noqa: ARG002
            pass

    fetcher = BrowserPageFetcher(  # type: ignore[arg-type]
        guard=_OKGuard(), max_html_bytes=10_000
    )
    result = await fetcher.fetch("https://example.com/page?token=SUPER_SECRET")

    text = caplog.text
    assert "hostname=example.com path=/page" in text
    assert "final_hostname=example.com final_path=/result" in text
    assert "SUPER_SECRET" not in text
    assert "token=" not in text
    assert result.url == "https://example.com/result?q=secret"  # URL preserved internally
