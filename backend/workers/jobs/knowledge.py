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


async def enqueue_process_website_documents(website_id: str) -> None:
    """Enqueue a whole-website knowledge pass."""
    await _arq_redis().enqueue_job("process_website_documents", website_id)


def _processor(ctx: dict[str, Any], embedder: EmbeddingClient) -> KnowledgeProcessor:
    db = MongoDB.db()
    return KnowledgeProcessor(
        documents=MongoDocumentRepository(db),
        vector=get_vector_repository(db),
        chunks=MongoKnowledgeChunkRepository(db),
        websites=MongoWebsiteRepository(db),
        audit=MongoAuditLogRepository(db),
        embedder=embedder,
    )


def _embedder(ctx: dict[str, Any]) -> EmbeddingClient:
    """Worker-injected embedding client; production default is the Google SDK."""
    return ctx.get("embedding_client") or GoogleEmbeddingClient()


async def process_document(ctx: dict[str, Any], document_id: str) -> dict[str, Any]:
    """Worker task: embed one document (registered in tasks.TASKS)."""
    return await _run_process_document(ctx, document_id, _processor(ctx, _embedder(ctx)))


async def _run_process_document(
    ctx: dict[str, Any], document_id: str, processor: KnowledgeProcessor
) -> dict[str, Any]:
    """Core logic, testable with an injected fake-backed processor."""
    return await processor.process_document(document_id)


async def process_website_documents(
    ctx: dict[str, Any], website_id: str
) -> dict[str, Any]:
    """Worker task: fan a website's documents out as per-document jobs."""
    return await _run_process_website(
        ctx, website_id, _processor(ctx, _embedder(ctx))
    )


async def _run_process_website(
    ctx: dict[str, Any], website_id: str, processor: KnowledgeProcessor
) -> dict[str, Any]:
    return await processor.process_website_documents(
        website_id, enqueue=enqueue_process_document
    )


__all__ = [
    "enqueue_process_document",
    "enqueue_process_website_documents",
    "process_document",
    "process_website_documents",
]
