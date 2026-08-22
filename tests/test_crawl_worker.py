"""Tests for the ARQ `crawl_website` worker logic (Phase 4, ADR-002).

`_run_crawl_job` is exercised directly with in-memory fakes and a fake page
fetcher injected via `ctx["crawler_fetcher"]`; `SsrFGuard.resolve_async` is
patched so no real DNS/network is touched.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest
from backend.models.audit_log import AUDIT_CRAWL_COMPLETED, AUDIT_CRAWL_FAILED
from backend.models.crawl_job import (
    CRAWL_ACTIVE_STATUSES,
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_FAILED,
    CrawlJob,
)
from backend.models.usage_record import usage_date_key
from backend.models.website import WEBSITE_STATUS_READY, Website
from backend.services.ingestion import SsrFGuard
from backend.workers.jobs.crawl import _run_crawl_job

from tests.crawl_helpers import SAMPLE_ABOUT, SAMPLE_HTML, FakePageFetcher
from tests.fakes import (
    FakeAuditLogRepository,
    FakeCacheStore,
    FakeCrawlJobRepository,
    FakeDocumentRepository,
    FakeUsageRecordRepository,
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
    usage = FakeUsageRecordRepository()
    website = Website.new(tenant_id="tenant-a", name="Acme", url=seed)
    await websites.create(website)
    job = CrawlJob.new(tenant_id="tenant-a", website_id=website.id)
    await jobs.create(job)
    fetcher = FakePageFetcher(
        pages or {seed: SAMPLE_HTML, "https://acme.example/about": SAMPLE_ABOUT}
    )
    ctx: dict = {"crawler_fetcher": fetcher, "job_try": 1, "max_tries": 3}
    return ctx, job, jobs, documents, websites, audit, usage


async def test_worker_completes_job_and_updates_website(patch_dns) -> None:
    ctx, job, jobs, documents, websites, audit, usage = await _env()

    result = await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
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
    ctx, _, jobs, documents, websites, audit, usage = await _env()
    result = await _run_crawl_job(
        ctx,
        "missing",
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
    )
    assert result == {"status": "not_found"}


async def test_worker_skips_already_terminal_job(patch_dns) -> None:
    ctx, job, jobs, documents, websites, audit, usage = await _env()
    job.status = CRAWL_STATUS_FAILED
    await jobs.update(job)

    result = await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
    )
    assert result == {"status": CRAWL_STATUS_FAILED}
    assert documents.documents == {}


async def test_worker_fails_job_when_website_missing(patch_dns) -> None:
    ctx, job, jobs, documents, websites, audit, usage = await _env()
    job.website_id = "gone"
    await jobs.update(job)

    result = await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
    )
    assert result == {"status": "failed"}
    stored = jobs.jobs[job.id]
    assert stored.status == CRAWL_STATUS_FAILED
    assert stored.error_message == "Website no longer exists."


async def test_worker_final_retry_marks_failed(patch_dns) -> None:
    ctx, job, jobs, documents, websites, audit, usage = await _env()
    ctx["crawler_fetcher"].fail(SEED, RuntimeError("browser crashed"))
    ctx["job_try"] = 3

    with pytest.raises(RuntimeError):
        await _run_crawl_job(
            ctx,
            job.id,
            crawl_jobs=jobs,
            documents=documents,
            websites=websites,
            audit=audit,
            usage=usage,
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

    ctx, job, jobs, documents, websites, audit, usage = await _env()
    result = await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
    )
    assert result["status"] == "completed"
    assert entered == ["enter"]


async def test_worker_fails_permanently_on_ssrf_blocked_seed(patch_dns, monkeypatch) -> None:
    """SSRF-blocked seeds fail immediately instead of burning ARQ retries."""

    async def private_resolve(self, host: str) -> list[str]:
        return ["127.0.0.1"]

    monkeypatch.setattr(SsrFGuard, "resolve_async", private_resolve)

    ctx, job, jobs, documents, websites, audit, usage = await _env()
    result = await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
    )

    assert result == {"status": "failed"}
    stored = jobs.jobs[job.id]
    assert stored.status == CRAWL_STATUS_FAILED
    assert "private or internal" in (stored.error_message or "")
    assert any(log.action == AUDIT_CRAWL_FAILED for log in audit.logs)


async def test_worker_keeps_job_active_on_transient_failure(patch_dns) -> None:
    ctx, job, jobs, documents, websites, audit, usage = await _env()
    ctx["crawler_fetcher"].fail(SEED, RuntimeError("browser crashed"))
    ctx["job_try"] = 1

    with pytest.raises(RuntimeError):
        await _run_crawl_job(
            ctx,
            job.id,
            crawl_jobs=jobs,
            documents=documents,
            websites=websites,
            audit=audit,
            usage=usage,
        )

    stored = jobs.jobs[job.id]
    assert stored.status in CRAWL_ACTIVE_STATUSES
    assert stored.error_message is None
    website = websites.websites[list(websites.websites)[0]]
    assert website.status == "pending"
    assert not any(log.action == AUDIT_CRAWL_FAILED for log in audit.logs)


async def test_worker_enqueues_knowledge_pass_after_success(patch_dns) -> None:
    """A successful crawl hands the documents off to the knowledge pipeline."""
    ctx, job, jobs, documents, websites, audit, usage = await _env()
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
        usage=usage,
        enqueue_knowledge=fake_enqueue,
    )

    assert result["status"] == "completed"
    assert enqueued == [job.website_id]


async def test_worker_skips_knowledge_pass_on_failure(patch_dns) -> None:
    """No knowledge handoff on a failed crawl (nothing new to embed)."""
    ctx, job, jobs, documents, websites, audit, usage = await _env()
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


# ---------------------------------------------------------------------------
# Usage rollup tests (Phase 12.3, ADR-005 §5.5)
# ---------------------------------------------------------------------------


async def test_crawl_success_increments_crawl_pages(patch_dns) -> None:
    """ADR-005 §5.5: every successfully indexed page counts on the daily rollup."""
    ctx, job, jobs, documents, websites, audit, usage = await _env()

    result = await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
    )

    assert result["status"] == "completed"
    record = usage.get_record("tenant-a", job.website_id, usage_date_key())
    assert record is not None
    assert record.counters["crawl_pages"] == result["pages"] == 2


async def test_failed_crawl_does_not_increment_crawl_pages(patch_dns) -> None:
    """A failed crawl must NOT increment the rollup; only success counts."""
    ctx, job, jobs, documents, websites, audit, usage = await _env()
    ctx["crawler_fetcher"].fail(SEED, RuntimeError("browser crashed"))
    ctx["job_try"] = 3

    with pytest.raises(RuntimeError):
        await _run_crawl_job(
            ctx,
            job.id,
            crawl_jobs=jobs,
            documents=documents,
            websites=websites,
            audit=audit,
            usage=usage,
        )

    record = usage.get_record("tenant-a", job.website_id, usage_date_key())
    assert record is None or record.counters.get("crawl_pages", 0) == 0


async def test_crawl_pages_is_tenant_scoped(patch_dns) -> None:
    """A second tenant's crawl must roll up under its own tenant_id only."""
    ctx, job, jobs, documents, websites, audit, usage = await _env()
    other_website = Website.new(tenant_id="tenant-b", name="Other", url="https://other.example/")
    await websites.create(other_website)
    other_job = CrawlJob.new(tenant_id="tenant-b", website_id=other_website.id)
    await jobs.create(other_job)
    other_pages = {
        "https://other.example/": SAMPLE_HTML,
        "https://other.example/about": SAMPLE_ABOUT,
    }
    other_fetcher = FakePageFetcher(other_pages)
    ctx_other: dict = {"crawler_fetcher": other_fetcher, "job_try": 1, "max_tries": 3}

    await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
    )
    await _run_crawl_job(
        ctx_other,
        other_job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
    )

    tenant_a = usage.get_record("tenant-a", job.website_id, usage_date_key())
    tenant_b = usage.get_record("tenant-b", other_website.id, usage_date_key())
    assert tenant_a is not None and tenant_b is not None
    assert tenant_a.counters["crawl_pages"] == 2
    assert tenant_b.counters["crawl_pages"] == 2
    # Cross-tenant reads return no record (the unique key scopes by tenant).
    assert usage.get_record("tenant-a", other_website.id, usage_date_key()) is None
    assert usage.get_record("tenant-b", job.website_id, usage_date_key()) is None


