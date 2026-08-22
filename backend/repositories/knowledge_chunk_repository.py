"""Read-side data access for `knowledge_chunks` (Phase 5).

Vector writes/reads go through `VectorRepository` (ADR: never couple to Mongo);
this repository only serves dashboard/worker statistics (counts per website)
without ever exposing embeddings (docs/05 §17).
"""

from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.core.embedding_identity import EmbeddingIdentity


class KnowledgeChunkRepository(Protocol):
    """Tenant-scoped read access to knowledge chunk statistics."""

    async def count_by_website(self, tenant_id: str, website_id: str) -> int: ...

    async def count_by_document(self, tenant_id: str, document_id: str) -> int: ...

    async def count_documents_by_website(self, tenant_id: str, website_id: str) -> int: ...

    async def has_incompatible_identity(
        self, tenant_id: str, website_id: str, identity: EmbeddingIdentity
    ) -> bool: ...


class MongoKnowledgeChunkRepository:
    """MongoDB-backed read repository over `knowledge_chunks`."""

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._collection = db["knowledge_chunks"]

    async def count_by_website(self, tenant_id: str, website_id: str) -> int:
        return await self._collection.count_documents(
            {"tenant_id": tenant_id, "website_id": website_id}
        )

    async def count_by_document(self, tenant_id: str, document_id: str) -> int:
        return await self._collection.count_documents(
            {"tenant_id": tenant_id, "document_id": document_id}
        )

    async def count_documents_by_website(self, tenant_id: str, website_id: str) -> int:
        """Distinct processed documents for a website (backed by an index)."""
        distinct = await self._collection.distinct(
            "document_id",
            {"tenant_id": tenant_id, "website_id": website_id},
        )
        return len(distinct)

    async def has_incompatible_identity(
        self, tenant_id: str, website_id: str, identity: EmbeddingIdentity
    ) -> bool:
        """Whether the website holds any chunk from another embedding space.

        Ingestion calls this before writing so one website can never end up
        with mixed embedding identities (BUG-1): chunks stamped with a
        different provider/model/dimensions/version - including legacy chunks
        with no stamp at all - block the write instead of silently joining the
        corpus. Only `_id` is projected; embeddings are never read.
        """
        found = await self._collection.find_one(
            {
                "tenant_id": tenant_id,
                "website_id": website_id,
                "$or": [
                    {"embedding_provider": {"$ne": identity.provider}},
                    {"embedding_model": {"$ne": identity.model}},
                    {"embedding_dimensions": {"$ne": identity.dimensions}},
                    {"embedding_version": {"$ne": identity.version}},
                ],
            },
            {"_id": 1},
        )
        return found is not None


__all__ = ["KnowledgeChunkRepository", "MongoKnowledgeChunkRepository"]
