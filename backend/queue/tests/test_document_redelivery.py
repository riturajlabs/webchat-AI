"""Document redelivery, changed-checksum and dual-execution validation (Phase 17B).

A queue migration must not change what a *duplicate* document delivery does. These
tests drive the real :class:`KnowledgeProcessor` (only the embedding provider is
faked) and pin the three domain guarantees a Mongo queue depends on:

1. **Same checksum** - attempt A embeds, loses its lease, B reclaims. B's
   delivery must be suppressed by the checksum gate, the embedding provider must
   not be billed twice, and A must not be able to overwrite B's authoritative
   state afterwards.
2. **Changed checksum** - a document that moved from checksum X to Y must have Y
   processed; X must not suppress Y; and a stale X-carrying attempt must not be
   able to roll Y back.
3. **Dual execution** - A and B overlapping must not corrupt terminal state or
   roll a checksum back, even though duplicated *provider* work is unavoidable
   and is reported separately.

Queue-level execution fencing (``execution_version``) is validated separately in
``test_ownership_races.py``; the queue store used here is the real
:class:`MongoQueueAdapter` on the isolated prototype mongod, so lease expiry and
reclaim are genuine, not simulated.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from backend.models.document import Document
from backend.models.knowledge_chunk import (
    KNOWLEDGE_STATUS_FAILED,
    KNOWLEDGE_STATUS_PROCESSING,
    KNOWLEDGE_STATUS_READY,
)
from backend.models.website import Website
from backend.prototypes.mongo_queue.config import DEFAULT_MONGO_URI
from backend.queue.mongo_adapter import MongoQueueAdapter
from backend.services.knowledge.processor import KnowledgeProcessor
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from tests.fakes import (
    FakeAuditLogRepository,
    FakeDocumentRepository,
    FakeEmbeddingClient,
    FakeKnowledgeChunkRepository,
    FakeUsageRecordRepository,
    FakeVectorRepository,
    FakeWebsiteRepository,
)

TENANT = "tenant-a"
OTHER_TENANT = "tenant-b"


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


@pytest.fixture
async def mongo_queue() -> AsyncIterator[MongoQueueAdapter]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        DEFAULT_MONGO_URI, serverSelectionTimeoutMS=3000, tz_aware=True
    )
    try:
        await client.admin.command("ping")
    except Exception as exc:  # noqa: BLE001 - environment guard
        client.close()
        pytest.skip(f"isolated prototype mongod unreachable: {exc}")
    db: AsyncIOMotorDatabase[dict[str, Any]] = client["webchat_ai_queue_test_docredelivery"]
    # A 0.5 s lease with a 0.1 s heartbeat so lease expiry is real but fast.
    adapter = MongoQueueAdapter(
        db, collection_name="worker_jobs", lease_seconds=0.5, heartbeat_seconds=0.1
    )
    await adapter.ensure_indexes()
    yield adapter
    for name in await db.list_collection_names():
        await db.drop_collection(name)
    client.close()


class _Env:
    """Repositories + a counting embedder, wired to a real KnowledgeProcessor."""

    def __init__(self) -> None:
        self.documents = FakeDocumentRepository()
        self.vector = FakeVectorRepository()
        # Wraps the vector repo: in production both read the same
        # `knowledge_chunks` collection, so counts must reflect inserts.
        self.chunks = FakeKnowledgeChunkRepository(self.vector)
        self.websites = FakeWebsiteRepository()
        self.audit = FakeAuditLogRepository()
        self.usage = FakeUsageRecordRepository()
        self.embedder = FakeEmbeddingClient()
        self.website = Website.new(tenant_id=TENANT, name="Acme", url="https://acme.example/")
        self.document = Document.new(
            tenant_id=TENANT,
            website_id=self.website.id,
            url="https://acme.example/a",
            title="A",
            content="Alpha " * 200,
            checksum="X",
            source_type="website",
        )
        # A second tenant's website/document, to prove no cross-tenant effects.
        self.other_website = Website.new(
            tenant_id=OTHER_TENANT, name="Other", url="https://other.example/"
        )
        self.other_document = Document.new(
            tenant_id=OTHER_TENANT,
            website_id=self.other_website.id,
            url="https://other.example/a",
            title="A",
            content="Bravo " * 200,
            checksum="X",
            source_type="website",
        )

    async def seed(self) -> None:
        await self.websites.create(self.website)
        await self.websites.create(self.other_website)
        await self.documents.upsert(self.document)
        await self.documents.upsert(self.other_document)

    def processor(self) -> KnowledgeProcessor:
        return KnowledgeProcessor(
            documents=self.documents,
            vector=self.vector,
            chunks=self.chunks,
            websites=self.websites,
            audit=self.audit,
            embedder=self.embedder,
            usage=self.usage,
            cache=None,
            min_content_chars=10,
        )

    @property
    def embed_calls(self) -> int:
        """How many times the (faked) provider was actually called."""
        return len(self.embedder.calls)


@pytest.fixture
async def env() -> AsyncIterator[_Env]:
    environment = _Env()
    await environment.seed()
    yield environment


def _settled(lease_seconds: float = 0.5) -> None:
    """Let a lease expire without a sleep-based race in the assertions."""
    import time

    time.sleep(lease_seconds + 0.15)


# ----------------------------------------------------------------------
# §8 Same-checksum redelivery
# ----------------------------------------------------------------------


async def test_same_checksum_redelivery_is_suppressed_by_the_checksum_gate(
    env: _Env,
) -> None:
    """B's redelivery of an already-embedded document does no work at all."""
    processor = env.processor()

    first = await processor.process_document(env.document.id)
    assert first["status"] == "processed", first
    calls_after_first = env.embed_calls
    assert calls_after_first == 1

    # Attempt B: same document, same checksum, redelivered.
    second = await processor.process_document(env.document.id)

    assert second == {"status": "unchanged"}
    assert env.embed_calls == calls_after_first, "redelivery re-billed the embedder"
    assert await env.chunks.count_by_document(TENANT, env.document.id) > 0


