"""Tests for crawl egress hardening (docs/CRAWL_EGRESS_HARDENING.md).

Covers the classification vocabulary (`crawl_failure.py`), bounded HTTP retry
before browser fallback, 403/429 handling in the hybrid fetcher, browser
failure classification + cleanup, reformatted zero-page worker outcomes
(blocked/rate-limited vs generic), knowledge-base preservation on a blocked
refresh, the per-host blocked-page cap, crawl concurrency bounds, and the
`crawl_fetch_failures_total` metric (fixed low-cardinality labels only).
"""

import asyncio
import logging
from collections.abc import Callable

import httpx
import pytest
from backend.core.config import Settings
from backend.core.errors import InvalidUrlError
from backend.core.metrics import (
    record_crawl_fetch_failure,
    render_prometheus,
    reset_registry,
)
from backend.models.audit_log import AUDIT_CRAWL_FAILED
from backend.models.crawl_job import CRAWL_STATUS_FAILED, CrawlJob
from backend.models.document import Document
from backend.models.website import WEBSITE_STATUS_READY, Website
from backend.services.ingestion import (
    BrowserPageFetcher,
    CrawlFailureClassification,
    CrawlSession,
    FetchedPage,
    FetchError,
    HybridPageFetcher,
    SsrFGuard,
    fetch_http_page,
)
from backend.services.ingestion.crawl_failure import (
    classify_http_status,
    classify_network_error,
    is_http_recoverable,
    is_http_retryable,
    safe_url_parts,
    user_facing_reason,
)
from backend.utils.robots import RobotsTxt
from backend.workers.jobs.crawl import _run_crawl_job

from tests.crawl_helpers import SAMPLE_ABOUT, SAMPLE_HTML, FakePageFetcher
from tests.fakes import (
    FakeAuditLogRepository,
    FakeCrawlJobRepository,
    FakeDocumentRepository,
    FakeUsageRecordRepository,
    FakeWebsiteRepository,
)

SEED = "https://acme.example/"
GUIDE_HTML = "<html><body><main><h1>Guide</h1><p>Step by step guide text.</p></main></body></html>"

LINKED_HTML = """<!doctype html>
<html><head><title>Acme Home</title></head>
<body><main>
  <p>Home page content for Acme.</p>
  <a href="/blocked-a">A</a>
  <a href="/blocked-b">B</a>
  <a href="/blocked-c">C</a>
</main></body></html>"""


