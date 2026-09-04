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
    def __init__(
        self,
        docs: list[dict],
        *,
        search_indexes: list[dict] | None = None,
    ) -> None:
        self._docs = docs
        self.aggregate_error: Exception | None = None
        self.probe_error: Exception | None = None
        self.search_indexes = search_indexes or []
        self.aggregations: list[list] = []
        self.find_projections: list[dict | None] = []
        self.name = "knowledge_chunks"

    def aggregate(self, pipeline: list) -> object:
        self.aggregations.append(pipeline)
        if any("$listSearchIndexes" in stage for stage in pipeline):
            if self.probe_error is not None:
                raise self.probe_error
            return self._search_index_cursor()
        if self.aggregate_error is not None:
            raise self.aggregate_error
        return self._empty()

    async def _search_index_cursor(self):
        for index in self.search_indexes:
            yield index

    async def _empty(self):
        return
        yield  # pragma: no cover

    def find(self, query: dict, projection: dict | None = None) -> object:
        self.find_projections.append(projection)
        _id_filter = query.get("_id")
        if isinstance(_id_filter, dict) and "$in" in _id_filter:
            wanted = set(_id_filter["$in"])
            matched = [
                doc
                for doc in self._docs
                if doc.get("_id") in wanted
                # Defense-in-depth mirrors the real Mongo query: an `_id` $in
                # fetch is additionally scoped by tenant_id/website_id when the
                # caller supplies them (see get_chunks_by_ids).
                and (query.get("tenant_id") is None or doc["tenant_id"] == query.get("tenant_id"))
                and (
                    query.get("website_id") is None or doc["website_id"] == query.get("website_id")
                )
            ]
        else:
            matched = []
            for doc in self._docs:
                if doc["tenant_id"] == query.get("tenant_id") and doc["website_id"] == query.get(
                    "website_id"
                ):
                    matched.append(doc)
        if projection and any(v == 0 for v in projection.values()):
            exclude_fields = [k for k, v in projection.items() if v == 0]
            matched = [{k: v for k, v in doc.items() if k not in exclude_fields} for doc in matched]

        class _Cursor:
            def __init__(self, items: list[dict]) -> None:
                self._items = items
                self._limit_val = 0

            def limit(self, n: int) -> _Cursor:
                self._limit_val = n
                return self

            def sort(self, field: str, direction: int) -> _Cursor:
                assert field == "_id"
                self._items.sort(key=lambda item: str(item.get("_id", "")), reverse=direction < 0)
                return self

            def __aiter__(self) -> _Cursor:
                self._pos = 0
                return self

            async def __anext__(self) -> dict:
                if self._limit_val > 0 and self._pos >= self._limit_val:
                    raise StopAsyncIteration
                if self._pos >= len(self._items):
                    raise StopAsyncIteration
                item = self._items[self._pos]
                self._pos += 1
                return item

        return _Cursor(matched)


class _FakeDb:
    def __init__(
        self,
        collection: FakeCollection,
        *,
        search_indexes: list[dict] | None = None,
        command_fails: bool = False,
    ) -> None:
        self._collection = collection
        if search_indexes is not None:
            collection.search_indexes = list(search_indexes)
        self.command_fails = command_fails

    def __getitem__(self, _name: str) -> FakeCollection:
        return self._collection

    async def command(self, _command: dict) -> dict:
        """The `listSearchIndexes` *command* form always fails here (BUG-2):
        production pymongo rejects it, so the probe must never rely on it."""
        raise RuntimeError(
            "command not found, full error: {'ok': 0, 'errmsg': 'command not found', 'code': 59}"
        )


@pytest.mark.asyncio
async def test_brute_force_scoring_runs_off_the_event_loop(monkeypatch) -> None:
    """Audit A-02: brute-force cosine scoring must not block the event loop.

    While the scoring pass is running, another coroutine must be able to make
    progress. With the pre-fix inline implementation the loop would stall
    inside the first cosine call and this test would time out.
    """
    import asyncio
    import threading

    from backend.repositories.vector import mongodb as mongodb_module

    started = threading.Event()
    release = threading.Event()

    def blocking_cosine(_a: list[float], _b: list[float]) -> float:
        started.set()
        release.wait(timeout=5)
        return 1.0

    monkeypatch.setattr(mongodb_module, "_cosine_similarity", blocking_cosine)
    docs = [
        _chunk("first", [1.0, 0.0], index=0),
        _chunk("second", [1.0, 0.0], index=1),
    ]
    collection = FakeCollection(docs)
    collection.aggregate_error = RuntimeError(
        "$vectorSearch stage is only allowed on MongoDB Atlas"
    )
    repo = MongoVectorRepository(_FakeDb(collection))

    search = asyncio.create_task(repo.similarity_search("tenant-a", "site-a", [1.0, 0.0], top_k=2))
    for _ in range(500):
        if started.is_set():
            break
        await asyncio.sleep(0.01)
    assert started.is_set(), "scoring never started"

    # The event loop stayed responsive while cosine scoring ran in its thread.
    await asyncio.wait_for(asyncio.sleep(0), timeout=1)

    release.set()
    results = await asyncio.wait_for(search, timeout=5)
    assert [r.chunk.chunk_text for r in results] == ["first", "second"]


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
    # No vector index reported by `$listSearchIndexes`: search unavailable.
    collection = FakeCollection(docs)
    repo = MongoVectorRepository(_FakeDb(collection))

    results = await repo.similarity_search("tenant-a", "site-a", query, top_k=2)

    assert [r.chunk.chunk_text for r in results] == [
        "Indira University offers BA and B.Com courses",
    ]
    assert results[0].score > 0.9


