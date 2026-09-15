"""Knowledge-processing management business logic (production hardening).

`KnowledgeService` backs the dashboard's per-document status surface, manual retry,
direct file uploads, and document deletion/downloads. Every lookup and mutation
is tenant-scoped by the caller-provided `tenant_id` (00-AI-Development-Rules §7).
"""

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from backend.core.cache import CacheStore
from backend.core.errors import (
    AppError,
    DocumentNotFoundError,
    DocumentTooLargeError,
    DuplicateFileError,
    NotAFileError,
    StorageError,
    WebsiteNotFoundError,
)
from backend.core.security import new_id, utcnow
from backend.models.audit_log import (
    AUDIT_KNOWLEDGE_DELETED,
    AUDIT_KNOWLEDGE_RETRIED,
    AUDIT_KNOWLEDGE_UPLOADED,
    AuditLog,
)
from backend.models.document import (
    DOCUMENT_STATUS_READY,
    SOURCE_TYPE_FILE,
    Document,
)
from backend.models.knowledge_chunk import (
    KNOWLEDGE_STATUS_PENDING,
    KNOWLEDGE_STATUS_PROCESSING,
)
from backend.repositories import (
    AuditLogRepository,
    DocumentRepository,
    WebsiteRepository,
)
from backend.repositories.vector.base import VectorRepository
from backend.services.auth import Principal
from backend.services.billing.usage_service import UsageService
from backend.services.ingestion.file_extractor import extract_text_from_file
from backend.services.storage.base import StorageService

logger = logging.getLogger("webchat_ai")

EnqueueFn = Callable[[str], Awaitable[None]]

MAX_FILES_PER_BATCH = 5
MAX_BATCH_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


