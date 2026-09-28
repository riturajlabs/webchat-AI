"""Producer routing across the two queue backends (Phase 18A).

The API producers (`enqueue_email`, `enqueue_crawl_website`,
`enqueue_process_document`, `enqueue_process_document_deferred`,
`enqueue_process_website_documents`) reach the queue through
:mod:`backend.queue.runtime`. What must hold on both backends:

* **ARQ (production default)** - the ``enqueue_job`` call shape is byte-identical
  to pre-Phase 18A, and *no* domain row is read at enqueue time. A queue
  submission must not become a database round-trip in the API hot path.
* **Mongo (opt-in)** - the row is attributed to the tenant of its authoritative
  domain row, and nothing lands on ARQ. A tenant that cannot be resolved fails
  loud: an unattributed queue row is unowned work nobody can observe or cancel.

No real Redis and no real ARQ worker is involved: the ARQ adapter's own Redis
handle is swapped for a recorder that mirrors ``ArqRedis.enqueue_job``. The Mongo
side uses the isolated prototype mongod via the shared fixtures.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from backend.core.config import Settings
from backend.queue import runtime
from backend.queue.arq_adapter import ArqQueueAdapter
from backend.queue.errors import UnresolvedTenantError
from backend.queue.mongo_adapter import MissingTenantError, MongoQueueAdapter
from backend.queue.runtime import enqueue_worker_job, producer_tenant
from backend.services.mail.base import EmailMessage
from backend.workers.jobs import crawl as crawl_jobs
from backend.workers.jobs import knowledge as knowledge_jobs
from backend.workers.jobs.crawl import enqueue_crawl_website
from backend.workers.jobs.email import enqueue_email
from backend.workers.jobs.knowledge import (
    enqueue_process_document,
    enqueue_process_document_deferred,
    enqueue_process_website_documents,
)

_TENANT = "tenant-a"


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


class _RecordingArq:
    """Records the exact ``ArqRedis.enqueue_job`` shape production receives.

    It also models ARQ's own ``_job_id`` suppression (a repeat id inside the
    result-retention window returns ``None`` and enqueues nothing), because
    FIND-02 behaviour is one of the things under test.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.job_ids: set[str] = set()

    async def enqueue_job(self, function: str, *args: Any, **kwargs: Any) -> object | None:
        job_id = kwargs.get("_job_id")
        if isinstance(job_id, str):
            if job_id in self.job_ids:
                return None
            self.job_ids.add(job_id)
        self.calls.append((function, args, kwargs))
        return SimpleNamespace(job_id=f"{function}:{len(self.calls)}")


def _arq_settings() -> Settings:
    return Settings(queue_backend="arq")


def _mongo_settings() -> Settings:
    return Settings(
        queue_backend="mongo",
        mongo_queue_enabled=True,
        mongo_queue_database="webchat_ai_queue_routing",
    )


def _use_arq(monkeypatch: pytest.MonkeyPatch) -> _RecordingArq:
    """Point the whole producer path at an ARQ recorder."""
    arq = _RecordingArq()
    monkeypatch.setattr(ArqQueueAdapter, "_arq_redis", lambda self: arq)
    monkeypatch.setattr(runtime, "get_settings", _arq_settings)
    monkeypatch.setattr("backend.queue.factory.get_settings", _arq_settings)
    runtime.reset_worker_queue()
    return arq


def _use_mongo(monkeypatch: pytest.MonkeyPatch, adapter: MongoQueueAdapter) -> _RecordingArq:
    """Route producers onto a real Mongo queue; return the ARQ recorder."""
    arq = _RecordingArq()
    monkeypatch.setattr(ArqQueueAdapter, "_arq_redis", lambda self: arq)
    monkeypatch.setattr(runtime, "get_settings", _mongo_settings)
    monkeypatch.setattr(runtime, "get_worker_queue", lambda: adapter)
    runtime.reset_worker_queue()
    return arq


def _tenant_repo(rows: dict[str, str | None], seen: list[str]) -> Any:
    """A domain repository that answers only the enqueue-time tenant lookup."""

    class _Repo:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._db = args[0] if args else None

        async def find_by_id_any(self, row_id: str) -> Any:
            seen.append(row_id)
            if row_id not in rows:
                return None
            return SimpleNamespace(tenant_id=rows[row_id])

    return _Repo


