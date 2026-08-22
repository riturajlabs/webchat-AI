# RAG Lightweight Chunk Loading Optimization

## Problem

Production `rag_timing` metrics showed `load_chunks_ms` consistently at **700-1100ms**.
This is the latency of `_load_all_chunks()` — the hybrid retrieval path that loads
candidate chunks for keyword/BM25 re-ranking via Reciprocal Rank Fusion.

### Root Cause

`MongoVectorRepository.list_chunks()` returns full `KnowledgeChunk` documents,
including the `embedding` field (1024-dimensional float vector, ~8KB per chunk).
The hybrid keyword scorer only needs `chunk_text`, `metadata`, and identifier
fields — it never reads `embedding`. With `limit=50` (default
`hybrid_search_candidate_limit`), this transfers ~400KB of unused embedding data
over the wire per chat request.

| Metric                       | Per chunk   | x50 chunks  |
| ---------------------------- | ----------- | ----------- |
| `embedding` (1024 x 8 bytes) | ~8 KB       | ~400 KB     |
| `chunk_text` + metadata      | ~0.6 KB     | ~30 KB      |
| **Total**                    | **~8.6 KB** | **~430 KB** |

---

## Changes

### Files Modified

| File                                     | Change                                                                         |
| ---------------------------------------- | ------------------------------------------------------------------------------ |
| `backend/models/knowledge_chunk.py`      | `embedding` field: `list[float]` → `list[float] = Field(default_factory=list)` |
| `backend/repositories/vector/base.py`    | Added `list_chunks_light()` to `VectorRepository` Protocol                     |
| `backend/repositories/vector/mongodb.py` | Implemented `list_chunks_light()` with `{"embedding": 0}` projection           |
| `backend/services/chat/rag_service.py`   | `_load_all_chunks()` now calls `list_chunks_light()`                           |
| `tests/fakes.py`                         | Added `list_chunks_light()` to `FakeVectorRepository`                          |
| `tests/test_vector_mongodb.py`           | Updated `FakeCollection.find()` to support projection; added 6 tests           |

### What Changed

1. **`KnowledgeChunk.embedding`** — Made optional with default empty list. Backward
   compatible: all existing code that provides embeddings still works. Documents
   fetched via projection deserialize cleanly without the field.

2. **`VectorRepository.list_chunks_light()`** — New protocol method. Same signature
   as `list_chunks()` but returns documents without the `embedding` field.

3. **`MongoVectorRepository.list_chunks_light()`** — Uses MongoDB projection
   `{"embedding": 0}` to exclude the embedding vector at the database level,
   preventing it from being fetched, transferred, or deserialized.

4. **`RagService._load_all_chunks()`** — Switched from `list_chunks()` to
   `list_chunks_light()`. This is the only caller change; it exclusively serves
   the hybrid keyword scoring path which never uses embeddings.

### What Did NOT Change

- `list_chunks()` — Unchanged, still returns full `KnowledgeChunk` with embeddings
- `similarity_search()` — Unchanged, still returns full chunks for cosine scoring
- `_brute_force_search()` — Unchanged, still loads full embeddings for exact scan
- RAG algorithm — Zero changes to scoring, ranking, or retrieval logic
- Retrieval accuracy — Identical results; embeddings were never used in this path

---

## Before / After Latency Expectations

| Metric                     | Before         | After (Atlas) | After (local) |
| -------------------------- | -------------- | ------------- | ------------- |
| Documents transferred      | ~430 KB        | ~30 KB        | ~30 KB        |
| Pydantic parse (50 chunks) | ~15-30ms       | ~2-5ms        | ~2-5ms        |
| MongoDB I/O                | ~50-80 pages   | ~5-10 pages   | ~5-10 pages   |
| Network round-trip         | ~50-150ms      | ~30-80ms      | ~0ms          |
| **`load_chunks_ms`**       | **700-1100ms** | **~50-150ms** | **~5-20ms**   |

The 14x reduction in document size eliminates the dominant cost (I/O + network
transfer of embedding vectors). On Atlas, the remaining latency is the index
range scan + small document fetch. On local MongoDB, sub-20ms.

---

## Accuracy Verification

**Zero impact on retrieval accuracy.** The `_load_all_chunks()` path feeds into
`HybridRetrievalStrategy.search()` which calls `keyword_search()` in
`repositories/vector/hybrid.py`. That function accesses only:

- `result.chunk.chunk_text` — for tokenization and TF-IDF scoring
- `result.chunk.id` — for RRF deduplication and rank mapping

It never accesses `result.chunk.embedding`. The `embedding` field is used
exclusively by `similarity_search()` (vector path) and `_brute_force_search()`
(exact cosine fallback), neither of which was modified.

---

## Test Results

```
pytest tests/ -q         → 1360 passed, 2 skipped
ruff check backend/ tests/ → All checks passed
mypy backend/             → Success: no issues found in 182 source files
```

### New Tests Added (`tests/test_vector_mongodb.py`)

| Test                                                                 | Verifies                                               |
| -------------------------------------------------------------------- | ------------------------------------------------------ |
| `test_list_chunks_light_excludes_embedding`                          | Returned chunks have `embedding == []`                 |
| `test_list_chunks_light_is_scoped_to_tenant_and_website`             | Tenant/website isolation preserved                     |
| `test_list_chunks_light_respects_limit`                              | `limit=3` returns at most 3 chunks                     |
| `test_list_chunks_light_returns_all_when_limit_zero`                 | `limit=0` returns all chunks                           |
| `test_list_chunks_light_preserves_metadata_and_ids`                  | All non-embedding fields intact                        |
| `test_list_chunks_light_same_results_as_list_chunks_minus_embedding` | Same chunk IDs/text as `list_chunks`, minus embeddings |
