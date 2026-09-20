"""Regression tests for the `crawl_pages` usage-event accounting gap.

Phase 13 billing documents `max_crawl_pages` as "crawl_pages usage_events per
calendar month" (`backend/models/plan.py`) and `crawl_pages` as an ingestion
event ("pages crawled by the ingestion pipeline", `backend/models/usage_event.py`),
but the crawl worker only used to write the daily `usage_records` rollup
(ADR-005 §5.5 analytics). `UsageService.check_limit`/`get_current_usage` read
`crawl_pages` from `usage_events`, so the limit could never fire in production.

These tests pin: a winning completed crawl appends exactly one `crawl_pages`
usage event whose quantity equals the pages stored; the event feeds enforcement
and the usage snapshot; an exhausted limit blocks further crawls; a losing,
stale or failed attempt never double-counts; tenants stay isolated; the
`usage_records` rollup is preserved; and the uploaded-file/document quota is
unaffected by crawl usage events.
"""

from datetime import UTC, datetime

import pytest
from backend.core.errors import LimitReachedError
from backend.models.crawl_job import CrawlJob
from backend.models.document import SOURCE_TYPE_FILE, Document
from backend.models.tenant import Tenant
from backend.models.usage_event import UsageEvent
from backend.models.usage_record import usage_date_key
from backend.models.website import Website
from backend.services.auth import Principal
from backend.services.billing import UsageService
from backend.services.crawl import CrawlService
from backend.services.ingestion import SsrFGuard
from backend.workers.jobs.crawl import _run_crawl_job

from tests.crawl_helpers import SAMPLE_ABOUT, SAMPLE_HTML, FakePageFetcher
from tests.fakes import (
    FakeAuditLogRepository,
    FakeCrawlJobRepository,
    FakeDocumentRepository,
    FakeTenantRepository,
    FakeUsageEventRepository,
    FakeUsageRecordRepository,
    FakeWebsiteRepository,
)

SEED = "https://acme.example/"
SINCE = datetime(2020, 1, 1, tzinfo=UTC)


@pytest.fixture
def patch_dns(monkeypatch):
    async def fake_resolve(self, host: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(SsrFGuard, "resolve_async", fake_resolve)


def _tenant(tenants: FakeTenantRepository, *, tenant_id: str = "tenant-a") -> None:
    tenant = Tenant.new(company_name="Acme")
    tenant.id = tenant_id
    tenant.plan = "free"
    tenants.tenants[tenant_id] = tenant


def _principal(*, tenant_id: str = "tenant-a") -> Principal:
    return Principal(
        user_id="user-a",
        tenant_id=tenant_id,
        role="owner",
        name="Alice",
        email="alice@example.com",
        email_verified=True,
        status="active",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


async def _worker_env(*, tenant_id: str = "tenant-a", pages: dict[str, str] | None = None):
    jobs = FakeCrawlJobRepository()
    documents = FakeDocumentRepository()
    websites = FakeWebsiteRepository()
    audit = FakeAuditLogRepository()
    usage = FakeUsageRecordRepository()
    events = FakeUsageEventRepository()
    website = Website.new(tenant_id=tenant_id, name="Acme", url=SEED)
    await websites.create(website)
    job = CrawlJob.new(tenant_id=tenant_id, website_id=website.id)
    await jobs.create(job)
    # Production parity (FIND-02): the ownership token fences the terminal write.
    website.crawl_job_id = job.id
    await websites.update(website)
    fetcher = FakePageFetcher(
        pages or {SEED: SAMPLE_HTML, "https://acme.example/about": SAMPLE_ABOUT}
    )
    ctx: dict = {"crawler_fetcher": fetcher, "job_try": 1, "max_tries": 3}
    return ctx, job, jobs, documents, websites, audit, usage, events


def _crawl_entries(events: FakeUsageEventRepository) -> list[UsageEvent]:
    return [event for event in events.events if event.event_type == "crawl_pages"]


# A. A successful crawl records the expected crawl_pages usage.
async def test_successful_crawl_records_crawl_pages_usage_event(patch_dns) -> None:
    ctx, job, jobs, documents, websites, audit, usage, events = await _worker_env()

    result = await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
        events=events,
    )

    assert result["status"] == "completed"
    assert result["pages"] == 2
    entries = _crawl_entries(events)
    assert len(entries) == 1
    assert entries[0].tenant_id == "tenant-a"
    assert entries[0].website_id == job.website_id
    assert entries[0].user_id is None  # worker is a system action
    assert entries[0].quantity == 2  # exactly one unit per stored page
    # The existing analytics rollup is still written (not replaced).
    record = usage.get_record("tenant-a", job.website_id, usage_date_key())
    assert record is not None
    assert record.counters["crawl_pages"] == 2


# B. quota enforcement and the usage snapshot see the recorded usage.
async def test_enforcement_and_snapshot_see_worker_recorded_pages(patch_dns) -> None:
    ctx, job, jobs, documents, websites, audit, usage, events = await _worker_env()
    await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
        events=events,
    )

    tenants = FakeTenantRepository()
    _tenant(tenants)
    service = UsageService(
        events=events,
        tenants=tenants,
        websites=websites,
        documents=documents,
        subscriptions=None,
    )

    snapshot = await service.get_current_usage("tenant-a")
    assert snapshot.totals.crawl_pages == 2
    crawl = next(metric for metric in snapshot.metrics if metric.metric == "crawl_pages")
    assert crawl.used == 2
    assert crawl.limit == 500  # Free plan, unchanged
    # 2 used + 1 for the next crawl still fits under the cap.
    await service.check_limit("tenant-a", event_type="crawl_pages")


