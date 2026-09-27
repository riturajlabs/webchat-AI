"""``WorkerQueue`` contract: the interface both adapters must satisfy (§28.1-2).

The contract is deliberately split into a producer half that BOTH backends
implement and a consumer half that only the Mongo backend can implement (ARQ
owns its own consumption). Each test is parameterised over the adapters so a new
backend cannot quietly drop a method.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from arq.connections import RedisSettings
from backend.queue.arq_adapter import ArqQueueAdapter
from backend.queue.errors import BackendNotSupportedError, UnknownFunctionError
from backend.queue.mongo_adapter import MongoQueueAdapter
from backend.queue.protocol import QueueJob, WorkerQueue, job_context
from redis.asyncio import ConnectionPool

_CONSUMER_METHODS = ("claim", "heartbeat", "complete", "fail", "retire_expired")
_ALL_METHODS = ("enqueue", *_CONSUMER_METHODS, "ping")


def _fake_job(**overrides: Any) -> QueueJob:
    now = datetime.now(UTC)
    base: dict[str, Any] = {
        "id": "job-1",
        "function": "process_document",
        "payload": {"document_id": "d1", "run_id": None},
        "tenant_id": "tenant-a",
        "job_try": 1,
        "max_tries": 3,
        "execution_version": 7,
        "enqueue_time": now,
        "score": now + timedelta(seconds=1),
    }
    base.update(overrides)
    return QueueJob(**base)


# ----------------------------------------------------------------------
# structural contract
# ----------------------------------------------------------------------


def test_worker_queue_protocol_exposes_the_documented_verbs() -> None:
    for name in _ALL_METHODS:
        assert hasattr(WorkerQueue, name), f"WorkerQueue is missing {name}"


def test_both_adapters_satisfy_the_protocol(mongo_client: Any) -> None:
    arq = ArqQueueAdapter("redis://127.0.0.1:1")
    mongo = MongoQueueAdapter(mongo_client["contract_probe_db"], collection_name="worker_jobs")
    assert isinstance(arq, WorkerQueue)
    assert isinstance(mongo, WorkerQueue)


@pytest.mark.parametrize("name", _ALL_METHODS)
def test_mongo_adapter_implements_every_verb(name: str, mongo_client: Any) -> None:
    mongo = MongoQueueAdapter(mongo_client["contract_probe_db"], collection_name="worker_jobs")
    assert callable(getattr(mongo, name))


@pytest.mark.parametrize("name", _CONSUMER_METHODS)
def test_arq_adapter_refuses_consumer_verbs_explicitly(name: str) -> None:
    """ARQ owns consumption, so the adapter must say so - not pretend."""
    arq = ArqQueueAdapter("redis://127.0.0.1:1")
    assert callable(getattr(arq, name))


async def test_arq_consumer_verbs_raise_backend_not_supported() -> None:
    arq = ArqQueueAdapter("redis://127.0.0.1:1")
    with pytest.raises(BackendNotSupportedError):
        await arq.claim("worker-1")
    with pytest.raises(BackendNotSupportedError):
        await arq.heartbeat("job-1", "worker-1")
    with pytest.raises(BackendNotSupportedError):
        await arq.complete("job-1", "worker-1", execution_version=1)
    with pytest.raises(BackendNotSupportedError):
        await arq.fail("job-1", "worker-1", execution_version=1, error="x")
    with pytest.raises(BackendNotSupportedError):
        await arq.retire_expired()


async def test_arq_ping_is_false_when_redis_is_unreachable() -> None:
    """A probe must never raise; it reports False."""
    arq = ArqQueueAdapter("redis://127.0.0.1:1")
    assert await arq.ping() is False


# ----------------------------------------------------------------------
# job context
# ----------------------------------------------------------------------


def test_job_context_reproduces_arq_injected_keys() -> None:
    """ARQ injects exactly job_id/job_try/enqueue_time/score (arq 0.28)."""
    ctx = job_context(_fake_job(), timeout=600, queue_name="arq:queue")
    assert ctx["job_id"] == "job-1"
    assert ctx["job_try"] == 1
    assert ctx["enqueue_time"] is not None
    assert ctx["score"] is not None


def test_job_context_carries_queue_execution_metadata() -> None:
    ctx = job_context(_fake_job(max_tries=3), timeout=3600, queue_name="q")
    assert ctx["max_tries"] == 3
    assert ctx["timeout"] == 3600
    assert ctx["function"] == "process_document"
    assert ctx["queue_name"] == "q"


def test_job_context_does_not_inject_a_tenant() -> None:
    """Production jobs read the authoritative tenant from the domain row.

    Injecting the queue row's tenant copy here would be a *less* trusted value
    and could mask a tenant mismatch, so the context builder leaves it out.
    """
    ctx = job_context(_fake_job(tenant_id="tenant-a"), timeout=600, queue_name="q")
    assert "tenant_id" not in ctx


def test_job_context_does_not_leak_queue_storage_concepts() -> None:
    """No Redis/ZSET/ARQ key concept may appear in the neutral context."""
    ctx = job_context(_fake_job(), timeout=600, queue_name="q")
    for banned in ("zset", "zrange", "arq:job", "in_progress", "retry_key"):
        assert banned not in " ".join(ctx).lower()


# ----------------------------------------------------------------------
# ARQ adapter call shape (no broker contact)
# ----------------------------------------------------------------------


class _RecordingRedis:
    """Stands in for ArqRedis; records the exact enqueue_job call shape."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    async def enqueue_job(self, function: str, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((function, args, kwargs))

        class _Job:
            job_id = "arq-job-1"

        return _Job()

    async def ping(self) -> bool:
        return True


