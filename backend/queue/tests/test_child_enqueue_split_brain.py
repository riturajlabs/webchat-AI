"""Child-enqueue backend consistency (Phase 17B).

A job executing on one queue must enqueue its children onto that same queue.

Before this suite existed, three worker modules each built a private
``_arq_redis()`` from ``settings.redis_url`` and called ``ArqRedis.enqueue_job``
directly, so a parent executed by :class:`MongoWorkerLoop` silently enqueued its
children into Redis. Reproduced before the fix with production code only:

    parent execution backend : MONGO (webchat_ai_queue_test_...worker_jobs)
    children -> REDIS/ARQ    : [('process_document', ('doc-1', 'run-1'), {}), ...]
    children -> MONGO queue  : 0

The invariant pinned here, in both directions:

* Mongo-executed parent -> children on the SAME Mongo queue, zero Redis contact.
* ARQ-executed parent (or the API process, which has no job context) -> children
  on ARQ, byte-identical to the pre-Phase-17B call shape.

Isolation: the ARQ side is always a recording double, the Mongo side is the
isolated prototype mongod. No test contacts production Redis or Atlas.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from backend.prototypes.mongo_queue.config import DEFAULT_MONGO_URI
from backend.queue.mongo_adapter import MongoQueueAdapter
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

_ARQ_CALLS: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []


class _RecordingArqRedis:
    """Stand-in for ``ArqRedis`` recording every enqueue attempt.

    A recorded call while executing on the Mongo queue is a split-brain event.
    """

    def __init__(self) -> None:
        self.job_id = "arq-job"

    async def enqueue_job(self, function: str, *args: Any, **kwargs: Any) -> Any:
        _ARQ_CALLS.append((function, args, kwargs))
        return self

    async def ping(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _clear_arq_recordings() -> Iterator[None]:
    _ARQ_CALLS.clear()
    yield
    _ARQ_CALLS.clear()


@pytest.fixture
async def mongo_queue() -> AsyncGenerator[MongoQueueAdapter]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        DEFAULT_MONGO_URI, serverSelectionTimeoutMS=3000, tz_aware=True
    )
    try:
        await client.admin.command("ping")
    except Exception as exc:  # noqa: BLE001 - environment guard
        client.close()
        pytest.skip(f"isolated prototype mongod unreachable: {exc}")
    db: AsyncIOMotorDatabase[dict[str, Any]] = client["webchat_ai_queue_test_splitbrain"]
    adapter = MongoQueueAdapter(db, collection_name="worker_jobs")
    await adapter.ensure_indexes()
    yield adapter
    for name in await db.list_collection_names():
        await db.drop_collection(name)
    client.close()


def _patch_arq(monkeypatch: pytest.MonkeyPatch) -> None:
    """Intercept every ARQ client, so no test can reach a real Redis.

    ``ArqQueueAdapter._arq_redis()`` is the single interception point that
    matters: since Phase 18A it backs every producer AND every in-worker child
    enqueue (the ctx-resolved adapter). The worker modules' private
    ``_arq_redis()`` helpers are still patched defensively - they remain
    importable for tests and ops tooling, but no producer calls them any more.
    """
    from backend.queue.arq_adapter import ArqQueueAdapter
    from backend.workers.jobs import crawl as crawl_module
    from backend.workers.jobs import email as email_module
    from backend.workers.jobs import knowledge as knowledge_module

    monkeypatch.setattr(ArqQueueAdapter, "_arq_redis", lambda self: _RecordingArqRedis())
    for module in (crawl_module, email_module, knowledge_module):
        monkeypatch.setattr(module, "_arq_redis", lambda: _RecordingArqRedis())


def _mongo_ctx(queue: MongoQueueAdapter, tenant_id: str = "tenant-a") -> dict[str, Any]:
    """The context ``MongoWorkerLoop`` builds, via the real ``job_context``."""
    from backend.queue.protocol import QueueJob, job_context

    now = datetime.now(UTC)
    job = QueueJob(
        id="parent-1",
        function="process_website_documents",
        payload={"website_id": "website-1"},
        tenant_id=tenant_id,
        job_try=1,
        max_tries=3,
        execution_version=1,
        enqueue_time=now,
        score=now,
    )
    return job_context(job, timeout=600, queue_name=queue.queue_name, queue=queue)


# ----------------------------------------------------------------------
# 1. Mongo-executed parents must not reach Redis
# ----------------------------------------------------------------------


async def test_website_fanout_from_a_mongo_parent_stays_on_mongo(
    mongo_queue: MongoQueueAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reproduced split-brain scenario, as a permanent guard."""
    _patch_arq(monkeypatch)

    from backend.workers.jobs import knowledge as knowledge_module

    class _StubProcessor:
        async def process_website_documents(
            self, website_id: str, *, enqueue: Any
        ) -> dict[str, Any]:
            for document_id in ("doc-1", "doc-2"):
                await enqueue(document_id, "run-1")
            return {"status": "queued", "documents": 2, "run_id": "run-1"}

    monkeypatch.setattr(knowledge_module, "_processor", lambda ctx, embedder: _StubProcessor())

    ctx = _mongo_ctx(mongo_queue)
    result = await knowledge_module.process_website_documents(ctx, "website-1")

    assert result["documents"] == 2
    assert _ARQ_CALLS == [], f"Mongo parent enqueued into Redis/ARQ: {_ARQ_CALLS}"
    assert await mongo_queue.count_documents(status="pending") == 2