async def test_usage_increment_failure_does_not_fail_crawl(patch_dns) -> None:
    """A broken usage repo must not fail the crawl (best-effort rollups)."""

    class FailingUsage(FakeUsageRecordRepository):
        async def increment(self, **kwargs: object) -> None:  # type: ignore[override]
            raise RuntimeError("mongo down")

    ctx, job, jobs, documents, websites, audit, _usage = await _env()

    result = await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=FailingUsage(),
    )

    assert result["status"] == "completed"
    assert result["pages"] == 2
    website = websites.websites[job.website_id]
    assert website.status == WEBSITE_STATUS_READY
    assert website.pages_indexed == 2


async def test_zero_page_crawl_does_not_increment(patch_dns) -> None:
    """An empty page crawl stores the page but the usage no-op guard holds.

    The page-count rollup guard `_record_crawl_pages` must skip `increment`
    when `count=0`. An empty body no longer produces zero stored pages (it is
    stored as a failed "Insufficient content" document), so the guard is
    verified directly with a `count=0` call.
    """
    ctx, job, jobs, documents, websites, audit, _usage = await _env()

    class RecordingUsage(FakeUsageRecordRepository):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[dict] = []

        async def increment(self, **kwargs: object) -> None:  # type: ignore[override]
            self.calls.append(kwargs)
            await super().increment(**kwargs)

    recording = RecordingUsage()
    empty_pages = {SEED: "<!doctype html><html><head></head></html>"}
    ctx["crawler_fetcher"] = FakePageFetcher(empty_pages)

    result = await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=recording,
    )

    assert result["status"] == "completed"
    # The empty page is stored (not dropped) so it surfaces on the dashboard.
    assert result["pages"] == 1
    # The success branch reaches `_record_crawl_pages` once with the page count.
    assert recording.calls == [{"count": 1}] or all(
        call.get("counters", {}).get("crawl_pages") == 1 for call in recording.calls
    )
    assert len(recording.calls) == 1
    stored = next(iter(documents.documents.values()))
    assert stored.knowledge_status == "failed"
    assert stored.knowledge_failure_reason == "Insufficient content"

    # The count=0 no-op guard: nothing is written for a zero-page rollup.
    from backend.workers.jobs.crawl import _record_crawl_pages

    await _record_crawl_pages(
        usage=recording,
        tenant_id=job.tenant_id,
        website_id=job.website_id,
        count=0,
    )
    assert len(recording.calls) == 1


