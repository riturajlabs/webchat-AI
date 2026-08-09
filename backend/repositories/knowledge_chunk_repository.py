"""Read-side data access for `knowledge_chunks` (Phase 5).

Vector writes/reads go through `VectorRepository` (ADR: never couple to Mongo);
this repository only serves dashboard/worker statistics (counts per website)
without ever exposing embeddings (docs/05 §17).
"""

from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase


class KnowledgeChunkRepository(Protocol):
    """Tenant-scoped read access to knowledge chunk statistics."""

    async def count_by_website(self, tenant_id: str, website_id: str) -> int: ...

    async def count_by_document(self, tenant_id: str, document_id: str) -> int: ...

    async def count_documents_by_website(self, tenant_id: str, website_id: str) -> int: ...


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


__all__ = ["KnowledgeChunkRepository", "MongoKnowledgeChunkRepository"]
