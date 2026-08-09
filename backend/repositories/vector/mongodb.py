"""MongoDB Atlas Vector Search implementation of `VectorRepository`.

Chunks live in the `knowledge_chunks` collection alongside their embeddings.
Inserts are idempotent via the unique (tenant_id, website_id, document_id,
chunk_index) index; deletes carry tenant scope; `similarity_search` runs the
Atlas `$vectorSearch` aggregation with a mandatory tenant/website pre-filter.

Atlas Vector Search is required for `similarity_search` (not the local MongoDB
community server); the query fails fast with an actionable message when no
vector index exists on `knowledge_chunks.embedding`.
"""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.models.knowledge_chunk import KnowledgeChunk
from backend.repositories.vector.base import VectorRepository, VectorSearchResult


class MongoVectorRepository(VectorRepository):
    """MongoDB Atlas Vector Search repository (docs/05 §7, ADR-008 Phase 5)."""

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._collection = db["knowledge_chunks"]

    async def insert_chunks(self, chunks: list[KnowledgeChunk]) -> int:
        if not chunks:
            return 0
        inserted = 0
        for chunk in chunks:
            query = {
                "tenant_id": chunk.tenant_id,
                "website_id": chunk.website_id,
                "document_id": chunk.document_id,
                "chunk_index": chunk.chunk_index,
            }
            payload = chunk.to_doc()
            payload.pop("_id", None)
            result = await self._collection.update_one(
                query, {"$set": payload}, upsert=False
            )
            if result.matched_count > 0:
                continue
            try:
                await self._collection.insert_one(chunk.to_doc())
                inserted += 1
            except Exception:
                # DuplicateKeyError race: another job processed this chunk
                # first; a plain update converges to the same content.
                await self._collection.update_one(
                    query, {"$set": payload}, upsert=False
                )
        return inserted

    async def delete_by_document(self, tenant_id: str, document_id: str) -> int:
        result = await self._collection.delete_many(
            {"tenant_id": tenant_id, "document_id": document_id}
        )
        return int(result.deleted_count)

    async def delete_by_website(self, tenant_id: str, website_id: str) -> int:
        result = await self._collection.delete_many(
            {"tenant_id": tenant_id, "website_id": website_id}
        )
        return int(result.deleted_count)

    async def similarity_search(
        self,
        tenant_id: str,
        website_id: str,
        query_embedding: list[float],
        *,
        top_k: int = 5,
    ) -> list[VectorSearchResult]:
        pipeline: list[dict[str, Any]] = [
            {
                "$vectorSearch": {
                    "index": "default",
                    "path": "embedding",
                    "queryVector": query_embedding,
                    "limit": top_k,
                    "numCandidates": max(top_k * 10, 50),
                    "filter": {
                        "tenant_id": tenant_id,
                        "website_id": website_id,
                    },
                }
            },
            {"$project": {"score": {"$meta": "vectorSearchScore"}, "doc": "$$ROOT"}},
            {"$sort": {"score": -1}},
            {"$limit": top_k},
        ]
        try:
            cursor = self._collection.aggregate(pipeline)
            return [
                VectorSearchResult(
                    chunk=KnowledgeChunk.from_doc(item["doc"]),
                    score=float(item["score"]),
                )
                async for item in cursor
            ]
        except Exception as exc:
            raise RuntimeError(
                "Vector search unavailable: create an Atlas Vector Search index "
                f"on knowledge_chunks.embedding (path='embedding'). Underlying error: {exc}"
            ) from exc


__all__ = ["MongoVectorRepository"]
