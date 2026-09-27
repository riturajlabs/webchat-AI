"""ARQ knowledge-processing jobs (Phase 5, ADR-002).

`process_document(document_id)` embeds one crawled document into the knowledge
base (chunking -> embedding -> vector store, with incremental checksum skip).
`process_website_documents(website_id)` fans a website's documents out as one
`process_document` job each. Both are registered in `backend.workers.tasks`.

The heavy logic lives in `KnowledgeProcessor`; these tasks only bind it to the
MongoDB-backed repositories (injectable fakes for tests, mirroring the crawl
job pattern).
"""

import logging
import random
from typing import Any

from arq.connections import ArqRedis
from redis.asyncio import ConnectionPool

from backend.ai.registry import select_ingestion_embedding_provider
from backend.core.config import get_settings
from backend.core.database import MongoDB
from backend.core.redis import get_redis
from backend.models.website import Website
from backend.queue.child import resolve_child_queue, resolve_child_tenant
from backend.repositories import (
    MongoAuditLogRepository,
    MongoDocumentRepository,
    MongoKnowledgeChunkRepository,
    MongoUsageRecordRepository,
    MongoWebsiteRepository,
)
from backend.repositories.vector import get_vector_repository
from backend.services.ai.provider_health import ProviderHealthStore
from backend.services.knowledge.embedding import EmbeddingClient, GoogleEmbeddingClient
from backend.services.knowledge.processor import KnowledgeProcessor
from backend.workers.jobs.log_context import request_context, reset_context

logger = logging.getLogger("webchat_ai")

_pool: ConnectionPool | None = None


def _arq_redis() -> ArqRedis:
    """The ARQ/Redis client, for API-process enqueues only.

    Phase 17B: a job that is *executing* on a queue must enqueue its children
    through :mod:`backend.queue.child` so they follow the parent's backend. This
    helper has no job context, so it is only correct for the API process (where
    ARQ is the production default). The worker tasks below no longer call it.
    """
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(get_settings().redis_url, decode_responses=True)
    return ArqRedis(connection_pool=_pool)


def _child_enqueue(ctx: dict[str, Any]) -> Any:
    """Build the ``(document_id, run_id) -> None`` enqueue callback for a job.

    The callback the processor receives now routes through the queue the parent
    is executing on. Under ARQ (production today) this resolves to
    :class:`ArqQueueAdapter` and reproduces today's call exactly; under the
    Mongo loop it enqueues onto Mongo.
    """
    queue = resolve_child_queue(ctx)
    tenant_id = resolve_child_tenant(ctx)

    # `run_id` defaults to None because `KnowledgeProcessor._enqueue_document`
    # deliberately calls the callback with ONE argument when there is no run
    # (it also tolerates 1-arg test doubles via a TypeError fallback). A
    # required second parameter here would turn a no-run fan-out into a crash.
    async def enqueue(document_id: str, run_id: str | None = None) -> None:
        await queue.enqueue(
            "process_document",
            payload={"document_id": document_id, "run_id": run_id},
            tenant_id=tenant_id,
        )

    return enqueue


def _child_enqueue_deferred(ctx: dict[str, Any]) -> Any:
    """Deferred (backoff) variant of :func:`_child_enqueue`, same backend rule.

    ARQ expresses the delay with ``_defer_by``; the Mongo adapter maps the same
    value onto its own ``run_at``. A retry therefore stays on the parent's
    backend under either consumer.
    """
    queue = resolve_child_queue(ctx)
    tenant_id = resolve_child_tenant(ctx)

    async def enqueue(
        document_id: str, delay_seconds: float, run_id: str | None = None
    ) -> None:
        await queue.enqueue(
            "process_document",
            payload={"document_id": document_id, "run_id": run_id},
            tenant_id=tenant_id,
            defer_by=delay_seconds,
        )

    return enqueue


async def enqueue_process_document(document_id: str, run_id: str | None = None) -> None:
    """Enqueue a per-document embedding job (ADR-002 task registry).

    API-process entry point: no job context, so this is ARQ, exactly as before
    Phase 17B. Jobs that fan out from inside the worker use
    :func:`_child_enqueue` instead.
    """
    await _arq_redis().enqueue_job("process_document", document_id, run_id)


async def enqueue_process_document_deferred(
    document_id: str, delay_seconds: float, run_id: str | None = None
) -> None:
    """Enqueue a per-document embedding job after a backoff delay.

    ARQ deferred jobs live in a Redis zset and only become runnable after
    `_defer_by` seconds, so the exponential document-level retry schedule
    survives worker restarts and never blocks a worker slot while sleeping.
    """
    await _arq_redis().enqueue_job("process_document", document_id, run_id, _defer_by=delay_seconds)