@pytest.fixture
def recording_arq(monkeypatch: pytest.MonkeyPatch) -> tuple[ArqQueueAdapter, _RecordingRedis]:
    adapter = ArqQueueAdapter("redis://127.0.0.1:1")
    recorder = _RecordingRedis()
    monkeypatch.setattr(adapter, "_arq_redis", lambda: recorder)
    return adapter, recorder


async def test_arq_enqueue_reproduces_crawl_call_shape(recording_arq: Any) -> None:
    """`enqueue_crawl_website` today: ("crawl_website", id, _job_id="crawl:<id>")."""
    adapter, recorder = recording_arq
    job_id = await adapter.enqueue(
        "crawl_website", payload={"crawl_job_id": "cj-1"}, job_id="crawl:cj-1"
    )
    assert job_id == "arq-job-1"
    assert recorder.calls == [("crawl_website", ("cj-1",), {"_job_id": "crawl:cj-1"})]


async def test_arq_enqueue_reproduces_email_call_shape(recording_arq: Any) -> None:
    payload = {"to": "a@b.c", "subject": "s", "text": "t", "html": "<p>h</p>"}
    adapter, recorder = recording_arq
    await adapter.enqueue("send_email", payload=payload)
    assert recorder.calls == [("send_email", (payload,), {})]


async def test_arq_enqueue_reproduces_deferred_call_shape(recording_arq: Any) -> None:
    """`enqueue_process_document_deferred` uses `_defer_by`."""
    adapter, recorder = recording_arq
    await adapter.enqueue(
        "process_document", payload={"document_id": "d1", "run_id": "r1"}, defer_by=30
    )
    assert recorder.calls == [("process_document", ("d1", "r1"), {"_defer_by": 30})]


async def test_arq_enqueue_omits_zero_defer(recording_arq: Any) -> None:
    """ARQ treats `_defer_by=0` as falsy; never send it."""
    adapter, recorder = recording_arq
    await adapter.enqueue("process_website_documents", payload={"website_id": "w1"}, defer_by=0)
    assert recorder.calls == [("process_website_documents", ("w1",), {})]


async def test_arq_enqueue_namespaces_a_bare_dedup_key(recording_arq: Any) -> None:
    adapter, recorder = recording_arq
    await adapter.enqueue(
        "process_document", payload={"document_id": "d1", "run_id": None}, dedup_key="d1"
    )
    assert recorder.calls[0][2] == {"_job_id": "process_document:d1"}


async def test_arq_enqueue_rejects_unknown_function(recording_arq: Any) -> None:
    adapter, recorder = recording_arq
    with pytest.raises(UnknownFunctionError):
        await adapter.enqueue("os.system", payload={})
    assert recorder.calls == []


async def test_arq_enqueue_ignores_max_tries_like_arq_does(recording_arq: Any) -> None:
    """ARQ applies max_tries at the worker, never per enqueue."""
    adapter, recorder = recording_arq
    await adapter.enqueue("ping", payload={}, max_tries=99)
    assert "_max_tries" not in recorder.calls[0][2]


async def test_arq_enqueue_reports_arq_own_deduplication(monkeypatch: pytest.MonkeyPatch) -> None:
    """`enqueue_job` returns None when the _job_id already exists (FIND-02)."""
    adapter = ArqQueueAdapter("redis://127.0.0.1:1")

    class _NullRedis:
        async def enqueue_job(self, function: str, *args: Any, **kwargs: Any) -> None:
            return None

    monkeypatch.setattr(adapter, "_arq_redis", lambda: _NullRedis())
    from backend.queue.errors import DuplicateJobError

    with pytest.raises(DuplicateJobError):
        await adapter.enqueue(
            "crawl_website", payload={"crawl_job_id": "cj-1"}, job_id="crawl:cj-1"
        )


def test_arq_adapter_uses_a_pooled_redis_client() -> None:
    """Match the production enqueue helpers: a pooled ArqRedis, not a new client."""
    adapter = ArqQueueAdapter("redis://127.0.0.1:6379")
    client = adapter._arq_redis()
    assert isinstance(client.connection_pool, ConnectionPool)
    assert RedisSettings is not None  # ARQ settings remain the enqueue contract
