"""Tests for `KnowledgeProcessor` (Phase 5, ADR-008).

The processor depends only on Protocols, so every test binds in-memory fakes:
FakeDocumentRepository, FakeVectorRepository, FakeKnowledgeChunkRepository,
FakeWebsiteRepository, FakeAuditLogRepository and FakeEmbeddingClient.
"""

from collections import Counter
from dataclasses import dataclass, field

import pytest
from backend.core.errors import EmbeddingError, EmbeddingUnavailableError
from backend.models.audit_log import AUDIT_KNOWLEDGE_FAILED, AUDIT_KNOWLEDGE_PROCESSED
from backend.models.document import Document
from backend.models.knowledge_chunk import (
    KNOWLEDGE_STATUS_FAILED,
    KNOWLEDGE_STATUS_PROCESSING,
    KNOWLEDGE_STATUS_READY,
    KnowledgeChunk,
)
from backend.models.usage_record import usage_date_key
from backend.models.website import WEBSITE_STATUS_DELETED, Website
from backend.services.knowledge.chunker import chunk_text
from backend.services.knowledge.processor import KnowledgeProcessor, _dedupe_text_chunks

from tests.fakes import (
    FakeAuditLogRepository,
    FakeBrokenCacheStore,
    FakeCacheStore,
    FakeDocumentRepository,
    FakeEmbeddingClient,
    FakeKnowledgeChunkRepository,
    FakeUsageRecordRepository,
    FakeVectorRepository,
    FakeWebsiteRepository,
)

TEXT = "Alpha beta. Gamma delta. " * 40  # enough for several chunks


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
    """Records per-document fan-out calls instead of touching Redis."""

    document_ids: list[str] = field(default_factory=list)

    async def __call__(self, document_id: str) -> None:
        self.document_ids.append(document_id)


