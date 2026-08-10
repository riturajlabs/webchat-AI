"""Tests for the ARQ `crawl_website` worker logic (Phase 4, ADR-002).

`_run_crawl_job` is exercised directly with in-memory fakes and a fake page
fetcher injected via `ctx["crawler_fetcher"]`; `SsrFGuard.resolve_async` is
patched so no real DNS/network is touched.
"""

import asyncio

import pytest
from backend.models.audit_log import AUDIT_CRAWL_COMPLETED, AUDIT_CRAWL_FAILED
from backend.models.crawl_job import (
    CRAWL_ACTIVE_STATUSES,
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_FAILED,
    CrawlJob,
)
from backend.models.website import WEBSITE_STATUS_READY, Website
from backend.services.ingestion import SsrFGuard
from backend.workers.jobs.crawl import _run_crawl_job
from tests.crawl_helpers import SAMPLE_ABOUT, SAMPLE_HTML, FakePageFetcher
from tests.fakes import (
    FakeAuditLogRepository,
    FakeCrawlJobRepository,
    FakeDocumentRepository,
    FakeWebsiteRepository,
)

SEED = "https://acme.example/"


@pytest.fixture
def patch_dns(monkeypatch):
    async def fake_resolve(self, host: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(SsrFGuard, "resolve_async", fake_resolve)


async def _env(*, seed: str = SEED, pages: dict[str, str] | None = None):
    jobs = FakeCrawlJobRepository()
    documents = FakeDocumentRepository()
    websites = FakeWebsiteRepository()
    audit = FakeAuditLogRepository()
    website = Website.new(tenant_id="tenant-a", name="Acme", url=seed)
    await websites.create(website)
    job = CrawlJob.new(tenant_id="tenant-a", website_id=website.id)
    await jobs.create(job)
    fetcher = FakePageFetcher(
        pages or {seed: SAMPLE_HTML, "https://acme.example/about": SAMPLE_ABOUT}
    )
    ctx: dict = {"crawler_fetcher": fetcher, "job_try": 1, "max_tries": 3}
    return ctx, job, jobs, documents, websites, audit


async def test_worker_completes_job_and_updates_website(patch_dns) -> None:
    ctx, job, jobs, documents, websites, audit = await _env()

    result = await _run_crawl_job(
        ctx, job.id, crawl_jobs=jobs, documents=documents, websites=websites, audit=audit
    )

    assert result["status"] == "completed"
    assert result["pages"] == 2
    stored = jobs.jobs[job.id]
    assert stored.status == CRAWL_STATUS_COMPLETED
    assert stored.completed_at is not None
    assert stored.pages_completed == 2
    website = websites.websites[list(websites.websites)[0]]
    assert website.status == WEBSITE_STATUS_READY
    assert website.pages_indexed == 2
    assert website.last_crawled_at is not None
    assert website.checksum
    assert any(log.action == AUDIT_CRAWL_COMPLETED for log in audit.logs)
    # Documents were stored with content checksums.
    assert len(documents.documents) == 2
    assert all(doc.checksum for doc in documents.documents.values())


async def test_worker_skips_unknown_job(patch_dns) -> None:
    ctx, _, jobs, documents, websites, audit = await _env()
    result = await _run_crawl_job(
        ctx, "missing", crawl_jobs=jobs, documents=documents, websites=websites, audit=audit
    )
    assert result == {"status": "not_found"}


async def test_worker_skips_already_terminal_job(patch_dns) -> None:
    ctx, job, jobs, documents, websites, audit = await _env()
    job.status = CRAWL_STATUS_FAILED
    await jobs.update(job)

    result = await _run_crawl_job(
        ctx, job.id, crawl_jobs=jobs, documents=documents, websites=websites, audit=audit
    )
    assert result == {"status": CRAWL_STATUS_FAILED}
    assert documents.documents == {}


async def test_worker_fails_job_when_website_missing(patch_dns) -> None:
    ctx, job, jobs, documents, websites, audit = await _env()
    job.website_id = "gone"
    await jobs.update(job)

    result = await _run_crawl_job(
        ctx, job.id, crawl_jobs=jobs, documents=documents, websites=websites, audit=audit
    )
    assert result == {"status": "failed"}
    stored = jobs.jobs[job.id]
    assert stored.status == CRAWL_STATUS_FAILED
    assert stored.error_message == "Website no longer exists."


async def test_worker_final_retry_marks_failed(patch_dns) -> None:
    ctx, job, jobs, documents, websites, audit = await _env()
    ctx["crawler_fetcher"].fail(SEED, RuntimeError("browser crashed"))
    ctx["job_try"] = 3

    with pytest.raises(RuntimeError):
        await _run_crawl_job(
            ctx, job.id, crawl_jobs=jobs, documents=documents, websites=websites, audit=audit
        )

    stored = jobs.jobs[job.id]
    assert stored.status == CRAWL_STATUS_FAILED
    assert "browser crashed" in (stored.error_message or "")
    website = websites.websites[list(websites.websites)[0]]
    assert website.status == "failed"
    assert any(log.action == AUDIT_CRAWL_FAILED for log in audit.logs)


async def test_worker_acquires_crawl_semaphore(patch_dns, monkeypatch) -> None:
    """`_run_crawl_job` bounds browser sessions through `crawl_semaphore`.

    The memory-safety contract (browser.py docstring): many jobs may be in
    flight under ARQ `max_jobs`, but only `crawl_max_concurrent` may drive the
    shared Chromium at once.
    """
    import backend.workers.jobs.crawl as crawl_module

    entered: list[str] = []

    class TrackingSemaphore:
        def __init__(self) -> None:
            self._sem = asyncio.Semaphore(2)

        async def __aenter__(self) -> None:
            entered.append("enter")
            await self._sem.__aenter__()

        async def __aexit__(self, *exc: object) -> None:
            await self._sem.__aexit__(*exc)

    monkeypatch.setattr(crawl_module, "crawl_semaphore", lambda: TrackingSemaphore())

    ctx, job, jobs, documents, websites, audit = await _env()
    result = await _run_crawl_job(
        ctx, job.id, crawl_jobs=jobs, documents=documents, websites=websites, audit=audit
    )
    assert result["status"] == "completed"
    assert entered == ["enter"]


async def test_worker_fails_permanently_on_ssrf_blocked_seed(patch_dns, monkeypatch) -> None:
    """SSRF-blocked seeds fail immediately instead of burning ARQ retries."""

    async def private_resolve(self, host: str) -> list[str]:
        return ["127.0.0.1"]

    monkeypatch.setattr(SsrFGuard, "resolve_async", private_resolve)

    ctx, job, jobs, documents, websites, audit = await _env()
    result = await _run_crawl_job(
        ctx, job.id, crawl_jobs=jobs, documents=documents, websites=websites, audit=audit
    )

    assert result == {"status": "failed"}
    stored = jobs.jobs[job.id]
    assert stored.status == CRAWL_STATUS_FAILED
    assert "private or internal" in (stored.error_message or "")
    assert any(log.action == AUDIT_CRAWL_FAILED for log in audit.logs)


async def test_worker_keeps_job_active_on_transient_failure(patch_dns) -> None:
    ctx, job, jobs, documents, websites, audit = await _env()
    ctx["crawler_fetcher"].fail(SEED, RuntimeError("browser crashed"))
    ctx["job_try"] = 1

    with pytest.raises(RuntimeError):
        await _run_crawl_job(
            ctx, job.id, crawl_jobs=jobs, documents=documents, websites=websites, audit=audit
        )

    stored = jobs.jobs[job.id]
    assert stored.status in CRAWL_ACTIVE_STATUSES
    assert stored.error_message is None
    website = websites.websites[list(websites.websites)[0]]
    assert website.status == "pending"
    assert not any(log.action == AUDIT_CRAWL_FAILED for log in audit.logs)


async def test_worker_enqueues_knowledge_pass_after_success(patch_dns) -> None:
    """A successful crawl hands the documents off to the knowledge pipeline."""
    ctx, job, jobs, documents, websites, audit = await _env()
    enqueued: list[str] = []

    async def fake_enqueue(website_id: str) -> None:
        enqueued.append(website_id)

    result = await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        enqueue_knowledge=fake_enqueue,
    )

    assert result["status"] == "completed"
    assert enqueued == [job.website_id]


async def test_worker_skips_knowledge_pass_on_failure(patch_dns) -> None:
    """No knowledge handoff on a failed crawl (nothing new to embed)."""
    ctx, job, jobs, documents, websites, audit = await _env()
    ctx["crawler_fetcher"].fail(SEED, RuntimeError("browser crashed"))
    ctx["job_try"] = 3
    enqueued: list[str] = []

    async def fake_enqueue(website_id: str) -> None:
        enqueued.append(website_id)

    with pytest.raises(RuntimeError):
        await _run_crawl_job(
            ctx,
            job.id,
            crawl_jobs=jobs,
            documents=documents,
            websites=websites,
            audit=audit,
            enqueue_knowledge=fake_enqueue,
        )

    assert enqueued == []
