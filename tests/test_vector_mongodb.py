"""Tests for `MongoVectorRepository` (Phase 5, ADR-008).

The Atlas-only `$vectorSearch` stage is unavailable on MongoDB community
servers (the local dev stack), and on some Atlas shared/serverless tiers it
*silently returns zero rows* instead of erroring. `similarity_search` degrades
to an exact brute-force cosine scan in all of those cases; genuine no-match on
a search-capable cluster stays empty. Other failures keep the actionable
fail-fast error. All paths are exercised with a fake collection below.
"""

from __future__ import annotations

import pytest
from backend.models.knowledge_chunk import KnowledgeChunk
from backend.repositories.vector.mongodb import MongoVectorRepository


def _chunk(chunk_text: str, embedding: list[float], *, index: int) -> dict:
    chunk = KnowledgeChunk.new(
        tenant_id="tenant-a",
        website_id="site-a",
        document_id="doc-a",
        chunk_text=chunk_text,
        embedding=embedding,
        chunk_index=index,
    )
    return chunk.to_doc()


def _vector_index_definition() -> dict:
    """The shape `listSearchIndexes` returns for a real Atlas vector index."""
    return {
        "name": "default",
        "type": "vectorSearch",
        "status": "READY",
        "latestDefinition": {
            "fields": [
                {
                    "type": "vector",
                    "path": "embedding",
                    "numDimensions": 4,
                    "similarity": "cosine",
                }
            ]
        },
    }


class FakeCollection:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs
        self.aggregate_error: Exception | None = None
        self.name = "knowledge_chunks"

    def aggregate(self, _pipeline: list) -> object:
        if self.aggregate_error is not None:
            raise self.aggregate_error
        return self._empty()

    async def _empty(self):
        return
        yield  # pragma: no cover

    def find(self, query: dict) -> object:
        async def _gen():
            for doc in self._docs:
                if doc["tenant_id"] == query.get("tenant_id") and doc["website_id"] == query.get(
                    "website_id"
                ):
                    yield doc

        return _gen()


class _FakeDb:
    def __init__(self, collection: FakeCollection, *, search_indexes: list[dict] | None = None,
                 command_fails: bool = False) -> None:
        self._collection = collection
        self._search_indexes = search_indexes or []
        self.command_fails = command_fails

    def __getitem__(self, _name: str) -> FakeCollection:
        return self._collection

    async def command(self, _command: dict) -> dict:
        if self.command_fails:
            raise RuntimeError(
                "command not found, full error: {'ok': 0, "
                "'errmsg': 'command not found', 'code': 59}"
            )
        return {"indexes": self._search_indexes}


@pytest.mark.asyncio
async def test_falls_back_to_brute_force_when_atlas_vector_search_is_unavailable() -> None:
    query = [1.0, 0.0]
    docs = [
        _chunk("exact match", [1.0, 0.0], index=0),
        _chunk("partially related", [0.8, 0.6], index=1),
    ]
    collection = FakeCollection(docs)
    collection.aggregate_error = RuntimeError(
        "$vectorSearch stage is only allowed on MongoDB Atlas"
    )
    repo = MongoVectorRepository(_FakeDb(collection))

    results = await repo.similarity_search("tenant-a", "site-a", query, top_k=2)

    assert [r.chunk.chunk_text for r in results] == [
        "exact match",
        "partially related",
    ]
    assert results[0].score > results[1].score
    assert results[0].score > 0.9


@pytest.mark.asyncio
async def test_falls_back_on_mongodb_80_search_not_enabled_error() -> None:
    """MongoDB 8.x community reports code 31082 SearchNotEnabled; the brute-force
    dev fallback must trigger there too."""
    query = [1.0, 0.0]
    docs = [_chunk("exact match", [1.0, 0.0], index=0)]
    collection = FakeCollection(docs)
    collection.aggregate_error = RuntimeError(
        "Using $search and $vectorSearch aggregation stages requires additional "
        "configuration. Please connect to Atlas or an AtlasCLI local deployment "
        "to enable. code: 31082 SearchNotEnabled"
    )
    repo = MongoVectorRepository(_FakeDb(collection))

    results = await repo.similarity_search("tenant-a", "site-a", query, top_k=2)

    assert [r.chunk.chunk_text for r in results] == ["exact match"]


@pytest.mark.asyncio
async def test_other_failures_still_raise_actionable_error() -> None:
    collection = FakeCollection([_chunk("a", [1.0, 0.0], index=0)])
    collection.aggregate_error = RuntimeError("vector index does not exist")
    repo = MongoVectorRepository(_FakeDb(collection))

    with pytest.raises(RuntimeError, match="create an Atlas Vector Search index"):
        await repo.similarity_search("tenant-a", "site-a", [1.0, 0.0], top_k=5)


@pytest.mark.asyncio
async def test_falls_back_to_brute_force_when_vector_search_silently_returns_zero() -> None:
    """On deployments where `$vectorSearch` no-ops to empty (Atlas shared /
    serverless tiers), the empty result must not be mistaken for a no-match:
    the exact cosine scan over the tenant/website's chunks runs instead."""
    query = [1.0, 0.0]
    docs = [
        _chunk("Indira University offers BA and B.Com courses", [1.0, 0.0], index=0),
        _chunk("another website's unrelated chunk", [0.0, 1.0], index=1),
    ]
    # No search index + `listSearchIndexes` unsupported: search unavailable.
    collection = FakeCollection(docs)
    repo = MongoVectorRepository(_FakeDb(collection, command_fails=True))

    results = await repo.similarity_search("tenant-a", "site-a", query, top_k=2)

    assert [r.chunk.chunk_text for r in results] == [
        "Indira University offers BA and B.Com courses",
    ]
    assert results[0].score > 0.9


@pytest.mark.asyncio
async def test_silent_zero_kept_empty_on_search_capable_deployment() -> None:
    """A genuine no-match on a search-capable cluster (a vector index exists)
    must still return an empty list - never the brute-force scan."""
    query = [1.0, 0.0]
    docs = [_chunk("Indira University offers BA and B.Com courses", [1.0, 0.0], index=0)]
    collection = FakeCollection(docs)
    repo = MongoVectorRepository(
        _FakeDb(collection, search_indexes=[_vector_index_definition()])
    )

    results = await repo.similarity_search("tenant-a", "site-a", query, top_k=2)

    assert results == []
