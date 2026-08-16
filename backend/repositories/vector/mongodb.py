"""MongoDB Atlas Vector Search implementation of `VectorRepository`.

Chunks live in the `knowledge_chunks` collection alongside their embeddings.
Inserts are idempotent via the unique (tenant_id, website_id, document_id,
chunk_index) index; deletes carry tenant scope; `similarity_search` runs the
Atlas `$vectorSearch` aggregation with a mandatory tenant/website pre-filter.

Search-capability handling (three cases):

* Atlas cluster with a vector index on `knowledge_chunks.embedding`: the
  `$vectorSearch` aggregation returns real hits.
* Local MongoDB community server / MongoDB 8.0+ without Atlas Search: the
  aggregation *raises* and we degrade to an exact brute-force cosine scan over
  the tenant/website's chunks (dev stack keeps working).
* Atlas shared/serverless tiers where search is unavailable yet `$vectorSearch`
  and `$search` *silently return zero rows without erroring*: the empty result
  would otherwise masquerade as a genuine "no match". We probe for a usable
  vector index once (cached) and, when none exists, degrade to the same exact
  cosine scan so retrieval still returns the tenant's relevant chunks.
  A genuine search-capable cluster keeps its `$vectorSearch` behavior; a
  misconfigured index there still fails fast with the actionable message.
"""

import logging
from math import sqrt
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.models.knowledge_chunk import KnowledgeChunk
from backend.repositories.vector.base import VectorRepository, VectorSearchResult

logger = logging.getLogger("webchat_ai")