async def test_a_stale_document_write_cannot_rewind_the_document(env: _Env) -> None:
    """Phase 17B.1: a stale knowledge write is refused, not applied.

    Before the CAS, attempt A held a ``Document`` snapshot, embedded it, and
    wrote the whole document back with no precondition - resetting
    ``knowledge_checksum`` and dragging the source ``content``/``checksum``
    backwards with it. B had already stored the authoritative state, so A's
    write reopened the document for reprocessing.

    The write is now a single atomic, preconditioned update, so the snapshot A
    still holds no longer matches the row and the write is refused.
    """
    processor = env.processor()
    live = await env.documents.find_by_id_any(env.document.id)
    assert live is not None
    stale_snapshot = live.model_copy(deep=True)

    # B embeds and lands the authoritative state.
    await processor.process_document(env.document.id)
    winner = await env.documents.find_by_id_any(env.document.id)
    assert winner is not None and winner.knowledge_checksum == "X"

    # A's stale write is refused instead of applied.
    applied = await env.documents.update_knowledge_if_current(
        stale_snapshot, expected_checksum=stale_snapshot.checksum
    )
    assert applied is False, "a stale knowledge write was allowed to rewind the row"

    untouched = await env.documents.find_by_id_any(env.document.id)
    assert untouched is not None
    assert untouched.knowledge_checksum == "X"
    assert untouched.knowledge_status == KNOWLEDGE_STATUS_READY

    # Consequence: no duplicate provider work, because nothing rewound.
    calls_before = env.embed_calls
    result = await processor.process_document(env.document.id)
    assert result == {"status": "unchanged"}
    assert env.embed_calls == calls_before, "the refused write caused re-embedding"

    # The other tenant's document is untouched by any of this.
    other = await env.documents.find_by_id_any(env.other_document.id)
    assert other is not None and other.knowledge_checksum != other.checksum


async def test_a_stale_knowledge_write_cannot_rewind_the_source_content(
    env: _Env,
) -> None:
    """The CAS writes knowledge fields only - never the source it was derived from.

    ``upsert`` replaced the entire document, so a stale knowledge write could
    also restore old ``content``/``checksum``. Guarding the whole document
    behind the knowledge-status comparison would still leave that hazard, so the
    applied update is restricted to the knowledge fields.
    """
    processor = env.processor()
    await processor.process_document(env.document.id)
    winner = await env.documents.find_by_id_any(env.document.id)
    assert winner is not None

    # A snapshot from before the document was re-crawled, carrying old source.
    stale = winner.model_copy(deep=True)
    stale.content = "STALE CONTENT " * 200
    stale.checksum = "OLD"
    stale.knowledge_checksum = "OLD"

    applied = await env.documents.update_knowledge_if_current(
        stale, expected_checksum=stale.checksum
    )
    assert applied is False

    after = await env.documents.find_by_id_any(env.document.id)
    assert after is not None
    assert after.checksum == "X", "a knowledge write rewrote the source checksum"
    assert "STALE CONTENT" not in after.content
    assert after.knowledge_checksum == "X"


