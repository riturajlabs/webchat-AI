"""Knowledge-processing management business logic (production hardening).

`KnowledgeService` backs the dashboard's per-document status surface and the
manual retry action. It is read-mostly: the heavy work runs in the ARQ
`process_document` worker; this service only lists processing states and
re-enqueues a failed document. Every lookup is tenant-scoped by the
caller-provided `tenant_id` (00-AI-Development-Rules §7).
"""

from collections.abc import Awaitable, Callable

from backend.core.errors import DocumentNotFoundError, WebsiteNotFoundError
from backend.core.security import utcnow
from backend.models.audit_log import AUDIT_KNOWLEDGE_RETRIED, AuditLog
from backend.models.document import Document
from backend.models.knowledge_chunk import KNOWLEDGE_STATUS_PROCESSING
from backend.repositories import AuditLogRepository, DocumentRepository, WebsiteRepository
from backend.services.auth import Principal

EnqueueFn = Callable[[str], Awaitable[None]]


class KnowledgeService:
    """Encapsulates the knowledge document-management workflows (tenant-scoped)."""

    def __init__(
        self,
        *,
        websites: WebsiteRepository,
        documents: DocumentRepository,
        audit: AuditLogRepository,
        enqueue: EnqueueFn,
    ) -> None:
        self._websites = websites
        self._documents = documents
        self._audit = audit
        self._enqueue = enqueue

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
        await self._audit_create(principal, ip_address, user_agent)
        return document

    async def _audit_create(
        self,
        principal: Principal,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        # Audited as best-effort: an audit-log outage must not fail a retry.
        try:
            await self._audit.create(
                AuditLog.new(
                    action=AUDIT_KNOWLEDGE_RETRIED,
                    tenant_id=principal.tenant_id,
                    user_id=principal.user_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
            )
        except Exception:  # noqa: BLE001 - best-effort auditing
            pass