@pytest.mark.asyncio
async def test_silent_zero_kept_empty_on_search_capable_deployment() -> None:
    """Regression (BUG-2, empty-result path): a genuine no-match on a
    search-capable cluster (a READY vector index exists per the
    `$listSearchIndexes` stage) must still return an empty list - never the
    brute-force scan."""
    query = [1.0, 0.0]
    docs = [_chunk("Indira University offers BA and B.Com courses", [1.0, 0.0], index=0)]
    collection = FakeCollection(docs)
    repo = MongoVectorRepository(_FakeDb(collection, search_indexes=[_vector_index_definition()]))

    results = await repo.similarity_search("tenant-a", "site-a", query, top_k=2)

    assert results == []


# ---------------------------------------------------------------------------
# `_probe_search_support` via the `$listSearchIndexes` aggregation stage
# ---------------------------------------------------------------------------


async def test_probe_detects_ready_vector_index() -> None:
    """The probe reports support when `$listSearchIndexes` yields a READY,
    queryable vector index on `embedding` - even though the `listSearchIndexes`
    *command* form fails (production pymongo rejects it)."""
    collection = FakeCollection([], search_indexes=[_vector_index_definition()])
    db = _FakeDb(collection)  # db.command always raises in this fake
    repo = MongoVectorRepository(db)

    assert await repo._probe_search_support() is True
    # The probe must use the aggregation stage, never the broken command.
    assert collection.aggregations == [[{"$listSearchIndexes": {}}]]


async def test_probe_ignores_index_not_ready() -> None:
    """An index still building is not usable search support."""
    index = _vector_index_definition() | {"status": "BUILDING"}
    repo = MongoVectorRepository(_FakeDb(FakeCollection([], search_indexes=[index])))

    assert await repo._probe_search_support() is False


async def test_probe_ignores_unqueryable_index() -> None:
    """A READY index that is not queryable is not usable search support."""
    index = _vector_index_definition() | {"queryable": False}
    repo = MongoVectorRepository(_FakeDb(FakeCollection([], search_indexes=[index])))

    assert await repo._probe_search_support() is False


async def test_probe_failure_degrades_to_brute_force() -> None:
    """When even the `$listSearchIndexes` stage fails, the probe gracefully
    reports "no search" and the empty-result path degrades to brute force."""
    query = [1.0, 0.0]
    docs = [_chunk("exact match", [1.0, 0.0], index=0)]
    collection = FakeCollection(docs)
    collection.probe_error = RuntimeError("$listSearchIndexes is not allowed here")
    repo = MongoVectorRepository(_FakeDb(collection))

    results = await repo.similarity_search("tenant-a", "site-a", query, top_k=2)

    assert [r.chunk.chunk_text for r in results] == ["exact match"]


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


# ---------------------------------------------------------------------------
# list_chunks_light (hybrid candidate loading optimization)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_chunks_light_excludes_embedding() -> None:
    """list_chunks_light returns documents without the embedding field."""
    docs = [
        _chunk("hello world", [1.0, 0.0, 0.5], index=0),
        _chunk("second chunk", [0.0, 1.0, 0.3], index=1),
    ]
    repo = MongoVectorRepository(_FakeDb(FakeCollection(docs)))

    chunks = await repo.list_chunks_light("tenant-a", "site-a")

    assert len(chunks) == 2
    assert [chunk.id for chunk in chunks] == sorted(chunk.id for chunk in chunks)
    assert {chunk.chunk_text for chunk in chunks} == {"hello world", "second chunk"}
    assert all(chunk.embedding == [] for chunk in chunks)
    assert chunks[1].embedding == []


