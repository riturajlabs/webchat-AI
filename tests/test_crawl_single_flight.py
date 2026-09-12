"""FIND-02 distributed single-flight gate for crawl jobs.

Covers the Mongo `CrawlJob.active` unique partial-index gate, the
`finish_if_active` single-terminator, the website `crawl_job_id` ownership
fence, the job-scoped ARQ `_job_id`, and the explicit TOCTOU race between two
simultaneous `start_crawl` callers (design §6–§14). Tests use the in-memory
fakes; the fence semantics mirror the real Mongo repository.
"""

import asyncio
import uuid

import pytest
from backend.core.errors import CrawlConflictError
from backend.core.security import utcnow
from backend.models.audit_log import AUDIT_CRAWL_COMPLETED, AUDIT_CRAWL_FAILED
from backend.models.crawl_job import (
    CRAWL_ACTIVE_STATUSES,
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_FAILED,
    CRAWL_STATUS_PENDING,
    CrawlJob,
)
from backend.models.usage_record import usage_date_key
from backend.models.website import (
    WEBSITE_STATUS_CRAWLING,
    WEBSITE_STATUS_DELETED,
    WEBSITE_STATUS_READY,
    Website,
)
from backend.services.crawl import CrawlService
from backend.services.ingestion import SsrFGuard
from backend.workers.jobs import crawl as crawl_module
from backend.workers.jobs.crawl import _run_crawl_job, enqueue_crawl_website

from tests.crawl_helpers import SAMPLE_ABOUT, SAMPLE_HTML, FakePageFetcher, build_crawl_env
from tests.fakes import (
    FakeAuditLogRepository,
    FakeCrawlJobRepository,
    FakeDocumentRepository,
    FakeUsageRecordRepository,
    FakeWebsiteRepository,
)
from tests.website_helpers import make_principal

SEED = "https://acme.example/"


@pytest.fixture
def patch_dns(monkeypatch) -> None:
    async def fake_resolve(self, host: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(SsrFGuard, "resolve_async", fake_resolve)


async def _add_website(env, *, tenant_id: str = "tenant-a", seed: str = SEED) -> Website:
    website = Website.new(tenant_id=tenant_id, name="Acme", url=seed)
    await env.websites.create(website)
    return website


async def _worker_env(
    *,
    seed: str = SEED,
    pages: dict[str, str] | None = None,
    website_status: str | None = None,
    crawl_job_owner: str | None = None,
):
    jobs = FakeCrawlJobRepository()
    documents = FakeDocumentRepository()
    websites = FakeWebsiteRepository()
    audit = FakeAuditLogRepository()
    usage = FakeUsageRecordRepository()
    website = Website.new(tenant_id="tenant-a", name="Acme", url=seed)
    if website_status is not None:
        website.status = website_status
        if website_status == WEBSITE_STATUS_DELETED:
            website.deleted = True
    await websites.create(website)

    job = CrawlJob.new(tenant_id="tenant-a", website_id=website.id)
    await jobs.create(job)

    # Production parity: `start_crawl` records the ownership token on the
    # website so the worker's terminal write is fenced to this job id.
    website.crawl_job_id = crawl_job_owner if crawl_job_owner is not None else job.id
    await websites.update(website)

    default_pages = {seed: SAMPLE_HTML, "https://acme.example/about": SAMPLE_ABOUT}
    fetcher = FakePageFetcher(pages if pages is not None else default_pages)
    ctx: dict = {"crawler_fetcher": fetcher, "job_try": 1, "max_tries": 3}
    return ctx, job, jobs, documents, websites, audit, usage


async def _run(
    ctx,
    job,
    *,
    jobs,
    documents,
    websites,
    audit,
    usage,
    enqueue_knowledge=None,
):
    return await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
        enqueue_knowledge=enqueue_knowledge,
    )


class _BarrierCrawlJobs(FakeCrawlJobRepository):
    """Freeze both callers inside the pre-check so neither `create()` runs first.

    Both `start_crawl` calls read `find_active_for_website -> None` before
    either reaches `create`. Correctness must come from the repository fence
    (the unique partial index), never from serializing the service call.
    """

    def __init__(self) -> None:
        super().__init__()
        self._entered = 0
        self._both_here = asyncio.Event()
        self._release = asyncio.Event()

    async def find_active_for_website(self, tenant_id: str, website_id: str) -> CrawlJob | None:
        self._entered += 1
        if self._entered >= 2:
            self._both_here.set()
        await self._release.wait()
        return await super().find_active_for_website(tenant_id, website_id)


