"""Knowledge document management endpoints (production hardening).

The dashboard reads per-document processing status (pending/processing/
completed/failed), failure reasons and retry accounting, and triggers manual
re-processing of failed documents. Tenancy comes from the authenticated
principal - a foreign tenant can never read or retry another tenant's
documents (00-AI-Development-Rules §7).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from backend.api.deps import (
    client_ip,
    current_user,
    get_knowledge_service,
    require_role,
    website_limiter,
)
from backend.schemas.knowledge import (
    DocumentProcessingOut,
    DocumentStatusSummary,
    KnowledgeDocumentsResponse,
    RetryDocumentResponse,
)
from backend.services.auth import Principal
from backend.services.knowledge import KnowledgeService

router = APIRouter(
    prefix="/knowledge",
    tags=["knowledge"],
    dependencies=[Depends(require_role("owner", "admin"))],
)


@router.get("/websites/{website_id}/documents", response_model=KnowledgeDocumentsResponse)
async def list_knowledge_documents(
    website_id: str,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
    _: Annotated[None, Depends(website_limiter)],
) -> KnowledgeDocumentsResponse:
    documents = await service.list_documents(principal.tenant_id, website_id)
    summary = DocumentStatusSummary(
        total=len(documents),
        pending=sum(1 for doc in documents if doc.processing_status == "pending"),
        processing=sum(1 for doc in documents if doc.processing_status == "processing"),
        completed=sum(1 for doc in documents if doc.processing_status == "completed"),
        failed=sum(1 for doc in documents if doc.processing_status == "failed"),
        rate_limited=sum(1 for doc in documents if doc.processing_status == "rate_limited"),
    )
    return KnowledgeDocumentsResponse(
        website_id=website_id,
        summary=summary,
        documents=[DocumentProcessingOut.from_document(doc) for doc in documents],
    )


@router.post(
    "/documents/{document_id}/retry",
    response_model=RetryDocumentResponse,
    status_code=202,
)
async def retry_knowledge_document(
    document_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
    _: Annotated[None, Depends(website_limiter)],
) -> RetryDocumentResponse:
    """Reset a failed document and re-queue it for embedding (manual retry)."""
    document = await service.retry_document(
        principal=principal,
        document_id=document_id,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return RetryDocumentResponse(
        document_id=document.id,
        website_id=document.website_id,
        status=document.processing_status,
    )