@pytest.mark.asyncio
async def test_list_chunks_light_is_scoped_to_tenant_and_website() -> None:
    """list_chunks_light respects tenant/website isolation."""
    docs = [
        _chunk("own chunk", [1.0, 0.0], index=0),
        _chunk("other website", [1.0, 0.0], index=1, website_id="site-b"),
        _chunk("other tenant", [1.0, 0.0], index=2, tenant_id="tenant-b"),
    ]
    repo = MongoVectorRepository(_FakeDb(FakeCollection(docs)))

    chunks = await repo.list_chunks_light("tenant-a", "site-a")

    assert len(chunks) == 1
    assert chunks[0].chunk_text == "own chunk"


@pytest.mark.asyncio
async def test_list_chunks_light_respects_limit() -> None:
    """list_chunks_light with limit returns at most limit chunks."""
    docs = [_chunk(f"chunk-{i}", [1.0, 0.0], index=i) for i in range(10)]
    repo = MongoVectorRepository(_FakeDb(FakeCollection(docs)))

    chunks = await repo.list_chunks_light("tenant-a", "site-a", limit=3)

    assert len(chunks) == 3


@pytest.mark.asyncio
async def test_list_chunks_light_returns_all_when_limit_zero() -> None:
    """list_chunks_light with limit=0 returns all matching chunks."""
    docs = [_chunk(f"chunk-{i}", [1.0, 0.0], index=i) for i in range(5)]
    repo = MongoVectorRepository(_FakeDb(FakeCollection(docs)))

    chunks = await repo.list_chunks_light("tenant-a", "site-a", limit=0)

    assert len(chunks) == 5


@pytest.mark.asyncio
async def test_list_chunks_light_preserves_metadata_and_ids() -> None:
    """list_chunks_light preserves all non-embedding fields."""
    chunk = KnowledgeChunk.new(
        tenant_id="tenant-a",
        website_id="site-a",
        document_id="doc-1",
        chunk_text="test content",
        embedding=[1.0, 0.0],
        chunk_index=0,
        metadata={"source_url": "https://example.com"},
    )
    repo = MongoVectorRepository(_FakeDb(FakeCollection([chunk.to_doc()])))

    chunks = await repo.list_chunks_light("tenant-a", "site-a")

    assert len(chunks) == 1
    c = chunks[0]
    assert c.id == chunk.id
    assert c.tenant_id == "tenant-a"
    assert c.website_id == "site-a"
    assert c.document_id == "doc-1"
    assert c.chunk_text == "test content"
    assert c.chunk_index == 0
    assert c.metadata == {"source_url": "https://example.com"}
    assert c.embedding == []


@pytest.mark.asyncio
async def test_list_chunks_light_same_results_as_list_chunks_minus_embedding() -> None:
    """list_chunks_light returns the same IDs as list_chunks, sans embeddings."""
    docs = [
        _chunk("alpha", [1.0, 0.0], index=0),
        _chunk("beta", [0.0, 1.0], index=1),
    ]
    repo = MongoVectorRepository(_FakeDb(FakeCollection(docs)))

    full = await repo.list_chunks("tenant-a", "site-a")
    light = await repo.list_chunks_light("tenant-a", "site-a")

    assert len(full) == len(light)
    assert {chunk.id for chunk in full} == {chunk.id for chunk in light}
    assert all(chunk.embedding != [] for chunk in full)  # full has embeddings
    assert all(chunk.embedding == [] for chunk in light)  # light does not


# ---------------------------------------------------------------------------
# get_chunks_by_ids (rerank-pool embedding hydration)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_chunks_by_ids_returns_full_chunks_with_embeddings() -> None:
    """get_chunks_by_ids returns full documents (with embeddings) for the ids.

    This is the targeted fetch that re-hydrates embeddings onto the small
    reranker candidate pool, so it must NOT exclude the embedding field.
    """
    docs = [
        _chunk("alpha", [1.0, 0.0, 0.5], index=0),
        _chunk("beta", [0.0, 1.0, 0.3], index=1),
        _chunk("gamma", [0.2, 0.4, 0.6], index=2),
    ]
    repo = MongoVectorRepository(_FakeDb(FakeCollection(docs)))
    ids = [docs[0]["_id"], docs[2]["_id"]]

    chunks = await repo.get_chunks_by_ids("tenant-a", "site-a", ids)

    assert {c.chunk_text for c in chunks} == {"alpha", "gamma"}
    for c in chunks:
        assert c.embedding != [], "hydrated chunks must carry embeddings"
    assert "embedding" not in (repo._collection.find_projections[-1] or {})


@pytest.mark.asyncio
async def test_get_chunks_by_ids_empty_ids_is_noop() -> None:
    docs = [_chunk("alpha", [1.0, 0.0], index=0)]
    repo = MongoVectorRepository(_FakeDb(FakeCollection(docs)))

    chunks = await repo.get_chunks_by_ids("tenant-a", "site-a", [])

    assert chunks == []


