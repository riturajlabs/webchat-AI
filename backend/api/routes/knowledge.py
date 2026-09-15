"""Knowledge document management endpoints (production hardening).

The dashboard reads per-document processing status (pending/processing/
completed/failed), failure reasons and retry accounting, triggers manual
re-processing of failed documents, uploads knowledge files, and downloads/deletes
documents. Tenancy comes from the authenticated principal - a foreign tenant can
never read, mutate, or retry another tenant's documents (00-AI-Development-Rules §7).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile

from backend.api.deps import (
    client_ip,
    current_user,
    get_knowledge_service,
    require_role,
    upload_limiter,
    website_limiter,
)
from backend.core.errors import AppError, DocumentTooLargeError
from backend.schemas.knowledge import (
    DocumentDeleteResponse,
    DocumentProcessingOut,
    DocumentStatusSummary,
    DocumentUploadItemOut,
    KnowledgeDocumentsResponse,
    KnowledgeUploadResponse,
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
    "/websites/{website_id}/documents/upload",
    response_model=KnowledgeUploadResponse,
    status_code=201,
)
async def upload_knowledge_documents(
    website_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
    files: Annotated[list[UploadFile], File()],
    _: Annotated[None, Depends(upload_limiter)] = None,
) -> KnowledgeUploadResponse:
    """Upload up to 5 document files (.txt, .md, .pdf, .docx) to a website's knowledge base."""
    if not files:
        raise AppError("No files provided for upload.")
    if len(files) > 5:
        raise AppError("Maximum of 5 files allowed per upload batch.")

    file_payloads: list[tuple[str, bytes, str | None]] = []
    total_batch_size = 0
    max_file_size = 10 * 1024 * 1024  # 10 MB

    for file in files:
        content = await file.read()
        if len(content) > max_file_size:
            raise DocumentTooLargeError(
                f"File '{file.filename}' exceeds maximum allowed size of 10 MB."
            )
        total_batch_size += len(content)
        if total_batch_size > max_file_size:
            raise DocumentTooLargeError("Total upload batch size exceeds 10 MB limit.")
        filename = file.filename or "document"
        file_payloads.append((filename, content, file.content_type))

    docs = await service.upload_files(
        principal=principal,
        website_id=website_id,
        files=file_payloads,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    return KnowledgeUploadResponse(
        website_id=website_id,
        uploaded=[
            DocumentUploadItemOut(
                id=doc.id,
                website_id=doc.website_id,
                file_name=doc.file_name or doc.title,
                file_size_bytes=doc.file_size_bytes or len(doc.content.encode("utf-8")),
                mime_type=doc.mime_type or "text/plain",
                status=doc.processing_status,
                char_count=len(doc.content),
            )
            for doc in docs
        ],
    )


@router.delete(
    "/documents/{document_id}",
    response_model=DocumentDeleteResponse,
)
async def delete_knowledge_document(
    document_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
    _: Annotated[None, Depends(website_limiter)],
) -> DocumentDeleteResponse:
    """Permanently delete a document, its vector chunks, and any storage attachment."""
    doc = await service.delete_document(
        principal=principal,
        document_id=document_id,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return DocumentDeleteResponse(
        document_id=doc.id,
        website_id=doc.website_id,
        deleted=True,
    )


@router.get("/documents/{document_id}/download")
async def download_knowledge_document(
    document_id: str,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
    _: Annotated[None, Depends(website_limiter)],
) -> Response:
    """Download the raw file attachment for an uploaded knowledge document."""
    doc, content = await service.get_document_file(
        principal=principal,
        document_id=document_id,
    )
    safe_filename = (doc.file_name or "download").replace('"', '\\"')
    return Response(
        content=content,
        media_type=doc.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
            "Content-Length": str(len(content)),
        },
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