# C. Once the configured limit is exhausted, another crawl is rejected.
async def test_exhausted_crawl_pages_limit_blocks_new_crawl(patch_dns) -> None:
    ctx, job, jobs, documents, websites, audit, usage, events = await _worker_env()
    await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
        events=events,
    )
    assert (await events.totals_by_type_since("tenant-a", SINCE)).crawl_pages == 2
    # Top the Free cap up: 2 recorded + 498 more = 500/500.
    await events.record(
        UsageEvent.new(
            tenant_id="tenant-a",
            user_id=None,
            website_id=None,
            event_type="crawl_pages",
            quantity=498,
        )
    )
    assert (await events.totals_by_type_since("tenant-a", SINCE)).crawl_pages == 500

    tenants = FakeTenantRepository()
    _tenant(tenants)
    usage_service = UsageService(
        events=events,
        tenants=tenants,
        websites=websites,
        documents=documents,
        subscriptions=None,
    )
    enqueued: list[str] = []

    async def enqueue(job_id: str) -> None:
        enqueued.append(job_id)

    crawl_service = CrawlService(
        crawl_jobs=jobs,
        websites=websites,
        audit=audit,
        enqueue=enqueue,
        usage=usage_service,
    )

    with pytest.raises(LimitReachedError):
        await crawl_service.start_crawl(
            principal=_principal(),
            website_id=job.website_id,
            ip_address=None,
            user_agent=None,
        )
    # Gated before the job was created/queued.
    assert len(jobs.jobs) == 1  # only the original completed job
    assert enqueued == []


# D. A losing/stale crawl does not double-count usage (duplicate delivery).
async def test_stale_duplicate_delivery_does_not_double_count(patch_dns) -> None:
    ctx, job, jobs, documents, websites, audit, usage, events = await _worker_env()

    first = await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
        events=events,
    )
    # The same (already terminal) job is re-delivered, e.g. by the queue.
    second = await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
        events=events,
    )

    assert first["status"] == "completed"
    assert second["status"] == "completed"
    assert len(_crawl_entries(events)) == 1
    assert _crawl_entries(events)[0].quantity == 2
    # The rollup is also recorded exactly once.
    record = usage.get_record("tenant-a", job.website_id, usage_date_key())
    assert record.counters["crawl_pages"] == 2


# E. A failed attempt then a successful retry records exactly once.
async def test_failed_attempt_then_retry_records_once(patch_dns) -> None:
    ctx, job, jobs, documents, websites, audit, usage, events = await _worker_env()
    ctx["crawler_fetcher"].fail(SEED, RuntimeError("browser crashed"))

    with pytest.raises(RuntimeError):
        await _run_crawl_job(
            ctx,
            job.id,
            crawl_jobs=jobs,
            documents=documents,
            websites=websites,
            audit=audit,
            usage=usage,
            events=events,
        )
    # Nothing was recorded while the job remained active (non-final try).
    assert _crawl_entries(events) == []
    record = usage.get_record("tenant-a", job.website_id, usage_date_key())
    assert record is None or record.counters.get("crawl_pages", 0) == 0

    # ARQ retries the SAME job id; this attempt succeeds.
    ctx["crawler_fetcher"] = FakePageFetcher(
        {SEED: SAMPLE_HTML, "https://acme.example/about": SAMPLE_ABOUT}
    )
    ctx["job_try"] = 2
    result = await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
        events=events,
    )

    assert result["status"] == "completed"
    entries = _crawl_entries(events)
    assert len(entries) == 1
    assert entries[0].quantity == 2
    record = usage.get_record("tenant-a", job.website_id, usage_date_key())
    assert record.counters["crawl_pages"] == 2