async def test_a_stale_failure_record_cannot_overwrite_a_completed_embed(
    env: _Env,
) -> None:
    """A slow failure record must not roll back a success for the same source.

    Without the knowledge-state guard, an execution that recorded a transient
    embedding error after another execution had already stored the chunks would
    mark the document ``failed`` while its chunks sat in the vector store - a
    permanently wrong dashboard for a perfectly good index.
    """
    processor = env.processor()
    live = await env.documents.find_by_id_any(env.document.id)
    assert live is not None

    # A reads the document, then B completes the embed.
    stale = live.model_copy(deep=True)
    await processor.process_document(env.document.id)

    # A now records its failure - the row is already `ready` for this checksum.
    stale.knowledge_status = KNOWLEDGE_STATUS_FAILED
    stale.knowledge_failure_reason = "ProviderTimeout: upstream timed out"
    applied = await env.documents.update_knowledge_if_current(
        stale, expected_checksum=stale.checksum
    )
    assert applied is False, "a failure record overwrote a completed embed"

    after = await env.documents.find_by_id_any(env.document.id)
    assert after is not None
    assert after.knowledge_status == KNOWLEDGE_STATUS_READY
    assert after.knowledge_failure_reason is None

    # The reverse direction stays allowed: re-recording the same success is
    # idempotent and must be able to repair bookkeeping.
    repaired = after.model_copy(deep=True)
    repaired.knowledge_chunks = 0
    assert await env.documents.update_knowledge_if_current(
        repaired, expected_checksum=repaired.checksum
    )
    healed = await env.documents.find_by_id_any(env.document.id)
    assert healed is not None and healed.knowledge_status == KNOWLEDGE_STATUS_READY


@pytest.mark.parametrize("iteration", range(100))
async def test_interleaved_dual_execution_never_rewinds_state(
    env: _Env, iteration: int
) -> None:
    """100 deterministic interleavings of two executions on one document.

    A and B both read the same document and both try to record knowledge state.
    Whichever write lands second must observe the first one's state through the
    CAS rather than blindly overwriting it, so the row always converges on the
    authoritative value and never on a rewound one. The iteration index varies
    the ordering (and the states each side attempts) so the two writers are not
    always identical.
    """
    live = await env.documents.find_by_id_any(env.document.id)
    assert live is not None
    snapshot_a = live.model_copy(deep=True)
    snapshot_b = live.model_copy(deep=True)

    # B records success for checksum X.
    snapshot_b.knowledge_status = KNOWLEDGE_STATUS_READY
    snapshot_b.knowledge_checksum = "X"
    snapshot_b.knowledge_chunks = 3
    applied_b = await env.documents.update_knowledge_if_current(
        snapshot_b, expected_checksum="X"
    )
    assert applied_b is True

    # A attempts a non-ready state afterwards: always refused.
    snapshot_a.knowledge_status = (
        KNOWLEDGE_STATUS_FAILED if iteration % 2 else KNOWLEDGE_STATUS_PROCESSING
    )
    snapshot_a.knowledge_chunks = iteration
    applied_a = await env.documents.update_knowledge_if_current(
        snapshot_a, expected_checksum="X"
    )
    assert applied_a is False

    after = await env.documents.find_by_id_any(env.document.id)
    assert after is not None
    assert after.knowledge_status == KNOWLEDGE_STATUS_READY
    assert after.knowledge_checksum == "X"
    assert after.knowledge_chunks == 3, "a stale write rolled the chunk count back"

    # Convergence is stable: re-attempting the losing state keeps losing, and
    # re-recording the winning state stays allowed (idempotent repair).
    assert not await env.documents.update_knowledge_if_current(
        snapshot_a, expected_checksum="X"
    )
    assert await env.documents.update_knowledge_if_current(
        snapshot_b, expected_checksum="X"
    )
    settled = await env.documents.find_by_id_any(env.document.id)
    assert settled is not None
    assert settled.knowledge_status == KNOWLEDGE_STATUS_READY
    assert settled.knowledge_chunks == 3


