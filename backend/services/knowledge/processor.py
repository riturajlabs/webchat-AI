"""Knowledge processing orchestration (Phase 5, ADR-008).

`KnowledgeProcessor` turns a crawled `Document` into embedded `knowledge_chunks`
via: checksum compare (incremental) -> token chunking -> embedding -> replace
stale chunks -> update website/dashboard statistics. It depends on the
`VectorRepository` and `EmbeddingClient` Protocols only, so tests inject fakes
and no Google SDK or Mongo import leaks into this core.

Incremental rule (docs/06 Phase 5): when a document's content checksum is
unchanged and it already has chunks, embedding is skipped entirely. When the
content changed, the old chunks are deleted and rebuilt.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from backend.core.errors import EmbeddingError
from backend.core.security import utcnow
from backend.models.audit_log import (
    AUDIT_KNOWLEDGE_FAILED,
    AUDIT_KNOWLEDGE_PROCESSED,
    AuditLog,
)
from backend.models.document import Document
from backend.models.knowledge_chunk import (
    KNOWLEDGE_STATUS_FAILED,
    KNOWLEDGE_STATUS_PROCESSING,
    KNOWLEDGE_STATUS_READY,
    KnowledgeChunk,
)
from backend.models.website import WEBSITE_STATUS_DELETED, Website
from backend.services.knowledge.chunker import TextChunk, chunk_text
from backend.services.knowledge.embedding import EmbeddingClient

EnqueueFn = Callable[[str], Awaitable[None]]


class KnowledgeProcessor:
    """Encapsulates every knowledge-processing workflow (tenant-scoped)."""

    def __init__(
        self,
        *,
        documents: Any,
        vector: Any,
        chunks: Any,
        websites: Any,
        audit: Any,
        embedder: EmbeddingClient,
        chunk_size: int | None = None,
        overlap: int | None = None,
    ) -> None:
        self._documents = documents
        self._vector = vector
        self._chunks = chunks
        self._websites = websites
        self._audit = audit
        self._embedder = embedder
        self._chunk_size = chunk_size
        self._overlap = overlap

    async def process_website_documents(
        self, website_id: str, *, enqueue: EnqueueFn
    ) -> dict[str, Any]:
        """Fan a website's documents out as per-document worker jobs.

        Returns queued counts; the heavy lifting runs in `process_document`.
        """
        website = await self._websites.find_by_id_any(website_id)
        if website is None or website.status == WEBSITE_STATUS_DELETED:
            return {"status": "not_found"}
        documents = await self._documents.list_by_website(website.tenant_id, website_id)
        if not documents:
            return {"status": "no_documents"}
        website.knowledge_status = KNOWLEDGE_STATUS_PROCESSING
        website.updated_at = utcnow()
        await self._websites.update(website)
        for document in documents:
            await enqueue(document.id)
        return {"status": "queued", "documents": len(documents)}

    async def process_document(self, document_id: str) -> dict[str, Any]:
        """Embed one document into the knowledge base (idempotent).

        Skips embedding when the document is unchanged (checksum match + chunks
        already stored); otherwise deletes stale chunks and rebuilds them.
        """
        document = await self._documents.find_by_id_any(document_id)
        if document is None:
            return {"status": "not_found"}
        website = await self._websites.find_by_id(document.tenant_id, document.website_id)
        if website is None:
            return {"status": "skipped", "reason": "website_missing"}

        existing_chunks = await self._chunks.count_by_document(document.tenant_id, document.id)
        if document.knowledge_checksum == document.checksum and existing_chunks > 0:
            return {"status": "unchanged"}

        text_chunks = chunk_text(
            document.content,
            chunk_size=self._chunk_size,
            overlap=self._overlap,
        )
        try:
            if not text_chunks:
                # Nothing embeddable (empty page): drop stale chunks and record
                # a clean "processed with no content" state.
                await self._vector.delete_by_document(document.tenant_id, document.id)
                await self._record_document(
                    document,
                    status=KNOWLEDGE_STATUS_READY,
                    checksum=document.checksum,
                    chunks=0,
                )
                await self._refresh_website(website)
                return {"status": "no_content"}

            vectors = await self._embedder.embed([text_chunk.text for text_chunk in text_chunks])
        except EmbeddingError:
            await self._record_document(
                document,
                status=KNOWLEDGE_STATUS_FAILED,
                checksum=document.knowledge_checksum,
                chunks=existing_chunks,
            )
            await self._refresh_website(website)
            await self._audit.create(
                AuditLog.new(action=AUDIT_KNOWLEDGE_FAILED, tenant_id=document.tenant_id)
            )
            raise

        # Changed (or first run): replace old chunks with freshly embedded ones.
        chunks = self._build_chunks(document, text_chunks, vectors)
        await self._vector.delete_by_document(document.tenant_id, document.id)
        await self._vector.insert_chunks(chunks)

        await self._record_document(
            document,
            status=KNOWLEDGE_STATUS_READY,
            checksum=document.checksum,
            chunks=len(chunks),
        )
        await self._refresh_website(website)
        await self._audit.create(
            AuditLog.new(action=AUDIT_KNOWLEDGE_PROCESSED, tenant_id=document.tenant_id)
        )
        return {"status": "processed", "chunks": len(chunks)}

    def _build_chunks(
        self,
        document: Document,
        text_chunks: list[TextChunk],
        vectors: list[list[float]],
    ) -> list[KnowledgeChunk]:
        metadata: dict[str, Any] = {
            "source_url": document.url,
            "title": document.title,
            "document_id": document.id,
            "tenant_id": document.tenant_id,
            "website_id": document.website_id,
            "language": document.language,
        }
        return [
            KnowledgeChunk.new(
                tenant_id=document.tenant_id,
                website_id=document.website_id,
                document_id=document.id,
                chunk_text=text_chunks[i].text,
                embedding=vectors[i],
                chunk_index=text_chunks[i].index,
                metadata=metadata,
            )
            for i in range(len(text_chunks))
        ]

    async def _record_document(
        self,
        document: Document,
        *,
        status: str,
        checksum: str | None,
        chunks: int,
    ) -> None:
        document.knowledge_status = status
        document.knowledge_checksum = checksum
        document.knowledge_chunks = chunks
        if status == KNOWLEDGE_STATUS_READY:
            document.knowledge_processed_at = utcnow()
        document.updated_at = utcnow()
        # Persist knowledge state on the shared document (upsert is idempotent).
        await self._documents.upsert(document)

    async def _refresh_website(self, website: Website) -> None:
        """Recompute and persist dashboard knowledge statistics for a website."""
        website.knowledge_chunks = await self._chunks.count_by_website(
            website.tenant_id, website.id
        )
        website.knowledge_documents = await self._chunks.count_documents_by_website(
            website.tenant_id, website.id
        )
        website.knowledge_status = (
            KNOWLEDGE_STATUS_READY if website.knowledge_chunks > 0 else website.knowledge_status
        )
        website.last_knowledge_at = utcnow()
        website.updated_at = utcnow()
        await self._websites.update(website)


__all__ = ["KnowledgeProcessor"]