async def test_second_active_job_for_same_website_conflicts() -> None:
    """The repository gate mirrors the Mongo unique partial index: creating a
    second ACTIVE crawl row for the same (tenant, website) fails."""
    env = build_crawl_env()
    website = await _add_website(env)
    await env.crawl_jobs.create(CrawlJob.new(tenant_id="tenant-a", website_id=website.id))

    with pytest.raises(CrawlConflictError):
        await env.crawl_jobs.create(CrawlJob.new(tenant_id="tenant-a", website_id=website.id))

    # Releasing the fence (terminal transition) admits a new active row.
    existing = env.crawl_jobs.jobs[list(env.crawl_jobs.jobs)[0]]
    await env.crawl_jobs.finish_if_active(
        existing.id,
        "tenant-a",
        terminal_status=CRAWL_STATUS_COMPLETED,
        completed_at=utcnow(),
    )
    await env.crawl_jobs.create(CrawlJob.new(tenant_id="tenant-a", website_id=website.id))


async def test_start_crawl_rejects_active_job_status() -> None:
    """The status fast-path pre-check also rejects an active job row."""
    env = build_crawl_env()
    website = await _add_website(env)
    active = CrawlJob.new(tenant_id="tenant-a", website_id=website.id)
    await env.crawl_jobs.create(active)
    principal = make_principal(tenant_id="tenant-a")

    with pytest.raises(CrawlConflictError):
        await env.service.start_crawl(
            principal=principal, website_id=website.id, ip_address=None, user_agent=None
        )
    assert env.enqueued == []


async def test_completed_job_releases_the_gate() -> None:
    """A released (terminal) job no longer blocks a new crawl for the website."""
    env = build_crawl_env()
    website = await _add_website(env)
    done = CrawlJob.new(tenant_id="tenant-a", website_id=website.id)
    await env.crawl_jobs.create(done)
    released = await env.crawl_jobs.finish_if_active(
        done.id, "tenant-a", terminal_status=CRAWL_STATUS_COMPLETED, completed_at=utcnow()
    )
    assert released is True
    assert env.crawl_jobs.jobs[done.id].active is False

    principal = make_principal(tenant_id="tenant-a")
    job = await env.service.start_crawl(
        principal=principal, website_id=website.id, ip_address=None, user_agent=None
    )
    assert job.status == CRAWL_STATUS_PENDING
    assert env.enqueued == [job.id]
    assert env.websites.websites[website.id].status == WEBSITE_STATUS_CRAWLING
    assert env.websites.websites[website.id].crawl_job_id == job.id


async def test_failed_job_releases_the_gate() -> None:
    env = build_crawl_env()
    website = await _add_website(env)
    failed = CrawlJob.new(tenant_id="tenant-a", website_id=website.id)
    await env.crawl_jobs.create(failed)
    await env.crawl_jobs.finish_if_active(
        failed.id, "tenant-a", terminal_status=CRAWL_STATUS_FAILED, completed_at=utcnow()
    )
    principal = make_principal(tenant_id="tenant-a")

    job = await env.service.start_crawl(
        principal=principal, website_id=website.id, ip_address=None, user_agent=None
    )
    assert job.status == CRAWL_STATUS_PENDING
    assert env.enqueued == [job.id]


async def test_simultaneous_start_crawl_race_single_winner() -> None:
    """Design §14 TOCTOU: two callers both see `no active job`; the repository
    fence guarantees exactly one crawl job exists and one is enqueued."""
    websites = FakeWebsiteRepository()
    website = Website.new(tenant_id="tenant-a", name="Acme", url=SEED)
    await websites.create(website)
    jobs = _BarrierCrawlJobs()
    enqueued: list[str] = []
    audit = FakeAuditLogRepository()

    async def enqueue(job_id: str) -> None:
        enqueued.append(job_id)

    service = CrawlService(crawl_jobs=jobs, websites=websites, audit=audit, enqueue=enqueue)
    principal = make_principal(tenant_id="tenant-a")

    async def call() -> CrawlJob:
        return await service.start_crawl(
            principal=principal, website_id=website.id, ip_address=None, user_agent=None
        )

    task_a = asyncio.create_task(call())
    task_b = asyncio.create_task(call())
    await jobs._both_here.wait()
    jobs._release.set()
    results = await asyncio.gather(task_a, task_b, return_exceptions=True)

    wins = [r for r in results if not isinstance(r, BaseException)]
    conflicts = [r for r in results if isinstance(r, CrawlConflictError)]
    assert len(wins) == 1
    assert len(conflicts) == 1
    assert len(jobs.jobs) == 1
    assert enqueued == [wins[0].id]
    assert websites.websites[website.id].status == WEBSITE_STATUS_CRAWLING
    assert websites.websites[website.id].crawl_job_id == wins[0].id