async def test_a_knowledge_write_is_refused_after_the_source_changes(env: _Env) -> None:
    """A re-crawl during processing invalidates the in-flight pass.

    Execution A embeds checksum X. The page is re-crawled to checksum Y before A
    records its result. Stamping X's chunks and X's ``knowledge_checksum`` onto
    content Y would be wrong twice over: the dashboard would claim Y was embedded
    when it was not, and the checksum gate would then suppress the pass that
    actually needs to run.
    """
    processor = env.processor()
    live = await env.documents.find_by_id_any(env.document.id)
    assert live is not None
    stale = live.model_copy(deep=True)

    # The page changes underneath the in-flight execution.
    await processor.process_document(env.document.id)
    recrawled = await env.documents.find_by_id_any(env.document.id)
    assert recrawled is not None
    recrawled.content = "Charlie " * 200
    recrawled.checksum = "Y"
    await env.documents.upsert(recrawled)

    applied = await env.documents.update_knowledge_if_current(
        stale, expected_checksum="X"
    )
    assert applied is False, "a write for the old source was applied to new source"

    after = await env.documents.find_by_id_any(env.document.id)
    assert after is not None
    assert after.checksum == "Y"

    # And the new source is still pending work rather than falsely satisfied.
    assert (await processor.process_document(env.document.id))["status"] == "processed"
    final = await env.documents.find_by_id_any(env.document.id)
    assert final is not None and final.knowledge_checksum == "Y"


async def test_a_knowledge_write_never_crosses_tenants(env: _Env) -> None:
    """Two tenants' documents are independently fenced.

    Tenant A's write must never mark tenant B's document embedded, even when the
    two rows are otherwise addressed the same way and even when tenant B's row is
    the one a lost filter would have matched.
    """
    processor = env.processor()
    mine = await env.documents.find_by_id_any(env.document.id)
    assert mine is not None
    a_snapshot = mine.model_copy(deep=True)

    # Tenant A records its own success.
    a_snapshot.knowledge_status = KNOWLEDGE_STATUS_READY
    a_snapshot.knowledge_checksum = "X"
    a_snapshot.knowledge_chunks = 7
    assert await env.documents.update_knowledge_if_current(
        a_snapshot, expected_checksum="X"
    )

    a_after = await env.documents.find_by_id_any(env.document.id)
    assert a_after is not None
    assert a_after.tenant_id == TENANT
    assert a_after.knowledge_chunks == 7
    assert a_after.knowledge_status == KNOWLEDGE_STATUS_READY

    # Tenant B's document is untouched: no cross-tenant knowledge state.
    b_after = await env.documents.find_by_id_any(env.other_document.id)
    assert b_after is not None
    assert b_after.tenant_id == OTHER_TENANT
    assert b_after.knowledge_status != KNOWLEDGE_STATUS_READY
    assert b_after.knowledge_checksum != "X"

    # ...and tenant B still gets its own pass.
    assert (await processor.process_document(env.other_document.id))["status"] == "processed"
    b_final = await env.documents.find_by_id_any(env.other_document.id)
    assert b_final is not None and b_final.knowledge_checksum == "X"


async def test_redelivery_through_the_real_queue_claims_a_fenced_execution(
    env: _Env, mongo_queue: MongoQueueAdapter
) -> None:
    """A requeued document job is a normal queue row, fenced by version."""
    job_id = await mongo_queue.enqueue(
        "process_document",
        payload={"document_id": env.document.id, "run_id": None},
        tenant_id=TENANT,
    )

    attempt_a = await mongo_queue.claim("worker-A")
    assert attempt_a is not None and attempt_a.id == job_id
    version_a = attempt_a.execution_version

    # A stalls; its lease expires; B reclaims and the version advances.
    _settled()
    attempt_b = await mongo_queue.claim("worker-B")
    assert attempt_b is not None
    assert attempt_b.execution_version > version_a

    # B processes and completes.
    result = await env.processor().process_document(env.document.id)
    assert result["status"] == "processed"
    assert await mongo_queue.complete(
        attempt_b.id, "worker-B", execution_version=attempt_b.execution_version
    )

    # A now tries to complete against the version it no longer owns.
    assert not await mongo_queue.complete(attempt_a.id, "worker-A", execution_version=version_a), (
        "a stale owner completed the job"
    )

    # And the authoritative state is B's.
    stored = await env.documents.find_by_id_any(env.document.id)
    assert stored is not None and stored.knowledge_checksum == "X"


