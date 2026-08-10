"""Tests for `KnowledgeProcessor` (Phase 5, ADR-008).

The processor depends only on Protocols, so every test binds in-memory fakes:
FakeDocumentRepository, FakeVectorRepository, FakeKnowledgeChunkRepository,
FakeWebsiteRepository, FakeAuditLogRepository and FakeEmbeddingClient.
"""

from dataclasses import dataclass, field

import pytest
from backend.core.errors import EmbeddingError
from backend.models.audit_log import AUDIT_KNOWLEDGE_FAILED, AUDIT_KNOWLEDGE_PROCESSED
from backend.models.document import Document
from backend.models.knowledge_chunk import (
    KNOWLEDGE_STATUS_FAILED,
    KNOWLEDGE_STATUS_PROCESSING,
    KNOWLEDGE_STATUS_READY,
)
from backend.models.website import WEBSITE_STATUS_DELETED, Website
from backend.services.knowledge.processor import KnowledgeProcessor
from tests.fakes import (
    FakeAuditLogRepository,
    FakeDocumentRepository,
    FakeEmbeddingClient,
    FakeKnowledgeChunkRepository,
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
) -> KnowledgeProcessor:
    return KnowledgeProcessor(
        documents=env.documents,
        vector=env.vector,
        chunks=env.chunks,
        websites=env.websites,
        audit=env.audit,
        embedder=env.embedder,
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
    env = Env(documents, vector, chunks, websites, audit, embedder, website, document, None)
    env.processor = _processor(env)
    return env


async def test_embeds_document_and_updates_stats() -> None:
    env = await _env()

    result = await env.processor.process_document(env.document.id)

    assert result["status"] == "processed"
    assert result["chunks"] > 0
    assert len(env.vector.chunks) == result["chunks"]
    assert all(chunk.tenant_id == "tenant-a" for chunk in env.vector.chunks)
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


async def test_no_content_records_ready_with_zero_chunks() -> None:
    env = await _env(content="   \n\n  ")

    result = await env.processor.process_document(env.document.id)

    assert result == {"status": "no_content"}
    assert env.vector.chunks == []
    stored = env.documents.documents[env.document.id]
    assert stored.knowledge_status == KNOWLEDGE_STATUS_READY
    assert stored.knowledge_chunks == 0
    assert stored.knowledge_checksum == "abc123"


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

    with pytest.raises(EmbeddingError):
        await env.processor.process_document(env.document.id)

    stored = env.documents.documents[env.document.id]
    assert stored.knowledge_status == KNOWLEDGE_STATUS_FAILED
    assert any(log.action == AUDIT_KNOWLEDGE_FAILED for log in env.audit.logs)
    assert env.vector.chunks == []


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

    assert result == {"status": "queued", "documents": 2}
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
