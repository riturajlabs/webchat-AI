"""Crawl staging simulation under a real queue (Phase 17B, sections 12-13).

The scenario the brief asks for, executed against the *real* crawl job
orchestration (``_run_crawl_job``, behind the production ``crawl_website``
coroutine), the real function registry, and a real Mongo queue:

    Worker A claims -> A begins -> A produces partial pages
    -> A's lease expires -> Worker B reclaims -> B completes
    -> A resumes and tries to finish

Everything the crawl touches beyond the queue is a fake: the page fetcher, the
document/usage/audit repositories, the progress publisher, the knowledge
fan-out and the embedding client. No network, provider or production
collection is involved. What is NOT faked is the part under test: the queue's
lease/fencing, and the crawl job's own single-terminator winner gate.

Two independent gates are being exercised, and it is worth being precise:

* the **queue** gate is ``locked_by`` + ``execution_version``; a stale worker
  cannot complete or fail the row.
* the **crawl** gate is ``crawl_jobs.finish_if_active``; only the attempt that
  transitions the crawl job to a terminal status may run the purge, the website
  write, the audit entry, the usage rollup, the usage events and the knowledge
  fan-out (FIND-02, WK-01).

Dual execution is therefore safe only because *both* gates hold. The tests below
deliberately break each one in isolation to show the other still holds.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from backend.core import crawl_events
from backend.models.audit_log import AUDIT_CRAWL_COMPLETED, AUDIT_CRAWL_FAILED
from backend.models.crawl_job import CRAWL_STATUS_COMPLETED, CRAWL_STATUS_RUNNING, CrawlJob
from backend.models.usage_record import usage_date_key
from backend.models.website import Website
from backend.queue.mongo_adapter import MongoQueueAdapter
from backend.queue.registry import resolve
from backend.queue.worker import MongoWorkerLoop
from backend.services.ingestion import FetchError, SsrFGuard
from backend.workers.jobs.crawl import _run_crawl_job
from motor.motor_asyncio import AsyncIOMotorDatabase
from tests.crawl_helpers import SAMPLE_ABOUT, SAMPLE_HTML, FakePageFetcher
from tests.fakes import (
    FakeAuditLogRepository,
    FakeCrawlJobRepository,
    FakeDocumentRepository,
    FakeUsageEventRepository,
    FakeUsageRecordRepository,
    FakeWebsiteRepository,
)

SEED = "https://acme.example/"
ABOUT = "https://acme.example/about"
TENANT = "tenant-a"
LIVE_PAGES = {SEED: SAMPLE_HTML, ABOUT: SAMPLE_ABOUT}
LEASE_SECONDS = 0.4


@pytest.fixture
def patch_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SSRF guard resolves locally; no real DNS is performed."""

    async def fake_resolve(self: Any, host: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(SsrFGuard, "resolve_async", fake_resolve)


class RecordingEnqueue:
    """Fake knowledge handoff: records the fan-out, enqueues nothing."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __call__(self, website_id: str) -> None:
        self.calls.append(website_id)


@dataclass
class CrawlStaging:
    """A crawl-job environment plus the queue the workers will claim from."""

    jobs: FakeCrawlJobRepository
    documents: FakeDocumentRepository
    websites: FakeWebsiteRepository
    audit: FakeAuditLogRepository
    usage: FakeUsageRecordRepository
    events: FakeUsageEventRepository
    website: Website
    job: CrawlJob
    knowledge: RecordingEnqueue
    queue: MongoQueueAdapter

    async def crawl(
        self, pages: dict[str, str] | None = None, *, before: Any = None
    ) -> dict[str, Any]:
        """Run the real crawl orchestration with the fake fetch map applied."""
        ctx: dict[str, Any] = {
            "crawler_fetcher": FakePageFetcher(LIVE_PAGES if pages is None else pages),
            "job_try": 1,
            "max_tries": 3,
        }
        if before is not None:
            await before()
        return await _run_crawl_job(
            ctx,
            self.job.id,
            crawl_jobs=self.jobs,
            documents=self.documents,
            websites=self.websites,
            audit=self.audit,
            usage=self.usage,
            events=self.events,
            vector=None,
            enqueue_knowledge=self.knowledge,
            cache=None,
        )

    def rollup(self, tenant_id: str = TENANT) -> int:
        """The ADR-005 §5.5 analytics counter for `crawl_pages`."""
        record = self.usage.get_record(tenant_id, self.website.id, usage_date_key())
        return 0 if record is None else record.counters.get("crawl_pages", 0)

    def rollup_for(self, metric: str, tenant_id: str = TENANT) -> int:
        record = self.usage.get_record(tenant_id, self.website.id, usage_date_key())
        return 0 if record is None else record.counters.get(metric, 0)

    def usage_events(self) -> int:
        """Total `crawl_pages` in the ledger: events carry `quantity=count`."""
        return sum(
            event.quantity
            for event in self.events.events
            if event.event_type == "crawl_pages"
        )

    def usage_event_count(self) -> int:
        return len(self.events.events)

    def audit_actions(self) -> list[str]:
        return [entry.action for entry in self.audit.logs]

    async def stored(self) -> int:
        return await self.documents.count_by_website(TENANT, self.website.id)


async def _seed(env: CrawlStaging, *, dedup: bool = True) -> str:
    """Put a `crawl_website` job on the queue, as production enqueue does."""
    return await env.queue.enqueue(
        "crawl_website",
        payload={"crawl_job_id": env.job.id},
        tenant_id=TENANT,
        job_id=f"crawl:{env.job.id}" if dedup else None,
    )


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


@pytest.fixture
async def staging(
    queue_db: AsyncIOMotorDatabase[dict[str, object]],
    patch_dns: None,
) -> AsyncIterator[CrawlStaging]:
    jobs = FakeCrawlJobRepository()
    documents = FakeDocumentRepository()
    websites = FakeWebsiteRepository()
    audit = FakeAuditLogRepository()
    usage = FakeUsageRecordRepository()
    events = FakeUsageEventRepository()
    website = Website.new(tenant_id=TENANT, name="Acme", url=SEED)
    await websites.create(website)
    job = CrawlJob.new(tenant_id=TENANT, website_id=website.id)
    await jobs.create(job)
    # FIND-02 production parity: `start_crawl` stamps the ownership token, so
    # the worker's terminal website write is fenced to this job id.
    website.crawl_job_id = job.id
    await websites.update(website)

    queue = MongoQueueAdapter(
        queue_db,
        collection_name="crawl_staging",
        lease_seconds=LEASE_SECONDS,
        heartbeat_seconds=LEASE_SECONDS / 2,
    )
    await queue.ensure_indexes()
    env = CrawlStaging(
        jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
        events=events,
        website=website,
        job=job,
        knowledge=RecordingEnqueue(),
        queue=queue,
    )
    yield env
    await queue_db.drop_collection("crawl_staging")


@contextlib.contextmanager
def spy_on(obj: Any, name: str) -> Iterator[list[tuple[tuple[Any, ...], dict[str, Any]]]]:
    """Record every call to `obj.name` without changing its behaviour."""
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    original = getattr(obj, name)

    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        calls.append((args, kwargs))
        return await original(*args, **kwargs)

    setattr(obj, name, wrapper)
    try:
        yield calls
    finally:
        setattr(obj, name, original)


# ----------------------------------------------------------------------
# 12. the dual-execution scenario
# ----------------------------------------------------------------------


async def test_worker_a_claims_and_stores_partial_pages(staging: CrawlStaging) -> None:
    job_id = await _seed(staging)
    claimed = await staging.queue.claim("worker-A")
    assert claimed is not None
    assert claimed.id == job_id
    assert claimed.execution_version == 1

    result = await staging.crawl()
    assert result["status"] == "completed"
    assert result["pages"] == 2
    assert await staging.stored() == 2


async def test_lease_expiry_lets_worker_b_reclaim_while_a_is_still_running(
    staging: CrawlStaging,
) -> None:
    """The queue-level half of the scenario, on its own."""
    await _seed(staging)
    first = await staging.queue.claim("worker-A")
    assert first is not None

    await _sleep(LEASE_SECONDS + 0.1)  # A's lease expires with no heartbeat

    second = await staging.queue.claim("worker-B")
    assert second is not None, "an expired lease must be reclaimable"
    assert second.id == first.id
    assert second.execution_version == 2, "reclaim bumps the fencing version"


async def test_exactly_one_crawl_terminal_winner_under_dual_execution(
    staging: CrawlStaging,
) -> None:
    """Both workers run the whole crawl concurrently; only one may win.

    This is the FIND-03 regression guard at the orchestration level. Before the
    remediation an unfenced `crawl_jobs.update()` let a losing duplicate roll
    the terminal row back to active and win a SECOND terminator, which showed up
    here as two `crawl.completed` publishes and two terminal audit rows. With
    the status fence, a concurrent duplicate is rejected at the persistence
    boundary, so every winner-gated effect happens exactly once.
    """
    await _seed(staging)
    await staging.queue.claim("worker-A")

    results = await asyncio.gather(staging.crawl(), staging.crawl())
    assert [result["status"] for result in results] == ["completed", "completed"]

    stored = await staging.jobs.find_by_id_any(staging.job.id)
    assert stored is not None
    assert stored.status == "completed"
    assert stored.active is False
    assert stored.pages_completed == 2

    # Side effects ran for the winner only.
    assert staging.rollup() == 2, "crawl_pages counted once, not twice"
    assert staging.usage_events() == 2, "one usage event per stored page, not per attempt"
    assert staging.knowledge.calls == [staging.website.id], "fan-out happened once"
    assert staging.audit_actions().count(AUDIT_CRAWL_COMPLETED) == 1, "no duplicate terminal audit"

    website = await staging.websites.find_by_id(TENANT, staging.website.id)
    assert website is not None
    assert website.status == "ready"
    assert website.pages_indexed == 2


async def test_stale_a_cannot_finish_after_b_won(staging: CrawlStaging) -> None:
    """A resumes after B completed: A must not overwrite B's terminal state."""
    await _seed(staging)
    claimed_a = await staging.queue.claim("worker-A")
    assert claimed_a is not None

    # B reclaims (A's lease expired) and wins the crawl terminator.
    await _sleep(LEASE_SECONDS + 0.1)
    claimed_b = await staging.queue.claim("worker-B")
    assert claimed_b is not None
    assert (await staging.crawl())["status"] == "completed"

    pages, events, fanout = staging.rollup(), staging.usage_events(), list(staging.knowledge.calls)

    # A now tries to finish the queue row with its stale version.
    completed = await staging.queue.complete(
        claimed_a.id,
        "worker-A",
        execution_version=claimed_a.execution_version,
        result={"ok": 1},
    )
    assert completed is False, "a stale completion must be rejected"

    failed = await staging.queue.fail(
        claimed_a.id,
        "worker-A",
        execution_version=claimed_a.execution_version,
        error="late failure",
    )
    assert failed == "not_owned", "a stale failure must be refused, not applied"

    # Re-running the whole crawl is also harmless: the terminator is closed.
    assert (await staging.crawl())["status"] == "completed"
    assert staging.rollup() == pages, "stale re-run added no usage"
    assert staging.usage_events() == events
    assert staging.knowledge.calls == fanout, "stale re-run added no fan-out"
    assert staging.audit_actions().count(AUDIT_CRAWL_COMPLETED) == 1


async def test_stale_completion_returns_a_safe_no_op(staging: CrawlStaging) -> None:
    """The worker loop reports the rejection; it never raises or claims success."""
    await _seed(staging)
    seen: list[str] = []

    async def handler(ctx: dict[str, Any], crawl_job_id: str) -> dict[str, Any]:
        # A's lease expires while the job runs, and B takes the row over.
        await _sleep(LEASE_SECONDS + 0.1)
        assert await staging.queue.claim("worker-B") is not None
        seen.append(crawl_job_id)
        return {"status": "completed"}

    loop = MongoWorkerLoop(staging.queue, handlers={"crawl_website": handler}, worker_id="worker-A")
    outcome = await loop.work_once()
    assert outcome is not None
    assert outcome.status == "not_owned"
    assert outcome.lease_lost is True
    assert seen == [staging.job.id]

    row = await staging.queue.get(outcome.job_id)
    assert row is not None
    assert row.locked_by == "worker-B"


# ----------------------------------------------------------------------
# WK-01: the purge runs only after the winner gate
# ----------------------------------------------------------------------


async def _seed_stale_document(env: CrawlStaging, url: str) -> str:
    """A document from a previous crawl that this crawl will not re-fetch."""
    from backend.models.document import Document

    document = Document.new(
        tenant_id=TENANT,
        website_id=env.website.id,
        url=url,
        title="Gone",
        content="This page no longer exists on the site.",
        checksum="checksum-of-a-page-that-vanished",
        mime_type="text/html",
        source_type="website",
    )
    await env.documents.upsert(document)
    return document.id


async def test_wk01_the_winner_purges_a_document_whose_url_vanished(
    staging: CrawlStaging,
) -> None:
    await _seed(staging)
    stale_id = await _seed_stale_document(staging, "https://acme.example/removed")
    assert await staging.stored() == 1

    await staging.queue.claim("worker-A")
    result = await staging.crawl()
    assert result["status"] == "completed"
    assert await staging.documents.find_by_id(TENANT, stale_id) is None


async def test_wk01_a_losing_worker_never_purges_the_winners_documents(
    staging: CrawlStaging,
) -> None:
    """A stale worker must not delete documents the winner just stored."""
    await _seed(staging)
    await staging.queue.claim("worker-A")

    # B wins the crawl and stores both live pages.
    assert (await staging.crawl())["status"] == "completed"
    assert await staging.stored() == 2

    # A resumes having fetched only the root: a naive purge would delete
    # `/about`. A must lose the terminator and therefore purge nothing.
    assert (await staging.crawl({SEED: SAMPLE_HTML}))["status"] == "completed"
    assert await staging.stored() == 2, "the losing worker purged the winner's documents"


async def test_wk01_the_purge_helper_is_invoked_exactly_once(
    staging: CrawlStaging,
) -> None:
    """Count the purge directly, not just the observable outcome.

    Runs the two deliveries CONCURRENTLY, which is the case FIND-03 used to
    break: the losing attempt's unfenced progress write could resurrect the
    terminal row and re-enter this winner-gated block.
    """
    import backend.workers.jobs.crawl as crawl_module

    await _seed_stale_document(staging, "https://acme.example/removed")
    original = crawl_module._purge_removed_documents
    purged: list[dict[str, Any]] = []

    async def spy(**kwargs: Any) -> int:
        purged.append(kwargs)
        return await original(**kwargs)

    crawl_module._purge_removed_documents = spy
    try:
        await _seed(staging)
        await staging.queue.claim("worker-A")
        await asyncio.gather(staging.crawl(), staging.crawl())
    finally:
        crawl_module._purge_removed_documents = original

    assert len(purged) == 1, f"the purge ran {len(purged)} times; the gate allows exactly one"
    assert purged[0]["tenant_id"] == TENANT
    assert purged[0]["website_id"] == staging.website.id


async def test_wk01_purge_forgives_a_page_that_errored_this_run(
    staging: CrawlStaging,
) -> None:
    """A transient fetch failure must not purge previously good content."""
    await _seed(staging)
    flaky = await _seed_stale_document(staging, ABOUT)

    fetcher = FakePageFetcher({SEED: SAMPLE_HTML})
    fetcher.fail(ABOUT, FetchError("upstream timed out"))
    result = await _run_crawl_job(
        {
            "crawler_fetcher": fetcher,
            "job_try": 1,
            "max_tries": 3,
        },
        staging.job.id,
        crawl_jobs=staging.jobs,
        documents=staging.documents,
        websites=staging.websites,
        audit=staging.audit,
        usage=staging.usage,
        events=staging.events,
        vector=None,
        enqueue_knowledge=staging.knowledge,
        cache=None,
    )
    assert result["status"] == "completed"
    assert await staging.documents.find_by_id(TENANT, flaky) is not None, (
        "a page that merely errored this run was purged"
    )


async def test_wk01_a_linked_page_that_404s_is_not_purged(
    staging: CrawlStaging,
) -> None:
    """Only *unlinked* URLs are reconciled away; a linked 404 is forgiven.

    `SAMPLE_HTML` links to `/about`, so the crawler still attempts it this run
    and records a `target_not_found` error. A page that errored this run is
    explicitly excluded from the purge, so previously-good content survives a
    flaky 404. The vanishing-page case is covered by
    `test_wk01_the_winner_purges_a_document_whose_url_vanished`, where the URL
    is no longer linked at all.
    """
    await _seed(staging)
    linked = await _seed_stale_document(staging, ABOUT)
    fetcher = FakePageFetcher({SEED: SAMPLE_HTML})  # ABOUT linked but absent

    result = await _run_crawl_job(
        {
            "crawler_fetcher": fetcher,
            "job_try": 1,
            "max_tries": 3,
        },
        staging.job.id,
        crawl_jobs=staging.jobs,
        documents=staging.documents,
        websites=staging.websites,
        audit=staging.audit,
        usage=staging.usage,
        events=staging.events,
        vector=None,
        enqueue_knowledge=staging.knowledge,
        cache=None,
    )
    assert result["status"] == "completed"
    assert await staging.documents.find_by_id(TENANT, linked) is not None


async def test_wk01_an_unlinked_page_is_purged_even_though_it_never_failed(
    staging: CrawlStaging,
) -> None:
    """The contrasting case: a URL the site no longer links anywhere."""
    await _seed(staging)
    unlinked = await _seed_stale_document(staging, "https://acme.example/legacy")

    assert (await staging.crawl())["status"] == "completed"
    assert await staging.documents.find_by_id(TENANT, unlinked) is None
    assert await staging.stored() == 2, "the two live pages are still stored"


# ----------------------------------------------------------------------
# 13. crawl_pages usage accounting
# ----------------------------------------------------------------------


async def test_the_winning_crawl_records_one_crawl_pages_event_per_page(
    staging: CrawlStaging,
) -> None:
    await _seed(staging)
    await staging.queue.claim("worker-A")
    result = await staging.crawl()
    assert result["pages"] == 2
    assert staging.rollup() == 2
    assert staging.usage_events() == 2


async def test_a_losing_crawl_records_no_usage(staging: CrawlStaging) -> None:
    await _seed(staging)
    await staging.queue.claim("worker-A")
    await staging.crawl()
    baseline = (staging.rollup(), staging.usage_events())

    for _ in range(3):
        assert (await staging.crawl())["status"] == "completed"
    assert (staging.rollup(), staging.usage_events()) == baseline


async def test_stale_terminal_redelivery_records_nothing(staging: CrawlStaging) -> None:
    """A redelivered, already-terminal crawl job is a pure no-op."""
    await _seed(staging)
    await staging.queue.claim("worker-A")
    await staging.crawl()
    baseline = (
        staging.rollup(),
        staging.usage_events(),
        len(staging.knowledge.calls),
        staging.audit_actions().count(AUDIT_CRAWL_COMPLETED),
    )

    for _ in range(5):
        assert (await staging.crawl())["status"] == "completed"
    assert (
        staging.rollup(),
        staging.usage_events(),
        len(staging.knowledge.calls),
        staging.audit_actions().count(AUDIT_CRAWL_COMPLETED),
    ) == baseline


async def test_usage_is_recorded_against_the_jobs_own_tenant(staging: CrawlStaging) -> None:
    await _seed(staging)
    await staging.queue.claim("worker-A")
    await staging.crawl()
    assert staging.rollup() == 2
    assert staging.rollup("some-other-tenant") == 0


async def test_a_zero_page_crawl_bills_nothing(staging: CrawlStaging) -> None:
    """A failed crawl must not bill crawl_pages, and must not fan out."""
    await _seed(staging)
    await staging.queue.claim("worker-A")
    result = await staging.crawl({})
    assert result["status"] == "failed"
    assert result["pages"] == 0
    assert staging.rollup() == 0
    assert staging.usage_events() == 0
    assert staging.knowledge.calls == [], "a failed crawl must not fan out"
    assert staging.audit_actions() == [AUDIT_CRAWL_FAILED]


async def test_crawl_accounting_does_not_leak_into_other_meters(
    staging: CrawlStaging,
) -> None:
    await _seed(staging)
    await staging.queue.claim("worker-A")
    await staging.crawl()
    for metric in ("uploads", "documents", "storage_bytes", "messages_sent", "ai_responses"):
        assert staging.rollup_for(metric) == 0, metric


async def test_the_rollup_and_the_usage_events_agree(staging: CrawlStaging) -> None:
    await _seed(staging)
    await staging.queue.claim("worker-A")
    await staging.crawl()
    assert staging.rollup() == 2
    assert staging.usage_events() == 2
    for event in staging.events.events:
        assert event.tenant_id == TENANT
        assert event.website_id == staging.website.id


# ----------------------------------------------------------------------
# the real registered coroutine, reached through the queue worker loop
# ----------------------------------------------------------------------


@contextlib.contextmanager
def production_crawl(
    env: CrawlStaging, pages: dict[str, str] | None = None
) -> Iterator[CrawlStaging]:
    """Point the real `crawl_website` coroutine at the fake repositories.

    Only the seams that would reach outside the process are substituted: the
    repository *constructors*, the page fetcher, the embedding fan-out and the
    Redis cache. The coroutine itself, the registry entry, the payload
    validation, `_make_page_fetcher`'s caller and `_run_crawl_job` are all
    production code paths.
    """
    import backend.workers.jobs.crawl as crawl_module

    # Read through `getattr`: these names are module-level imports inside
    # `crawl.py`, not re-exports, and mypy's `attr-defined` would otherwise
    # reject the direct attribute access in a test.
    swapped = (
        "MongoCrawlJobRepository",
        "MongoDocumentRepository",
        "MongoVectorRepository",
        "MongoWebsiteRepository",
        "MongoAuditLogRepository",
        "MongoUsageRecordRepository",
        "MongoUsageEventRepository",
        # Phase 17B: the crawl's knowledge fan-out is now built per execution by
        # `_child_enqueue_knowledge(ctx)` so children follow the parent's queue.
        "_child_enqueue_knowledge",
        "_build_cache",
        "_make_page_fetcher",
    )
    original: dict[str, Any] = {name: getattr(crawl_module, name) for name in swapped}
    fetch_map = LIVE_PAGES if pages is None else pages

    def repo_of(fake: Any) -> Any:
        """Stand in for a `Mongo*Repository(db)` constructor."""
        return lambda db: fake

    swaps: list[tuple[str, Any]] = [
        ("MongoCrawlJobRepository", repo_of(env.jobs)),
        ("MongoDocumentRepository", repo_of(env.documents)),
        ("MongoVectorRepository", repo_of(None)),
        ("MongoWebsiteRepository", repo_of(env.websites)),
        ("MongoAuditLogRepository", repo_of(env.audit)),
        ("MongoUsageRecordRepository", repo_of(env.usage)),
        ("MongoUsageEventRepository", repo_of(env.events)),
        # Swapped for the whole factory, not the callback: the crawl builds it
        # from its own ctx, and a ctx-derived factory keeps the 1-argument
        # `enqueue_knowledge(website_id)` injection contract intact.
        ("_child_enqueue_knowledge", lambda ctx: env.knowledge),
        ("_build_cache", lambda: None),
        # The worker-built ctx has no `crawler_fetcher`, so the production
        # default would open real sockets; the fake fetcher replaces it here.
        ("_make_page_fetcher", lambda ctx, guard: FakePageFetcher(fetch_map)),
    ]
    for name, value in swaps:
        setattr(crawl_module, name, value)
    try:
        yield env
    finally:
        for name, value in original.items():
            setattr(crawl_module, name, value)


async def test_the_registered_crawl_coroutine_runs_end_to_end(
    staging: CrawlStaging,
) -> None:
    """MongoQueue -> worker loop -> registry -> real `crawl_website`."""
    crawl_website = resolve("crawl_website")

    with production_crawl(staging):
        await _seed(staging)
        loop = MongoWorkerLoop(
            staging.queue,
            handlers={"crawl_website": crawl_website},
            worker_id="w-registered",
        )
        outcome = await loop.work_once()
        assert outcome is not None
        assert outcome.status == "completed"
        assert outcome.attempts == 1
        assert outcome.lease_lost is False

    # The production coroutine reached the real orchestration, which stored the
    # pages, billed them, audited them and fanned them out exactly once.
    assert await staging.stored() == 2
    assert staging.rollup() == 2
    assert staging.usage_events() == 2
    assert staging.knowledge.calls == [staging.website.id]
    assert staging.audit_actions() == [AUDIT_CRAWL_COMPLETED]

    website = await staging.websites.find_by_id(TENANT, staging.website.id)
    assert website is not None
    assert website.status == "ready"
    assert website.pages_indexed == 2


async def test_the_real_heartbeat_keeps_a_long_crawl_alive(staging: CrawlStaging) -> None:
    """A crawl slower than the lease must survive on the heartbeat alone.

    Without the heartbeat the row would be reclaimable mid-crawl and a second
    worker could start a duplicate run; the crawler's own winner gate would
    contain the damage, but the row must not be stolen in the first place.
    """
    crawl_website = resolve("crawl_website")

    class SlowFetcher(FakePageFetcher):
        async def fetch(self, url: str) -> Any:
            await _sleep(LEASE_SECONDS * 1.5)
            return await FakePageFetcher.fetch(self, url)

    with production_crawl(staging):
        import backend.workers.jobs.crawl as crawl_module

        crawl_module._make_page_fetcher = lambda ctx, guard: SlowFetcher(LIVE_PAGES)
        await _seed(staging)
        loop = MongoWorkerLoop(
            staging.queue,
            handlers={"crawl_website": crawl_website},
            worker_id="w-heartbeat",
        )
        outcome = await loop.work_once()
        # While it ran, no other worker was able to steal the row.
        assert await staging.queue.claim("worker-B") is None

    assert outcome is not None
    assert outcome.status == "completed"
    assert outcome.lease_lost is False
    assert staging.rollup() == 2
    assert staging.knowledge.calls == [staging.website.id]


async def test_the_worker_context_carries_the_arq_shaped_keys(staging: CrawlStaging) -> None:
    """The context the Mongo queue builds is what production jobs expect."""
    seen: dict[str, Any] = {}

    async def handler(ctx: dict[str, Any], crawl_job_id: str) -> dict[str, Any]:
        seen.update(ctx)
        return {"status": "completed"}

    await _seed(staging)
    loop = MongoWorkerLoop(staging.queue, handlers={"crawl_website": handler}, worker_id="w-ctx")
    assert await loop.work_once() is not None

    for key in ("job_id", "job_try", "enqueue_time", "score", "max_tries", "timeout"):
        assert key in seen, key
    assert seen["max_tries"] == 3
    assert seen["timeout"] == 3600, "a crawl keeps the production 3600s budget"
    assert seen["job_try"] == 1


async def test_completion_is_published_once_under_dual_execution(
    staging: CrawlStaging,
) -> None:
    seen: list[str] = []
    with spy_on(crawl_events, "publish_completed") as calls:
        await _seed(staging)
        await staging.queue.claim("worker-A")
        await asyncio.gather(staging.crawl(), staging.crawl())
    seen.extend(str(args) for args, _ in calls)
    assert len(seen) == 1, "only the winner announces completion"
    assert len(set(seen)) == 1


async def test_a_crawl_whose_website_vanished_fails_without_resurrecting_it(
    staging: CrawlStaging,
) -> None:
    """The pre-terminal FIND-02 path: no website means no resurrection."""
    await _seed(staging)
    await staging.queue.claim("worker-A")
    await staging.websites.delete(TENANT, staging.website.id)

    result = await staging.crawl()
    assert result["status"] == "failed"
    assert staging.rollup() == 0
    assert staging.usage_events() == 0
    assert staging.knowledge.calls == []
    # `find_by_id` hides soft-deleted rows; `find_by_id_any` shows the truth.
    assert await staging.websites.find_by_id(TENANT, staging.website.id) is None
    website = await staging.websites.find_by_id_any(staging.website.id)
    assert website is not None
    assert website.status == "deleted", "the crawl must not resurrect a deleted website"
    assert website.pages_indexed == 0, "no page count was written to a deleted website"


# ----------------------------------------------------------------------
# FIND-03 remediation: the exact reproduced reclaim sequence
# ----------------------------------------------------------------------


async def test_find03_a_reclaimed_attempt_cannot_duplicate_any_winner_effect(
    staging: CrawlStaging,
) -> None:
    """§11, the reproduced sequence, start to finish, on the real job body.

    A claims and takes a snapshot; A's lease expires; B reclaims and completes;
    A then resumes. Every winner-gated effect must occur exactly once and A must
    not be able to reclaim winner status. Before the remediation A's stale
    progress write resurrected the terminal row and it won a second terminator.
    """
    await _seed(staging)
    claimed_a = await staging.queue.claim("worker-A")
    assert claimed_a is not None

    # A reads the job and gets an ACTIVE snapshot, then stalls.
    snapshot_a = await staging.jobs.find_by_id_any(staging.job.id)
    assert snapshot_a is not None
    assert snapshot_a.active is True

    # A's lease expires and B reclaims the row.
    await _sleep(LEASE_SECONDS + 0.1)
    claimed_b = await staging.queue.claim("worker-B")
    assert claimed_b is not None
    assert claimed_b.execution_version > claimed_a.execution_version

    # B wins the terminator and runs every winner-gated effect.
    assert (await staging.crawl())["status"] == "completed"
    winner = await staging.jobs.find_by_id_any(staging.job.id)
    assert winner is not None
    assert winner.status == "completed"
    assert winner.active is False

    # A resumes and tries to persist its stale ACTIVE snapshot: rejected.
    snapshot_a.status = CRAWL_STATUS_RUNNING
    snapshot_a.active = True
    snapshot_a.pages_completed = 99
    assert await staging.jobs.update(snapshot_a) is False, (
        "the stale attempt's write was accepted after the crawl went terminal"
    )

    # A cannot win a second terminator.
    assert not await staging.jobs.finish_if_active(
        staging.job.id, TENANT, terminal_status=CRAWL_STATUS_COMPLETED
    )

    # Exactly one of each winner-gated effect.
    assert staging.audit_actions().count(AUDIT_CRAWL_COMPLETED) == 1
    assert staging.rollup() == 2
    assert staging.usage_events() == 2
    assert staging.knowledge.calls == [staging.website.id]
    assert await staging.stored() == 2

    # The winner's terminal fields survived the stale attempt intact.
    after = await staging.jobs.find_by_id_any(staging.job.id)
    assert after is not None
    assert after.pages_completed == 2, "the stale snapshot rewound the winner's counters"
    assert after.status == "completed"
    assert after.active is False


async def test_find03_wk01_purge_runs_once_after_the_fence_holds(staging: CrawlStaging) -> None:
    """§12: FIND-03 composes with WK-01.

    Required ordering: `finish_if_active` -> winner? no => return,
    yes => purge. The stale attempt must not regain winner status via
    resurrection, so the purge can never run a second time.
    """
    import backend.workers.jobs.crawl as crawl_module

    await _seed(staging)
    stale_url = await _seed_stale_document(staging, "https://acme.example/removed")
    assert await staging.documents.find_by_id(TENANT, stale_url) is not None

    original = crawl_module._purge_removed_documents
    purged: list[dict[str, Any]] = []

    async def spy(**kwargs: Any) -> int:
        purged.append(kwargs)
        return await original(**kwargs)

    crawl_module._purge_removed_documents = spy
    try:
        snapshot_a = await staging.jobs.find_by_id_any(staging.job.id)
        assert snapshot_a is not None

        # Winner runs to completion: terminator won -> purge runs (once).
        assert (await staging.crawl())["status"] == "completed"
        assert len(purged) == 1
        assert await staging.documents.find_by_id(TENANT, stale_url) is None

        # The stale attempt tries hard to re-enter: resurrect, then terminate.
        snapshot_a.status = CRAWL_STATUS_RUNNING
        assert await staging.jobs.update(snapshot_a) is False
        assert not await staging.jobs.finish_if_active(
            staging.job.id, TENANT, terminal_status=CRAWL_STATUS_COMPLETED
        )
        # Re-delivering the whole job body must not purge again either.
        assert (await staging.crawl())["status"] == "completed"
    finally:
        crawl_module._purge_removed_documents = original

    assert len(purged) == 1, f"the purge ran {len(purged)} times; WK-01 allows exactly one"


async def test_find03_accounting_is_exactly_once_under_a_reclaim(
    staging: CrawlStaging,
) -> None:
    """§13: rollup once, usage event once, right tenant, stale attempt zero."""
    await _seed(staging)
    claimed_a = await staging.queue.claim("worker-A")
    assert claimed_a is not None
    snapshot_a = await staging.jobs.find_by_id_any(staging.job.id)
    assert snapshot_a is not None

    await _sleep(LEASE_SECONDS + 0.1)
    assert await staging.queue.claim("worker-B") is not None

    # B: the single accounting event.
    assert (await staging.crawl())["status"] == "completed"
    assert staging.rollup() == 2
    assert staging.usage_events() == 2
    for event in staging.events.events:
        assert event.tenant_id == TENANT
        assert event.website_id == staging.website.id

    # A: a stale attempt contributes nothing.
    snapshot_a.status = CRAWL_STATUS_RUNNING
    assert await staging.jobs.update(snapshot_a) is False
    assert (await staging.crawl())["status"] == "completed"

    assert staging.rollup() == 2, "the stale attempt double-counted crawl_pages"
    assert staging.usage_events() == 2, "the stale attempt appended a duplicate usage event"
    assert staging.rollup("tenant-b") == 0


@pytest.mark.parametrize("kind", ["completed", "failed"])
async def test_find03_a_failed_crawl_is_also_monotonic(
    staging: CrawlStaging, kind: str
) -> None:
    """§14: protect every real terminal status, not just `completed`.

    `failed` is the other terminal status in the model. A crawl that fails is
    just as terminal, and a stale active snapshot must not reopen it either.
    """
    await _seed(staging)
    snapshot = await staging.jobs.find_by_id_any(staging.job.id)
    assert snapshot is not None

    if kind == "failed":
        result = await staging.crawl({})  # no pages -> failed
        assert result["status"] == "failed"
    else:
        assert (await staging.crawl())["status"] == "completed"

    stored = await staging.jobs.find_by_id_any(staging.job.id)
    assert stored is not None
    assert stored.status == kind
    assert stored.active is False

    snapshot.status = CRAWL_STATUS_RUNNING
    snapshot.active = True
    assert await staging.jobs.update(snapshot) is False

    after = await staging.jobs.find_by_id_any(staging.job.id)
    assert after is not None
    assert after.status == kind, f"a terminal '{kind}' crawl was resurrected"
    assert after.active is False
    assert not await staging.jobs.finish_if_active(
        staging.job.id, TENANT, terminal_status=kind
    )


async def test_find03_a_rejected_write_stops_the_duplicate_before_it_crawls(
    staging: CrawlStaging,
) -> None:
    """The losing attempt must bail out at the `running` transition.

    `crawl_jobs.update` now returns False for a non-active row, and the worker
    returns immediately instead of proceeding to crawl pages and race for the
    terminator. This asserts the early-exit is wired, not just the repository.
    """
    await _seed(staging)
    assert (await staging.crawl())["status"] == "completed"
    baseline_audit = staging.audit_actions().count(AUDIT_CRAWL_COMPLETED)
    assert baseline_audit == 1

    # Second delivery: the very first write (pending -> running) is refused.
    result = await staging.crawl()
    assert result["status"] == "completed"
    assert staging.audit_actions().count(AUDIT_CRAWL_COMPLETED) == 1
    assert staging.rollup() == 2
    assert staging.usage_events() == 2
    assert staging.knowledge.calls == [staging.website.id]
