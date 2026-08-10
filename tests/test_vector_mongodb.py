"""Tests for `MongoVectorRepository` (Phase 5, ADR-008).

The Atlas-only `$vectorSearch` stage is unavailable on MongoDB community
servers (the local dev stack). `similarity_search` degrades to an exact
brute-force cosine scan there; other failures keep the actionable fail-fast
error. Both paths are exercised with a fake collection below.
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


class FakeCollection:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs
        self.aggregate_error: Exception | None = None

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
async def test_other_failures_still_raise_actionable_error() -> None:
    collection = FakeCollection([_chunk("a", [1.0, 0.0], index=0)])
    collection.aggregate_error = RuntimeError("vector index does not exist")
    repo = MongoVectorRepository(_FakeDb(collection))

    with pytest.raises(RuntimeError, match="create an Atlas Vector Search index"):
        await repo.similarity_search("tenant-a", "site-a", [1.0, 0.0], top_k=5)


class _FakeDb:
    def __init__(self, collection: FakeCollection) -> None:
        self._collection = collection

    def __getitem__(self, _name: str) -> FakeCollection:
        return self._collection