# ---------------------------------------------------------------------------
# Crawl event emission tests (Phase 16, real-time progress)
# ---------------------------------------------------------------------------


async def test_worker_publishes_started_event(patch_dns, monkeypatch) -> None:
    """Worker emits crawl.started when the job begins."""
    publish_started = AsyncMock()
    monkeypatch.setattr("backend.workers.jobs.crawl.crawl_events.publish_started", publish_started)

    ctx, job, jobs, documents, websites, audit, usage = await _env()
    await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
    )
    publish_started.assert_awaited_once_with(job.id)


async def test_worker_publishes_progress_events(patch_dns, monkeypatch) -> None:
    """Worker emits crawl.progress during page fetching."""
    publish_progress = AsyncMock()
    monkeypatch.setattr(
        "backend.workers.jobs.crawl.crawl_events.publish_progress", publish_progress
    )

    ctx, job, jobs, documents, websites, audit, usage = await _env()
    await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
    )
    # on_progress is called at least once (initial + per page)
    assert publish_progress.await_count >= 1


async def test_worker_publishes_completed_event(patch_dns, monkeypatch) -> None:
    """Worker emits crawl.completed with page/chunk counts on success."""
    publish_completed = AsyncMock()
    monkeypatch.setattr(
        "backend.workers.jobs.crawl.crawl_events.publish_completed",
        publish_completed,
    )

    ctx, job, jobs, documents, websites, audit, usage = await _env()
    await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
    )
    publish_completed.assert_awaited_once()
    call_kwargs = publish_completed.call_args[1]
    assert call_kwargs["pages"] == 2