class MongoVectorRepository(VectorRepository):
    """MongoDB Atlas Vector Search repository (docs/05 §7, ADR-008 Phase 5)."""

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._database = db
        self._collection = db["knowledge_chunks"]
        self._search_supported: bool | None = None

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
            result = await self._collection.update_one(query, {"$set": payload}, upsert=False)
            if result.matched_count > 0:
                continue
            try:
                await self._collection.insert_one(chunk.to_doc())
                inserted += 1
            except Exception:
                # DuplicateKeyError race: another job processed this chunk
                # first; a plain update converges to the same content.
                await self._collection.update_one(query, {"$set": payload}, upsert=False)
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
            results = [
                VectorSearchResult(
                    chunk=KnowledgeChunk.from_doc(item["doc"]),
                    score=float(item["score"]),
                )
                async for item in cursor
            ]
        except Exception as exc:
            if _atlas_only_error(exc):
                # Local MongoDB community server has no `$vectorSearch` (Atlas
                # only). Degrade to an exact brute-force scan over the tenant's
                # chunks so the dev stack stays fully functional; production
                # Atlas still uses the vector index. Any other failure keeps
                # the actionable fail-fast message below.
                logger.warning(
                    "vector search unavailable (%s); falling back to exact cosine scan "
                    "(tenant=%s website=%s)",
                    exc,
                    tenant_id,
                    website_id,
                )
                return await self._brute_force_search(
                    tenant_id, website_id, query_embedding, top_k=top_k
                )
            raise RuntimeError(
                "Vector search unavailable: create an Atlas Vector Search index "
                f"on knowledge_chunks.embedding (path='embedding'). Underlying error: {exc}"
            ) from exc

        if results:
            return results

        # Atlas returned zero rows *without* erroring. On some Atlas tiers
        # (shared/serverless) search is unavailable and `$vectorSearch`/`$search`
        # silently no-op to empty - the result is indistinguishable from a
        # genuine no-match except by checking for a usable vector index. Do that
        # once (cached), and fall back to the exact scan when none exists.
        if await self._has_search_index():
            logger.info(
                "vector search returned zero hits (tenant=%s website=%s top_k=%s)",
                tenant_id,
                website_id,
                top_k,
            )
            return []
        logger.warning(
            "Atlas Search is unavailable on this deployment (no vector index on "
            "knowledge_chunks.embedding); falling back to exact cosine scan "
            "(tenant=%s website=%s top_k=%s)",
            tenant_id,
            website_id,
            top_k,
        )
        return await self._brute_force_search(tenant_id, website_id, query_embedding, top_k=top_k)

    async def _has_search_index(self) -> bool:
        """Whether a usable Atlas Search vector index exists (cached probe).

        The probe only runs after an empty `$vectorSearch` result, so healthy
        deployments never pay for it. The result is cached for the repository
        lifetime: an index created later is picked up on the next process start.
        """
        if self._search_supported is None:
            self._search_supported = await self._probe_search_support()
        return self._search_supported

    async def _probe_search_support(self) -> bool:
        """`listSearchIndexes` works and reports a vector index on `embedding`."""
        try:
            info = await self._database.command({"listSearchIndexes": self._collection.name})
        except Exception:  # noqa: BLE001 - any probe failure means "no search"
            return False
        indexes = info.get("indexes", []) if isinstance(info, dict) else []
        for index in indexes:
            definition = index.get("latestDefinition") or index.get("definition") or {}
            fields = definition.get("fields", []) if isinstance(definition, dict) else []
            for field in fields:
                if field.get("path") == "embedding":
                    return True
        return False

    async def _brute_force_search(
        self,
        tenant_id: str,
        website_id: str,
        query_embedding: list[float],
        *,
        top_k: int,
    ) -> list[VectorSearchResult]:
        """Exact cosine similarity over the tenant/website's chunks (fallback).

        Chunks whose embedding length differs from the query embedding cannot
        be compared and are skipped. That is a sign of mixed embedding
        dimensions in storage (e.g. an embedding-provider migration), and it
        would otherwise surface only as silently missing hits - so the skip is
        counted and reported. Only the expected/detected dimensions and the
        skipped count are logged, never the vector values.
        """
        cursor = self._collection.find({"tenant_id": tenant_id, "website_id": website_id})
        scored: list[tuple[float, KnowledgeChunk]] = []
        scanned = 0
        expected_dimension = len(query_embedding)
        skipped_mismatched = 0
        detected_dimensions: dict[int, int] = {}
        async for item in cursor:
            chunk = KnowledgeChunk.from_doc(item)
            scanned += 1
            if not chunk.embedding:
                continue
            if len(chunk.embedding) != expected_dimension:
                skipped_mismatched += 1
                detected_dimensions[len(chunk.embedding)] = (
                    detected_dimensions.get(len(chunk.embedding), 0) + 1
                )
                continue
            score = _cosine_similarity(query_embedding, chunk.embedding)
            if score > 0:
                scored.append((score, chunk))
        if skipped_mismatched:
            logger.warning(
                "skipped %s chunk(s) with mismatched embedding dimensions "
                "(expected=%s detected=%s tenant=%s website=%s)",
                skipped_mismatched,
                expected_dimension,
                detected_dimensions,
                tenant_id,
                website_id,
            )
        scored.sort(key=lambda pair: pair[0], reverse=True)
        results = [VectorSearchResult(chunk=chunk, score=score) for score, chunk in scored[:top_k]]
        logger.info(
            "exact cosine scan finished (tenant=%s website=%s scanned=%s hits=%s)",
            tenant_id,
            website_id,
            scanned,
            len(results),
        )
        return results


def _atlas_only_error(exc: Exception) -> bool:
    """True when the failure is the Atlas-only `$vectorSearch` limitation.

    Detection must cover the error variants across MongoDB versions: community
    servers historically reject the stage outright (`$vectorSearch stage`,
    "only allowed on MongoDB Atlas"), while MongoDB 8.0+ community reports
    code 31082 `SearchNotEnabled` ("Using $search and $vectorSearch
    aggregation stages requires additional configuration..."). All three mean
    the local server cannot run `$vectorSearch` and the brute-force dev
    fallback should kick in - genuine Atlas index misconfigurations keep their
    fail-fast error because they do not match any marker.
    """
    message = str(exc)
    markers = (
        "only allowed on MongoDB Atlas",
        "$vectorSearch stage",
        "requires additional configuration",
        "SearchNotEnabled",
    )
    return any(marker in message for marker in markers)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors (0.0 on zero norm)."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (sqrt(norm_a) * sqrt(norm_b))


__all__ = ["MongoVectorRepository"]