async def test_finish_if_active_is_single_terminator() -> None:
    """Only one caller wins the terminal transition; stale calls no-op and the
    winning terminal fields are preserved."""
    jobs = FakeCrawlJobRepository()
    job = CrawlJob.new(tenant_id="tenant-a", website_id="w1")
    await jobs.create(job)
    completed_at = utcnow()

    assert (
        await jobs.finish_if_active(
            job.id,
            "tenant-a",
            terminal_status=CRAWL_STATUS_COMPLETED,
            completed_at=completed_at,
            pages_completed=5,
        )
        is True
    )
    stored = jobs.jobs[job.id]
    assert stored.status == CRAWL_STATUS_COMPLETED
    assert stored.active is False
    assert stored.pages_completed == 5
    assert stored.completed_at == completed_at

    assert (
        await jobs.finish_if_active(
            job.id, "tenant-a", terminal_status=CRAWL_STATUS_FAILED, error_message="boom"
        )
        is False
    )
    reloaded = jobs.jobs[job.id]
    assert reloaded.status == CRAWL_STATUS_COMPLETED
    assert reloaded.pages_completed == 5
    assert reloaded.error_message != "boom"


async def test_finish_if_active_requires_active_status() -> None:
    jobs = FakeCrawlJobRepository()
    job = CrawlJob.new(tenant_id="tenant-a", website_id="w1")
    job.status = CRAWL_STATUS_COMPLETED
    await jobs.create(job)

    assert (
        await jobs.finish_if_active(job.id, "tenant-a", terminal_status=CRAWL_STATUS_FAILED)
        is False
    )


async def test_finish_if_active_is_tenant_scoped() -> None:
    jobs = FakeCrawlJobRepository()
    job = CrawlJob.new(tenant_id="tenant-a", website_id="w1")
    await jobs.create(job)

    # Credential confusion (wrong tenant) must never transition another tenant's job.
    assert (
        await jobs.finish_if_active(job.id, "other-tenant", terminal_status=CRAWL_STATUS_FAILED)
        is False
    )
    assert jobs.jobs[job.id].active is True


class _FakeArqRedis:
    """Mirrors ARQ's `_job_id` deduplication (`WATCH`/`MULTI` on the job key)."""

    def __init__(self) -> None:
        self.job_ids: set[str] = set()
        self.calls: list[tuple[str, str]] = []

    async def enqueue_job(
        self,
        function: str,
        *args: object,
        _job_id: str | None = None,
        **kwargs: object,
    ) -> str | None:
        key = _job_id or uuid.uuid4().hex
        if key in self.job_ids:
            return None
        self.job_ids.add(key)
        self.calls.append((function, str(args[0]), _job_id))
        return key


async def test_enqueue_job_id_is_job_scoped(monkeypatch) -> None:
    """ARQ dedup key is `crawl:{crawl_job_id}`, never a static website key."""
    fake = _FakeArqRedis()
    monkeypatch.setattr(crawl_module, "_arq_redis", lambda: fake)

    await enqueue_crawl_website("job-123")
    await enqueue_crawl_website("job-456")

    assert fake.calls == [
        ("crawl_website", "job-123", "crawl:job-123"),
        ("crawl_website", "job-456", "crawl:job-456"),
    ]


async def test_reenqueue_same_job_id_is_deduplicated(monkeypatch) -> None:
    fake = _FakeArqRedis()
    monkeypatch.setattr(crawl_module, "_arq_redis", lambda: fake)

    await enqueue_crawl_website("job-123")
    await enqueue_crawl_website("job-123")

    assert len(fake.calls) == 1
    assert fake.job_ids == {"crawl:job-123"}


async def test_new_job_after_completion_still_enqueues(monkeypatch) -> None:
    """ARQ `keep_result` (1 h) suppresses only the SAME job id, so a manual
    re-crawl (a new job id) always enqueues within the window."""
    fake = _FakeArqRedis()
    monkeypatch.setattr(crawl_module, "_arq_redis", lambda: fake)

    await enqueue_crawl_website("job-123")
    # Simulate ARQ's keep_result window: the same id is swallowed.
    assert await enqueue_crawl_website("job-123") is None
    # A fresh job id always enqueues.
    await enqueue_crawl_website("job-456")

    assert [job_id for _, _, job_id in fake.calls] == ["crawl:job-123", "crawl:job-456"]