async def test_crawl_fanout_from_a_mongo_parent_stays_on_mongo(
    mongo_queue: MongoQueueAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The crawl -> knowledge fan-out is the other child enqueue path."""
    _patch_arq(monkeypatch)

    from backend.workers.jobs.crawl import _child_enqueue_knowledge

    ctx = _mongo_ctx(mongo_queue)
    await _child_enqueue_knowledge(ctx)("website-1")

    assert _ARQ_CALLS == []
    assert await mongo_queue.count_documents(status="pending") == 1
    claimed = await mongo_queue.claim("tester")
    assert claimed is not None
    assert claimed.function == "process_website_documents"
    assert claimed.payload == {"website_id": "website-1"}


async def test_document_retry_from_a_mongo_parent_stays_on_mongo(
    mongo_queue: MongoQueueAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deferred document retry is the third child enqueue path."""
    _patch_arq(monkeypatch)

    from backend.workers.jobs.knowledge import _child_enqueue_deferred

    ctx = _mongo_ctx(mongo_queue)
    await _child_enqueue_deferred(ctx)("doc-1", 5.0, "run-1")

    assert _ARQ_CALLS == []
    row = await mongo_queue.queue.get((await mongo_queue.list_jobs(limit=1))[0].id)
    assert row is not None
    assert row.function == "process_document"
    assert row.run_at > datetime.now(UTC), "defer_by must postpone the row"


# ----------------------------------------------------------------------
# 2. Mongo children are real, claimable, tenant-attributable queue rows
# ----------------------------------------------------------------------


async def test_mongo_children_carry_the_parent_tenant(
    mongo_queue: MongoQueueAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_arq(monkeypatch)

    from backend.workers.jobs.knowledge import _child_enqueue

    ctx = _mongo_ctx(mongo_queue, tenant_id="tenant-x")
    await _child_enqueue(ctx)("doc-1", "run-1")

    jobs = await mongo_queue.list_jobs(limit=10)
    assert len(jobs) == 1
    assert jobs[0].tenant_id == "tenant-x"
    assert jobs[0].payload == {"document_id": "doc-1", "run_id": "run-1"}


async def test_a_child_enqueued_on_mongo_actually_dispatches(
    mongo_queue: MongoQueueAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The child is a normal queue job: claimable, args-mapped, completable."""
    _patch_arq(monkeypatch)

    from backend.workers.jobs.knowledge import _child_enqueue

    ctx = _mongo_ctx(mongo_queue)
    await _child_enqueue(ctx)("doc-1", "run-1")

    claimed = await mongo_queue.claim("worker-1")
    assert claimed is not None
    assert claimed.function == "process_document"
    assert await mongo_queue.job_args(claimed) == ("doc-1", "run-1")
    assert await mongo_queue.complete(
        claimed.id, "worker-1", execution_version=claimed.execution_version
    )


async def test_no_cross_tenant_leakage_through_child_routing(
    mongo_queue: MongoQueueAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two parents of different tenants cannot cross-route children."""
    _patch_arq(monkeypatch)

    from backend.workers.jobs.knowledge import _child_enqueue

    a = _child_enqueue(_mongo_ctx(mongo_queue, tenant_id="tenant-a"))
    b = _child_enqueue(_mongo_ctx(mongo_queue, tenant_id="tenant-b"))
    await a("doc-a", None)
    await b("doc-b", None)

    by_tenant = {job.tenant_id: job for job in await mongo_queue.list_jobs(limit=10)}
    assert set(by_tenant) == {"tenant-a", "tenant-b"}
    assert by_tenant["tenant-a"].payload["document_id"] == "doc-a"
    assert by_tenant["tenant-b"].payload["document_id"] == "doc-b"
    assert await mongo_queue.get_for_tenant("tenant-a", by_tenant["tenant-b"].id) is None


# ----------------------------------------------------------------------
# 3. Production ARQ behaviour must be byte-identical
# ----------------------------------------------------------------------


async def test_arq_parent_still_enqueues_into_arq(monkeypatch: pytest.MonkeyPatch) -> None:
    """An ARQ worker context carries no queue handle, so children stay on ARQ."""
    _patch_arq(monkeypatch)

    from backend.workers.jobs.knowledge import _child_enqueue

    arq_ctx: dict[str, Any] = {"job_id": "arq-1", "job_try": 1, "max_tries": 3}
    await _child_enqueue(arq_ctx)("doc-1", "run-1")

    assert _ARQ_CALLS == [("process_document", ("doc-1", "run-1"), {})]


async def test_the_api_process_default_stays_arq(monkeypatch: pytest.MonkeyPatch) -> None:
    """No job context at all (the API process) keeps today's behaviour."""
    _patch_arq(monkeypatch)

    from backend.workers.jobs.knowledge import (
        _child_enqueue,
        _child_enqueue_deferred,
        enqueue_process_document,
    )

    await _child_enqueue({})("doc-1", None)
    await _child_enqueue_deferred({})("doc-2", 5.0, None)
    await enqueue_process_document("doc-3", None)

    assert [call[0] for call in _ARQ_CALLS] == ["process_document"] * 3
    assert _ARQ_CALLS[0][1] == ("doc-1", None)
    assert _ARQ_CALLS[1][2] == {"_defer_by": 5.0}
    assert _ARQ_CALLS[2][1] == ("doc-3", None)


async def test_arq_crawl_fanout_call_shape_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The crawl fan-out must be the same single positional ARQ call as before."""
    _patch_arq(monkeypatch)

    from backend.workers.jobs.crawl import _child_enqueue_knowledge

    await _child_enqueue_knowledge({"job_id": "arq-2"})("website-1")

    assert _ARQ_CALLS == [("process_website_documents", ("website-1",), {})]


# ----------------------------------------------------------------------
# 4. The resolver cannot be hijacked
# ----------------------------------------------------------------------


def test_a_foreign_queue_handle_cannot_hijack_routing() -> None:
    """A non-WorkerQueue ``queue`` value falls back to ARQ, it is never called."""
    from backend.queue.arq_adapter import ArqQueueAdapter
    from backend.queue.child import resolve_child_queue

    for hostile in (object(), "mongodb://evil", 42, None, {"enqueue": "not-callable"}):
        resolved = resolve_child_queue({"queue": hostile})
        assert isinstance(resolved, ArqQueueAdapter)


def test_resolve_child_queue_defaults_to_arq_without_a_context() -> None:
    from backend.queue.arq_adapter import ArqQueueAdapter
    from backend.queue.child import resolve_child_queue

    assert isinstance(resolve_child_queue(None), ArqQueueAdapter)
    assert isinstance(resolve_child_queue({}), ArqQueueAdapter)


def test_child_routing_never_falls_back_when_a_real_mongo_queue_is_present() -> None:
    """A genuine Mongo adapter in the context must win, not fall back to ARQ."""
    from backend.queue.arq_adapter import ArqQueueAdapter
    from backend.queue.child import resolve_child_queue
    from backend.queue.mongo_adapter import MongoQueueAdapter

    adapter = MongoQueueAdapter.__new__(MongoQueueAdapter)  # no DB needed for routing
    resolved = resolve_child_queue({"queue": adapter})
    assert resolved is adapter
    assert not isinstance(resolved, ArqQueueAdapter)


def test_get_queue_still_defaults_to_arq() -> None:
    from backend.queue.arq_adapter import ArqQueueAdapter
    from backend.queue.factory import get_queue

    assert isinstance(get_queue(), ArqQueueAdapter)


async def test_the_worker_loop_publishes_its_own_queue(
    mongo_queue: MongoQueueAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: MongoWorkerLoop -> real task -> children on the same queue."""
    _patch_arq(monkeypatch)

    from backend.queue.protocol import QueueJob, job_context
    from backend.queue.worker import MongoWorkerLoop

    now = datetime.now(UTC)
    job = QueueJob(
        id="parent-2",
        function="process_website_documents",
        payload={"website_id": "website-1"},
        tenant_id="tenant-loop",
        job_try=1,
        max_tries=3,
        execution_version=1,
        enqueue_time=now,
        score=now,
    )
    ctx = job_context(job, timeout=600, queue_name="q", queue=mongo_queue)
    assert ctx["queue"] is mongo_queue

    seen: dict[str, Any] = {}

    async def handler(handler_ctx: dict[str, Any], website_id: str) -> dict[str, Any]:
        # What a real job does: build its child enqueue from its own context.
        from backend.workers.jobs.knowledge import _child_enqueue

        enqueue = _child_enqueue(handler_ctx)
        await enqueue("doc-1", "run-1")
        seen["queue"] = handler_ctx.get("queue")
        return {"status": "queued"}

    loop = MongoWorkerLoop(mongo_queue, handlers={"process_website_documents": handler})
    assert await mongo_queue.enqueue(
        "process_website_documents", payload={"website_id": "website-1"}, tenant_id="tenant-loop"
    )

    outcome = await loop.work_once()
    assert outcome is not None
    assert outcome.status == "completed"
    assert seen["queue"] is mongo_queue
    assert _ARQ_CALLS == []
    assert await mongo_queue.count_documents(status="pending") == 1