@pytest.mark.asyncio
async def test_get_chunks_by_ids_is_scoped_to_tenant_and_website() -> None:
    """A raw ``_id`` from another tenant/website must NOT be hydratable.

    Defense-in-depth regression for D1: even though the rerank pool is already
    tenant/website-scoped upstream, the repository query itself must enforce the
    scope so a stale or out-of-context ``_id`` can never leak another tenant's
    or website's embeddings into the rerank pool.
    """
    docs = [
        _chunk("same tenant and website", [1.0, 0.0], index=0),
        _chunk("same tenant other website", [1.0, 0.0], index=1, website_id="site-b"),
        _chunk("other tenant", [1.0, 0.0], index=2, tenant_id="tenant-b"),
    ]
    repo = MongoVectorRepository(_FakeDb(FakeCollection(docs)))
    # Request the ids of ALL three docs, but scoped to tenant-a / site-a.
    chunks = await repo.get_chunks_by_ids("tenant-a", "site-a", [d["_id"] for d in docs])

    assert [c.chunk_text for c in chunks] == ["same tenant and website"]


@pytest.mark.asyncio
async def test_list_chunks_light_projection_excludes_embedding() -> None:
    """The keyword-corpus light load requests the embedding-free projection."""
    docs = [_chunk("alpha", [1.0, 0.0, 0.5], index=0)]
    fake = FakeCollection(docs)
    repo = MongoVectorRepository(_FakeDb(fake))

    await repo.list_chunks_light("tenant-a", "site-a")

    assert fake.find_projections[-1] == {"embedding": 0}, (
        "keyword corpus load must project out the embedding/vector field"
    )


class _ReplaceFakeCollection:
    """Minimal collection fake supporting the Mongo `replace_by_document` ops."""

    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs
        self.name = "knowledge_chunks"

    async def update_one(self, query: dict, update: dict, upsert: bool = False) -> object:
        set_payload = update.get("$set", {})
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                doc.update(set_payload)
                return _UpdateResult(matched_count=1)
        if upsert:
            self._docs.append({**query, **set_payload})
        return _UpdateResult(matched_count=0)

    async def insert_one(self, doc: dict) -> object:
        self._docs.append(doc)
        return None

    async def delete_many(self, query: dict) -> object:
        before = len(self._docs)
        self._docs = [
            doc
            for doc in self._docs
            if not (
                doc["tenant_id"] == query.get("tenant_id")
                and doc["document_id"] == query.get("document_id")
                and (
                    not query.get("chunk_index")
                    or doc.get("chunk_index") not in query["chunk_index"]["$nin"]
                )
            )
        ]
        return _DeleteResult(before - len(self._docs))

    @property
    def docs(self) -> list[dict]:
        return self._docs


class _UpdateResult:
    def __init__(self, matched_count: int) -> None:
        self.matched_count = matched_count


class _DeleteResult:
    def __init__(self, deleted_count: int) -> None:
        self.deleted_count = deleted_count


class _ReplaceFakeDb:
    def __init__(self, collection: _ReplaceFakeCollection) -> None:
        self._collection = collection

    def __getitem__(self, _name: str) -> _ReplaceFakeCollection:
        return self._collection


@pytest.mark.asyncio
async def test_replace_by_document_inserts_first_then_deletes_stale() -> None:
    """Mongo `replace_by_document` upserts new chunks then removes stale ones.

    Old chunks of `doc-a` at indexes 0..2 are replaced by new chunks at indexes
    0..1 plus a new index 5. Only the stale indexes (2) are removed; the new
    indexes land first so a mid-replacement failure can never leave zero chunks.
    """
    old = [
        _chunk("old zero", [1.0], index=0),
        _chunk("old one", [1.0], index=1),
        _chunk("old two", [1.0], index=2),
    ]
    fake = _ReplaceFakeCollection(old)
    repo = MongoVectorRepository(_ReplaceFakeDb(fake))  # type: ignore[arg-type]

    new_chunks = [
        KnowledgeChunk.new(
            tenant_id="tenant-a",
            website_id="site-a",
            document_id="doc-a",
            chunk_text=text,
            embedding=[1.0],
            chunk_index=index,
        )
        for index, text in [(0, "new zero"), (1, "new one"), (5, "new five")]
    ]

    inserted = await repo.replace_by_document("tenant-a", "doc-a", new_chunks)

    # Only the genuinely-new index (5) is an insert; indexes 0 and 1 are in
    # place replacement via the unique upsert key.
    assert inserted == 1
    indexes = {doc.get("chunk_index") for doc in fake.docs}
    assert indexes == {0, 1, 5}
    # Old stale index 2 was removed; new text at index 0 replaced the old text.
    text_by_index = {doc.get("chunk_index"): doc.get("chunk_text") for doc in fake.docs}
    assert text_by_index[0] == "new zero"
    assert text_by_index[5] == "new five"