async def test_worker_publishes_failed_event_on_final_retry(patch_dns, monkeypatch) -> None:
    """Worker emits crawl.failed when all retries exhausted."""
    publish_failed = AsyncMock()
    monkeypatch.setattr("backend.workers.jobs.crawl.crawl_events.publish_failed", publish_failed)

    ctx, job, jobs, documents, websites, audit, usage = await _env()
    ctx["crawler_fetcher"].fail(SEED, RuntimeError("browser crashed"))
    ctx["job_try"] = 3

    with pytest.raises(RuntimeError):
        await _run_crawl_job(
            ctx,
            job.id,
            crawl_jobs=jobs,
            documents=documents,
            websites=websites,
            audit=audit,
            usage=usage,
        )
    publish_failed.assert_awaited_once()
    call_kwargs = publish_failed.call_args[1]
    assert "browser crashed" in call_kwargs["error"]


async def test_worker_publishes_fetching_events(patch_dns, monkeypatch) -> None:
    """Worker emits crawl.fetching for each page URL."""
    publish_fetching = AsyncMock()
    monkeypatch.setattr(
        "backend.workers.jobs.crawl.crawl_events.publish_fetching",
        publish_fetching,
    )

    ctx, job, jobs, documents, websites, audit, usage = await _env()
    await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
    )
    # Should be called for each page URL fetched
    assert publish_fetching.await_count >= 2


async def test_worker_publishes_extracting_events(patch_dns, monkeypatch) -> None:
    """Worker emits crawl.extracting for each page after fetch."""
    publish_extracting = AsyncMock()
    monkeypatch.setattr(
        "backend.workers.jobs.crawl.crawl_events.publish_extracting",
        publish_extracting,
    )

    ctx, job, jobs, documents, websites, audit, usage = await _env()
    await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
    )
    # Should be called for each page after extraction
    assert publish_extracting.await_count >= 2


async def test_worker_publishes_failed_on_ssrf_blocked(patch_dns, monkeypatch) -> None:
    """Worker emits crawl.failed for SSRF-blocked seeds."""
    publish_failed = AsyncMock()
    monkeypatch.setattr("backend.workers.jobs.crawl.crawl_events.publish_failed", publish_failed)

    async def private_resolve(self, host: str) -> list[str]:
        return ["127.0.0.1"]

    monkeypatch.setattr(SsrFGuard, "resolve_async", private_resolve)

    ctx, job, jobs, documents, websites, audit, usage = await _env()
    await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
    )
    publish_failed.assert_awaited_once()


async def test_worker_invalidates_retrieval_cache_on_completion(patch_dns) -> None:
    """Successful crawl invalidates retrieval cache for the website only."""
    ctx, job, jobs, documents, websites, audit, usage = await _env()
    cache = FakeCacheStore()

    # Seed the cache with entries for this website and a different website.
    await cache.set("retrieval", f"{job.website_id}:what is acme", '["stale"]')
    await cache.set("retrieval", f"{job.website_id}:pricing", '["stale"]')
    await cache.set("retrieval", "other-website-id:pricing", '["keep"]')
    assert len(cache._data) == 3

    result = await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
        cache=cache,
    )

    assert result["status"] == "completed"
    # The two entries for this website must be evicted.
    assert await cache.get("retrieval", f"{job.website_id}:what is acme") is None
    assert await cache.get("retrieval", f"{job.website_id}:pricing") is None
    # The entry for the other website must be untouched.
    assert await cache.get("retrieval", "other-website-id:pricing") == '["keep"]'


async def test_worker_cache_invalidation_is_best_effort(patch_dns) -> None:
    """Cache invalidation failure must not fail the crawl job."""

    class BrokenCache:
        async def delete_by_prefix(self, namespace: str, prefix: str) -> int:
            raise ConnectionError("Redis down")

        async def get(self, namespace: str, key: str) -> str | None:
            return None

        async def set(
            self, namespace: str, key: str, value: str, *, ttl: int | None = None
        ) -> None:
            pass

        async def delete(self, namespace: str, key: str) -> None:
            pass

    ctx, job, jobs, documents, websites, audit, usage = await _env()

    result = await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
        cache=BrokenCache(),
    )

    assert result["status"] == "completed"