async def test_successful_crawl_releases_gate_and_writes_owned_website(patch_dns) -> None:
    ctx, job, jobs, documents, websites, audit, usage = await _worker_env()
    enqueued: list[str] = []

    async def enqueue(website_id: str) -> None:
        enqueued.append(website_id)

    result = await _run(
        ctx,
        job,
        jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
        enqueue_knowledge=enqueue,
    )

    assert result["status"] == "completed"
    stored = jobs.jobs[job.id]
    assert stored.status == CRAWL_STATUS_COMPLETED
    assert stored.active is False
    website = websites.websites[job.website_id]
    assert website.status == WEBSITE_STATUS_READY
    assert website.pages_indexed == 2
    assert website.crawl_job_id == job.id
    assert enqueued == [job.website_id]


async def test_duplicate_terminal_completion_has_no_second_side_effects(patch_dns) -> None:
    """A stale re-delivery of an already-terminal job skips before any side
    effect: no second website write, audit log, usage rollup, or knowledge
    handoff."""
    ctx, job, jobs, documents, websites, audit, usage = await _worker_env()
    enqueued: list[str] = []

    async def enqueue(website_id: str) -> None:
        enqueued.append(website_id)

    first = await _run(
        ctx,
        job,
        jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
        enqueue_knowledge=enqueue,
    )
    second = await _run(
        ctx,
        job,
        jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
        enqueue_knowledge=enqueue,
    )

    assert first["status"] == "completed"
    assert second["status"] == "completed"
    completed_audits = [log for log in audit.logs if log.action == AUDIT_CRAWL_COMPLETED]
    assert len(completed_audits) == 1
    assert enqueued == [job.website_id]
    record = usage.get_record("tenant-a", job.website_id, usage_date_key())
    assert (record.counters.get("crawl_pages") if record else 0) == 2


async def test_older_crawl_cannot_overwrite_newer_owner_website(patch_dns) -> None:
    """A newer crawl re-queued on the website (new owner token) must not be
    overwritten by this older active job finishing."""
    ctx, job, jobs, documents, websites, audit, usage = await _worker_env(
        crawl_job_owner="newer-job"
    )
    result = await _run(
        ctx, job, jobs=jobs, documents=documents, websites=websites, audit=audit, usage=usage
    )

    assert result["status"] == "completed"
    stored = jobs.jobs[job.id]
    assert stored.status == CRAWL_STATUS_COMPLETED
    website = websites.websites[job.website_id]
    assert website.crawl_job_id == "newer-job"
    assert website.status != WEBSITE_STATUS_READY
    assert website.last_crawled_at is None


async def test_deleted_website_mid_job_fails_without_resurrect(patch_dns) -> None:
    ctx, job, jobs, documents, websites, audit, usage = await _worker_env(
        website_status=WEBSITE_STATUS_DELETED
    )
    result = await _run(
        ctx, job, jobs=jobs, documents=documents, websites=websites, audit=audit, usage=usage
    )

    assert result == {"status": "failed"}
    stored = jobs.jobs[job.id]
    assert stored.status == CRAWL_STATUS_FAILED
    assert stored.error_message == "Website no longer exists."
    assert stored.active is False
    website = websites.websites[job.website_id]
    assert website.status == WEBSITE_STATUS_DELETED
    assert website.deleted is True


async def test_website_fence_refuses_resurrection(patch_dns) -> None:
    websites = FakeWebsiteRepository()
    website = Website.new(tenant_id="tenant-a", name="Acme", url=SEED)
    website.status = WEBSITE_STATUS_DELETED
    website.deleted = True
    website.crawl_job_id = "job-1"
    await websites.create(website)

    replacement = website.model_copy(update={"status": WEBSITE_STATUS_READY, "deleted": False})
    ok = await websites.update_if_crawl_owner("tenant-a", website.id, "job-1", replacement)

    assert ok is False
    assert websites.websites[website.id].status == WEBSITE_STATUS_DELETED
    assert websites.websites[website.id].deleted is True


async def test_zero_page_terminal_is_fenced(patch_dns) -> None:
    ctx, job, jobs, documents, websites, audit, usage = await _worker_env(pages={})
    result = await _run(
        ctx, job, jobs=jobs, documents=documents, websites=websites, audit=audit, usage=usage
    )

    assert result == {"status": "failed", "pages": 0}
    stored = jobs.jobs[job.id]
    assert stored.status == CRAWL_STATUS_FAILED
    assert stored.active is False
    website = websites.websites[job.website_id]
    assert website.status == "failed"
    assert not any(log.action == AUDIT_CRAWL_COMPLETED for log in audit.logs)
    record = usage.get_record("tenant-a", job.website_id, usage_date_key())
    assert record is None or record.counters.get("crawl_pages", 0) == 0


