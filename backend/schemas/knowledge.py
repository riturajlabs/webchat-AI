"""Pydantic v2 request/response schemas for the knowledge-processing API.

The per-document surface exposes the pipeline's `pending`/`processing`/
`completed`/`failed` statuses plus retry accounting so the dashboard can render
failed-document visibility, direct file upload status, and a manual retry action.
"""

from datetime import datetime

from pydantic import BaseModel

from backend.models.document import Document


class DocumentProcessingOut(BaseModel):
    """Dashboard-facing shape for one crawled document or uploaded file."""

    id: str
    website_id: str
    url: str
    title: str
    status: str
    failure_reason: str | None
    retry_count: int
    last_attempt_at: datetime | None
    chunks: int
    source_type: str = "website"
    file_name: str | None = None
    file_size_bytes: int | None = None
    mime_type: str | None = None

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
            source_type=getattr(document, "source_type", "website") or "website",
            file_name=getattr(document, "file_name", None),
            file_size_bytes=getattr(document, "file_size_bytes", None),
            mime_type=getattr(document, "mime_type", None),
        )


class DocumentUploadItemOut(BaseModel):
    """Dashboard-facing shape for an uploaded file document."""

    id: str
    website_id: str
    file_name: str
    file_size_bytes: int
    mime_type: str
    status: str
    char_count: int
    pages: int | None = None


class KnowledgeUploadResponse(BaseModel):
    """Response returned upon successfully uploading file attachments."""

    website_id: str
    uploaded: list[DocumentUploadItemOut]


class DocumentDeleteResponse(BaseModel):
    """Response returned upon deleting a document."""

    document_id: str
    website_id: str
    deleted: bool


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
