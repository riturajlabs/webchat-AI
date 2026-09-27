"""Safety-scenario tests (crawl, document, email) using ONLY mock providers.

The headline result is §18: the queue gives at-least-once delivery; it CANNOT
make a side effect exactly-once by itself. Only provider-level idempotency
does. This file proves the difference with a crash-after-send simulation.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from backend.prototypes.mongo_queue import STATUS_COMPLETED, MongoQueue
from backend.prototypes.mongo_queue.ids import utcnow
from backend.prototypes.mongo_queue.models import Job
from backend.prototypes.mongo_queue.sim_jobs import (
    CrawlFence,
    DocumentChecksumStore,
    MockMailProvider,
    crawl_handler,
    process_document_handler,
    send_email_handler,
)
from backend.prototypes.mongo_queue.worker import JobContext


def _ctx(job: Job, worker: str, tenant: str) -> JobContext:
    return JobContext(
        job_id=job.id,
        function=job.function,
        tenant_id=tenant,
        worker_id=worker,
        job_try=job.attempts,
        execution_version=job.execution_version,
        claimed_at=job.started_at or utcnow(),
    )


async def test_crawl_stale_worker_cannot_corrupt_terminal_state(queue: MongoQueue) -> None:
    """§16: crawl-A claims, starts, lease expires; crawl-B claims, completes;
    crawl-A's late completion is rejected. Existing `finish_if_active` domain
    fence (miniature: CrawlFence) + queue fencing keep the terminal state the
    single winner's."""
    base = utcnow()
    job_id = await queue.enqueue(
        function="crawl",
        payload={"crawl_job_id": "cj-1", "website_id": "w1"},
        tenant_id="tenant-a",
        now=base,
    )
    fence = CrawlFence()
    await fence.mark_active("cj-1")

    crawl_a = await queue.claim("crawl-a", now=base)
    assert crawl_a is not None
    await fence.crawl_side_effect("cj-1", "home")  # A does partial work
    # A crashes (no completion). Lease expires at base+120.
    crawl_b = await queue.claim(
        "crawl-b", now=base + timedelta(seconds=queue.lease_seconds + 1)
    )
    assert crawl_b is not None
    result_b = await crawl_handler(
        {"crawl_job_id": "cj-1"}, _ctx(crawl_b, "crawl-b", "tenant-a"), fence=fence
    )
    assert result_b["winner"] is True
    assert await queue.complete_job(
        job_id, "crawl-b", execution_version=crawl_b.execution_version
    ) is True

    # A later tries to complete with its stale (already reclaimed) execution.
    assert (
        await queue.complete_job(job_id, "crawl-a", execution_version=crawl_a.execution_version)
        is False
    )
    # B's terminal write is intact, and only ONE crawl completed.
    terminal = await queue.get(job_id)
    assert terminal is not None and terminal.status == STATUS_COMPLETED
    assert len([e for e in fence.events if e.startswith("completed:")]) == 1
    assert fence.is_active("cj-1") is False


async def test_concurrent_crawl_completions_single_winner(queue: MongoQueue) -> None:
    """Two runs race the terminal step; the single-terminator fence allows
    exactly one winner (mirrors `update_if_crawl_owner` + `finish_if_active`)."""
    fence = CrawlFence()
    for cjid in ("cj-x", "cj-y"):
        await fence.mark_active(cjid)
    outcomes = await asyncio.gather(
        crawl_handler(
            {"crawl_job_id": "cj-x"}, _ctx(mock_job(cjid="cj-x", v=1), "w-a", "t"), fence=fence
        ),
        crawl_handler(
            {"crawl_job_id": "cj-x"}, _ctx(mock_job(cjid="cj-x", v=2), "w-b", "t"), fence=fence
        ),
    )
    assert {o["winner"] for o in outcomes} == {True, False}
    assert fence.is_active("cj-x") is False


def mock_job(*, cjid: str, v: int) -> Job:
    return Job(
        id=f"job-{cjid}-{v}",
        function="crawl",
        payload={},
        tenant_id="t",
        execution_version=v,
        attempts=1,
    )


async def test_document_checksum_idempotency_under_redelivery(queue: MongoQueue) -> None:
    """§17: worker-a embeds then crashes before completion; worker-b re-runs
    the SAME document; the checksum gate skips re-embedding. One side effect
    despite two executions (mirrors processor checksum-skip)."""
    base = utcnow()
    store = DocumentChecksumStore()
    job_id = await queue.enqueue(
        function="process_document",
        payload={"document_id": "d1", "checksum": "sha-1"},
        tenant_id="tenant-a",
        now=base,
    )
    a = await queue.claim("worker-a", now=base)
    assert a is not None
    # A performs the embed side effect but crashes before completing.
    await process_document_handler(
        {"document_id": "d1", "checksum": "sha-1"}, _ctx(a, "worker-a", "tenant-a"), store=store
    )
    assert store.events == ["embedded:d1"]
    # B reclaims after lease expiry and re-runs: checksum gate => skipped.
    b = await queue.claim("worker-b", now=base + timedelta(seconds=queue.lease_seconds + 1))
    assert b is not None
    result_b = await process_document_handler(
        {"document_id": "d1", "checksum": "sha-1"}, _ctx(b, "worker-b", "tenant-a"), store=store
    )
    assert result_b["skipped"] is True
    assert (
        await queue.complete_job(
            job_id, "worker-b", execution_version=b.execution_version
        )
        is True
    )
    # Exactly one embed side effect happened.
    assert len([e for e in store.events if e == "embedded:d1"]) == 1