class KnowledgeService:
    """Encapsulates the knowledge document-management workflows (tenant-scoped)."""

    def __init__(
        self,
        *,
        websites: WebsiteRepository,
        documents: DocumentRepository,
        audit: AuditLogRepository,
        enqueue: EnqueueFn,
        storage: StorageService | None = None,
        vector: VectorRepository | None = None,
        usage: UsageService | None = None,
        cache: CacheStore | None = None,
    ) -> None:
        self._websites = websites
        self._documents = documents
        self._audit = audit
        self._enqueue = enqueue
        self._storage = storage
        self._vector = vector
        self._usage = usage
        self._cache = cache

    async def list_documents(self, tenant_id: str, website_id: str) -> list[Document]:
        """Return every document of a tenant-owned website, newest stored first."""
        website = await self._websites.find_by_id(tenant_id, website_id)
        if website is None:
            raise WebsiteNotFoundError("Website not found.")
        documents = await self._documents.list_by_website(tenant_id, website_id)
        return sorted(documents, key=lambda document: document.created_at, reverse=True)

    async def retry_document(
        self,
        *,
        principal: Principal,
        document_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> Document:
        """Reset a failed document and re-queue it for embedding.

        Tenancy is resolved from the authenticated principal - a document that
        does not belong to the tenant is reported as missing (never leaks its
        existence to another tenant). The retry starts a fresh attempt budget.
        """
        document = await self._documents.find_by_id(principal.tenant_id, document_id)
        if document is None:
            raise DocumentNotFoundError("Document not found.")

        document.knowledge_status = KNOWLEDGE_STATUS_PROCESSING
        document.knowledge_retry_count = 0
        document.knowledge_failure_reason = None
        document.knowledge_last_attempt_at = utcnow()
        document.updated_at = utcnow()
        await self._documents.upsert(document)
        await self._enqueue(document.id)
        await self._audit_create_action(
            principal=principal,
            action=AUDIT_KNOWLEDGE_RETRIED,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return document

    async def upload_files(
        self,
        *,
        principal: Principal,
        website_id: str,
        files: list[tuple[str, bytes, str | None]],
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> list[Document]:
        """Validate, extract, store, and enqueue uploaded knowledge files.

        Enforces tenant isolation, plan document limits, batch size limits,
        and duplicate detection.
        """
        website = await self._websites.find_by_id(principal.tenant_id, website_id)
        if website is None:
            raise WebsiteNotFoundError("Website not found.")

        if not files:
            raise AppError("No files provided for upload.")
        if len(files) > MAX_FILES_PER_BATCH:
            raise AppError(f"Maximum of {MAX_FILES_PER_BATCH} files allowed per upload batch.")

        total_batch_size = sum(len(content) for _, content, _ in files)
        if total_batch_size > MAX_BATCH_SIZE_BYTES:
            raise DocumentTooLargeError("Total upload batch size exceeds 10 MB limit.")

        if self._usage is not None:
            await self._usage.check_limit(
                principal.tenant_id, event_type="documents", quantity=len(files)
            )

        # Check in-batch duplicate binary checksums
        batch_hashes: set[str] = set()
        for filename, content, _ in files:
            file_sha256 = hashlib.sha256(content).hexdigest()
            if file_sha256 in batch_hashes:
                raise DuplicateFileError(
                    f"Duplicate file '{filename}' detected in the same upload batch."
                )
            batch_hashes.add(file_sha256)

        # Check existing website duplicate binary checksums
        for filename, content, _ in files:
            file_sha256 = hashlib.sha256(content).hexdigest()
            existing = await self._documents.find_by_file_checksum(
                principal.tenant_id, website_id, file_sha256
            )
            if existing is not None:
                raise DuplicateFileError(
                    f"File '{filename}' has already been uploaded for this website."
                )

        created_docs: list[Document] = []
        for filename, content, mime_type in files:
            safe_filename = Path(filename).name.strip()
            if not safe_filename:
                raise AppError("Invalid filename provided.")

            extracted = await asyncio.to_thread(
                extract_text_from_file, safe_filename, content, mime_type
            )

            doc_id = new_id()
            storage_key: str | None = None
            if self._storage is not None:
                storage_key = await self._storage.upload(
                    tenant_id=principal.tenant_id,
                    website_id=website_id,
                    document_id=doc_id,
                    filename=safe_filename,
                    content=content,
                    mime_type=extracted.mime_type,
                )

            text_checksum = hashlib.sha256(extracted.text.encode("utf-8")).hexdigest()
            file_sha256 = hashlib.sha256(content).hexdigest()

            doc = Document.new(
                tenant_id=principal.tenant_id,
                website_id=website_id,
                url=f"file://upload/{doc_id}/{safe_filename}",
                title=safe_filename,
                content=extracted.text,
                checksum=text_checksum,
                source_type=SOURCE_TYPE_FILE,
                file_name=safe_filename,
                file_size_bytes=len(content),
                mime_type=extracted.mime_type,
                storage_key=storage_key,
                file_checksum_sha256=file_sha256,
            )
            doc.id = doc_id
            doc.status = DOCUMENT_STATUS_READY
            doc.knowledge_status = KNOWLEDGE_STATUS_PENDING

            await self._documents.upsert(doc)
            await self._enqueue(doc.id)
            created_docs.append(doc)

        for _doc in created_docs:
            await self._audit_create_action(
                principal=principal,
                action=AUDIT_KNOWLEDGE_UPLOADED,
                ip_address=ip_address,
                user_agent=user_agent,
            )

        return created_docs

    async def delete_document(
        self,
        *,
        principal: Principal,
        document_id: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Document:
        """Permanently delete a document, its vector chunks, and raw storage binary."""
        doc = await self._documents.find_by_id(principal.tenant_id, document_id)
        if doc is None:
            raise DocumentNotFoundError("Document not found.")

        # 1. Delete chunks from vector repository
        if self._vector is not None:
            await self._vector.delete_by_document(principal.tenant_id, document_id)

        # 2. Delete raw file from storage if applicable
        if getattr(doc, "source_type", None) == SOURCE_TYPE_FILE and doc.storage_key:
            if self._storage is not None:
                await self._storage.delete(
                    tenant_id=principal.tenant_id,
                    storage_key=doc.storage_key,
                )

        # 3. Delete from documents repository
        await self._documents.delete_by_ids(principal.tenant_id, [document_id])

        # 4. Invalidate retrieval cache for the website
        if self._cache is not None:
            try:
                prefix = f"{principal.tenant_id}:{doc.website_id}:"
                await self._cache.delete_by_prefix("retrieval", prefix)
                await self._cache.delete_by_prefix("lexical", prefix)
            except Exception:
                pass

        # 5. Audit
        await self._audit_create_action(
            principal=principal,
            action=AUDIT_KNOWLEDGE_DELETED,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        return doc

    async def get_document_file(
        self,
        *,
        principal: Principal,
        document_id: str,
    ) -> tuple[Document, bytes]:
        """Download raw binary content for a stored document file."""
        doc = await self._documents.find_by_id(principal.tenant_id, document_id)
        if doc is None:
            raise DocumentNotFoundError("Document not found.")

        if getattr(doc, "source_type", None) != SOURCE_TYPE_FILE or not doc.storage_key:
            raise NotAFileError("Document has no downloadable file attachment.")

        if self._storage is None:
            raise StorageError("Storage service is not configured.")

        content = await self._storage.download(
            tenant_id=principal.tenant_id,
            storage_key=doc.storage_key,
        )
        return doc, content

    async def _audit_create_action(
        self,
        *,
        principal: Principal,
        action: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        try:
            await self._audit.create(
                AuditLog.new(
                    action=action,
                    tenant_id=principal.tenant_id,
                    user_id=principal.user_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
            )
        except Exception:  # noqa: BLE001 - best-effort auditing
            pass