def _forbid_repositories(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any domain-row construction an immediate, loud failure."""

    class _Forbidden:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError("ARQ mode must not read a domain row to enqueue")

    for module, name in (
        (crawl_jobs, "MongoCrawlJobRepository"),
        (knowledge_jobs, "MongoDocumentRepository"),
        (knowledge_jobs, "MongoWebsiteRepository"),
    ):
        monkeypatch.setattr(module, name, _Forbidden)


def _message(tenant: str = "") -> EmailMessage:
    message = EmailMessage(to="user@example.com", subject="Reset", text="body", html="<p>body</p>")
    return message.for_tenant(tenant) if tenant else message


@pytest.fixture
async def routing_adapter(queue_db: Any) -> Any:
    adapter = MongoQueueAdapter(queue_db, collection_name="worker_jobs_routing")
    await adapter.ensure_indexes()
    yield adapter
    await queue_db.drop_collection("worker_jobs_routing")


# ----------------------------------------------------------------------
# ARQ mode: unchanged call shape, no domain reads
# ----------------------------------------------------------------------


async def test_arq_mode_reproduces_the_production_enqueue_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every producer emits exactly the pre-Phase-18A ARQ call."""
    arq = _use_arq(monkeypatch)
    _forbid_repositories(monkeypatch)

    await enqueue_crawl_website("job-123")
    await enqueue_process_document("d1")
    await enqueue_process_document_deferred("d2", 5.0)
    await enqueue_process_website_documents("w1")
    await enqueue_email(_message(tenant=_TENANT))

    assert arq.calls == [
        ("crawl_website", ("job-123",), {"_job_id": "crawl:job-123"}),
        ("process_document", ("d1", None), {}),
        ("process_document", ("d2", None), {"_defer_by": 5.0}),
        ("process_website_documents", ("w1",), {}),
        (
            "send_email",
            (
                {
                    "to": "user@example.com",
                    "subject": "Reset",
                    "text": "body",
                    "html": "<p>body</p>",
                    "delivery_id": arq.calls[4][1][0]["delivery_id"],
                    "idempotency_key": arq.calls[4][1][0]["idempotency_key"],
                    "tenant_id": _TENANT,
                },
            ),
            {},
        ),
    ]


async def test_arq_mode_never_carries_a_tenant_on_the_wire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ARQ job arguments stay exactly the production positional values.

    The tenant travels in the email *payload* (delivery metadata), never as an
    added job argument: adding one would change every job signature.
    """
    arq = _use_arq(monkeypatch)
    _forbid_repositories(monkeypatch)

    await enqueue_crawl_website("job-9")
    await enqueue_process_document("d9")
    await enqueue_process_website_documents("w9")

    for function, args, kwargs in arq.calls:
        assert _TENANT not in args
        assert _TENANT not in str(kwargs)
        assert function in {"crawl_website", "process_document", "process_website_documents"}


async def test_arq_mode_skips_the_tenant_lookup_entirely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The enqueue-time resolver is never even called under ARQ."""
    _use_arq(monkeypatch)
    calls: list[str] = []

    async def resolver() -> str:
        calls.append("resolved")
        return _TENANT

    assert await producer_tenant(resolver) == ""
    assert calls == []


# ----------------------------------------------------------------------
# Mongo mode: rows are attributed to the domain row's tenant
# ----------------------------------------------------------------------


async def test_mongo_mode_attributes_every_row_to_its_domain_tenant(
    monkeypatch: pytest.MonkeyPatch, routing_adapter: MongoQueueAdapter
) -> None:
    """No ARQ, no unattributed row: each job lands with its own tenant."""
    arq = _use_mongo(monkeypatch, routing_adapter)
    seen: list[str] = []
    repo = _tenant_repo(
        {"job-1": "tenant-crawl", "d1": "tenant-doc", "d2": "tenant-doc", "w1": "tenant-web"},
        seen,
    )
    monkeypatch.setattr(crawl_jobs, "MongoCrawlJobRepository", repo)
    monkeypatch.setattr(knowledge_jobs, "MongoDocumentRepository", repo)
    monkeypatch.setattr(knowledge_jobs, "MongoWebsiteRepository", repo)

    await enqueue_crawl_website("job-1")
    await enqueue_process_document("d1")
    await enqueue_process_document_deferred("d2", 5.0)
    await enqueue_process_website_documents("w1")
    await enqueue_email(_message(tenant="tenant-mail"))

    assert arq.calls == [], "Mongo mode must never enqueue onto ARQ"
    assert sorted(seen) == ["d1", "d2", "job-1", "w1"]

    rows = {job.function: job for job in await routing_adapter.list_jobs(limit=10)}
    assert rows["crawl_website"].tenant_id == "tenant-crawl"
    assert rows["crawl_website"].payload == {"crawl_job_id": "job-1"}
    assert rows["process_document"].tenant_id == "tenant-doc"
    assert rows["process_website_documents"].tenant_id == "tenant-web"
    assert rows["send_email"].tenant_id == "tenant-mail"
    # The deferred retry keeps its delay and its run_id.
    assert rows["process_document"].run_at is not None
    assert rows["process_document"].payload["run_id"] is None
    # The JOB-scoped dedup key still applies, on the Mongo unique key.
    assert rows["crawl_website"].dedup_key == "crawl:job-1"


async def test_mongo_mode_survives_a_redis_outage(
    monkeypatch: pytest.MonkeyPatch, routing_adapter: MongoQueueAdapter
) -> None:
    """A Mongo-mode producer needs no Redis at all (ARQ may be switched off).

    Constructing the ARQ adapter would only build a lazy pool, so this is proven
    by asserting no ARQ call happened while every row was still enqueued.
    """
    arq = _use_mongo(monkeypatch, routing_adapter)
    seen: list[str] = []
    repo = _tenant_repo({"d1": "tenant-doc"}, seen)
    monkeypatch.setattr(knowledge_jobs, "MongoDocumentRepository", repo)

    def _explode(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Mongo mode must not reach for Redis")

    monkeypatch.setattr(ArqQueueAdapter, "_arq_redis", _explode)
    await enqueue_process_document("d1")

    assert arq.calls == []
    assert (await routing_adapter.count_documents()) == 1


# ----------------------------------------------------------------------
# fail loud: never fabricate or fall back
# ----------------------------------------------------------------------


async def test_mongo_mode_missing_crawl_job_row_fails_loud(
    monkeypatch: pytest.MonkeyPatch, routing_adapter: MongoQueueAdapter
) -> None:
    arq = _use_mongo(monkeypatch, routing_adapter)
    monkeypatch.setattr(crawl_jobs, "MongoCrawlJobRepository", _tenant_repo({}, []))

    with pytest.raises(UnresolvedTenantError, match="was not found"):
        await enqueue_crawl_website("gone")

    assert await routing_adapter.count_documents() == 0
    assert arq.calls == [], "a Mongo failure must never fall back to ARQ"


async def test_mongo_mode_missing_document_row_fails_loud(
    monkeypatch: pytest.MonkeyPatch, routing_adapter: MongoQueueAdapter
) -> None:
    _use_mongo(monkeypatch, routing_adapter)
    monkeypatch.setattr(knowledge_jobs, "MongoDocumentRepository", _tenant_repo({}, []))

    with pytest.raises(UnresolvedTenantError, match="was not found"):
        await enqueue_process_document("gone")
    with pytest.raises(UnresolvedTenantError, match="was not found"):
        await enqueue_process_document_deferred("gone", 5.0)
    assert await routing_adapter.count_documents() == 0


async def test_mongo_mode_missing_website_row_fails_loud(
    monkeypatch: pytest.MonkeyPatch, routing_adapter: MongoQueueAdapter
) -> None:
    _use_mongo(monkeypatch, routing_adapter)
    monkeypatch.setattr(knowledge_jobs, "MongoWebsiteRepository", _tenant_repo({}, []))

    with pytest.raises(UnresolvedTenantError, match="was not found"):
        await enqueue_process_website_documents("gone")
    assert await routing_adapter.count_documents() == 0


async def test_mongo_mode_an_empty_domain_tenant_is_never_fabricated(
    monkeypatch: pytest.MonkeyPatch, routing_adapter: MongoQueueAdapter
) -> None:
    """A row that exists but carries no tenant is still unresolvable."""
    _use_mongo(monkeypatch, routing_adapter)
    monkeypatch.setattr(crawl_jobs, "MongoCrawlJobRepository", _tenant_repo({"job-1": "  "}, []))

    with pytest.raises(UnresolvedTenantError, match="carries no tenant"):
        await enqueue_crawl_website("job-1")
    assert await routing_adapter.count_documents() == 0


async def test_mongo_mode_email_without_a_tenant_is_rejected_by_the_adapter(
    monkeypatch: pytest.MonkeyPatch, routing_adapter: MongoQueueAdapter
) -> None:
    """An email has no domain row: the message's own tenant IS the scope.

    The adapter is the enforcing boundary here, so a caller that skipped
    ``for_tenant`` gets a hard error instead of an unowned row.
    """
    _use_mongo(monkeypatch, routing_adapter)

    with pytest.raises(MissingTenantError):
        await enqueue_email(_message())
    assert await routing_adapter.count_documents() == 0

    await enqueue_email(_message(tenant=_TENANT))
    assert (await routing_adapter.count_documents()) == 1


async def test_arq_duplicate_suppression_is_still_a_silent_no_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A duplicate ``_job_id`` returns ``None`` - today's behaviour, unchanged."""

    class _DuplicateArq:
        async def enqueue_job(self, function: str, *args: Any, **kwargs: Any) -> None:
            return None

    monkeypatch.setattr(ArqQueueAdapter, "_arq_redis", lambda self: _DuplicateArq())
    runtime.reset_worker_queue()

    assert (
        await enqueue_worker_job("process_document", payload={"document_id": "d1", "run_id": None})
        is None
    )


async def test_a_new_job_id_still_enqueues_after_a_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FIND-02: only the SAME job id is suppressed (the crawl dedup key)."""
    arq = _RecordingArq()
    monkeypatch.setattr(ArqQueueAdapter, "_arq_redis", lambda self: arq)
    monkeypatch.setattr(runtime, "get_settings", _arq_settings)
    monkeypatch.setattr("backend.queue.factory.get_settings", _arq_settings)
    runtime.reset_worker_queue()

    await enqueue_crawl_website("job-123")
    # The producers keep their `-> None` signature: suppression is invisible.
    assert await enqueue_crawl_website("job-123") is None  # type: ignore[func-returns-value]
    await enqueue_crawl_website("job-456")

    assert [call[2].get("_job_id") for call in arq.calls] == [
        "crawl:job-123",
        "crawl:job-456",
    ]


async def test_producer_tenant_resolves_the_domain_row_in_mongo_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime, "get_settings", _mongo_settings)

    async def resolver() -> str:
        return f"  {_TENANT}  "

    assert await producer_tenant(resolver) == _TENANT

    async def empty() -> str:
        return ""

    with pytest.raises(UnresolvedTenantError, match="could not be resolved"):
        await producer_tenant(empty)


async def test_closing_a_broken_worker_queue_never_raises() -> None:
    """Shutdown is best-effort: a pool that cannot be released must not stop the
    API process from finishing its remaining cleanup."""
    closes: list[str] = []

    class _BrokenQueue:
        async def close(self) -> None:
            closes.append("broken")
            raise RuntimeError("connection pool already gone")

    class _NoPoolQueue:
        """The Mongo adapter shape: no pool of its own, so nothing to close."""

    runtime.reset_worker_queue()
    runtime._worker_queue = _BrokenQueue()  # type: ignore[assignment]
    await runtime.close_worker_queue()
    assert closes == ["broken"]

    runtime._worker_queue = _NoPoolQueue()  # type: ignore[assignment]
    await runtime.close_worker_queue()  # no `close` attribute: still not an error

    # The swap is unconditional, so a later producer rebuilds instead of reusing
    # a closed adapter.
    assert runtime._worker_queue is None
    runtime.reset_worker_queue()