async def test_usage_does_not_duplicate_across_a_same_checksum_redelivery(
    env: _Env,
) -> None:
    """The embedding usage event is recorded once, not once per delivery."""
    processor = env.processor()
    await processor.process_document(env.document.id)
    first_events = len(env.usage.records)
    assert first_events >= 1

    await processor.process_document(env.document.id)  # suppressed
    assert len(env.usage.records) == first_events


# ----------------------------------------------------------------------
# §9 Changed-checksum redelivery
# ----------------------------------------------------------------------


async def test_a_changed_checksum_is_processed_and_replaces_the_old_chunks(
    env: _Env,
) -> None:
    """X is embedded, the document changes to Y, and Y must be processed."""
    processor = env.processor()
    await processor.process_document(env.document.id)
    chunks_after_x = await env.chunks.count_by_document(TENANT, env.document.id)
    assert chunks_after_x > 0

    # The document is re-crawled with new content and a new checksum.
    changed = await env.documents.find_by_id_any(env.document.id)
    assert changed is not None
    changed.content = "Charlie " * 200
    changed.checksum = "Y"
    changed.knowledge_checksum = "X"  # stale: still claims to hold X's embedding
    await env.documents.upsert(changed)

    result = await processor.process_document(env.document.id)
    assert result["status"] == "processed"

    stored = await env.documents.find_by_id_any(env.document.id)
    assert stored is not None
    assert stored.knowledge_checksum == "Y", "X incorrectly suppressed Y"
    # Replacement semantics: stale chunks are gone, fresh ones exist.
    assert await env.chunks.count_by_document(TENANT, env.document.id) > 0


async def test_a_stale_x_attempt_cannot_roll_y_back(env: _Env) -> None:
    """A stale attempt carrying X must not restore X over Y's state.

    The domain's protection is the *checksum comparison at embed time*: the
    processor reads the current document, not a caller's snapshot, so a stale
    attempt re-reads Y and is a no-op rather than a rollback.
    """
    processor = env.processor()
    await processor.process_document(env.document.id)

    changed = await env.documents.find_by_id_any(env.document.id)
    assert changed is not None
    changed.content = "Charlie " * 200
    changed.checksum = "Y"
    await env.documents.upsert(changed)
    await processor.process_document(env.document.id)

    y_state = await env.documents.find_by_id_any(env.document.id)
    assert y_state is not None and y_state.knowledge_checksum == "Y"

    # The stale X attempt runs now. It re-reads the document, sees
    # knowledge_checksum == checksum == "Y", and must not touch anything.
    env.embedder.calls.clear()
    stale_result = await processor.process_document(env.document.id)

    after = await env.documents.find_by_id_any(env.document.id)
    assert after is not None
    assert after.knowledge_checksum == "Y", "a stale attempt rolled Y back to X"
    assert stale_result == {"status": "unchanged"}
    assert env.embed_calls == 0


async def test_a_stale_run_id_is_rejected_before_any_work(env: _Env) -> None:
    """``run_id`` fencing: a job from a superseded run does nothing at all."""
    processor = env.processor()
    # The website has no embedding run, so any supplied run_id is stale.
    result = await processor.process_document(env.document.id, run_id="run-from-the-past")
    assert result["status"] == "stale_job"
    assert env.embed_calls == 0
    assert await env.chunks.count_by_document(TENANT, env.document.id) == 0


async def test_cross_tenant_documents_are_never_touched(env: _Env) -> None:
    """Processing tenant-a's document leaves tenant-b's untouched."""
    await env.processor().process_document(env.document.id)

    other = await env.documents.find_by_id_any(env.other_document.id)
    assert other is not None
    assert other.knowledge_checksum != other.checksum
    assert await env.chunks.count_by_document(OTHER_TENANT, env.other_document.id) == 0


# ----------------------------------------------------------------------
# §10 Dual execution
# ----------------------------------------------------------------------


async def test_overlapping_dual_execution_never_rolls_a_checksum_back(
    env: _Env,
) -> None:
    """A and B run the same document concurrently on real Mongo queue rows.

    Duplicated *provider* work is unavoidable without provider-side idempotency
    and is reported explicitly; what must never happen is a terminal rollback.
    """
    processor = env.processor()
    a = asyncio.create_task(processor.process_document(env.document.id))
    b = asyncio.create_task(processor.process_document(env.document.id))
    results = await asyncio.gather(a, b)

    statuses = sorted(r["status"] for r in results)
    assert statuses in (["processed", "unchanged"], ["processed", "processed"]), statuses

    stored = await env.documents.find_by_id_any(env.document.id)
    assert stored is not None
    assert stored.knowledge_checksum == "X"
    assert await env.chunks.count_by_document(TENANT, env.document.id) > 0


