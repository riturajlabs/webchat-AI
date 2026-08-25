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
from typing import Any

from arq.connections import ArqRedis
from redis.asyncio import ConnectionPool

from backend.core.config import get_settings
from backend.core.database import MongoDB
from backend.repositories import (
    MongoAuditLogRepository,
    MongoDocumentRepository,
    MongoKnowledgeChunkRepository,
    MongoUsageRecordRepository,
    MongoWebsiteRepository,
)
from backend.repositories.vector import get_vector_repository
from backend.services.knowledge.embedding import EmbeddingClient, GoogleEmbeddingClient
from backend.services.knowledge.processor import KnowledgeProcessor

logger = logging.getLogger("webchat_ai")

_pool: ConnectionPool | None = None


def _arq_redis() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(get_settings().redis_url, decode_responses=True)
    return ArqRedis(connection_pool=_pool)


async def enqueue_process_document(document_id: str) -> None:
    """Enqueue a per-document embedding job (ADR-002 task registry)."""
    await _arq_redis().enqueue_job("process_document", document_id)


async def enqueue_process_document_deferred(document_id: str, delay_seconds: float) -> None:
    """Enqueue a per-document embedding job after a backoff delay.

    ARQ deferred jobs live in a Redis zset and only become runnable after
    `_defer_by` seconds, so the exponential document-level retry schedule
    survives worker restarts and never blocks a worker slot while sleeping.
    """
    await _arq_redis().enqueue_job("process_document", document_id, _defer_by=delay_seconds)


async def enqueue_process_website_documents(website_id: str) -> None:
    """Enqueue a whole-website knowledge pass."""
    await _arq_redis().enqueue_job("process_website_documents", website_id)


def _build_cache() -> Any:
    """Build the retrieval CacheStore (same namespace convention as crawl).

    Audit R-03: the API writes retrieval answers under
    `{redis_prefix}:rag:...`, so invalidation after successful processing must
    target that exact namespace. Best-effort: a Redis outage disables only the
    post-processing invalidation, never embedding itself.
    """
    try:
        from redis.asyncio import Redis as _Redis

        from backend.core.cache import RedisCacheStore

        redis = _Redis.from_url(get_settings().redis_url, decode_responses=True)
        return RedisCacheStore(redis, prefix=f"{get_settings().redis_prefix}:rag")
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
    )


def _embedder(ctx: dict[str, Any]) -> EmbeddingClient:
    """Worker-injected embedding client; production default is the Google SDK."""
    return ctx.get("embedding_client") or GoogleEmbeddingClient()


async def process_document(ctx: dict[str, Any], document_id: str) -> dict[str, Any]:
    """Worker task: embed one document (registered in tasks.TASKS).

    Temporary embedding failures are retried at the document level: the
    processor schedules a deferred re-run with exponential backoff instead of
    letting the job fail, so a transient provider outage cannot permanently
    fail an entire crawl fan-out.
    """
    processor = _processor(ctx, _embedder(ctx))
    return await _run_process_document(
        ctx, document_id, processor, on_retry=enqueue_process_document_deferred
    )


async def _run_process_document(
    ctx: dict[str, Any],
    document_id: str,
    processor: KnowledgeProcessor,
    on_retry: Any = None,
) -> dict[str, Any]:
    """Core logic, testable with an injected fake-backed processor."""
    return await processor.process_document(document_id, on_retry=on_retry)


async def process_website_documents(ctx: dict[str, Any], website_id: str) -> dict[str, Any]:
    """Worker task: fan a website's documents out as per-document jobs."""
    return await _run_process_website(ctx, website_id, _processor(ctx, _embedder(ctx)))


async def _run_process_website(
    ctx: dict[str, Any], website_id: str, processor: KnowledgeProcessor
) -> dict[str, Any]:
    return await processor.process_website_documents(website_id, enqueue=enqueue_process_document)


__all__ = [
    "enqueue_process_document",
    "enqueue_process_website_documents",
    "process_document",
    "process_website_documents",
]
