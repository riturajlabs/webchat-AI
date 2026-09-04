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

import asyncio
import logging
from math import sqrt
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.core.embedding_identity import EmbeddingIdentity, ensure_embedding_compatibility
from backend.core.errors import EmbeddingCompatibilityError
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
        """Upsert/insert knowledge chunks (idempotent on the document key).

        Embedding-identity safety: this upsert intentionally does NOT re-assert
        the embedding identity on the composite key. It depends on the earlier
        per-website processor guard (see ``KnowledgeProcessor._acquire_embedding_run``
        / ``_persist_ingestion_lock`` and ``ensure_embedding_compatibility``),
        which locks the whole website to a single embedding identity and rejects
        incompatible runs before any chunk is written. Re-asserting identity
        here would repeat that check on every chunk write; the processor ordering
        guarantee is what prevents a mixed-identity corpus. If that guard is ever
        reordered, identity must be enforced here too.
        """
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

    async def replace_by_document(
        self, tenant_id: str, document_id: str, chunks: list[KnowledgeChunk]
    ) -> int:
        """Insert-first, delete-stale replacement for one document (P1 safe).

        New chunks are upserted on the unique (tenant, website, document,
        chunk_index) key before any delete runs, so a failure mid-replacement
        leaves the document with its previous chunks (or a superset) - never
        zero. Only after the new chunks are stored are the document's stale
        chunk indexes (the old indexes no longer produced) removed.
        """
        inserted = await self.insert_chunks(chunks)
        if not chunks:
            return inserted
        new_indexes = {chunk.chunk_index for chunk in chunks}
        request_filter = {
            "tenant_id": tenant_id,
            "document_id": document_id,
            "chunk_index": {"$nin": list(new_indexes)},
        }
        await self._collection.delete_many(request_filter)
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

    async def list_chunks(
        self, tenant_id: str, website_id: str, *, limit: int = 0
    ) -> list[KnowledgeChunk]:
        query = {"tenant_id": tenant_id, "website_id": website_id}
        cursor = self._collection.find(query)
        if limit > 0:
            cursor = cursor.limit(limit)
        return [KnowledgeChunk.from_doc(item) async for item in cursor]

    async def list_chunks_light(
        self, tenant_id: str, website_id: str, *, limit: int = 0
    ) -> list[KnowledgeChunk]:
        """Like :pymeth:`list_chunks` but excludes embedding vectors.

        Used by the hybrid keyword corpus load in ``RagService._load_all_chunks``:
        keyword scoring consumes only chunk text/metadata, so we keep every
        non-embedding field (id, chunk_text, metadata, document_id, created_at,
        etc.) while dropping the ``embedding`` payload.  This removes a large
        vector transfer (2162 chunks × 1024 dims ≈ 25–33 s on production)
        at no cost to keyword/hybrid retrieval correctness.
        """
        query = {"tenant_id": tenant_id, "website_id": website_id}
        # A lexical corpus must be repeatable: natural Mongo collection order
        # changes as documents are inserted/rebuilt. `_id` is stable per chunk
        # and provides a deterministic tie/order source without transferring
        # any embedding payload.
        cursor = self._collection.find(query, {"embedding": 0}).sort("_id", 1)
        if limit > 0:
            cursor = cursor.limit(limit)
        return [KnowledgeChunk.from_doc(item) async for item in cursor]

    async def get_chunks_by_ids(
        self, tenant_id: str, website_id: str, ids: list[str]
    ) -> list[KnowledgeChunk]:
        """Fetch full documents (with embeddings) for specific chunk ids.

        Used to hydrate embeddings onto the small reranker candidate pool that
        the embedding-free keyword corpus load cannot provide.  The pool is
        bounded by the hybrid candidate limit (small), so this is a lightweight
        ``$in`` fetch and not a full-corpus embedding transfer.

        Defense-in-depth: the query enforces tenant/website scope in addition to
        the chunk ids, matching the retrieval call path. A raw ``_id`` from
        another tenant/website therefore resolves to nothing.
        """
        if not ids:
            return []
        cursor = self._collection.find(
            {
                "_id": {"$in": ids},
                "tenant_id": tenant_id,
                "website_id": website_id,
            }
        )
        return [KnowledgeChunk.from_doc(item) async for item in cursor]

    async def similarity_search(
        self,
        tenant_id: str,
        website_id: str,
        query_embedding: list[float],
        *,
        top_k: int = 5,
        embedding_identity: EmbeddingIdentity | None = None,
    ) -> list[VectorSearchResult]:
        pipeline: list[dict[str, Any]] = [
            {
                "$vectorSearch": {
                    "index": "default",
                    "path": "embedding",
                    "queryVector": query_embedding,
                    "limit": top_k,
                    "numCandidates": max(top_k * 20, 100),
                    "filter": {
                        "tenant_id": tenant_id,
                        "website_id": website_id,
                        **(
                            {
                                "embedding_provider": embedding_identity.provider,
                                "embedding_model": embedding_identity.model,
                                "embedding_dimensions": embedding_identity.dimensions,
                                "embedding_version": embedding_identity.version,
                            }
                            if embedding_identity is not None
                            else {}
                        ),
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
                    dense_score=float(item["score"]),
                )
                async for item in cursor
            ]
            if embedding_identity is not None:
                for result in results:
                    ensure_embedding_compatibility(result.chunk, embedding_identity)
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
                    tenant_id,
                    website_id,
                    query_embedding,
                    top_k=top_k,
                    embedding_identity=embedding_identity,
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
            if embedding_identity is not None and await self._has_incompatible_chunks(
                tenant_id, website_id, embedding_identity
            ):
                raise EmbeddingCompatibilityError(
                    "Knowledge chunks exist with an incompatible or missing embedding "
                    "identity; re-index this website before querying it."
                )
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
        return await self._brute_force_search(
            tenant_id,
            website_id,
            query_embedding,
            top_k=top_k,
            embedding_identity=embedding_identity,
        )

    async def _has_incompatible_chunks(
        self,
        tenant_id: str,
        website_id: str,
        identity: EmbeddingIdentity,
    ) -> bool:
        """Detect legacy or mixed-space chunks when Atlas returns no hits."""
        find_one = getattr(self._collection, "find_one", None)
        if find_one is None:
            return False
        query = {
            "tenant_id": tenant_id,
            "website_id": website_id,
            "$or": [
                {"embedding_provider": {"$ne": identity.provider}},
                {"embedding_model": {"$ne": identity.model}},
                {"embedding_dimensions": {"$ne": identity.dimensions}},
                {"embedding_version": {"$ne": identity.version}},
            ],
        }
        return await find_one(query, {"_id": 1}) is not None

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
        """A queryable Atlas Search vector index exists on `embedding` (BUG-2).

        Probes via the `$listSearchIndexes` *aggregation stage*: the
        `listSearchIndexes` command form fails on several deployments (pymongo
        reports `command not found` / client-side type errors) while the stage
        works and is the documented introspection path. An index counts as
        usable when it indexes the `embedding` path and - when the server
        reports them - is `READY` and `queryable`. Any probe failure means "no
        search support" so the caller degrades to the exact cosine scan.
        """
        try:
            cursor = self._collection.aggregate([{"$listSearchIndexes": {}}])
            async for index in cursor:
                if not isinstance(index, dict):
                    continue
                status = index.get("status")
                if status is not None and status != "READY":
                    continue
                if index.get("queryable") is False:
                    continue
                definition = index.get("latestDefinition") or index.get("definition") or {}
                fields = definition.get("fields", []) if isinstance(definition, dict) else []
                if any(
                    isinstance(field, dict) and field.get("path") == "embedding" for field in fields
                ):
                    return True
        except Exception:  # noqa: BLE001 - any probe failure means "no search"
            return False
        return False

    async def _brute_force_search(
        self,
        tenant_id: str,
        website_id: str,
        query_embedding: list[float],
        *,
        top_k: int,
        embedding_identity: EmbeddingIdentity | None = None,
    ) -> list[VectorSearchResult]:
        """Exact cosine similarity over the tenant/website's chunks (fallback).

        Chunks whose embedding length differs from the query embedding cannot
        be compared and are skipped. That is a sign of mixed embedding
        dimensions in storage (e.g. an embedding-provider migration), and it
        would otherwise surface only as silently missing hits - so the skip is
        counted and reported. Only the expected/detected dimensions and the
        skipped count are logged, never the vector values.

        Audit A-02: the per-chunk scoring pass is pure-Python CPU work over the
        whole website corpus; it runs in a worker thread via ``asyncio.to_thread``
        so one large knowledge base cannot stall the event loop for every other
        request. Mongo I/O (the cursor) stays on the loop.
        """
        cursor = self._collection.find({"tenant_id": tenant_id, "website_id": website_id})
        items = [item async for item in cursor]
        scored, scanned, skipped_mismatched, detected_dimensions = await asyncio.to_thread(
            _score_corpus, items, query_embedding, embedding_identity
        )
        if skipped_mismatched:
            logger.warning(
                "skipped %s chunk(s) with mismatched embedding dimensions "
                "(expected=%s detected=%s tenant=%s website=%s)",
                skipped_mismatched,
                len(query_embedding),
                detected_dimensions,
                tenant_id,
                website_id,
            )
        results = [VectorSearchResult(chunk=chunk, score=score) for score, chunk in scored[:top_k]]
        logger.info(
            "exact cosine scan finished (tenant=%s website=%s scanned=%s hits=%s)",
            tenant_id,
            website_id,
            scanned,
            len(results),
        )
        return results


def _score_corpus(
    items: list[dict[str, Any]],
    query_embedding: list[float],
    embedding_identity: EmbeddingIdentity | None,
) -> tuple[list[tuple[float, KnowledgeChunk]], int, int, dict[int, int]]:
    """Score fetched chunks by cosine similarity (audit A-02).

    Pure-Python CPU pass over the website corpus, executed via
    ``asyncio.to_thread`` so the event loop stays responsive. Raises
    ``EmbeddingCompatibilityError`` on an identity mismatch and skips chunks
    with missing or mismatched-dimension embeddings. Returns
    ``(scored, scanned, skipped_mismatched, detected_dimensions)`` where
    ``scored`` is sorted by descending similarity.
    """
    expected_dimension = len(query_embedding)
    scored: list[tuple[float, KnowledgeChunk]] = []
    scanned = 0
    skipped_mismatched = 0
    detected_dimensions: dict[int, int] = {}
    for item in items:
        chunk = KnowledgeChunk.from_doc(item)
        scanned += 1
        if embedding_identity is not None:
            ensure_embedding_compatibility(chunk, embedding_identity)
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
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored, scanned, skipped_mismatched, detected_dimensions


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