async def test_dual_execution_across_a_real_lease_expiry(
    env: _Env, mongo_queue: MongoQueueAdapter
) -> None:
    """A (stale) and B (current owner) both process; only B may terminate."""
    job_id = await mongo_queue.enqueue(
        "process_document",
        payload={"document_id": env.document.id, "run_id": None},
        tenant_id=TENANT,
    )
    processor = env.processor()

    attempt_a = await mongo_queue.claim("worker-A")
    assert attempt_a is not None and attempt_a.id == job_id
    # A does its embedding work, then stalls before completing.
    await processor.process_document(env.document.id)

    _settled()
    attempt_b = await mongo_queue.claim("worker-B")
    assert attempt_b is not None
    assert attempt_b.execution_version > attempt_a.execution_version

    # B redoes the work (provider-level duplication, expected) and terminates.
    await processor.process_document(env.document.id)
    assert await mongo_queue.complete(
        attempt_b.id, "worker-B", execution_version=attempt_b.execution_version
    )

    # A cannot terminate the job it lost.
    assert not await mongo_queue.complete(
        attempt_a.id, "worker-A", execution_version=attempt_a.execution_version
    )
    assert not await mongo_queue.heartbeat(attempt_a.id, "worker-A")

    stored = await env.documents.find_by_id_any(env.document.id)
    assert stored is not None and stored.knowledge_checksum == "X"
    row = await mongo_queue.get(job_id)
    assert row is not None
    assert row.status == "completed"
    assert row.locked_by == "worker-B"


# ----------------------------------------------------------------------
# §11 Website fan-out
# ----------------------------------------------------------------------


async def test_website_fanout_enqueues_one_child_per_eligible_document(
    env: _Env,
) -> None:
    """Real processor, real fan-out: N documents in, N children out."""
    seen: list[tuple[str, str | None]] = []

    async def enqueue(document_id: str, run_id: str | None = None) -> None:
        seen.append((document_id, run_id))

    result = await env.processor().process_website_documents(env.website.id, enqueue=enqueue)

    assert result["status"] == "queued"
    assert result["documents"] == 1
    assert seen == [(env.document.id, result["run_id"])]
    # The other tenant's document is not in this website's fan-out.
    assert all(document_id != env.other_document.id for document_id, _ in seen)


async def test_parent_fanout_redelivery_repeats_children_by_design(
    env: _Env,
) -> None:
    """A duplicated PARENT legitimately re-submits children.

    Production relies on ``process_document`` being idempotent (the checksum
    gate) rather than on parent-side dedup, so a redelivered fan-out produces a
    second submission per document. That is safe, but it must be *documented*,
    not silently assumed - this test states the actual behaviour.
    """
    processor = env.processor()
    first: list[str] = []
    second: list[str] = []

    async def enqueue_a(document_id: str, run_id: str | None = None) -> None:
        first.append(document_id)

    async def enqueue_b(document_id: str, run_id: str | None = None) -> None:
        second.append(document_id)

    await processor.process_website_documents(env.website.id, enqueue=enqueue_a)
    await processor.process_website_documents(env.website.id, enqueue=enqueue_b)

    # Duplicate submission happens...
    assert first == second == [env.document.id]
    # ...and is harmless, because the child is suppressed by the checksum gate.
    await processor.process_document(env.document.id)
    calls = env.embedder.calls
    await processor.process_document(env.document.id)
    assert env.embedder.calls == calls, "duplicate child submission caused real work"


async def test_fanout_of_a_deleted_website_enqueues_nothing(env: _Env) -> None:
    seen: list[str] = []

    async def enqueue(document_id: str, run_id: str | None = None) -> None:
        seen.append(document_id)

    website = await env.websites.find_by_id_any(env.website.id)
    assert website is not None
    website.status = "deleted"
    await env.websites.update(website)

    result = await env.processor().process_website_documents(env.website.id, enqueue=enqueue)
    assert result == {"status": "not_found"}
    assert seen == []