async def enqueue_process_website_documents(website_id: str) -> None:
    """Enqueue a whole-website knowledge pass."""
    await _arq_redis().enqueue_job("process_website_documents", website_id)


def _build_cache() -> Any:
    """Build the retrieval CacheStore (same namespace convention as crawl).

    Uses the shared singleton Redis client from ``core.redis`` so worker
    connections are pooled and closed on shutdown.  Best-effort: a Redis
    outage disables only the post-processing invalidation, never embedding
    itself.
    """
    try:
        from backend.core.cache import RedisCacheStore

        return RedisCacheStore(get_redis(), prefix=f"{get_settings().redis_prefix}:rag")
    except Exception:
        logger.warning("Could not build cache for knowledge invalidation", exc_info=True)
        return None


def _processor(ctx: dict[str, Any], embedder: EmbeddingClient) -> KnowledgeProcessor:
    db = MongoDB.db()
    return KnowledgeProcessor(
        documents=MongoDocumentRepository(db),
        vector=get_vector_repository(db),
        chunks=MongoKnowledgeChunkRepository(db),
        websites=MongoWebsiteRepository(db),
        audit=MongoAuditLogRepository(db),
        embedder=embedder,
        usage=MongoUsageRecordRepository(db),
        cache=ctx.get("retrieval_cache") or _build_cache(),
        provider_resolver=lambda website: _resolve_ingestion_provider(
            website, health=ctx.get("embedding_provider_health")
        ),
    )


async def _resolve_ingestion_provider(
    website: Website, *, health: ProviderHealthStore | None = None
) -> EmbeddingClient:
    """Resolve the embedding provider locked to `website` (provider consistency).

    If the website already carries a persisted ingestion lock, exactly that
    provider is forced - a retry resumes in the SAME embedding space and never
    silently switches to another provider. Without a lock (first ingestion),
    the configured providers are health-checked and the first healthy one is
    selected; the processor then persists it as the website's lock.

    A website locked to a provider that is no longer configured/available
    raises `ProviderConfigurationError`; the processor records that document as
    a permanent failure rather than switching to a different embedding space.
    """
    locked = website.embedding_identity
    return await select_ingestion_embedding_provider(
        force_provider=locked.provider if locked is not None else None, health=health
    )


def _embedder(ctx: dict[str, Any]) -> EmbeddingClient:
    """Worker-injected embedding client; production default is the Google SDK."""
    return ctx.get("embedding_client") or GoogleEmbeddingClient()


async def process_document(
    ctx: dict[str, Any], document_id: str, run_id: str | None = None
) -> dict[str, Any]:
    """Worker task: embed one document (registered in tasks.TASKS).

    Temporary embedding failures are retried at the document level: the
    processor schedules a deferred re-run with exponential backoff instead of
    letting the job fail, so a transient provider outage cannot permanently
    fail an entire crawl fan-out.
    """
    request_token, tenant_token = request_context(ctx)
    try:
        processor = _processor(ctx, _embedder(ctx))

        enqueue_retry = _child_enqueue_deferred(ctx)

        async def retry(document: str, delay: float, retry_run_id: str | None = run_id) -> None:
            # Full jitter avoids a quota-recovery thundering herd while retaining
            # the same fenced run/provider identity for every retry. Phase 17B:
            # the retry is enqueued through the parent's queue, not Redis.
            await enqueue_retry(document, random.uniform(0, delay), retry_run_id)

        return await _run_process_document(
            ctx, document_id, processor, on_retry=retry, run_id=run_id
        )
    finally:
        reset_context(request_token, tenant_token)


async def _run_process_document(
    ctx: dict[str, Any],
    document_id: str,
    processor: KnowledgeProcessor,
    on_retry: Any = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Core logic, testable with an injected fake-backed processor."""
    if run_id is None:
        return await processor.process_document(document_id, on_retry=on_retry)
    return await processor.process_document(document_id, on_retry=on_retry, run_id=run_id)


async def process_website_documents(ctx: dict[str, Any], website_id: str) -> dict[str, Any]:
    """Worker task: fan a website's documents out as per-document jobs."""
    request_token, tenant_token = request_context(ctx)
    try:
        return await _run_process_website(ctx, website_id, _processor(ctx, _embedder(ctx)))
    finally:
        reset_context(request_token, tenant_token)


async def _run_process_website(
    ctx: dict[str, Any], website_id: str, processor: KnowledgeProcessor
) -> dict[str, Any]:
    # Phase 17B: children follow the parent's backend. Under ARQ this is the
    # identical `enqueue_process_document` call production makes today.
    return await processor.process_website_documents(
        website_id, enqueue=_child_enqueue(ctx)
    )


__all__ = [
    "enqueue_process_document",
    "enqueue_process_website_documents",
    "process_document",
    "process_website_documents",
]
