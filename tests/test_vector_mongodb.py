"""Tests for `MongoVectorRepository` (Phase 5, ADR-008).

The Atlas-only `$vectorSearch` stage is unavailable on MongoDB community
servers (the local dev stack), and on some Atlas shared/serverless tiers it
*silently returns zero rows* instead of erroring. `similarity_search` degrades
to an exact brute-force cosine scan in all of those cases; genuine no-match on
a search-capable cluster stays empty. Other failures keep the actionable
fail-fast error. All paths are exercised with a fake collection below.
"""

from __future__ import annotations

import logging

import pytest
from backend.models.knowledge_chunk import KnowledgeChunk
from backend.repositories.vector.mongodb import MongoVectorRepository


def _chunk(
    chunk_text: str,
    embedding: list[float],
    *,
    index: int,
    tenant_id: str = "tenant-a",
    website_id: str = "site-a",
) -> dict:
    chunk = KnowledgeChunk.new(
        tenant_id=tenant_id,
        website_id=website_id,
        document_id="doc-a",
        chunk_text=chunk_text,
        embedding=embedding,
        chunk_index=index,
    )
    return chunk.to_doc()


@pytest.mark.asyncio
async def test_list_chunks_is_scoped_to_tenant_and_website() -> None:
    docs = [
        _chunk("same tenant and website", [1.0, 0.0], index=0),
        _chunk("different website", [1.0, 0.0], index=1, website_id="site-b"),
        _chunk("different tenant", [1.0, 0.0], index=2, tenant_id="tenant-b"),
    ]
    repo = MongoVectorRepository(_FakeDb(FakeCollection(docs)))

    chunks = await repo.list_chunks("tenant-a", "site-a")

    assert [chunk.chunk_text for chunk in chunks] == ["same tenant and website"]


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
    def __init__(
        self,
        collection: FakeCollection,
        *,
        search_indexes: list[dict] | None = None,
        command_fails: bool = False,
    ) -> None:
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
    repo = MongoVectorRepository(_FakeDb(collection, search_indexes=[_vector_index_definition()]))

    results = await repo.similarity_search("tenant-a", "site-a", query, top_k=2)

    assert results == []


@pytest.mark.asyncio
async def test_matching_dimensions_log_no_warning(caplog) -> None:
    """Uniform dimensions never trip the mismatch warning."""
    query = [1.0, 0.0, 0.0, 0.0]
    docs = [
        _chunk("exact match", [1.0, 0.0, 0.0, 0.0], index=0),
        _chunk("partially related", [0.8, 0.6, 0.0, 0.0], index=1),
    ]
    collection = FakeCollection(docs)
    collection.aggregate_error = RuntimeError(
        "$vectorSearch stage is only allowed on MongoDB Atlas"
    )
    repo = MongoVectorRepository(_FakeDb(collection))

    with caplog.at_level(logging.WARNING, logger="webchat_ai"):
        results = await repo.similarity_search("tenant-a", "site-a", query, top_k=2)

    assert len(results) == 2
    mismatch = [r for r in caplog.records if "mismatched embedding dimensions" in r.getMessage()]
    assert mismatch == []


@pytest.mark.asyncio
async def test_mismatched_dimensions_emit_warning(caplog) -> None:
    """A stored chunk with a different embedding length is skipped, and the
    skip is reported with the expected/detected dimensions and tenant."""
    query = [1.0, 0.0]  # expected dimension 2
    docs = [
        _chunk("exact match", [1.0, 0.0], index=0),
        _chunk("wrong dimension", [1.0, 0.0, 0.0], index=1),
    ]
    collection = FakeCollection(docs)
    collection.aggregate_error = RuntimeError(
        "$vectorSearch stage is only allowed on MongoDB Atlas"
    )
    repo = MongoVectorRepository(_FakeDb(collection))

    with caplog.at_level(logging.WARNING, logger="webchat_ai"):
        results = await repo.similarity_search("tenant-a", "site-a", query, top_k=2)

    # The mismatched chunk is silently excluded from results (behavior unchanged)...
    assert [r.chunk.chunk_text for r in results] == ["exact match"]
    # ...but the skip is no longer invisible.
    mismatch = [r for r in caplog.records if "mismatched embedding dimensions" in r.getMessage()]
    assert len(mismatch) == 1
    message = mismatch[0].getMessage()
    assert "expected=2" in message
    assert "detected={3: 1}" in message
    assert "skipped 1 chunk(s)" in message
    assert "tenant-a" in message


@pytest.mark.asyncio
async def test_multiple_mismatched_chunks_counted(caplog) -> None:
    """Multiple skipped chunks across several detected dimensions are all
    counted in a single warning."""
    query = [1.0, 0.0]
    docs = [
        _chunk("exact match", [1.0, 0.0], index=0),
        _chunk("bad-3a", [1.0, 0.0, 0.0], index=1),
        _chunk("bad-3b", [0.0, 1.0, 0.0], index=2),
        _chunk("bad-5", [1.0, 0.0, 0.0, 0.0, 0.0], index=3),
    ]
    collection = FakeCollection(docs)
    collection.aggregate_error = RuntimeError(
        "$vectorSearch stage is only allowed on MongoDB Atlas"
    )
    repo = MongoVectorRepository(_FakeDb(collection))

    with caplog.at_level(logging.WARNING, logger="webchat_ai"):
        results = await repo.similarity_search("tenant-a", "site-a", query, top_k=2)

    assert [r.chunk.chunk_text for r in results] == ["exact match"]
    mismatch = [r for r in caplog.records if "mismatched embedding dimensions" in r.getMessage()]
    assert len(mismatch) == 1
    message = mismatch[0].getMessage()
    assert "skipped 3 chunk(s)" in message
    assert "expected=2" in message
    assert "detected={3: 2, 5: 1}" in message


@pytest.mark.asyncio
async def test_mismatch_warning_never_logs_vector_values(caplog) -> None:
    """The mismatch warning carries dimensions and counts only - never any
    embedding coordinates."""
    query = [1.0, 0.0]
    docs = [_chunk("bad", [1.0, 0.0, 0.0], index=0)]
    collection = FakeCollection(docs)
    collection.aggregate_error = RuntimeError(
        "$vectorSearch stage is only allowed on MongoDB Atlas"
    )
    repo = MongoVectorRepository(_FakeDb(collection))

    with caplog.at_level(logging.WARNING, logger="webchat_ai"):
        results = await repo.similarity_search("tenant-a", "site-a", query, top_k=2)

    assert results == []
    mismatch = [r for r in caplog.records if "mismatched embedding dimensions" in r.getMessage()]
    assert len(mismatch) == 1
    message = mismatch[0].getMessage()
    assert "1.0" not in message
    assert "0.0" not in message
    assert "[" not in message
    assert "embedding=[" not in message