def _processor(
    env: Env,
    *,
    chunk_size: int | None = 30,
    overlap: int | None = 5,
    usage: FakeUsageRecordRepository | None = None,
) -> KnowledgeProcessor:
    return KnowledgeProcessor(
        documents=env.documents,
        vector=env.vector,
        chunks=env.chunks,
        websites=env.websites,
        audit=env.audit,
        embedder=env.embedder,
        usage=usage if usage is not None else env.usage,
        chunk_size=chunk_size,
        overlap=overlap,
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
    env = Env(
        documents,
        vector,
        chunks,
        websites,
        audit,
        embedder,
        usage,
        website,
        document,
        None,
    )
    env.processor = _processor(env)
    return env


async def test_embeds_document_and_updates_stats() -> None:
    env = await _env()

    result = await env.processor.process_document(env.document.id)

    assert result["status"] == "processed"
    assert result["chunks"] > 0
    assert len(env.vector.chunks) == result["chunks"]
    assert all(chunk.tenant_id == "tenant-a" for chunk in env.vector.chunks)
    assert all(chunk.embedding_provider == "fake" for chunk in env.vector.chunks)
    assert all(chunk.embedding_model == "fake-embedding" for chunk in env.vector.chunks)
    assert all(chunk.embedding_dimensions == 4 for chunk in env.vector.chunks)
    assert all(chunk.embedding_version == "1" for chunk in env.vector.chunks)
    stored = env.documents.documents[env.document.id]
    assert stored.knowledge_status == KNOWLEDGE_STATUS_READY
    assert stored.knowledge_checksum == "abc123"
    assert stored.knowledge_chunks == result["chunks"]
    assert stored.knowledge_processed_at is not None
    website = env.websites.websites[env.website.id]
    assert website.knowledge_chunks == result["chunks"]
    assert website.knowledge_documents == 1
    assert website.knowledge_status == KNOWLEDGE_STATUS_READY
    assert website.last_knowledge_at is not None
    assert any(log.action == AUDIT_KNOWLEDGE_PROCESSED for log in env.audit.logs)


async def test_website_stats_are_persisted_after_processing() -> None:
    """`_refresh_website` must persist, not just mutate (Mongo returns fresh
    objects on every read, so in-memory-only changes would be lost)."""

    class CopyOnReadWebsites(FakeWebsiteRepository):
        async def find_by_id(self, tenant_id: str, website_id: str) -> Website | None:
            website = await super().find_by_id(tenant_id, website_id)
            return website.model_copy(deep=True) if website else None

        async def find_by_id_any(self, website_id: str) -> Website | None:
            website = self._websites.get(website_id)
            return website.model_copy(deep=True) if website else None

    env = await _env()
    websites = CopyOnReadWebsites()
    websites._websites = env.websites._websites
    env.websites = websites
    env.processor = _processor(env)

    result = await env.processor.process_document(env.document.id)

    assert result["status"] == "processed"
    persisted = await websites.find_by_id(env.document.tenant_id, env.website.id)
    assert persisted is not None
    assert persisted.knowledge_chunks == result["chunks"]
    assert persisted.knowledge_documents == 1
    assert persisted.knowledge_status == KNOWLEDGE_STATUS_READY
    assert persisted.last_knowledge_at is not None


async def test_chunk_metadata_carries_source_and_document_ids() -> None:
    env = await _env()

    await env.processor.process_document(env.document.id)

    chunk = env.vector.chunks[0]
    assert chunk.document_id == env.document.id
    assert chunk.website_id == env.website.id
    assert chunk.metadata["source_url"] == env.document.url
    assert chunk.metadata["title"] == "Home"
    assert chunk.chunk_text  # non-empty


async def test_idempotent_skip_when_unchanged() -> None:
    env = await _env()
    await env.processor.process_document(env.document.id)
    first_calls = len(env.embedder.calls)
    first_count = len(env.vector.chunks)

    result = await env.processor.process_document(env.document.id)

    assert result == {"status": "unchanged"}
    assert len(env.embedder.calls) == first_calls  # no re-embedding
    assert len(env.vector.chunks) == first_count
    processed_audits = [log for log in env.audit.logs if log.action == AUDIT_KNOWLEDGE_PROCESSED]
    assert len(processed_audits) == 1


async def test_replaces_chunks_when_content_changed() -> None:
    env = await _env()
    await env.processor.process_document(env.document.id)
    first_count = len(env.vector.chunks)
    assert first_count > 0

    env.document.content = TEXT + " New content sentence appended. "
    env.document.checksum = "changed-456"
    await env.documents.upsert(env.document)

    result = await env.processor.process_document(env.document.id)

    assert result["status"] == "processed"
    assert result["chunks"] == len(env.vector.chunks)
    assert len(env.vector.chunks) > first_count  # longer text => more chunks
    stored = env.documents.documents[env.document.id]
    assert stored.knowledge_checksum == "changed-456"


async def test_no_content_records_failed_with_reason() -> None:
    """Cleaned content below the threshold is a permanent `InsufficientContent`
    failure surfaced on the dashboard - it is never embedded into junk chunks."""
    env = await _env(content="   \n\n  ")

    result = await env.processor.process_document(env.document.id)

    assert result == {"status": "insufficient_content"}
    assert env.vector.chunks == []
    stored = env.documents.documents[env.document.id]
    assert stored.knowledge_status == KNOWLEDGE_STATUS_FAILED
    assert stored.knowledge_failure_reason == "InsufficientContent: Insufficient content"
    assert any(log.action == AUDIT_KNOWLEDGE_FAILED for log in env.audit.logs)


async def test_thin_content_records_failed_with_reason() -> None:
    """Short but non-empty pages (boilerplate-only) fail permanently instead of
    producing near-empty embeddings."""
    env = await _env(content="Short page")

    result = await env.processor.process_document(env.document.id)

    assert result == {"status": "insufficient_content"}
    stored = env.documents.documents[env.document.id]
    assert stored.knowledge_status == KNOWLEDGE_STATUS_FAILED
    assert stored.processing_status == "failed"
    assert "Insufficient content" in (stored.knowledge_failure_reason or "")


async def test_embedding_failure_records_failed_state_and_audits() -> None:
    env = await _env()

    class FailingEmbedder(FakeEmbeddingClient):
        async def embed(self, texts: list[str]) -> list[list[float]]:
            raise EmbeddingError("boom")

    env.processor = KnowledgeProcessor(
        documents=env.documents,
        vector=env.vector,
        chunks=env.chunks,
        websites=env.websites,
        audit=env.audit,
        embedder=FailingEmbedder(),
        chunk_size=30,
        overlap=5,
    )

    result = await env.processor.process_document(env.document.id)

    assert result["status"] == "failed"
    stored = env.documents.documents[env.document.id]
    assert stored.knowledge_status == KNOWLEDGE_STATUS_FAILED
    assert stored.processing_status == "failed"
    assert stored.knowledge_retry_count == 1
    assert any(log.action == AUDIT_KNOWLEDGE_FAILED for log in env.audit.logs)
    assert env.vector.chunks == []


async def test_forced_rechunk_embedding_failure_preserves_existing_chunks() -> None:
    env = await _env()
    await env.processor.process_document(env.document.id)
    original = list(env.vector.chunks)

    class FailingEmbedder(FakeEmbeddingClient):
        async def embed(self, texts: list[str]) -> list[list[float]]:
            raise EmbeddingError("rate limited")

    processor = KnowledgeProcessor(
        documents=env.documents,
        vector=env.vector,
        chunks=env.chunks,
        websites=env.websites,
        audit=env.audit,
        embedder=FailingEmbedder(),
        chunk_size=30,
        overlap=5,
    )

    result = await processor.process_document(env.document.id, force_rechunk=True)

    assert result["status"] == "failed"
    assert env.vector.chunks == original


async def test_missing_document_is_not_found() -> None:
    env = await _env()
    assert await env.processor.process_document("missing") == {"status": "not_found"}


async def test_skips_when_website_deleted() -> None:
    env = await _env()
    env.website.status = WEBSITE_STATUS_DELETED
    await env.websites.update(env.website)

    result = await env.processor.process_website_documents(
        env.website.id, enqueue=RecordingEnqueue()
    )

    assert result == {"status": "not_found"}


async def test_website_fanout_enqueues_each_document() -> None:
    env = await _env()
    second = Document.new(
        tenant_id="tenant-a",
        website_id=env.website.id,
        url="https://acme.example/about",
        title="About",
        content="About us page content. " * 20,
        checksum="second-1",
    )
    await env.documents.upsert(second)
    enqueue = RecordingEnqueue()

    result = await env.processor.process_website_documents(env.website.id, enqueue=enqueue)

    assert result["status"] == "queued"
    assert result["documents"] == 2
    assert set(enqueue.document_ids) == {env.document.id, second.id}
    website = env.websites.websites[env.website.id]
    assert website.knowledge_status == KNOWLEDGE_STATUS_PROCESSING


async def test_website_fanout_with_no_documents() -> None:
    env = await _env()
    env.documents.documents.clear()

    result = await env.processor.process_website_documents(
        env.website.id, enqueue=RecordingEnqueue()
    )

    assert result == {"status": "no_documents"}


async def test_tenants_are_isolated() -> None:
    env = await _env()
    await env.processor.process_document(env.document.id)

    other = Website.new(tenant_id="tenant-b", name="Other", url="https://other.example/")
    await env.websites.create(other)
    other_doc = Document.new(
        tenant_id="tenant-b",
        website_id=other.id,
        url="https://other.example/",
        title="Other",
        content=TEXT,
        checksum="other-1",
    )
    await env.documents.upsert(other_doc)

    assert await env.chunks.count_by_website("tenant-a", env.website.id) == len(env.vector.chunks)
    assert await env.chunks.count_by_website("tenant-b", other.id) == 0
    assert await env.chunks.count_by_website("tenant-a", other.id) == 0


async def test_embedding_usage_is_reported_through_hook() -> None:
    usages: list = []
    env = await _env()

    class RecordingEmbedder(FakeEmbeddingClient):
        async def embed(self, texts: list[str]) -> list[list[float]]:
            usages.append(sum(len(t) for t in texts))
            return await super().embed(texts)

    env.processor = KnowledgeProcessor(
        documents=env.documents,
        vector=env.vector,
        chunks=env.chunks,
        websites=env.websites,
        audit=env.audit,
        embedder=RecordingEmbedder(),
        chunk_size=30,
        overlap=5,
    )

    await env.processor.process_document(env.document.id)

    assert len(usages) == 1  # single embed call for the whole document
    assert usages[0] > 0


# ---------------------------------------------------------------------------
# Usage rollup tests (Phase 12.3, ADR-005 §5.5)
# ---------------------------------------------------------------------------


async def test_successful_embedding_increments_embeddings_created() -> None:
    """ADR-005 §5.5: every successful embedding counts on the daily rollup."""
    env = await _env()

    result = await env.processor.process_document(env.document.id)

    assert result["status"] == "processed"
    record = env.usage.get_record(env.document.tenant_id, env.website.id, usage_date_key())
    assert record is not None
    assert record.counters["embeddings_created"] == result["chunks"]


async def test_unchanged_document_does_not_increment_embeddings_created() -> None:
    """The incremental skip (checksum match + existing chunks) must not pollute
    the rollup: zero embeddings means zero rollup increments."""
    env = await _env()
    await env.processor.process_document(env.document.id)  # first run increments

    result = await env.processor.process_document(env.document.id)

    assert result == {"status": "unchanged"}
    record = env.usage.get_record(env.document.tenant_id, env.website.id, usage_date_key())
    assert record is not None
    assert record.counters["embeddings_created"] == len(env.vector.chunks)


async def test_embedding_failure_does_not_increment_embeddings_created() -> None:
    """A failing embed must NOT increment the rollup; only success counts."""
    env = await _env()

    class FailingEmbedder(FakeEmbeddingClient):
        async def embed(self, texts: list[str]) -> list[list[float]]:
            raise EmbeddingError("boom")

    env.processor = KnowledgeProcessor(
        documents=env.documents,
        vector=env.vector,
        chunks=env.chunks,
        websites=env.websites,
        audit=env.audit,
        embedder=FailingEmbedder(),
        usage=env.usage,
        chunk_size=30,
        overlap=5,
    )

    await env.processor.process_document(env.document.id)

    record = env.usage.get_record(env.document.tenant_id, env.website.id, usage_date_key())
    assert record is None or record.counters.get("embeddings_created", 0) == 0


async def test_embeddings_created_is_tenant_scoped() -> None:
    """A second tenant's embeddings must roll up under its own tenant_id only."""
    env = await _env()
    await env.processor.process_document(env.document.id)

    other_website = Website.new(tenant_id="tenant-b", name="Other", url="https://other.example/")
    await env.websites.create(other_website)
    other_doc = Document.new(
        tenant_id="tenant-b",
        website_id=other_website.id,
        url="https://other.example/",
        title="Other",
        content=TEXT,
        checksum="other-1",
    )
    await env.documents.upsert(other_doc)

    await env.processor.process_document(other_doc.id)

    tenant_a = env.usage.get_record("tenant-a", env.website.id, usage_date_key())
    tenant_b = env.usage.get_record("tenant-b", other_website.id, usage_date_key())
    assert tenant_a is not None and tenant_b is not None
    assert tenant_a.counters["embeddings_created"] > 0
    assert tenant_b.counters["embeddings_created"] > 0
    # Cross-tenant reads return no record (the unique key scopes by tenant).
    assert env.usage.get_record("tenant-a", other_website.id, usage_date_key()) is None
    assert env.usage.get_record("tenant-b", env.website.id, usage_date_key()) is None


async def test_usage_increment_failure_does_not_fail_processing() -> None:
    """A broken usage repo must not fail the knowledge pipeline (best-effort
    rollups mirror the chat pipeline's `chat_stage("persist.usage")` policy)."""

    class FailingUsage(FakeUsageRecordRepository):
        async def increment(self, **kwargs: object) -> None:  # type: ignore[override]
            raise RuntimeError("mongo down")

    env = await _env()
    env.processor = _processor(env, usage=FailingUsage())

    # process_document must succeed despite the failing usage repo.
    result = await env.processor.process_document(env.document.id)

    assert result["status"] == "processed"
    assert len(env.vector.chunks) == result["chunks"]


# ---------------------------------------------------------------------------
# Document-level retry system (production hardening)
# ---------------------------------------------------------------------------


@dataclass
class RecordingRetry:
    """Records deferred retries instead of touching Redis."""

    scheduled: list[tuple[str, float]] = field(default_factory=list)

    async def __call__(self, document_id: str, delay_seconds: float) -> None:
        self.scheduled.append((document_id, delay_seconds))


def _failing_processor(
    env: Env,
    *,
    error: Exception,
    max_retries: int = 3,
    retry_base_delay_seconds: float = 5.0,
    retry_backoff_factor: float = 6.0,
) -> KnowledgeProcessor:
    class FailingEmbedder(FakeEmbeddingClient):
        async def embed(self, texts: list[str]) -> list[list[float]]:
            raise error

    return KnowledgeProcessor(
        documents=env.documents,
        vector=env.vector,
        chunks=env.chunks,
        websites=env.websites,
        audit=env.audit,
        embedder=FailingEmbedder(),
        usage=env.usage,
        chunk_size=30,
        overlap=5,
        max_retries=max_retries,
        retry_base_delay_seconds=retry_base_delay_seconds,
        retry_backoff_factor=retry_backoff_factor,
    )


async def test_temporary_embedding_failure_schedules_backoff_retry() -> None:
    """A transient embedding error must schedule a deferred re-run with the
    configured backoff delay instead of losing the document permanently."""
    env = await _env()
    retries = RecordingRetry()
    env.processor = _failing_processor(env, error=EmbeddingError("provider timeout"))

    result = await env.processor.process_document(env.document.id, on_retry=retries)

    assert result["status"] == "retry_scheduled"
    assert result["retry_in_seconds"] == 5.0
    assert result["attempt"] == 1
    assert retries.scheduled == [(env.document.id, 5.0)]
    stored = env.documents.documents[env.document.id]
    assert stored.knowledge_status == KNOWLEDGE_STATUS_FAILED
    assert stored.knowledge_retry_count == 1
    assert stored.knowledge_last_attempt_at is not None


async def test_retry_backoff_grows_exponentially() -> None:
    """The backoff schedule follows 5s, 30s, 180s (base * factor**attempt)."""
    env = await _env()
    retries = RecordingRetry()
    env.processor = _failing_processor(env, error=EmbeddingError("provider timeout"))

    for attempt, expected_delay in enumerate((5.0, 30.0, 180.0), start=1):
        result = await env.processor.process_document(env.document.id, on_retry=retries)
        assert result["status"] == "retry_scheduled"
        assert result["retry_in_seconds"] == expected_delay
        assert result["attempt"] == attempt

    assert retries.scheduled == [
        (env.document.id, 5.0),
        (env.document.id, 30.0),
        (env.document.id, 180.0),
    ]
    assert env.documents.documents[env.document.id].knowledge_retry_count == 3


async def test_retries_exhausted_is_permanent_and_does_not_loop_forever() -> None:
    """Once the retry budget is spent the document fails permanently and no
    further retry is scheduled (Case 4: no infinite retry)."""
    env = await _env()
    retries = RecordingRetry()
    env.processor = _failing_processor(env, error=EmbeddingError("provider timeout"), max_retries=2)

    await env.processor.process_document(env.document.id, on_retry=retries)  # attempt 1
    await env.processor.process_document(env.document.id, on_retry=retries)  # attempt 2

    result = await env.processor.process_document(env.document.id, on_retry=retries)

    assert result["status"] == "failed"
    assert result["retryable"] is False
    assert len(retries.scheduled) == 2  # no third retry
    stored = env.documents.documents[env.document.id]
    assert stored.knowledge_status == KNOWLEDGE_STATUS_FAILED
    assert stored.processing_status == "failed"
    assert stored.knowledge_failure_reason is not None


async def test_embedding_unavailable_is_permanent_without_retry() -> None:
    """A configuration error (e.g. missing API key) cannot be fixed by retrying,
    so it fails immediately and never schedules a retry."""
    env = await _env()
    retries = RecordingRetry()
    env.processor = _failing_processor(
        env, error=EmbeddingUnavailableError("GEMINI_API_KEY is not configured")
    )

    result = await env.processor.process_document(env.document.id, on_retry=retries)

    assert result["status"] == "failed"
    assert result["retryable"] is False
    assert retries.scheduled == []
    stored = env.documents.documents[env.document.id]
    assert stored.knowledge_status == KNOWLEDGE_STATUS_FAILED
    assert stored.knowledge_retry_count == 0


async def test_success_after_retry_clears_failure_state() -> None:
    """A document that fails once then succeeds on the retry pass must reset its
    retry accounting so the next outage starts a fresh budget."""
    env = await _env()
    retries = RecordingRetry()

    class FlakyEmbedder(FakeEmbeddingClient):
        def __init__(self) -> None:
            super().__init__()
            self.fail_once = True

        async def embed(self, texts: list[str]) -> list[list[float]]:
            if self.fail_once:
                self.fail_once = False
                raise EmbeddingError("transient")
            return await super().embed(texts)

    env.processor = KnowledgeProcessor(
        documents=env.documents,
        vector=env.vector,
        chunks=env.chunks,
        websites=env.websites,
        audit=env.audit,
        embedder=FlakyEmbedder(),
        usage=env.usage,
        chunk_size=30,
        overlap=5,
    )

    first = await env.processor.process_document(env.document.id, on_retry=retries)
    assert first["status"] == "retry_scheduled"
    assert len(retries.scheduled) == 1

    second = await env.processor.process_document(env.document.id, on_retry=retries)
    assert second["status"] == "processed"

    stored = env.documents.documents[env.document.id]
    assert stored.knowledge_status == KNOWLEDGE_STATUS_READY
    assert stored.knowledge_retry_count == 0
    assert stored.knowledge_failure_reason is None


async def test_retry_returns_failed_without_callback_when_on_retry_missing() -> None:
    """When no retry callback is bound, a temporary failure still records the
    failure and reports `retryable` so callers can decide what to do."""
    env = await _env()
    env.processor = _failing_processor(env, error=EmbeddingError("provider timeout"))

    result = await env.processor.process_document(env.document.id)

    assert result["status"] == "failed"
    assert result["retryable"] is True
    assert env.documents.documents[env.document.id].knowledge_retry_count == 1


async def test_failure_is_logged_with_structured_fields(caplog) -> None:
    """Every failed document must emit a structured record carrying url,
    document_id, website_id, stage, error_type and error_message."""
    import logging

    env = await _env()
    env.processor = _failing_processor(env, error=EmbeddingError("provider timeout"))

    with caplog.at_level(logging.WARNING, logger="webchat_ai"):
        await env.processor.process_document(env.document.id)

    records = [
        r
        for r in caplog.records
        if getattr(r, "document_id", None) == env.document.id
        and "knowledge processing failed" in r.getMessage()
    ]
    assert records, "no structured failure log emitted"
    record = records[0]
    assert record.url == env.document.url
    assert record.website_id == env.website.id
    assert record.stage == "embedding"
    assert record.error_type == "EmbeddingError"
    assert record.error_message == "provider timeout"
    assert record.timestamp is not None


# ---------------------------------------------------------------------------
# Embedding-identity quarantine (audit BUG-1)
# ---------------------------------------------------------------------------


def _legacy_chunk(document: Document, *, provider: str | None, model: str | None) -> KnowledgeChunk:
    return KnowledgeChunk.new(
        tenant_id=document.tenant_id,
        website_id=document.website_id,
        document_id="doc-legacy-other-space",
        chunk_text="chunk embedded in another vector space",
        embedding=[0.5, 0.5, 0.5, 0.5],
        chunk_index=0,
        embedding_provider=provider,
        embedding_model=model,
        embedding_dimensions=4,
        embedding_version="1",
    )


async def test_website_with_foreign_identity_quarantines_ingestion() -> None:
    """A website whose corpus lives in another embedding space must never
    receive chunks from a different identity: the document is quarantined
    (permanent failure) and the existing corpus stays untouched."""
    env = await _env()
    await env.vector.insert_chunks(
        [_legacy_chunk(env.document, provider="jina", model="jina-embeddings-v3")]
    )

    result = await env.processor.process_document(env.document.id)

    assert result["status"] == "failed"
    assert result["retryable"] is False
    assert result["reason"] == "embedding_identity_conflict"
    # Nothing was written or deleted: only the pre-existing foreign chunk remains.
    assert [c.document_id for c in env.vector.chunks] == ["doc-legacy-other-space"]
    stored = env.documents.documents[env.document.id]
    assert stored.knowledge_status == KNOWLEDGE_STATUS_FAILED
    assert stored.knowledge_retry_count == 0  # permanent: no retry budget burned
    assert "EmbeddingIdentityConflict" in (stored.knowledge_failure_reason or "")
    assert any(log.action == AUDIT_KNOWLEDGE_FAILED for log in env.audit.logs)


async def test_matching_identity_processes_normally() -> None:
    """Chunks already stamped with the active embedding identity never block
    ingestion - including this document's own stale chunks on a rebuild."""
    env = await _env()
    await env.processor.process_document(env.document.id)

    env.document.content = TEXT + " Freshly appended sentence. "
    env.document.checksum = "changed-789"
    await env.documents.upsert(env.document)

    result = await env.processor.process_document(env.document.id)

    assert result["status"] == "processed"
    assert all(chunk.embedding_provider == "fake" for chunk in env.vector.chunks)


async def test_legacy_unstamped_chunks_block_ingestion() -> None:
    """Chunks without any identity stamp cannot be proven compatible, so they
    quarantine ingestion instead of silently joining a new embedding space."""
    env = await _env()
    unstamped = _legacy_chunk(env.document, provider=None, model=None)
    unstamped.embedding_dimensions = None
    unstamped.embedding_version = None
    await env.vector.insert_chunks([unstamped])

    result = await env.processor.process_document(env.document.id)

    assert result["reason"] == "embedding_identity_conflict"
    assert [c.document_id for c in env.vector.chunks] == ["doc-legacy-other-space"]


# ---------------------------------------------------------------------------
# Heading metadata (audit R-08) + post-completion cache invalidation (R-03)
# ---------------------------------------------------------------------------


async def test_chunk_metadata_carries_section_heading() -> None:
    env = await _env(content="# Pricing\nAlpha beta. Gamma delta. " * 20)
    await env.processor.process_document(env.document.id)

    stored = env.vector.chunks
    assert stored
    assert all(chunk.metadata.get("heading") == "Pricing" for chunk in stored)


async def test_chunk_metadata_heading_absent_without_headings() -> None:
    env = await _env()
    await env.processor.process_document(env.document.id)

    assert env.vector.chunks
    assert all("heading" not in chunk.metadata for chunk in env.vector.chunks)


class OrderRecordingCache(FakeCacheStore):
    """Appends markers so tests can assert invalidation ordering."""

    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self._events = events

    async def delete_by_prefix(self, namespace: str, prefix: str) -> int:
        self._events.append("delete_by_prefix")
        return await super().delete_by_prefix(namespace, prefix)


class RecordingVectorRepository(FakeVectorRepository):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self._events = events

    async def insert_chunks(self, chunks):  # type: ignore[no-untyped-def]
        self._events.append("insert_chunks")
        return await super().insert_chunks(chunks)


def _processor_with(cache, events, *, website_id: str | None = None):  # type: ignore[no-untyped-def]
    documents = FakeDocumentRepository()
    vector = RecordingVectorRepository(events)
    chunks = FakeKnowledgeChunkRepository(vector=vector)
    websites = FakeWebsiteRepository()
    audit = FakeAuditLogRepository()

    async def build():
        website = Website.new(tenant_id="tenant-a", name="Acme", url="https://acme.example/")
        if website_id is not None:
            website.id = website_id
        await websites.create(website)
        document = Document.new(
            tenant_id="tenant-a",
            website_id=website.id,
            url="https://acme.example/",
            title="Home",
            content=TEXT,
            checksum="abc123",
        )
        await documents.upsert(document)
        processor = KnowledgeProcessor(
            documents=documents,
            vector=vector,
            chunks=chunks,
            websites=websites,
            audit=audit,
            embedder=FakeEmbeddingClient(),
            usage=FakeUsageRecordRepository(),
            chunk_size=30,
            overlap=5,
            cache=cache,
        )
        return processor, document, vector

    return build


async def test_cache_purge_happens_after_chunks_are_stored() -> None:
    """Audit R-03 regression: invalidation must follow successful storage.

    Previously the crawl worker purged the retrieval cache BEFORE embedding,
    so a slow re-index served stale answers repopulated during the window.
    The processor now purges only after `insert_chunks` succeeds.
    """
    events: list[str] = []
    cache = OrderRecordingCache(events)
    build = _processor_with(cache, events)
    processor, document, _vector = await build()

    result = await processor.process_document(document.id)
    assert result["status"] == "processed"
    assert events.index("insert_chunks") < events.index("delete_by_prefix")


async def test_completed_processing_removes_stale_retrieval_entries() -> None:
    """Stale answers seeded before re-processing must not survive it."""
    events: list[str] = []
    cache = FakeCacheStore()
    await cache.set("retrieval", "tenant-a:site-1:old question", '["stale answer"]')
    await cache.set("lexical", "tenant-a:site-1:v1:fake:model:1:1", '{"chunks": []}')
    await cache.set("retrieval", "tenant-a:other-site:q", '["keep"]')

    build = _processor_with(cache, events, website_id="site-1")
    processor, document, _vector = await build()

    result = await processor.process_document(document.id)
    assert result["status"] == "processed"
    assert await cache.get("retrieval", "tenant-a:site-1:old question") is None
    assert await cache.get("lexical", "tenant-a:site-1:v1:fake:model:1:1") is None
    # Only the re-processed website's entries are purged.
    assert await cache.get("retrieval", "tenant-a:other-site:q") == '["keep"]'


async def test_cache_purge_is_best_effort_on_cache_outage() -> None:
    """A broken cache must not fail document processing (same contract as crawl)."""
    events: list[str] = []
    build = _processor_with(FakeBrokenCacheStore(), events)
    processor, document, vector = await build()

    result = await processor.process_document(document.id)
    assert result["status"] == "processed"
    assert vector.chunks


class FailOnInsertVectorRepository(FakeVectorRepository):
    """Vector repo whose `insert_chunks` fails (simulating a transient DB error).

    `replace_by_document` on the base runs insert-first; this forces the insert
    to fail so tests can assert the document is NOT left zeroed out.
    """

    async def insert_chunks(self, chunks):  # type: ignore[no-untyped-def]
        if getattr(self, "fail", False):
            raise EmbeddingError("insert failed (transient)")
        return await super().insert_chunks(chunks)


async def test_replacement_insert_failure_never_zeroes_document() -> None:
    """P1 safe-re-ingestion: a failed insert must not wipe existing chunks.

    Historically the processor deleted a document's chunks BEFORE inserting the
    replacement, so a transient insert failure left the document with zero
    chunks. `replace_by_document` inserts first and deletes stale indexes
    second, so an insert failure leaves the prior corpus intact.
    """
    vector = FailOnInsertVectorRepository()
    chunks = FakeKnowledgeChunkRepository(vector=vector)
    documents = FakeDocumentRepository()
    websites = FakeWebsiteRepository()
    audit = FakeAuditLogRepository()
    embedder = FakeEmbeddingClient()

    website = Website.new(tenant_id="tenant-a", name="Acme", url="https://acme.example/")
    await websites.create(website)
    document = Document.new(
        tenant_id="tenant-a",
        website_id=website.id,
        url="https://acme.example/",
        title="Home",
        content=TEXT,
        checksum="abc123",
    )
    await documents.upsert(document)

    processor = KnowledgeProcessor(
        documents=documents,
        vector=vector,
        chunks=chunks,
        websites=websites,
        audit=audit,
        embedder=embedder,
        chunk_size=30,
        overlap=5,
    )

    # First (successful) pass stores the document's chunks.
    assert (await processor.process_document(document.id))["status"] == "processed"
    old_chunks = vector.by_document(document.tenant_id, document.id)
    assert old_chunks

    # Changing the content and breaking the insert must not zero the doc.
    document.content = TEXT + " New content appended with more words. "
    document.checksum = "changed-456"
    await documents.upsert(document)
    vector.fail = True

    with pytest.raises(EmbeddingError, match="insert failed"):
        await processor.process_document(document.id)

    # The pre-replacement corpus is intact - zero-chunk window is impossible.
    assert len(vector.by_document(document.tenant_id, document.id)) == len(old_chunks)


async def test_replacement_success_replaces_with_only_new_chunks() -> None:
    """On success `replace_by_document` converges to exactly the new chunks."""
    env = await _env()
    await env.processor.process_document(env.document.id)
    old_chunks = env.vector.by_document(env.document.tenant_id, env.document.id)
    assert old_chunks

    env.document.content = TEXT + " New content appended to grow the page. "
    env.document.checksum = "changed-789"
    await env.documents.upsert(env.document)

    result = await env.processor.process_document(env.document.id)

    assert result["status"] == "processed"
    new_chunks = env.vector.by_document(env.document.tenant_id, env.document.id)
    assert new_chunks
    assert len(new_chunks) == result["chunks"]
    # The stored set matches the replacement chunk list exactly - no stale
    # chunks from the old corpus survive the insert-first/delete-stale step.
    stored = {
        (c.chunk_index, c.chunk_text)
        for c in env.vector.by_document(env.document.tenant_id, env.document.id)
    }
    assert stored == {(c.chunk_index, c.chunk_text) for c in new_chunks}


# P1.1 G1: per-document exact normalized-text dedup (bba triple regression).
async def test_dedupe_text_chunks_keeps_unique_normalized_text() -> None:
    """Byte-identical chunks (after normalization) collapse to one instance.

    The overlapping chunker can re-emit the same text on one document (e.g. a
    repeated "Learning Experiences" intro across curriculum tables on a BBA
    course page). Duplication is pure redundancy; the first occurrence in
    document order wins.
    """
    chunks = chunk_text(
        "## Learning Experiences\nAt Indira University, the BBA program offers "
        "an immersive learning journey with industry-relevant exposure. " * 8,
        chunk_size=30,
        overlap=5,
    )
    counts = Counter(c.text for c in chunks)
    raw_extra = sum(max(0, n - 1) for n in counts.values())
    assert raw_extra > 0, "test fixture must actually produce duplicate chunks"

    deduped = _dedupe_text_chunks(chunks)
    keys = {" ".join((c.text or "").split()).lower() for c in deduped}
    # Every stored chunk has a distinct normalized text.
    assert len(keys) == len(deduped)
    # The first occurrence survives (position 0 of every duplicate run).
    first_occurrence = []
    seen = set()
    for c in chunks:
        key = " ".join((c.text or "").split()).lower()
        if key not in seen:
            seen.add(key)
            first_occurrence.append(c.text)
    assert [c.text for c in deduped] == first_occurrence


async def test_dedup_collapses_bba_style_triple_before_replacement() -> None:
    """End-to-end: a document whose chunker emits an identical triple stores 1.

    Mirrors the P1 dry-run finding on `course/bba-banking-and-financial-services`,
    where a repeated "Learning Experiences" intro produced three byte-identical
    chunks. Dedup must run before embedding/replacement so the replacement set
    ends with no exact-duplicate normalized text, while preserving insert-first
    safety.
    """
    env = await _env(
        content="## Learning Experiences\nAt Indira University, the BBA program "
        "offers not just academic knowledge but an immersive learning journey "
        "that blends theory with real-world applications for our students. " * 8,
    )

    result = await env.processor.process_document(env.document.id)

    assert result["status"] == "processed"
    stored = env.vector.by_document(env.document.tenant_id, env.document.id)
    assert stored
    assert len(stored) == result["chunks"]
    norm = {" ".join((c.chunk_text or "").split()).lower() for c in stored}
    # No two stored chunks may share normalized text (G1: 0 exact-dup extras).
    assert len(norm) == len(stored)