async def test_invalid_url_terminates_job_once_via_fence(patch_dns) -> None:
    ctx, job, jobs, documents, websites, audit, usage = await _worker_env(
        seed="mailto:hi@acme.example"
    )
    result = await _run(
        ctx, job, jobs=jobs, documents=documents, websites=websites, audit=audit, usage=usage
    )

    assert result == {"status": "failed"}
    stored = jobs.jobs[job.id]
    assert stored.status == CRAWL_STATUS_FAILED
    assert stored.active is False
    assert "not crawlable" in (stored.error_message or "")
    failed_audits = [log for log in audit.logs if log.action == AUDIT_CRAWL_FAILED]
    assert len(failed_audits) == 1
    website = websites.websites[job.website_id]
    assert website.status == "failed"

    # A stale re-delivery of the same failed job emits nothing new.
    again = await _run(
        ctx, job, jobs=jobs, documents=documents, websites=websites, audit=audit, usage=usage
    )
    assert again == {"status": "failed"}
    assert len(audit.logs) == 1


async def test_final_retry_failure_is_fenced(patch_dns) -> None:
    ctx, job, jobs, documents, websites, audit, usage = await _worker_env()
    ctx["crawler_fetcher"].fail(SEED, RuntimeError("browser crashed"))
    ctx["job_try"] = 3

    with pytest.raises(RuntimeError):
        await _run(
            ctx, job, jobs=jobs, documents=documents, websites=websites, audit=audit, usage=usage
        )

    stored = jobs.jobs[job.id]
    assert stored.status == CRAWL_STATUS_FAILED
    assert stored.active is False
    assert "browser crashed" in (stored.error_message or "")
    website = websites.websites[job.website_id]
    assert website.status == "failed"
    assert sum(1 for log in audit.logs if log.action == AUDIT_CRAWL_FAILED) == 1

    # A stale duplicate terminal attempt no-ops.
    assert (
        await jobs.finish_if_active(job.id, "tenant-a", terminal_status=CRAWL_STATUS_COMPLETED)
        is False
    )


async def test_transient_retry_keeps_job_active(patch_dns) -> None:
    ctx, job, jobs, documents, websites, audit, usage = await _worker_env()
    ctx["crawler_fetcher"].fail(SEED, RuntimeError("browser crashed"))
    ctx["job_try"] = 1

    with pytest.raises(RuntimeError):
        await _run(
            ctx, job, jobs=jobs, documents=documents, websites=websites, audit=audit, usage=usage
        )

    stored = jobs.jobs[job.id]
    assert stored.status in CRAWL_ACTIVE_STATUSES
    assert stored.active is True
    assert not any(log.action == AUDIT_CRAWL_FAILED for log in audit.logs)
    assert websites.websites[job.website_id].status != "failed"


async def test_different_tenants_same_website_id_are_independent() -> None:
    """The unique index is per (tenant, website), so tenants never fence each
    other even when a shared website id string appears under both."""
    jobs = FakeCrawlJobRepository()
    await jobs.create(CrawlJob.new(tenant_id="tenant-a", website_id="w1"))
    await jobs.create(CrawlJob.new(tenant_id="tenant-b", website_id="w1"))

    assert len(jobs.jobs) == 2
    # Each tenant's own active row blocks only that tenant.
    with pytest.raises(CrawlConflictError):
        await jobs.create(CrawlJob.new(tenant_id="tenant-a", website_id="w1"))
    with pytest.raises(CrawlConflictError):
        await jobs.create(CrawlJob.new(tenant_id="tenant-b", website_id="w1"))


async def test_legacy_crawl_job_without_active_flag_defaults_active(patch_dns) -> None:
    """Documents written before FIND-02 have no `active` field; they must parse
    with `active=True` so legacy in-progress rows still count toward the fence."""
    from backend.models.crawl_job import CrawlJob as ModelCrawlJob

    now = utcnow()
    legacy_doc = {
        "_id": "legacy-1",
        "tenant_id": "tenant-a",
        "website_id": "w1",
        "status": "running",
        "pages_total": 0,
        "pages_completed": 0,
        "errors": [],
        "created_at": now,
        "updated_at": now,
        "schema_version": 1,
    }
    job = ModelCrawlJob.from_doc(legacy_doc)
    assert job.active is True
    assert job.id == "legacy-1"