@pytest.fixture
def guard(monkeypatch):
    g = SsrFGuard()

    async def fake_resolve(host: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(g, "resolve_async", fake_resolve)
    return g


@pytest.fixture
def patch_dns(monkeypatch):
    async def fake_resolve(self, host: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(SsrFGuard, "resolve_async", fake_resolve)


@pytest.fixture(autouse=True)
def _quiet_httpx_loggers():
    # Mirrors `configure_logging`: httpx logs full URLs (incl. query strings)
    # at INFO, so pin them to WARNING as in production.
    previous: dict[str, int] = {}
    for noisy_logger in ("httpx", "httpcore"):
        logger = logging.getLogger(noisy_logger)
        previous[noisy_logger] = logger.level
        logger.setLevel(logging.WARNING)
    yield
    for noisy_logger, level in previous.items():
        logging.getLogger(noisy_logger).setLevel(level)


def _settings(**overrides) -> Settings:
    values = {"environment": "test", "crawl_max_pages": 10, "crawl_max_depth": 2}
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class _RecordingSleeper:
    """Injects into `HybridPageFetcher` so bounded retries sleep instantly and
    record the exact delays instead of stalling the suite."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


class _BlockedBrowser:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def fetch(self, url: str) -> FetchedPage:
        self.calls.append(url)
        return FetchedPage(url=url, html=GUIDE_HTML)

    async def close(self) -> None:
        pass


class _BrowserRejecting:
    def __init__(self, classification: str, status_code: int | None = None) -> None:
        self._classification = classification
        self._status_code = status_code

    async def fetch(self, url: str) -> FetchedPage:
        raise FetchError(
            f"HTTP {self._status_code or 'error'} for {url}.",
            classification=self._classification,
            status_code=self._status_code,
            method="browser",
        )

    async def close(self) -> None:
        pass


def _never_browser() -> None:
    raise AssertionError("Chromium must not be launched in this scenario.")


async def _hybrid(guard, handler, monkeypatch, **settings_overrides) -> tuple:
    monkeypatch.setattr("backend.services.ingestion.browser.get_browser", _never_browser)
    monkeypatch.setattr(
        "backend.services.ingestion.http_first.get_settings",
        lambda: _settings(**settings_overrides),
    )
    client = _mock_client(handler)
    sleeper = _RecordingSleeper()
    fetcher = HybridPageFetcher(guard=guard, http_client_factory=lambda: client, sleep_fn=sleeper)
    return fetcher, client, sleeper


# ---------------------------------------------------------------------------
# Classification vocabulary (crawl_failure.py)
# ---------------------------------------------------------------------------


def test_classify_http_status_maps_hostile_statuses() -> None:
    assert classify_http_status(401) is CrawlFailureClassification.TARGET_BLOCKED
    assert classify_http_status(403) is CrawlFailureClassification.TARGET_BLOCKED
    assert classify_http_status(429) is CrawlFailureClassification.TARGET_RATE_LIMITED
    assert classify_http_status(404) is CrawlFailureClassification.TARGET_NOT_FOUND
    assert classify_http_status(410) is CrawlFailureClassification.TARGET_NOT_FOUND
    assert classify_http_status(500) is CrawlFailureClassification.TARGET_SERVER_ERROR
    assert classify_http_status(502) is CrawlFailureClassification.TARGET_SERVER_ERROR
    assert classify_http_status(503) is CrawlFailureClassification.TARGET_SERVER_ERROR
    assert classify_http_status(504) is CrawlFailureClassification.TARGET_SERVER_ERROR
    assert classify_http_status(200) is CrawlFailureClassification.UNKNOWN_FAILURE
    assert classify_http_status(301) is CrawlFailureClassification.UNKNOWN_FAILURE


def test_classify_network_error_splits_timeouts() -> None:
    assert (
        classify_network_error(TimeoutError("timed out"))
        is CrawlFailureClassification.CRAWL_TIMEOUT
    )
    assert (
        classify_network_error(httpx.ReadTimeout("slow"))
        is CrawlFailureClassification.CRAWL_TIMEOUT
    )
    assert (
        classify_network_error(httpx.ConnectError("down"))
        is CrawlFailureClassification.RETRYABLE_NETWORK_ERROR
    )
    assert (
        classify_network_error(RuntimeError("browser crashed"))
        is CrawlFailureClassification.RETRYABLE_NETWORK_ERROR
    )


def test_recoverable_and_retryable_status_sets() -> None:
    assert is_http_recoverable(403) is True
    assert is_http_recoverable(429) is True
    assert is_http_recoverable(503) is True
    assert is_http_recoverable(404) is False
    assert is_http_retryable(429) is True
    assert is_http_retryable(503) is True
    assert is_http_retryable(403) is False
    assert is_http_retryable(404) is False


def test_user_facing_reasons_never_expose_internals() -> None:
    assert (
        user_facing_reason(CrawlFailureClassification.TARGET_BLOCKED)
        == "The website rejected automated crawling (HTTP 403)."
    )
    assert (
        user_facing_reason(CrawlFailureClassification.TARGET_RATE_LIMITED)
        == "The website is rate-limiting automated requests."
    )
    assert user_facing_reason(CrawlFailureClassification.TARGET_SERVER_ERROR) is None
    assert user_facing_reason(CrawlFailureClassification.BROWSER_LAUNCH_FAILURE) is None
    assert user_facing_reason(None) is None


def test_safe_url_parts_strips_secrets() -> None:
    host, path = safe_url_parts("https://user:password@ExAmPle.com:8443/a/b?token=SECRET123#frag")
    assert host == "example.com"
    assert path == "/a/b"
    host, path = safe_url_parts("https://acme.example/")
    assert host == "acme.example"
    assert path == "/"


def test_fetch_error_carries_classification_metadata() -> None:
    error = FetchError(
        "HTTP 403 for x.",
        recoverable=True,
        classification="target_blocked",
        status_code=403,
        method="http",
        attempt=1,
        retry_after_seconds=5.0,
    )
    assert error.recoverable is True
    assert error.classification == "target_blocked"
    assert error.status_code == 403
    assert error.method == "http"
    assert error.attempt == 1
    assert error.retry_after_seconds == 5.0


# ---------------------------------------------------------------------------
# HybridPageFetcher retry / fallback behaviour
# ---------------------------------------------------------------------------


async def test_http_403_single_attempt_then_fallback(guard, monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    requests: list[str] = []
    browser = _BlockedBrowser()
    monkeypatch.setattr(
        "backend.services.ingestion.http_first.BrowserPageFetcher",
        lambda *, guard: browser,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(403)

    fetcher, client, sleeper = await _hybrid(guard, handler, monkeypatch)
    page = await fetcher.fetch(SEED)
    await fetcher.close()
    assert page.html == GUIDE_HTML
    assert requests == ["/"], "403 must not be retried over HTTP"
    assert browser.calls == [SEED]
    assert sleeper.delays == []


async def test_http_403_then_browser_403_yields_target_blocked(guard, monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.services.ingestion.http_first.BrowserPageFetcher",
        lambda *, guard: _BrowserRejecting("target_blocked", 403),
    )
    client = _mock_client(lambda request: httpx.Response(403))
    fetcher = HybridPageFetcher(
        guard=guard,
        http_client_factory=lambda: client,
        sleep_fn=_RecordingSleeper(),
    )
    with pytest.raises(FetchError) as exc_info:
        await fetcher.fetch(SEED)
    await fetcher.close()
    assert exc_info.value.classification == "target_blocked"
    assert exc_info.value.status_code == 403
    assert exc_info.value.method == "browser"


async def test_http_429_bounded_retries_then_falls_back(guard, monkeypatch) -> None:
    requests: list[str] = []
    browser = _BlockedBrowser()
    monkeypatch.setattr(
        "backend.services.ingestion.http_first.BrowserPageFetcher",
        lambda *, guard: browser,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(429)

    fetcher, client, sleeper = await _hybrid(guard, handler, monkeypatch)
    fetched = await fetcher.fetch(SEED)
    await fetcher.close()
    assert fetched.html == GUIDE_HTML
    assert browser.calls == [SEED]
    assert requests == ["/", "/"], "429 is bounded by crawl_http_max_attempts (2)"
    assert sleeper.delays == []


async def test_http_429_retry_after_is_capped(guard, monkeypatch) -> None:
    browser = _BlockedBrowser()
    monkeypatch.setattr(
        "backend.services.ingestion.http_first.BrowserPageFetcher",
        lambda *, guard: browser,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "3600"})

    fetcher, client, sleeper = await _hybrid(
        guard, handler, monkeypatch, crawl_retry_max_wait_seconds=30.0
    )
    page = await fetcher.fetch(SEED)
    await fetcher.close()
    assert page.html == GUIDE_HTML
    assert sleeper.delays == [30.0], "a hostile Retry-After must be capped"


async def test_http_5xx_uses_bounded_exponential_backoff(guard, monkeypatch) -> None:
    browser = _BlockedBrowser()
    monkeypatch.setattr(
        "backend.services.ingestion.http_first.BrowserPageFetcher",
        lambda *, guard: browser,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    fetcher, client, sleeper = await _hybrid(
        guard,
        handler,
        monkeypatch,
        crawl_http_max_attempts=3,
        crawl_retry_backoff_base_seconds=1.0,
        crawl_retry_backoff_cap_seconds=5.0,
    )
    page = await fetcher.fetch(SEED)
    await fetcher.close()
    assert page.html == GUIDE_HTML
    assert sleeper.delays == [1.0, 2.0]
    assert browser.calls == [SEED]


async def test_http_404_fails_without_browser_or_retry(guard, monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.services.ingestion.http_first.BrowserPageFetcher",
        lambda *, guard: pytest.fail("404 must not launch Chromium"),
    )
    client = _mock_client(lambda request: httpx.Response(404))
    fetcher = HybridPageFetcher(
        guard=guard,
        http_client_factory=lambda: client,
        sleep_fn=_RecordingSleeper(),
    )
    with pytest.raises(FetchError) as exc_info:
        await fetcher.fetch(SEED)
    await fetcher.close()
    assert exc_info.value.classification == "target_not_found"
    assert exc_info.value.status_code == 404
    assert exc_info.value.recoverable is False


async def test_blocked_fetch_logs_are_token_free(guard, monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(
        "backend.services.ingestion.http_first.BrowserPageFetcher",
        lambda *, guard: _BrowserRejecting("target_blocked", 403),
    )
    client = _mock_client(lambda request: httpx.Response(403))
    fetcher = HybridPageFetcher(
        guard=guard,
        http_client_factory=lambda: client,
        sleep_fn=_RecordingSleeper(),
    )
    token_url = "https://acme.example/private/portal?token=super-secret-abc"
    with pytest.raises(FetchError):
        await fetcher.fetch(token_url)
    await fetcher.close()
    assert "super-secret-abc" not in caplog.text
    assert "hostname=acme.example" in caplog.text
    assert "path=/private/portal" in caplog.text


async def test_ssrf_blocked_fetch_records_invalid_url_classification(guard) -> None:
    class _InvalidUrlFetcher:
        async def fetch(self, url: str) -> FetchedPage:
            raise InvalidUrlError(f"Blocked: private IP for {url}")

        async def close(self) -> None:
            pass

    session = CrawlSession(
        tenant_id="tenant-a",
        website_id="website-a",
        seed_url=SEED,
        fetcher=_InvalidUrlFetcher(),
        documents=FakeDocumentRepository(),
        guard=guard,
        settings=_settings(),
        # FIND-07: the robots gate must stay open for this test, whose intent is
        # the invalid-URL classification on the *page* fetch, not robots policy.
        robots=RobotsTxt.allow_all(),
    )
    assert await session.run() == 0
    assert session.errors[0].classification == CrawlFailureClassification.INVALID_URL.value
    assert session.errors[0].url == SEED


# ---------------------------------------------------------------------------
# Browser failure classification and cleanup
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status


class _FakePage:
    def __init__(
        self,
        *,
        status: int = 200,
        html: str = "",
        goto_error: Exception | None = None,
    ) -> None:
        self._status = status
        self._html = html
        self._goto_error = goto_error
        self.url = SEED
        self.closed = False

    async def route(self, *args, **kwargs) -> None:
        return None

    async def goto(self, url: str, *, wait_until: str, **kwargs) -> _FakeResponse:
        if self._goto_error is not None:
            raise self._goto_error
        return _FakeResponse(self._status)

    async def content(self) -> str:
        return self._html

    async def close(self) -> None:
        self.closed = True


class _FakeContext:
    def __init__(self, page: _FakePage) -> None:
        self._page = page

    async def new_page(self) -> _FakePage:
        return self._page

    async def close(self) -> None:
        pass


class _FakeBrowser:
    def __init__(self, page: _FakePage) -> None:
        self._page = page

    async def new_context(self, **kwargs) -> _FakeContext:
        return _FakeContext(self._page)


def _patch_real_browser(monkeypatch, page: _FakePage) -> None:
    async def _fake_get_browser():
        return _FakeBrowser(page)

    monkeypatch.setattr("backend.services.ingestion.browser.get_browser", _fake_get_browser)


async def test_browser_launch_failure_classified(guard, monkeypatch) -> None:
    async def _raise_launch():
        raise RuntimeError("browserType.launch: Process failed to launch")

    monkeypatch.setattr("backend.services.ingestion.browser.get_browser", _raise_launch)
    fetcher = BrowserPageFetcher(guard=guard)
    with pytest.raises(FetchError) as exc_info:
        await fetcher.fetch(SEED)
    assert exc_info.value.classification == CrawlFailureClassification.BROWSER_LAUNCH_FAILURE.value
    assert exc_info.value.method == "browser"


async def test_browser_navigation_timeout_classified_and_page_closed(guard, monkeypatch) -> None:
    page = _FakePage(goto_error=TimeoutError("Timeout 30000ms exceeded"))
    _patch_real_browser(monkeypatch, page)
    fetcher = BrowserPageFetcher(guard=guard)
    with pytest.raises(FetchError) as exc_info:
        await fetcher.fetch(SEED)
    assert exc_info.value.classification == CrawlFailureClassification.CRAWL_TIMEOUT.value
    assert exc_info.value.method == "browser"
    assert page.closed is True, "page must be released after a timeout"


async def test_browser_403_classified_and_page_closed(guard, monkeypatch) -> None:
    page = _FakePage(status=403)
    _patch_real_browser(monkeypatch, page)
    fetcher = BrowserPageFetcher(guard=guard)
    with pytest.raises(FetchError) as exc_info:
        await fetcher.fetch(SEED)
    assert exc_info.value.classification == CrawlFailureClassification.TARGET_BLOCKED.value
    assert exc_info.value.status_code == 403
    assert exc_info.value.method == "browser"
    assert page.closed is True


async def test_browser_fetch_cancellation_closes_page(guard, monkeypatch) -> None:
    class _BlockingPage(_FakePage):
        def __init__(self) -> None:
            super().__init__()
            self._wait = asyncio.Event()

        async def goto(self, url: str, *, wait_until: str, **kwargs) -> None:
            await self._wait.wait()

    page = _BlockingPage()
    _patch_real_browser(monkeypatch, page)
    fetcher = BrowserPageFetcher(guard=guard)
    task = asyncio.create_task(fetcher.fetch(SEED))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert page.closed is True, "page must be closed even when the job is cancelled"


# ---------------------------------------------------------------------------
# Worker zero-page outcomes (blocked vs generic) and KB preservation
# ---------------------------------------------------------------------------


async def _worker_env(seed: str = SEED):
    jobs = FakeCrawlJobRepository()
    documents = FakeDocumentRepository()
    websites = FakeWebsiteRepository()
    audit = FakeAuditLogRepository()
    usage = FakeUsageRecordRepository()
    website = Website.new(tenant_id="tenant-a", name="Acme", url=seed)
    await websites.create(website)
    job = CrawlJob.new(tenant_id="tenant-a", website_id=website.id)
    await jobs.create(job)
    # Production parity (FIND-02): `start_crawl` records the ownership token so
    # the worker's terminal READY/FAILED write is fenced to this job id.
    website.crawl_job_id = job.id
    await websites.update(website)
    return job, jobs, documents, websites, audit, usage


async def test_worker_zero_page_blocked_new_site(patch_dns, caplog) -> None:
    job, jobs, documents, websites, audit, usage = await _worker_env()
    fetcher = FakePageFetcher({})
    fetcher.fail(
        SEED,
        FetchError(
            "HTTP 403 for https://acme.example/.",
            recoverable=True,
            classification="target_blocked",
            status_code=403,
            method="http",
            attempt=1,
        ),
    )
    result = await _run_crawl_job(
        {"crawler_fetcher": fetcher, "job_try": 1, "max_tries": 3},
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
    )

    assert result == {"status": "failed", "pages": 0}
    stored = jobs.jobs[job.id]
    assert stored.status == CRAWL_STATUS_FAILED
    assert stored.error_message == "The website rejected automated crawling (HTTP 403)."
    first = stored.errors[0]
    assert first.classification == "target_blocked"
    assert first.status_code == 403
    assert first.method == "http"
    assert first.attempt == 1
    assert websites.websites[job.website_id].status == "failed"
    assert any(log.action == AUDIT_CRAWL_FAILED for log in audit.logs)
    assert "crawl_target_blocked job_id=" in caplog.text
    assert "hostname=acme.example" in caplog.text
    assert "path=/ " in caplog.text
    assert "status_code=403" in caplog.text
    assert "method=http" in caplog.text
    assert "attempt=1" in caplog.text
    assert "existing_pages=0" in caplog.text
    assert "reason=target_blocked" in caplog.text


async def test_worker_zero_page_rate_limited(patch_dns, caplog) -> None:
    job, jobs, documents, websites, audit, usage = await _worker_env()
    fetcher = FakePageFetcher({})
    fetcher.fail(
        SEED,
        FetchError(
            "HTTP 429 for https://acme.example/.",
            recoverable=True,
            classification="target_rate_limited",
            status_code=429,
            method="http",
            attempt=2,
        ),
    )
    result = await _run_crawl_job(
        {"crawler_fetcher": fetcher, "job_try": 1, "max_tries": 3},
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
    )

    assert result == {"status": "failed", "pages": 0}
    stored = jobs.jobs[job.id]
    assert stored.error_message == "The website is rate-limiting automated requests."
    assert stored.errors[0].classification == "target_rate_limited"
    assert stored.errors[0].attempt == 2
    assert "crawl_target_rate_limited job_id=" in caplog.text
    assert "status_code=429" in caplog.text
    assert "reason=target_rate_limited" in caplog.text


async def test_worker_zero_page_non_blocked_keeps_generic_message(patch_dns, caplog) -> None:
    job, jobs, documents, websites, audit, usage = await _worker_env()
    fetcher = FakePageFetcher({})
    fetcher.fail(SEED, FetchError("browser crashed"))
    result = await _run_crawl_job(
        {"crawler_fetcher": fetcher, "job_try": 1, "max_tries": 3},
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
    )

    assert result == {"status": "failed", "pages": 0}
    stored = jobs.jobs[job.id]
    assert stored.error_message == "No pages were fetched."
    assert "reason=no_pages" in caplog.text
    assert "crawl_target_blocked" not in caplog.text


async def test_worker_blocked_refresh_preserves_knowledge_base(patch_dns) -> None:
    job, jobs, documents, websites, audit, usage = await _worker_env()
    existing = Document.new(
        tenant_id="tenant-a",
        website_id=job.website_id,
        url=SEED,
        title="Existing home",
        content="Existing indexed content",
        checksum="c" * 64,
    )
    await documents.upsert(existing)
    website = websites.websites[job.website_id]
    website.status = WEBSITE_STATUS_READY
    website.pages_indexed = 1
    await websites.update(website)
    fetcher = FakePageFetcher({})
    fetcher.fail(
        SEED,
        FetchError(
            "HTTP 403 for https://acme.example/.",
            recoverable=True,
            classification="target_blocked",
            status_code=403,
            method="http",
            attempt=1,
        ),
    )

    result = await _run_crawl_job(
        {"crawler_fetcher": fetcher, "job_try": 1, "max_tries": 3},
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
    )

    assert result == {"status": "failed", "pages": 0}
    stored_job = jobs.jobs[job.id]
    assert stored_job.error_message == (
        "The website rejected automated crawling (HTTP 403). "
        "Your existing knowledge base is still available."
    )
    assert documents.documents[existing.id].content == "Existing indexed content"
    assert websites.websites[job.website_id].status == WEBSITE_STATUS_READY
    assert websites.websites[job.website_id].pages_indexed == 1


# ---------------------------------------------------------------------------
# Per-host blocked/rate-limited budget
# ---------------------------------------------------------------------------


async def test_blocked_page_cap_aborts_session(guard) -> None:
    pages = {SEED: LINKED_HTML, "https://acme.example/about": SAMPLE_ABOUT}
    fetcher = FakePageFetcher(pages)
    for path in ("blocked-a", "blocked-b", "blocked-c"):
        fetcher.fail(
            f"https://acme.example/{path}",
            FetchError(
                f"HTTP 403 for https://acme.example/{path}.",
                classification="target_blocked",
                status_code=403,
                method="browser",
            ),
        )
    session = CrawlSession(
        tenant_id="tenant-a",
        website_id="website-a",
        seed_url=SEED,
        fetcher=fetcher,
        documents=FakeDocumentRepository(),
        guard=guard,
        settings=_settings(crawl_max_blocked_pages_per_host=2),
    )
    stored = await session.run()

    assert stored == 1
    assert session.blocked_host_aborted is True
    blocked = [error for error in session.errors if error.classification == "target_blocked"]
    assert len(blocked) == 2
    assert any("multiple pages" in error.message for error in session.errors)
    attempted = {error.url for error in session.errors}
    assert sum("blocked-" in url for url in attempted) == 2


async def test_worker_logs_blocked_host_abort(patch_dns, caplog, monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.services.ingestion.crawler.get_settings",
        lambda: _settings(crawl_max_blocked_pages_per_host=2),
    )
    job, jobs, documents, websites, audit, usage = await _worker_env()
    fetcher = FakePageFetcher({SEED: LINKED_HTML})
    for path in ("blocked-a", "blocked-b"):
        fetcher.fail(
            f"https://acme.example/{path}",
            FetchError(
                f"HTTP 403 for https://acme.example/{path}.",
                classification="target_blocked",
                status_code=403,
                method="browser",
            ),
        )
    result = await _run_crawl_job(
        {"crawler_fetcher": fetcher, "job_try": 1, "max_tries": 3},
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
    )

    assert result == {"status": "completed", "pages": 1}
    stored_job = jobs.jobs[job.id]
    assert stored_job.status != CRAWL_STATUS_FAILED
    assert stored_job.pages_completed == 1
    assert "crawl_finished" in caplog.text
    assert "reason=blocked_host_aborted" in caplog.text


async def test_worker_unblocked_crawl_completes_with_reason_success(patch_dns, caplog) -> None:
    caplog.set_level(logging.INFO)
    job, jobs, documents, websites, audit, usage = await _worker_env()
    fetcher = FakePageFetcher({SEED: SAMPLE_HTML, "https://acme.example/about": SAMPLE_ABOUT})
    result = await _run_crawl_job(
        {"crawler_fetcher": fetcher, "job_try": 1, "max_tries": 3},
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
    )

    assert result == {"status": "completed", "pages": 2}
    assert "crawl_finished" in caplog.text
    assert "reason=success" in caplog.text
    assert "reason=blocked_host_aborted" not in caplog.text


# ---------------------------------------------------------------------------
# Crawl concurrency bound (memory safety)
# ---------------------------------------------------------------------------


def test_crawl_semaphore_reads_configured_limit(monkeypatch) -> None:
    import backend.services.ingestion.browser as browser_module

    class StubSettings:
        crawl_max_concurrent = 1

    monkeypatch.setattr(browser_module, "get_settings", lambda: StubSettings())
    monkeypatch.setattr(browser_module, "_semaphore", None)
    semaphore = browser_module.crawl_semaphore()
    assert semaphore._value == 1


# ---------------------------------------------------------------------------
# Metrics (crawl_fetch_failures_total)
# ---------------------------------------------------------------------------


class TestCrawlFailureMetrics:
    @pytest.fixture(autouse=True)
    def _clean_metrics(self):
        reset_registry()
        yield
        reset_registry()

    def test_record_crawl_fetch_failure_labels(self) -> None:
        record_crawl_fetch_failure(classification="target_blocked", status_code=403, method="http")
        record_crawl_fetch_failure(
            classification="target_blocked", status_code=403, method="browser"
        )
        record_crawl_fetch_failure(classification="target_rate_limited", status_code=429)
        output = render_prometheus()
        assert (
            'crawl_fetch_failures_total{classification="target_blocked", status_code="403", '
            'method="http"} 1'
        ) in output
        assert (
            'crawl_fetch_failures_total{classification="target_blocked", status_code="403", '
            'method="browser"} 1'
        ) in output
        assert (
            'crawl_fetch_failures_total{classification="target_rate_limited", status_code="429", '
            'method="http"} 1'
        ) in output

    async def test_metric_labels_never_contain_urls(self, guard) -> None:
        client = _mock_client(lambda request: httpx.Response(403))
        with pytest.raises(FetchError):
            await fetch_http_page(
                "https://acme.example/private?token=super-secret-abc",
                client=client,
                guard=guard,
                max_html_bytes=5_000_000,
            )
        await client.aclose()
        output = render_prometheus()
        assert "super-secret-abc" not in output
        assert "acme.example" not in output
        assert (
            'crawl_fetch_failures_total{classification="target_blocked", status_code="403", '
            'method="http"} 1'
        ) in output
