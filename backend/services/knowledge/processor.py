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
from typing import Any, cast

from backend.core.config import get_settings
from backend.core.embedding_identity import EmbeddingIdentity
from backend.core.errors import (
    EmbeddingError,
    EmbeddingRateLimitedError,
    EmbeddingUnavailableError,
    ProviderConfigurationError,
)
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
    KNOWLEDGE_STATUS_RATE_LIMITED,
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
# Resolves the per-website locked embedding provider for an ingestion.
# Returns the `EmbeddingClient` whose `embedding_identity` is (or becomes) the
# website's persistent lock; raises when the locked provider is unavailable.
ProviderResolver = Callable[[Website], Awaitable[EmbeddingClient]]

INSUFFICIENT_CONTENT_REASON = "Insufficient content"


def _dedupe_text_chunks(text_chunks: list[TextChunk]) -> list[TextChunk]:
    """Return `text_chunks` with exact (normalized-text) duplicates removed.

    Two chunks are treated as duplicates when their text is identical after
    lowercasing and collapsing whitespace. The first occurrence in document
    order is retained; later identical copies are dropped. Deterministic and
    pure (no IO), so it can run before embedding without disturbing the
    insert-first safety of `replace_by_document`.
    """
    seen: set[str] = set()
    deduped: list[TextChunk] = []
    for chunk in text_chunks:
        key = " ".join((chunk.text or "").split()).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(chunk)
    return deduped


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
        provider_resolver: ProviderResolver | None = None,
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
        # Per-website provider lock resolver (provider consistency). When set,
        # every fan-out and per-document pass resolves the website's locked
        # embedding provider through it; otherwise the single injected
        # `embedder` is used (backward-compatible single-provider behavior).
        self._provider_resolver = provider_resolver

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
        # Provider-lock the website BEFORE fanning out (provider consistency):
        # resolve the locked (or newly health-selected) embedding provider and
        # persist its identity as the website's ingestion lock so every
        # document and retry of this pass uses the SAME embedding space. If the
        # provider cannot be resolved we stop here - never switch, never fan out
        # into a mixed embedding space.
        if self._provider_resolver is not None:
            embedder = await self._resolve_embedder(website)
            acquired = await self._acquire_embedding_run(website, embedder)
            if acquired is None:
                return {"status": "already_processing"}
            website = acquired
            # Keep the existing public identity fields in sync for retrieval
            # compatibility while the run record fences worker writes.
            await self._persist_ingestion_lock(website, embedder)
        website.knowledge_status = KNOWLEDGE_STATUS_PROCESSING
        website.updated_at = utcnow()
        await self._websites.update(website)
        run_id = website.embedding_run.id if website.embedding_run is not None else None
        for document in documents:
            await self._enqueue_document(enqueue, document.id, run_id)
        return {"status": "queued", "documents": len(documents), "run_id": run_id}

    async def process_document(
        self,
        document_id: str,
        *,
        on_retry: RetryFn | None = None,
        run_id: str | None = None,
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
        if run_id is not None:
            active_run = website.embedding_run
            if active_run is None or active_run.id != run_id or active_run.state != "running":
                return {"status": "stale_job", "run_id": run_id}

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
        # P1.1 G1: drop byte-identical (after normalization) chunks within a
        # single document before embedding/replacement. The overlapping chunker
        # can emit the same text more than once (e.g. a "Learning Experiences"
        # intro repeated across curriculum tables on one course page); storing
        # each copy is pure redundancy. Keeping only the first occurrence in
        # document order preserves the source's logical sequence and keeps the
        # vectors list aligned with the stored chunk list.
        text_chunks = _dedupe_text_chunks(text_chunks)
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

            embedder = await self._resolve_embedder(website)
            vectors = await embedder.embed([text_chunk.text for text_chunk in text_chunks])
            embedding_identity = embedder.embedding_identity
            # Record the provider used for this document as the website's
            # ingestion lock (idempotent - re-resolving the same provider is a
            # no-op), so every document/retry of this website stays in one space.
            await self._persist_ingestion_lock(website, embedder)
        except ProviderConfigurationError as exc:
            # The website is locked to an embedding provider that is no longer
            # available (key removed / provider disabled). Switching would move
            # this document into a different embedding space, corrupting the
            # corpus, so fail permanently instead of silently changing provider.
            await self._record_failure(
                document,
                website,
                stage="embedding",
                error_type="EmbeddingProviderLocked",
                error_message=str(exc),
                permanent=True,
                audit=True,
            )
            return {"status": "failed", "retryable": False, "reason": str(exc)}
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
        except EmbeddingRateLimitedError as exc:
            # Provider quota/rate-limit rejection (429): the client already
            # retried with Retry-After/backoff (ING-02). Still retry at the
            # document level with exponential backoff, but record the document
            # as `rate_limited` (non-terminal, awaiting deferred retry) so the
            # dashboard can distinguish it from a permanently failed document
            # (Part E).
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
                status=KNOWLEDGE_STATUS_RATE_LIMITED,
            )
            if on_retry is None:
                return {"status": "failed", "retryable": True, "reason": str(exc)}
            await self._schedule_retry(on_retry, document_id, delay, run_id)
            return {
                "status": "retry_scheduled",
                "retry_in_seconds": delay,
                "attempt": retries_used + 1,
            }
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
            await self._schedule_retry(on_retry, document_id, delay, run_id)
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
        await self._vector.replace_by_document(document.tenant_id, document.id, chunks)

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
        await self._invalidate_retrieval_cache(document.tenant_id, document.website_id)
        return {"status": "processed", "chunks": len(chunks)}

    async def _resolve_embedder(self, website: Website) -> EmbeddingClient:
        """Resolve the embedding provider locked to `website`.

        Uses the injected `provider_resolver` when one is configured (the
        worker binds a resolver that forces the website's persisted lock and
        health-selects/persists a fresh one when none exists). Without a
        resolver this falls back to the single injected `embedder`
        (backward-compatible behavior). A resolver that cannot honor the lock
        raises `ProviderConfigurationError` - the caller treats it as a
        permanent failure rather than switching providers.
        """
        if self._provider_resolver is None:
            return self._embedder
        return await self._provider_resolver(website)

    async def _acquire_embedding_run(
        self, website: Website, embedder: EmbeddingClient
    ) -> Website | None:
        """Acquire the repository's atomic run fence when it is available."""
        acquire = getattr(self._websites, "acquire_embedding_run", None)
        if acquire is None:
            # Backward-compatible test/custom repository path. Production's
            # Mongo repository always implements the atomic operation.
            return website
        typed_acquire = cast(
            Callable[[str, str, EmbeddingIdentity], Awaitable[Website | None]], acquire
        )
        return await typed_acquire(website.tenant_id, website.id, embedder.embedding_identity)

    @staticmethod
    async def _enqueue_document(enqueue: EnqueueFn, document_id: str, run_id: str | None) -> None:
        """Pass the fence token, retaining one-argument test integrations."""
        if run_id is None:
            await enqueue(document_id)
            return
        try:
            await enqueue(document_id, run_id)  # type: ignore[call-arg]
        except TypeError:
            await enqueue(document_id)

    @staticmethod
    async def _schedule_retry(
        on_retry: RetryFn, document_id: str, delay: float, run_id: str | None
    ) -> None:
        if run_id is None:
            await on_retry(document_id, delay)
            return
        try:
            await on_retry(document_id, delay, run_id)  # type: ignore[call-arg]
        except TypeError:
            await on_retry(document_id, delay)

    async def _persist_ingestion_lock(self, website: Website, embedder: EmbeddingClient) -> None:
        """Record `embedder`'s identity as the website's ingestion provider lock.

        Idempotent: if the website is already locked to the same provider/model/
        dimensions/version this is a no-op (no DB write). The lock is what keeps
        every document and retry of a website's ingestion in ONE embedding space.
        """
        identity = embedder.embedding_identity
        if (
            website.ingestion_embedding_provider == identity.provider
            and website.ingestion_embedding_model == identity.model
            and website.ingestion_embedding_dimensions == identity.dimensions
            and website.ingestion_embedding_version == identity.version
        ):
            return
        website.ingestion_embedding_provider = identity.provider
        website.ingestion_embedding_model = identity.model
        website.ingestion_embedding_dimensions = identity.dimensions
        website.ingestion_embedding_version = identity.version
        website.updated_at = utcnow()
        await self._websites.update(website)

    async def _invalidate_retrieval_cache(self, tenant_id: str, website_id: str) -> None:
        """Best-effort retrieval-cache invalidation after successful processing."""
        if self._cache is None:
            return
        try:
            prefix = f"{tenant_id}:{website_id}:"
            await self._cache.delete_by_prefix("retrieval", prefix)
            await self._cache.delete_by_prefix("lexical", prefix)
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
        status: str | None = None,
    ) -> None:
        """Record a failed embedding pass on the document.

        `permanent=True` keeps the current retry count (the document will not
        be retried automatically); `permanent=False` increments the retry count
        so the next pass computes the next backoff delay. `status` overrides the
        stored knowledge status (default `failed`); the rate-limited path passes
        `KNOWLEDGE_STATUS_RATE_LIMITED` so a doc awaiting a deferred retry is
        distinguishable from a permanently failed one (Part E).
        """
        if not permanent:
            document.knowledge_retry_count += 1
        document.knowledge_status = status or KNOWLEDGE_STATUS_FAILED
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