# F. Tenant A usage cannot affect Tenant B (and vice versa).
async def test_crawl_pages_usage_events_are_tenant_scoped(patch_dns) -> None:
    ctx, job, jobs, documents, websites, audit, usage, events = await _worker_env()
    other_website = Website.new(tenant_id="tenant-b", name="Other", url=SEED)
    await websites.create(other_website)
    other_job = CrawlJob.new(tenant_id="tenant-b", website_id=other_website.id)
    await jobs.create(other_job)
    other_website.crawl_job_id = other_job.id
    await websites.update(other_website)
    ctx_other: dict = {
        "crawler_fetcher": FakePageFetcher(
            {SEED: SAMPLE_HTML, "https://acme.example/about": SAMPLE_ABOUT}
        ),
        "job_try": 1,
        "max_tries": 3,
    }

    await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
        events=events,
    )
    await _run_crawl_job(
        ctx_other,
        other_job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
        events=events,
    )

    assert (await events.totals_by_type_since("tenant-a", SINCE)).crawl_pages == 2
    assert (await events.totals_by_type_since("tenant-b", SINCE)).crawl_pages == 2
    assert all(event.tenant_id in ("tenant-a", "tenant-b") for event in events.events)
    # Each event carries exactly its own tenant id.
    assert {event.tenant_id for event in _crawl_entries(events)} == {"tenant-a", "tenant-b"}
    tenant_a_rollup = usage.get_record("tenant-a", job.website_id, usage_date_key())
    tenant_b_rollup = usage.get_record("tenant-b", other_website.id, usage_date_key())
    assert tenant_a_rollup is not None and tenant_b_rollup is not None
    assert tenant_a_rollup.counters["crawl_pages"] == 2
    assert tenant_b_rollup.counters["crawl_pages"] == 2


# G. usage_records analytics behavior remains correct alongside events.
async def test_usage_records_rollup_and_events_stay_consistent(patch_dns) -> None:
    ctx, job, jobs, documents, websites, audit, usage, events = await _worker_env()

    await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
        events=events,
    )

    # Analytics rollup: every stored page counted under (tenant, website, day).
    record = usage.get_record("tenant-a", job.website_id, usage_date_key())
    assert record.counters["crawl_pages"] == 2
    # Billing ledger: the same winning run appends exactly one event with the
    # same page count. The two stores are independent by design: rollups feed
    # analytics/admin, events feed monthly limit enforcement.
    assert (await events.totals_by_type_since("tenant-a", SINCE)).crawl_pages == 2
    assert len(_crawl_entries(events)) == 1


# H. Website/file document quota is unaffected by crawl usage events.
async def test_document_quota_ignores_crawl_usage_events(patch_dns) -> None:
    ctx, job, jobs, documents, websites, audit, usage, events = await _worker_env()
    await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
        events=events,
    )

    # The crawl stored 2 website documents; add one uploaded file document.
    await documents.upsert(
        Document.new(
            tenant_id="tenant-a",
            website_id=job.website_id,
            url="file://budget.pdf",
            title="budget.pdf",
            content="budget contents",
            checksum="b" * 64,
            source_type=SOURCE_TYPE_FILE,
            file_name="budget.pdf",
            file_size_bytes=1024,
            mime_type="application/pdf",
            storage_key="tenant-a/budget.pdf",
            file_checksum_sha256="c" * 64,
        )
    )

    tenants = FakeTenantRepository()
    _tenant(tenants)
    service = UsageService(
        events=events,
        tenants=tenants,
        websites=websites,
        documents=documents,
        subscriptions=None,
    )
    snapshot = await service.get_current_usage("tenant-a")
    # Only the uploaded file counts toward the documents (upload) quota.
    assert snapshot.websites == 1
    assert snapshot.documents == 1
    assert (await events.totals_by_type_since("tenant-a", SINCE)).crawl_pages == 2
    # A crawl that stored 2 website pages never inflated the document quota.
    document_metric = next(metric for metric in snapshot.metrics if metric.metric == "documents")
    assert document_metric.used == 1
    assert document_metric.limit == 10  # Free plan, unchanged