async def test_email_duplicate_delivery_without_idempotency(queue: MongoQueue) -> None:
    """§18 CRITICAL: worker-a SENDS the email, then crashes before writing
    completion. Lease expires. worker-b SENDS AGAIN. Two emails delivered.
    This is the exact risk the production send_email path carries today."""
    base = utcnow()
    provider = MockMailProvider()
    job_id = await queue.enqueue(
        function="send_email",
        payload={"to": "u@mail.dev", "subject": "x", "body": "y", "idempotency_key": None},
        tenant_id="tenant-a",
        now=base,
    )
    a = await queue.claim("worker-a", now=base)
    assert a is not None
    # A sends the email (side effect), then crashes BEFORE the completion write.
    await send_email_handler(
        {"to": "u@mail.dev", "subject": "x", "body": "y", "idempotency_key": None},
        _ctx(a, "worker-a", "tenant-a"),
        provider=provider,
    )
    assert provider.sent_count == 1
    # B reclaims after lease expiry and re-sends.
    b = await queue.claim("worker-b", now=base + timedelta(seconds=queue.lease_seconds + 1))
    assert b is not None
    outcome = await send_email_handler(
        {"to": "u@mail.dev", "subject": "x", "body": "y", "idempotency_key": None},
        _ctx(b, "worker-b", "tenant-a"),
        provider=provider,
    )
    assert outcome["duplicated"] is False
    assert (
        await queue.complete_job(
            job_id, "worker-b", execution_version=b.execution_version
        )
        is True
    )
    # DUPLICATE DELIVERY: the same logical job produced two emails.
    assert provider.sent_count == 2
    assert provider.email_received is True


async def test_email_provider_idempotency_prevents_duplicate(queue: MongoQueue) -> None:
    """§18: the SAME crash-after-send scenario, but the send passes a
    provider-level idempotency_key derived from the job. Worker-b's re-send is
    rejected by the provider as a duplicate and returns the original id."""
    base = utcnow()
    provider = MockMailProvider()
    payload = {
        "to": "u@mail.dev",
        "subject": "x",
        "body": "y",
        "idempotency_key": "email-key-123",
    }
    job_id = await queue.enqueue(
        function="send_email", payload=payload, tenant_id="tenant-a", now=base
    )
    a = await queue.claim("worker-a", now=base)
    assert a is not None
    first = await send_email_handler(payload, _ctx(a, "worker-a", "tenant-a"), provider=provider)
    assert first["duplicated"] is False and provider.sent_count == 1
    # A crashes before completion.
    b = await queue.claim("worker-b", now=base + timedelta(seconds=queue.lease_seconds + 1))
    assert b is not None
    second = await send_email_handler(payload, _ctx(b, "worker-b", "tenant-a"), provider=provider)
    assert second["duplicated"] is True
    assert second["message_id"] == first["message_id"]
    assert (
        await queue.complete_job(
            job_id, "worker-b", execution_version=b.execution_version
        )
        is True
    )
    # Exactly ONE physical email despite two executions.
    assert provider.sent_count == 1


async def test_job_dedup_and_side_effect_idempotency_are_distinct(queue: MongoQueue) -> None:
    """§18: job deduplication (dedup_key) prevents a SECOND job; side-effect
    idempotency (provider key) prevents a SECOND delivery of the SAME job.
    They are different mechanisms; the queue provides only the first."""
    provider = MockMailProvider()

    # 1) Job-level dedup: same dedup_key -> one logical job -> one send.
    first_id = await queue.enqueue(
        function="send_email",
        payload={"to": "u@mail.dev", "subject": "s", "body": "b", "idempotency_key": "k1"},
        tenant_id="t",
        dedup_key="crawl:same",
    )
    second_id = await queue.enqueue(
        function="send_email",
        payload={"to": "u@mail.dev", "subject": "s", "body": "b", "idempotency_key": "k1"},
        tenant_id="t",
        dedup_key="crawl:same",
    )
    assert second_id == first_id  # callers see one logical job
    claimed = await queue.claim("w")
    assert claimed is not None
    await send_email_handler(claimed.payload, _ctx(claimed, "w", "t"), provider=provider)
    assert provider.sent_count == 1

    # 2) Side-effect idempotency: a DIFFERENT job (new dedup_key, so a real job)
    # re-delivers; only the provider key stops the second physical email.
    payload2 = {"to": "u@mail.dev", "subject": "s", "body": "b", "idempotency_key": "k1"}
    job2 = await queue.enqueue(
        function="send_email", payload=payload2, tenant_id="t", dedup_key="other"
    )
    c2 = await queue.claim("w")
    assert c2 is not None and c2.id == job2
    res = await send_email_handler(payload2, _ctx(c2, "w", "t"), provider=provider)
    assert res["duplicated"] is True  # provider absorbed it
    assert provider.sent_count == 1