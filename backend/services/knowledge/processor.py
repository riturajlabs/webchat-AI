"""Knowledge processing orchestration (Phase 5, ADR-008).

`KnowledgeProcessor` turns a crawled `Document` into embedded `knowledge_chunks`
via: checksum compare (incremental) -> token chunking -> embedding -> replace
stale chunks -> update website/dashboard statistics. It depends on the
`VectorRepository` and `EmbeddingClient` Protocols only, so tests inject fakes
and no Google SDK or Mongo import leaks into this core.

Incremental rule (docs/06 Phase 5): when a document's content checksum is
unchanged and it already has chunks, embedding is skipped entirely. When the
content changed, the old chunks are deleted and rebuilt.

Failure handling (production hardening): embedding failures are classified
permanent vs temporary. Temporary failures (generic `EmbeddingError` from
timeouts/rate limits/provider errors) are retried at the document level with an
exponential backoff schedule (5s, 30s, 180s by default); a retry re-enqueues
the document through the injected `on_retry` callback (the ARQ worker binds a
deferred job). Permanent failures (missing API key, insufficient content,
retries exhausted) land in the dashboard's failed list with a reason and can be
re-processed manually via the retry endpoint. Every failure is logged as a
structured record carrying the document's URL, ids, stage, error type and
message so the exact failure point is traceable.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from backend.core.config import get_settings
from backend.core.embedding_identity import EmbeddingIdentity
from backend.core.errors import EmbeddingError, EmbeddingUnavailableError
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
from backend.models.usage_record import USAGE_COUNTER_EMBEDDINGS_CREATED, usage_date_key
from backend.models.website import WEBSITE_STATUS_DELETED, Website
from backend.repositories.usage_record_repository import UsageRecordRepository
from backend.services.knowledge.chunker import TextChunk, chunk_text
from backend.services.knowledge.embedding import EmbeddingClient

logger = logging.getLogger("webchat_ai")

EnqueueFn = Callable[[str], Awaitable[None]]
# `(document_id, delay_seconds)` -> schedules a deferred re-processing pass.
RetryFn = Callable[[str, float], Awaitable[None]]

INSUFFICIENT_CONTENT_REASON = "Insufficient content"


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
        usage: UsageRecordRepository | None = None,
        cache: Any = None,
        chunk_size: int | None = None,
        overlap: int | None = None,
        max_retries: int | None = None,
        retry_base_delay_seconds: float | None = None,
        retry_backoff_factor: float | None = None,
        min_content_chars: int | None = None,
    ) -> None:
        settings = get_settings()
        self._documents = documents
        self._vector = vector
        self._chunks = chunks
        self._websites = websites
        self._audit = audit
        self._embedder = embedder
        self._usage = usage
        # Audit R-03: optional CacheStore used to invalidate retrieval answers
        # AFTER new chunks are stored (post-completion invalidation).
        self._cache = cache
        self._chunk_size = chunk_size
        self._overlap = overlap
        self._max_retries = (
            max_retries if max_retries is not None else settings.knowledge_max_document_retries
        )
        self._retry_base_delay = (
            retry_base_delay_seconds
            if retry_base_delay_seconds is not None
            else settings.knowledge_retry_base_delay_seconds
        )
        self._retry_backoff_factor = (
            retry_backoff_factor
            if retry_backoff_factor is not None
            else settings.knowledge_retry_backoff_factor
        )
        self._min_content_chars = (
            min_content_chars
            if min_content_chars is not None
            else settings.knowledge_min_content_chars
        )

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

    async def process_document(
        self,
        document_id: str,
        *,
        on_retry: RetryFn | None = None,
    ) -> dict[str, Any]:
        """Embed one document into the knowledge base (idempotent).

        Skips embedding when the document is unchanged (checksum match + chunks
        already stored); otherwise deletes stale chunks and rebuilds them.
        Returns a structured result; temporary embedding failures schedule a
        document-level retry through `on_retry` when retries remain.

        Audit R-03: when processing completes successfully, the website's
        retrieval cache is invalidated AFTER the new chunks are stored - an
        answer cached from the old corpus mid-reindex cannot outlive the
        completed reindex. Best-effort: a cache outage never fails processing.
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

        document.knowledge_status = KNOWLEDGE_STATUS_PROCESSING
        document.knowledge_last_attempt_at = utcnow()
        await self._documents.upsert(document)

        if len(document.content.strip()) < self._min_content_chars:
            # Nothing meaningful to embed: drop stale chunks and record a
            # permanent failure the dashboard can show and the owner can retry
            # once real content lands (a re-crawl replaces the document).
            await self._vector.delete_by_document(document.tenant_id, document.id)
            await self._record_failure(
                document,
                website,
                stage="chunk",
                error_type="InsufficientContent",
                error_message=INSUFFICIENT_CONTENT_REASON,
                permanent=True,
                audit=True,
            )
            return {"status": "insufficient_content"}

        text_chunks = chunk_text(
            document.content,
            chunk_size=self._chunk_size,
            overlap=self._overlap,
        )
        try:
            if not text_chunks:
                # Content stripped to nothing by the chunker: permanent failure.
                await self._vector.delete_by_document(document.tenant_id, document.id)
                await self._record_failure(
                    document,
                    website,
                    stage="chunk",
                    error_type="InsufficientContent",
                    error_message=INSUFFICIENT_CONTENT_REASON,
                    permanent=True,
                    audit=True,
                )
                return {"status": "insufficient_content"}

            vectors = await self._embedder.embed([text_chunk.text for text_chunk in text_chunks])
            embedding_identity = self._embedder.embedding_identity
        except EmbeddingUnavailableError as exc:
            # Configuration error (e.g. missing API key): retrying cannot fix
            # it, so fail the document permanently and surface the reason.
            await self._record_failure(
                document,
                website,
                stage="embedding",
                error_type=type(exc).__name__,
                error_message=str(exc),
                permanent=True,
                audit=True,
            )
            return {"status": "failed", "retryable": False, "reason": str(exc)}
        except EmbeddingError as exc:
            # Temporary provider failure (timeout/rate limit/provider error
            # after the client's own batch retries). Retry at the document
            # level with exponential backoff until the budget is exhausted.
            retries_used = document.knowledge_retry_count
            if retries_used >= self._max_retries:
                await self._record_failure(
                    document,
                    website,
                    stage="embedding",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    permanent=True,
                    audit=True,
                )
                return {"status": "failed", "retryable": False, "reason": str(exc)}

            delay = self._retry_base_delay * (self._retry_backoff_factor**retries_used)
            await self._record_failure(
                document,
                website,
                stage="embedding",
                error_type=type(exc).__name__,
                error_message=str(exc),
                permanent=False,
                audit=True,
            )
            if on_retry is None:
                return {"status": "failed", "retryable": True, "reason": str(exc)}
            await on_retry(document_id, delay)
            return {
                "status": "retry_scheduled",
                "retry_in_seconds": delay,
                "attempt": retries_used + 1,
            }

        # Changed (or first run): replace old chunks with freshly embedded ones.
        chunks = self._build_chunks(document, text_chunks, vectors, embedding_identity)
        if await self._chunks.has_incompatible_identity(
            document.tenant_id, document.website_id, embedding_identity
        ):
            # BUG-1 guard: the website corpus lives in another embedding space.
            # Storing these chunks would create mixed identities and hide one
            # of them from every identity-filtered `$vectorSearch`. Quarantine
            # instead: keep the existing corpus untouched and fail permanently
            # (retrying cannot fix an identity conflict; re-index the website).
            await self._record_failure(
                document,
                website,
                stage="embedding",
                error_type="EmbeddingIdentityConflict",
                error_message=(
                    "Website already contains knowledge chunks with a different "
                    f"embedding identity than {embedding_identity.provider}/"
                    f"{embedding_identity.model}; refusing to store mixed "
                    "embedding spaces. Re-index the website with one consistent "
                    "embedding provider."
                ),
                permanent=True,
                audit=True,
            )
            return {
                "status": "failed",
                "retryable": False,
                "reason": "embedding_identity_conflict",
            }
        await self._vector.delete_by_document(document.tenant_id, document.id)
        await self._vector.insert_chunks(chunks)

        # ADR-005 §5.5: count every successful embedding on the daily usage
        # rollup. Best-effort: a usage-tracking outage must never fail the
        # pipeline (chat pipeline applies the same principle).
        await self._record_embeddings_created(
            tenant_id=document.tenant_id,
            website_id=document.website_id,
            count=len(chunks),
        )

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
        # Audit R-03: the new corpus is fully stored - drop any retrieval
        # answers cached from the previous corpus while this document was
        # re-processing, so stale entries cannot survive a completed reindex.
        await self._invalidate_retrieval_cache(document.website_id)
        return {"status": "processed", "chunks": len(chunks)}

    async def _invalidate_retrieval_cache(self, website_id: str) -> None:
        """Best-effort retrieval-cache invalidation after successful processing."""
        if self._cache is None:
            return
        try:
            await self._cache.delete_by_prefix("retrieval", f"{website_id}:")
        except Exception:  # noqa: BLE001 - cache outage must not fail processing
            logger.warning(
                "Failed to invalidate retrieval cache for website %s after processing",
                website_id,
                exc_info=True,
            )

    def _build_chunks(
        self,
        document: Document,
        text_chunks: list[TextChunk],
        vectors: list[list[float]],
        embedding_identity: EmbeddingIdentity,
    ) -> list[KnowledgeChunk]:
        base_metadata: dict[str, Any] = {
            "source_url": document.url,
            "title": document.title,
            "document_id": document.id,
            "tenant_id": document.tenant_id,
            "website_id": document.website_id,
            "language": document.language,
        }
        chunks: list[KnowledgeChunk] = []
        for i in range(len(text_chunks)):
            metadata = dict(base_metadata)
            # Audit R-08: carry the nearest heading into chunk metadata. The
            # prompt's ContextItem already renders it; this only connects the
            # existing field - the chunk schema itself is unchanged.
            if text_chunks[i].heading:
                metadata["heading"] = text_chunks[i].heading
            chunks.append(
                KnowledgeChunk.new(
                    tenant_id=document.tenant_id,
                    website_id=document.website_id,
                    document_id=document.id,
                    chunk_text=text_chunks[i].text,
                    embedding=vectors[i],
                    chunk_index=text_chunks[i].index,
                    metadata=metadata,
                    embedding_provider=embedding_identity.provider,
                    embedding_model=embedding_identity.model,
                    embedding_dimensions=embedding_identity.dimensions,
                    embedding_version=embedding_identity.version,
                )
            )
        return chunks

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
            # A successful pass clears prior failure state (attempt accounting).
            document.knowledge_failure_reason = None
            document.knowledge_retry_count = 0
        document.updated_at = utcnow()
        # Persist knowledge state on the shared document (upsert is idempotent).
        await self._documents.upsert(document)

    async def _record_failure(
        self,
        document: Document,
        website: Website,
        *,
        stage: str,
        error_type: str,
        error_message: str,
        permanent: bool,
        audit: bool,
    ) -> None:
        """Record a failed embedding pass on the document.

        `permanent=True` keeps the current retry count (the document will not
        be retried automatically); `permanent=False` increments the retry count
        so the next pass computes the next backoff delay.
        """
        if not permanent:
            document.knowledge_retry_count += 1
        document.knowledge_status = KNOWLEDGE_STATUS_FAILED
        document.knowledge_failure_reason = f"{error_type}: {error_message}"
        document.knowledge_checksum = document.knowledge_checksum or document.checksum
        document.updated_at = utcnow()
        await self._documents.upsert(document)
        await self._refresh_website(website)
        if audit:
            await self._audit.create(
                AuditLog.new(action=AUDIT_KNOWLEDGE_FAILED, tenant_id=document.tenant_id)
            )
        self._log_failure(document, stage=stage, error_type=error_type, error_message=error_message)

    @staticmethod
    def _log_failure(
        document: Document,
        *,
        stage: str,
        error_type: str,
        error_message: str,
    ) -> None:
        """Structured per-document failure record (00-AI-Development-Rules §17).

        The JSON formatter merges the `extra` payload into each log line so
        ops can group failures by url/error_type/stage without parsing message
        text. The development formatter ignores `extra`, which is fine.
        """
        logger.warning(
            "knowledge processing failed: %s",
            error_message,
            extra={
                "timestamp": utcnow().isoformat(),
                "url": document.url,
                "document_id": document.id,
                "website_id": document.website_id,
                "tenant_id": document.tenant_id,
                "stage": stage,
                "error_type": error_type,
                "error_message": error_message,
                "retry_count": document.knowledge_retry_count,
            },
        )

    async def _refresh_website(self, website: Website) -> None:
        """Recompute and persist dashboard knowledge statistics for a website."""
        website.knowledge_chunks = await self._chunks.count_by_website(
            website.tenant_id, website.id
        )
        website.knowledge_documents = await self._chunks.count_documents_by_website(
            website.tenant_id, website.id
        )
        if website.knowledge_chunks > 0:
            website.knowledge_status = KNOWLEDGE_STATUS_READY
        elif (
            website.knowledge_status != KNOWLEDGE_STATUS_PROCESSING
            and await self._documents.count_failed_by_website(website.tenant_id, website.id) > 0
        ):
            # Not mid-fan-out and every embeddable page failed: surface the
            # failure at the website level instead of leaving it stuck in
            # `processing` forever (dashboard visibility).
            website.knowledge_status = KNOWLEDGE_STATUS_FAILED
        elif (
            website.knowledge_status == KNOWLEDGE_STATUS_PROCESSING
            and await self._documents.count_non_terminal_by_website(website.tenant_id, website.id)
            == 0
            and await self._documents.count_failed_by_website(website.tenant_id, website.id) > 0
        ):
            # The fan-out has drained and every page failed: the website is
            # done (nothing left processing) and should read `failed`.
            website.knowledge_status = KNOWLEDGE_STATUS_FAILED
        website.last_knowledge_at = utcnow()
        website.updated_at = utcnow()
        await self._websites.update(website)

    async def _record_embeddings_created(
        self,
        *,
        tenant_id: str,
        website_id: str,
        count: int,
    ) -> None:
        """Increment the daily `embeddings_created` counter.

        Best-effort: a usage-tracking outage must never fail the knowledge
        pipeline, so any exception from the rollup repo is logged and dropped
        (mirrors the chat pipeline's `chat_stage("persist.usage")` policy).
        """
        if self._usage is None or count <= 0:
            return
        try:
            await self._usage.increment(
                tenant_id=tenant_id,
                website_id=website_id,
                date=usage_date_key(),
                counters={USAGE_COUNTER_EMBEDDINGS_CREATED: count},
            )
        except Exception as exc:  # noqa: BLE001 - best-effort usage tracking
            logger.warning(
                "usage rollup increment failed (counter=embeddings_created): %s",
                exc,
            )


__all__ = ["KnowledgeProcessor"]
