"""Regression tests for the `embedding_run` lifecycle (run finalization).

Covers the confirmed latent bug: `embedding_run` was acquired as ``running``
but never transitioned to ``completed``/``failed``, permanently blocking
automatic re-embedding. These tests exercise the fenced acquisition, the
drain-based finalization in `KnowledgeProcessor._refresh_website`, the
best-effort healing of stuck-but-drained runs, and the repository-level
`finalize_embedding_run` atomic fencing (idempotent, run-id/state-guarded).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.core.errors import EmbeddingRateLimitedError
from backend.core.security import utcnow
from backend.models.document import Document
from backend.models.knowledge_chunk import (
    KNOWLEDGE_STATUS_FAILED,
    KNOWLEDGE_STATUS_RATE_LIMITED,
    KNOWLEDGE_STATUS_READY,
)
from backend.models.website import EmbeddingRun, Website
from backend.repositories.website_repository import MongoWebsiteRepository
from backend.services.knowledge.processor import KnowledgeProcessor

from tests.fakes import (
    FakeAuditLogRepository,
    FakeDocumentRepository,
    FakeEmbeddingClient,
    FakeKnowledgeChunkRepository,
    FakeUsageRecordRepository,
    FakeVectorRepository,
    FakeWebsiteRepository,
)

TEXT = "Alpha beta. Gamma delta. " * 40


@dataclass
class Env:
    documents: FakeDocumentRepository
    vector: FakeVectorRepository
    chunks: FakeKnowledgeChunkRepository
    websites: FakeWebsiteRepository
    audit: FakeAuditLogRepository
    embedder: FakeEmbeddingClient
    usage: FakeUsageRecordRepository
    website: Website
    document: Document
    processor: KnowledgeProcessor


@dataclass
class RecordingEnqueue:
    document_ids: list[str] = field(default_factory=list)

    async def __call__(self, document_id: str) -> None:
        self.document_ids.append(document_id)


@dataclass
class RecordingRetry:
    scheduled: list[tuple[str, float]] = field(default_factory=list)

    async def __call__(self, document_id: str, delay_seconds: float) -> None:
        self.scheduled.append((document_id, delay_seconds))


def _fenced_processor(env: Env) -> KnowledgeProcessor:
    async def resolve(_website: Website) -> FakeEmbeddingClient:
        return env.embedder

    return KnowledgeProcessor(
        documents=env.documents,
        vector=env.vector,
        chunks=env.chunks,
        websites=env.websites,
        audit=env.audit,
        embedder=env.embedder,
        usage=env.usage,
        chunk_size=30,
        overlap=5,
        provider_resolver=resolve,
    )


async def _env(*, content: str = TEXT) -> Env:
    documents = FakeDocumentRepository()
    vector = FakeVectorRepository()
    chunks = FakeKnowledgeChunkRepository(vector=vector)
    websites = FakeWebsiteRepository()
    audit = FakeAuditLogRepository()
    embedder = FakeEmbeddingClient()
    usage = FakeUsageRecordRepository()

    website = Website.new(tenant_id="tenant-a", name="Acme", url="https://acme.example/")
    await websites.create(website)
    document = Document.new(
        tenant_id="tenant-a",
        website_id=website.id,
        url="https://acme.example/",
        title="Home",
        content=content,
        checksum="abc123",
    )
    await documents.upsert(document)
    env = Env(documents, vector, chunks, websites, audit, embedder, usage, website, document, None)  # type: ignore[arg-type]
    env.processor = _fenced_processor(env)
    return env


# A. A fresh website acquires a running run when the fan-out starts.
async def test_fresh_run_acquires_successfully() -> None:
    env = await _env()
    enqueue = RecordingEnqueue()
    result = await env.processor.process_website_documents(env.website.id, enqueue=enqueue)

    assert result["status"] == "queued"
    assert result["documents"] == 1
    run_id = result["run_id"]
    website = env.websites.websites[env.website.id]
    assert website.embedding_run is not None
    assert website.embedding_run.id == run_id
    assert website.embedding_run.state == "running"
    assert enqueue.document_ids == [env.document.id]


# B. A running run rejects a second fan-out without touching it.
async def test_running_run_returns_already_processing() -> None:
    env = await _env()
    await env.processor.process_website_documents(env.website.id, enqueue=RecordingEnqueue())

    result = await env.processor.process_website_documents(
        env.website.id, enqueue=RecordingEnqueue()
    )

    assert result["status"] == "already_processing"
    website = env.websites.websites[env.website.id]
    assert website.embedding_run is not None
    assert website.embedding_run.state == "running"


# C. A fully-drained pass (every document terminal and READY) finalizes the
#    run as `completed` so the next pass can re-acquire.
async def test_successful_drain_finalizes_run_completed() -> None:
    env = await _env()
    enqueue = RecordingEnqueue()
    fanout = await env.processor.process_website_documents(env.website.id, enqueue=enqueue)
    run_id = fanout["run_id"]

    result = await env.processor.process_document(env.document.id, run_id=run_id)

    assert result["status"] == "processed"
    website = env.websites.websites[env.website.id]
    assert website.embedding_run is not None
    assert website.embedding_run.id == run_id
    assert website.embedding_run.state == "completed"
    assert website.knowledge_status == KNOWLEDGE_STATUS_READY


# D. An all-failed drain finalizes the run as `failed` (still re-acquirable).
async def test_all_failed_drain_finalizes_run_failed() -> None:
    env = await _env(content="Short page")
    fanout = await env.processor.process_website_documents(
        env.website.id, enqueue=RecordingEnqueue()
    )
    run_id = fanout["run_id"]

    result = await env.processor.process_document(env.document.id, run_id=run_id)

    assert result["status"] == "insufficient_content"
    website = env.websites.websites[env.website.id]
    assert website.embedding_run is not None
    assert website.embedding_run.id == run_id
    assert website.embedding_run.state == "failed"
    assert website.knowledge_status == KNOWLEDGE_STATUS_FAILED


# E. A completed run releases the fence: the next fan-out acquires a NEW run.
async def test_second_run_can_acquire_after_completed() -> None:
    env = await _env()
    fanout1 = await env.processor.process_website_documents(
        env.website.id, enqueue=RecordingEnqueue()
    )
    first_run_id = fanout1["run_id"]
    await env.processor.process_document(env.document.id, run_id=first_run_id)

    fanout2 = await env.processor.process_website_documents(
        env.website.id, enqueue=RecordingEnqueue()
    )

    assert fanout2["status"] == "queued"
    assert fanout2["run_id"] != first_run_id
    website = env.websites.websites[env.website.id]
    assert website.embedding_run is not None
    assert website.embedding_run.id == fanout2["run_id"]
    assert website.embedding_run.state == "running"


# F. A failed run also releases the fence for the next pass.
async def test_second_run_can_acquire_after_failed() -> None:
    env = await _env(content="Short page")
    fanout1 = await env.processor.process_website_documents(
        env.website.id, enqueue=RecordingEnqueue()
    )
    first_run_id = fanout1["run_id"]
    await env.processor.process_document(env.document.id, run_id=first_run_id)

    fanout2 = await env.processor.process_website_documents(
        env.website.id, enqueue=RecordingEnqueue()
    )

    assert fanout2["status"] == "queued"
    assert fanout2["run_id"] != first_run_id
    website = env.websites.websites[env.website.id]
    assert website.embedding_run is not None
    assert website.embedding_run.state == "running"


# G. A stale run_id cannot finalize a newer, currently-running run.
async def test_stale_run_id_cannot_finalize_newer_run() -> None:
    env = await _env()
    fanout1 = await env.processor.process_website_documents(
        env.website.id, enqueue=RecordingEnqueue()
    )
    old_run_id = fanout1["run_id"]
    await env.processor.process_document(env.document.id, run_id=old_run_id)
    fanout2 = await env.processor.process_website_documents(
        env.website.id, enqueue=RecordingEnqueue()
    )
    new_run_id = fanout2["run_id"]
    assert new_run_id != old_run_id

    finalized = await env.websites.finalize_embedding_run(
        "tenant-a", env.website.id, old_run_id, "failed"
    )

    assert finalized is False
    website = env.websites.websites[env.website.id]
    assert website.embedding_run is not None
    assert website.embedding_run.id == new_run_id
    assert website.embedding_run.state == "running"


# H. Rate-limited documents awaiting a deferred retry are non-terminal, so the
#    run stays `running` until the deferred retry drains it.
async def test_rate_limited_document_keeps_run_running() -> None:
    env = await _env()

    class RateLimitedEmbedder(FakeEmbeddingClient):
        async def embed(self, texts: list[str]) -> list[list[float]]:
            raise EmbeddingRateLimitedError("429 provider rate limit")

    env.embedder = RateLimitedEmbedder()
    env.processor = _fenced_processor(env)
    retries = RecordingRetry()
    fanout = await env.processor.process_website_documents(
        env.website.id, enqueue=RecordingEnqueue()
    )
    run_id = fanout["run_id"]

    result = await env.processor.process_document(env.document.id, on_retry=retries, run_id=run_id)

    assert result["status"] == "retry_scheduled"
    stored = env.documents.documents[env.document.id]
    assert stored.knowledge_status == KNOWLEDGE_STATUS_RATE_LIMITED
    website = env.websites.websites[env.website.id]
    assert website.embedding_run is not None
    assert website.embedding_run.id == run_id
    assert website.embedding_run.state == "running"


# I. Manual retry (`run_id=None`) still works while a fenced run is running,
#    and the drained pass still finalizes the run.
async def test_manual_retry_works_while_run_is_running() -> None:
    env = await _env()
    second = Document.new(
        tenant_id="tenant-a",
        website_id=env.website.id,
        url="https://acme.example/about",
        title="About",
        content=TEXT,
        checksum="second-1",
    )
    await env.documents.upsert(second)

    enqueue = RecordingEnqueue()
    fanout = await env.processor.process_website_documents(env.website.id, enqueue=enqueue)
    run_id = fanout["run_id"]
    assert fanout["documents"] == 2

    first = await env.processor.process_document(env.document.id, run_id=run_id)
    assert first["status"] == "processed"
    website = env.websites.websites[env.website.id]
    assert website.embedding_run is not None
    assert website.embedding_run.state == "running"

    manual = await env.processor.process_document(second.id)
    assert manual["status"] == "processed"
    assert env.websites.websites[env.website.id].embedding_run.state == "completed"


# J. Re-acquisition after a completed run mirrors what the maintenance
#    `reingest_website_corpus.py` precondition needs.
async def test_maintenance_reingest_can_acquire_after_completed() -> None:
    env = await _env()
    fanout = await env.processor.process_website_documents(
        env.website.id, enqueue=RecordingEnqueue()
    )
    run_id = fanout["run_id"]
    await env.processor.process_document(env.document.id, run_id=run_id)
    assert env.websites.websites[env.website.id].embedding_run.state == "completed"

    identity = env.embedder.embedding_identity
    reacquired = await env.websites.acquire_embedding_run("tenant-a", env.website.id, identity)

    assert reacquired is not None
    assert reacquired.embedding_run is not None
    assert reacquired.embedding_run.state == "running"


# J2. While a run is still running, acquire returns None (the reingest script
#     aborts with its "another embedding run is already active" guard).
async def test_reingest_acquire_refused_while_run_running() -> None:
    env = await _env()
    await env.processor.process_website_documents(env.website.id, enqueue=RecordingEnqueue())

    reacquired = await env.websites.acquire_embedding_run(
        "tenant-a", env.website.id, env.embedder.embedding_identity
    )

    assert reacquired is None


# K. A stuck `running` run on a website with zero documents is drained away on
#    the no-documents pass, keeping the website re-acquirable.
async def test_no_documents_heals_stuck_running_run() -> None:
    env = await _env()
    env.documents.documents.clear()
    now = utcnow()
    env.websites.websites[env.website.id].embedding_run = EmbeddingRun(
        id="stuck-run", identity=env.embedder.embedding_identity, started_at=now, updated_at=now
    )

    result = await env.processor.process_website_documents(
        env.website.id, enqueue=RecordingEnqueue()
    )

    assert result["status"] == "no_documents"
    website = env.websites.websites[env.website.id]
    assert website.embedding_run is not None
    assert website.embedding_run.state == "failed"
    reacquired = await env.websites.acquire_embedding_run(
        "tenant-a", env.website.id, env.embedder.embedding_identity
    )
    assert reacquired is not None


# K2. A stuck-but-drained `running` run is healed by the `already_processing`
#     pass so the NEXT pass can acquire (recovers pre-existing stuck sites).
async def test_already_processing_heals_drained_stuck_run() -> None:
    env = await _env()
    fanout1 = await env.processor.process_website_documents(
        env.website.id, enqueue=RecordingEnqueue()
    )
    await env.processor.process_document(env.document.id, run_id=fanout1["run_id"])
    fanout2 = await env.processor.process_website_documents(
        env.website.id, enqueue=RecordingEnqueue()
    )
    # The unchanged doc never drains run2 through a terminal event.
    unchanged = await env.processor.process_document(env.document.id, run_id=fanout2["run_id"])
    assert unchanged["status"] == "unchanged"
    website = env.websites.websites[env.website.id]
    assert website.embedding_run is not None
    assert website.embedding_run.state == "running"

    healed = await env.processor.process_website_documents(
        env.website.id, enqueue=RecordingEnqueue()
    )

    assert healed["status"] == "already_processing"
    assert website.embedding_run.state == "completed"

    fanout3 = await env.processor.process_website_documents(
        env.website.id, enqueue=RecordingEnqueue()
    )
    assert fanout3["status"] == "queued"
    assert fanout3["run_id"] != fanout2["run_id"]


# L. Repository-level: the terminal transition is run-id/state fenced and
#    idempotent (one-shot; stale/foreign/unknown targets are safe no-ops).
async def test_finalize_is_run_id_fenced_and_idempotent() -> None:
    env = await _env()
    fanout = await env.processor.process_website_documents(
        env.website.id, enqueue=RecordingEnqueue()
    )
    run_id = fanout["run_id"]
    repo = env.websites

    assert await repo.finalize_embedding_run("tenant-a", env.website.id, run_id, "failed") is True
    website = repo.websites[env.website.id]
    assert website.embedding_run is not None
    assert website.embedding_run.state == "failed"

    assert (
        await repo.finalize_embedding_run("tenant-a", env.website.id, run_id, "completed") is False
    )
    assert (
        await repo.finalize_embedding_run("tenant-a", env.website.id, "stale-run", "failed")
        is False
    )
    assert await repo.finalize_embedding_run("tenant-b", env.website.id, run_id, "failed") is False
    assert await repo.finalize_embedding_run("tenant-a", "missing-site", run_id, "failed") is False
    website = repo.websites[env.website.id]
    assert website.embedding_run.state == "failed"


# L2. MongoDB implementation produces the exact fenced update.
class _FinalizeResult:
    def __init__(self, matched_count: int) -> None:
        self.matched_count = matched_count


class _RunDocCollection:
    def __init__(self, doc: dict[str, Any]) -> None:
        self._doc = doc
        self.filters: list[dict[str, Any]] = []

    async def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> _FinalizeResult:
        self.filters.append(query)
        doc = self._doc
        run = doc.get("embedding_run")
        matches = (
            query.get("_id") == doc.get("_id")
            and query.get("tenant_id") == doc.get("tenant_id")
            and run is not None
            and query.get("embedding_run.id") == run.get("id")
            and query.get("embedding_run.state") == "running"
            and run.get("state") == "running"
        )
        if matches:
            run["state"] = update["$set"]["embedding_run.state"]
            run["updated_at"] = update["$set"]["embedding_run.updated_at"]
            return _FinalizeResult(1)
        return _FinalizeResult(0)


class _RunFakeDb:
    def __init__(self, collection: _RunDocCollection) -> None:
        self._collection = collection

    def __getitem__(self, _name: str) -> _RunDocCollection:
        return self._collection


async def test_mongo_finalize_update_is_fenced() -> None:
    doc: dict[str, Any] = {
        "_id": "site-a",
        "tenant_id": "tenant-a",
        "embedding_run": {"id": "run-1", "state": "running", "updated_at": None},
    }
    collection = _RunDocCollection(doc)
    repo = MongoWebsiteRepository(_RunFakeDb(collection))  # type: ignore[arg-type]

    assert await repo.finalize_embedding_run("tenant-a", "site-a", "run-1", "completed") is True
    assert doc["embedding_run"]["state"] == "completed"

    fence = collection.filters[0]
    assert fence["_id"] == "site-a"
    assert fence["tenant_id"] == "tenant-a"
    assert fence["embedding_run.id"] == "run-1"
    assert fence["embedding_run.state"] == "running"

    assert await repo.finalize_embedding_run("tenant-a", "site-a", "run-1", "failed") is False
    assert await repo.finalize_embedding_run("tenant-a", "site-a", "stale", "failed") is False
    assert await repo.finalize_embedding_run("tenant-b", "site-a", "run-1", "failed") is False
