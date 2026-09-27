"""Phase 16 email idempotency tests: deterministic keys, provider honour/ignore
semantics, crash-after-send, response-loss, and stale-worker fencing (crash
matrix cases 2, 4, 5, 7 and §22 test list)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from backend.prototypes.mongo_queue.config import QueueConfig
from backend.prototypes.mongo_queue.email_idempotency import (
    LostResponseMailProvider,
    email_idempotency_key,
    email_logical_id,
    execute_email_job,
)
from backend.prototypes.mongo_queue.ids import utcnow
from backend.prototypes.mongo_queue.models import (
    STATUS_COMPLETED,
    STATUS_RETRY_PENDING,
)
from backend.prototypes.mongo_queue.queue import MongoQueue
from backend.prototypes.mongo_queue.sim_jobs import MockMailProvider
from backend.prototypes.mongo_queue.worker import JobContext
from motor.motor_asyncio import AsyncIOMotorClient

_MESSAGE = {"to": "user@example.com", "subject": "Welcome", "body": "hi"}
_TENANT = "tenant-a"


def _ctx(job_id: str, worker_id: str, execution_version: int, attempts: int) -> JobContext:
    return JobContext(
        job_id=job_id,
        function="send_email",
        tenant_id=_TENANT,
        worker_id=worker_id,
        job_try=attempts,
        execution_version=execution_version,
        claimed_at=utcnow(),
    )


def test_deterministic_key_same_logical_email_same_key() -> None:
    """Same tenant + same rendered message must collide on every retry."""
    assert email_idempotency_key(_TENANT, _MESSAGE) == email_idempotency_key(
        _TENANT, _MESSAGE
    )
    assert email_idempotency_key(_TENANT, _MESSAGE) == email_idempotency_key(
        _TENANT, dict(_MESSAGE)
    )


def test_deterministic_key_changes_when_identity_changes() -> None:
    assert email_idempotency_key(_TENANT, _MESSAGE) != email_idempotency_key(
        _TENANT, {**_MESSAGE, "to": "other@example.com"}
    )
    # Content hash only: different tenant namespace => different key.
    assert email_idempotency_key("tenant-b", _MESSAGE) != email_idempotency_key(
        _TENANT, _MESSAGE
    )


def test_key_shape_and_resend_limits() -> None:
    key = email_idempotency_key(_TENANT, _MESSAGE)
    assert key.startswith("email:")
    # Resend caps Idempotency-Key at 256 characters (official docs).
    assert len(key) <= 256
    # 64 hex digest chars => compact, repeatable key.
    assert len(email_logical_id(_MESSAGE)) == 64


async def test_100_concurrent_sends_one_delivery_when_provider_honours() -> None:
    provider = MockMailProvider(honors_idempotency=True)
    ctx = _ctx("job-1", "w", 1, 1)
    results = await asyncio.gather(
        *(execute_email_job(_MESSAGE, ctx, provider=provider) for _ in range(100))
    )
    wins = [r for r in results if not r["duplicated"]]
    assert len(wins) == 1
    assert provider.sent_count == 1
    assert len({r["message_id"] for r in results}) == 1


async def test_100_concurrent_sends_duplicate_when_provider_ignores() -> None:
    provider = MockMailProvider(honors_idempotency=False)
    ctx = _ctx("job-1", "w", 1, 1)
    results = await asyncio.gather(
        *(execute_email_job(_MESSAGE, ctx, provider=provider) for _ in range(100))
    )
    assert provider.sent_count == 100
    # Explicit: without provider support the queue cannot make it exactly-once.
    assert any(r["duplicated"] for r in results) is False


async def test_crash_after_send_single_delivery_with_key(queue: MongoQueue) -> None:
    """Crash matrix case 2/7: worker sends then dies before completing."""
    provider = MockMailProvider(honors_idempotency=True)
    job_id = await queue.enqueue(
        function="send_email", payload=_MESSAGE, tenant_id=_TENANT
    )
    base = utcnow()
    first = await queue.claim("worker-a", now=base)
    assert first is not None
    r1 = await execute_email_job(
        first.payload,
        _ctx(job_id, "worker-a", first.execution_version, first.attempts),
        provider=provider,
    )
    # worker-a crashes here: no complete_job. Lease expires; worker-b reclaims.
    reclaimed = await queue.claim(
        "worker-b", now=base + timedelta(seconds=queue.lease_seconds + 1)
    )
    assert reclaimed is not None and reclaimed.execution_version == first.execution_version + 1
    r2 = await execute_email_job(
        reclaimed.payload,
        _ctx(job_id, "worker-b", reclaimed.execution_version, reclaimed.attempts),
        provider=provider,
    )
    assert r2["duplicated"] is True
    assert r2["message_id"] == r1["message_id"]
    assert provider.sent_count == 1
    assert (
        await queue.complete_job(
            job_id, "worker-b", execution_version=reclaimed.execution_version
        )
        is True
    )


async def test_response_loss_retry_same_message_id_when_provider_honours(
    queue: MongoQueue,
) -> None:
    """Crash matrix case 4/5: provider accepted; response lost (timeout)."""
    provider = LostResponseMailProvider(honors_idempotency=True)
    job_id = await queue.enqueue(
        function="send_email", payload=_MESSAGE, tenant_id=_TENANT
    )
    base = utcnow()
    claimed = await queue.claim("worker-a", now=base)
    assert claimed is not None
    with pytest.raises(TimeoutError):
        await execute_email_job(
            claimed.payload,
            _ctx(job_id, "worker-a", claimed.execution_version, claimed.attempts),
            provider=provider,
        )
    assert provider.sent_count == 1  # provider accepted despite the timeout
    outcome = await queue.fail_job(
        job_id, "worker-a", "TimeoutError: response lost",
        execution_version=claimed.execution_version, now=base,
    )
    assert outcome == STATUS_RETRY_PENDING
    retry = await queue.claim("worker-b", now=base + timedelta(seconds=600))
    assert retry is not None
    r2 = await execute_email_job(
        retry.payload,
        _ctx(job_id, "worker-b", retry.execution_version, retry.attempts),
        provider=provider,
    )
    assert provider.sent_count == 1
    assert r2["duplicated"] is True
    assert (
        await queue.complete_job(job_id, "worker-b", execution_version=retry.execution_version)
        is True
    )


async def test_response_loss_duplicates_without_provider_idempotency(
    queue: MongoQueue,
) -> None:
    """Crash matrix case 4/5: without provider idempotency the retry re-sends."""
    provider = LostResponseMailProvider(honors_idempotency=False)
    job_id = await queue.enqueue(
        function="send_email", payload=_MESSAGE, tenant_id=_TENANT
    )
    base = utcnow()
    claimed = await queue.claim("worker-a", now=base)
    assert claimed is not None
    with pytest.raises(TimeoutError):
        await execute_email_job(
            claimed.payload,
            _ctx(job_id, "worker-a", claimed.execution_version, claimed.attempts),
            provider=provider,
        )
    assert provider.sent_count == 1
    await queue.fail_job(
        job_id, "worker-a", "TimeoutError: response lost",
        execution_version=claimed.execution_version, now=base,
    )
    retry = await queue.claim("worker-b", now=base + timedelta(seconds=600))
    assert retry is not None
    await execute_email_job(
        retry.payload,
        _ctx(job_id, "worker-b", retry.execution_version, retry.attempts),
        provider=provider,
    )
    # The provider ignored the key: a second physical email went out.
    assert provider.sent_count == 2


async def test_stale_email_worker_blocked_by_fencing_and_dedup_protects_delivery(
    mongo_client: AsyncIOMotorClient[Any],
) -> None:
    """Crash matrix case 6: stale worker keeps running after claim lost/won."""
    config = QueueConfig(lease_seconds=0.5, heartbeat_interval_seconds=60)
    database = mongo_client[config.db_name]
    await database.drop_collection(config.collection_name)
    q = MongoQueue(database, config)
    await q.ensure_indexes()
    provider = MockMailProvider(honors_idempotency=True)
    job_id = await q.enqueue(function="send_email", payload=_MESSAGE, tenant_id=_TENANT)
    base = utcnow()
    worker_a = await q.claim("worker-a", now=base)
    assert worker_a is not None
    await execute_email_job(
        worker_a.payload,
        _ctx(job_id, "worker-a", worker_a.execution_version, worker_a.attempts),
        provider=provider,
    )
    # Lease expires in real time (0.5 s); worker-b takes over.
    await asyncio.sleep(0.6)
    worker_b = await q.claim("worker-b", now=utcnow())
    assert worker_b is not None and worker_b.execution_version == worker_a.execution_version + 1
    r2 = await execute_email_job(
        worker_b.payload,
        _ctx(job_id, "worker-b", worker_b.execution_version, worker_b.attempts),
        provider=provider,
    )
    assert r2["duplicated"] is True
    assert (
        await q.complete_job(job_id, "worker-b", execution_version=worker_b.execution_version)
        is True
    )
    # The stale worker cannot complete the reclaimed execution.
    assert (
        await q.complete_job(
            job_id, "worker-a", execution_version=worker_a.execution_version
        )
        is False
    )
    finished = await q.get(job_id)
    assert finished is not None and finished.status == STATUS_COMPLETED
    assert provider.sent_count == 1
    await database.drop_collection(config.collection_name)