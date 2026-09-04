"""Pydantic v2 request/response schemas for the knowledge-processing API.

The per-document surface exposes the pipeline's `pending`/`processing`/
`completed`/`failed` statuses plus retry accounting so the dashboard can render
failed-document visibility and a manual retry action (production hardening).
"""

from datetime import datetime

from pydantic import BaseModel

from backend.models.document import Document


class DocumentProcessingOut(BaseModel):
    """Dashboard-facing shape for one crawled document's processing state."""

    id: str
    website_id: str
    url: str
    title: str
    status: str
    failure_reason: str | None
    retry_count: int
    last_attempt_at: datetime | None
    chunks: int

    @classmethod
    def from_document(cls, document: Document) -> "DocumentProcessingOut":
        return cls(
            id=document.id,
            website_id=document.website_id,
            url=document.url,
            title=document.title,
            status=document.processing_status,
            failure_reason=document.knowledge_failure_reason,
            retry_count=document.knowledge_retry_count,
            last_attempt_at=document.knowledge_last_attempt_at,
            chunks=document.knowledge_chunks,
        )


class DocumentStatusSummary(BaseModel):
    """Aggregate processing-state counts for a website's documents."""

    total: int
    pending: int
    processing: int
    completed: int
    failed: int
    # Documents awaiting a deferred retry after provider quota/rate-limit
    # rejection (Part E/ING-02): non-terminal, rendered separately from failed.
    rate_limited: int = 0


class KnowledgeDocumentsResponse(BaseModel):
    website_id: str
    summary: DocumentStatusSummary
    documents: list[DocumentProcessingOut]


class RetryDocumentResponse(BaseModel):
    document_id: str
    website_id: str
    status: str
