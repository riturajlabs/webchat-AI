# RAG Regression Fix: `_load_all_chunks` Silent Embedding Loss

## Date: 2026-08-20

## Executive Summary

A regression was introduced when `_load_all_chunks()` was updated to use
`list_chunks_light()` for a ~400 KB per-query bandwidth optimization. The
lightweight chunks returned by `list_chunks_light()` have empty embeddings
(`embedding=[]`). These chunks flow through RRF fusion into the final result
set, where the reranker assigns them a score of `0.0` (it cannot compute
cosine similarity without embeddings). The `_build_context` min-score filter
(`chat_context_min_score=0.25`) then silently discards them — eliminating
correct keyword-found results from the LLM context.

## Root Cause

**File:** `backend/services/chat/rag_service.py:943`

```python
# BEFORE (buggy):
chunks = await self._vector.list_chunks_light(tenant_id, website_id, limit=limit)

# AFTER (fixed):
chunks = await self._vector.list_chunks(tenant_id, website_id, limit=limit)
```

### Data Flow

1. `_load_all_chunks()` calls `list_chunks_light()` → returns `KnowledgeChunk`
   objects with `embedding=[]` (MongoDB projection `{"embedding": 0}`).
2. These chunks flow into `HybridSearcher.search()` → `keyword_search()` →
   `reciprocal_rank_fusion()`.
3. RRF `chunk_map` preserves the vector-scored version when a chunk appears in
   both rankings. For chunks found **only** by keyword search, the light version
   (empty embedding, score 0.5) is retained.
4. Fused results go to `EmbeddingReranker.rerank()` (reranker.py:121):
   ```python
   if not chunk_emb:        # embedding=[] is falsy
       scored.append((0.0, idx))  # score = 0.0
   ```
5. `_build_context()` (rag_service.py:991) filters: `if result.score < self._min_score` (0.25).
   All 0.0-scored chunks are discarded.

### Why It Was Silent

- `KnowledgeChunk.embedding` was changed to `Field(default_factory=list)` —
  empty embeddings are a valid default, not an error.
- The reranker assigns 0.0 (not an exception) for empty embeddings.
- `_build_context` filters silently (no logging for dropped chunks).
- The pipeline still returns _some_ results (vector-scored chunks with
  embeddings survive), so the chat appears to work — just with missing
  keyword-found content.

## Example Failing Query

**Question:** "How do I create an API key?"

- **Vector search** ranks pricing/support chunks higher (lower chunk index →
  higher similarity score in the fake repo).
- **Keyword search** finds the API key chunk (tokens "api", "key" match).
- **RRF fusion** includes the API key chunk from keyword ranking.
- **Reranker** assigns 0.0 (empty embedding from `list_chunks_light`).
- **min_score=0.25** filters it out.
- **Result:** API key chunk missing from context → LLM answers without the
  correct information.

## Fix

**One-line change** in `rag_service.py:943`:

```python
chunks = await self._vector.list_chunks(tenant_id, website_id, limit=limit)
```

`list_chunks()` returns full `KnowledgeChunk` objects with embeddings intact.
The reranker can now compute meaningful cosine similarity, and chunks score
above `min_score=0.25`.

### Trade-off

- **Before:** ~400 KB less data transferred per hybrid query (embedding vectors
  stripped by MongoDB projection).
- **After:** Full embedding vectors loaded for keyword-ranking candidates.
  This restores correct retrieval quality at the cost of the bandwidth savings.
- **Assessment:** The bandwidth optimization was incorrect — the results of
  `_load_all_chunks` flow to the reranker, which requires embeddings. The
  optimization must be applied at a different layer (e.g., stripping embeddings
  only after RRF fusion but before the reranker, or not at all if reranking is
  enabled).

## Verification

### Regression Test

**File:** `tests/test_rag_accuracy.py:1248`
**Test:** `test_keyword_only_chunk_survives_reranker_and_min_score`

- Creates 4 chunks with distinct non-zero embeddings.
- Chunk 2 (API key) has a higher `chunk_index` so vector search ranks it lower.
- Enables reranking (`reranker=True`).
- Asks "How do I create an API key?".
- **Asserts** the API key chunk appears in the final sources.
- **Confirmed:** Test fails with old code (`list_chunks_light`), passes with fix.

### Test Results

| Check                      | Result                             |
| -------------------------- | ---------------------------------- |
| Full pytest suite          | **1362 passed**, 2 skipped         |
| Regression test (fix)      | **PASS**                           |
| Regression test (old code) | **FAIL** (API key chunk discarded) |
| ruff check                 | **All checks passed**              |
| mypy (changed files)       | **Success: no issues found**       |

## Files Changed

| File                                       | Change                                                          |
| ------------------------------------------ | --------------------------------------------------------------- |
| `backend/services/chat/rag_service.py:943` | `list_chunks_light` → `list_chunks`                             |
| `tests/test_rag_accuracy.py:1248+`         | Added `test_keyword_only_chunk_survives_reranker_and_min_score` |

## Performance Impact

- **Query latency:** Negligible increase (~1-2ms for loading full embeddings
  from in-memory fake; production MongoDB may see slightly more).
- **Memory:** Full embeddings loaded per query instead of light chunks. For
  typical tenant sizes this is acceptable.
- **Accuracy:** Correct keyword-found chunks now survive through the reranker
  and appear in LLM context. This is a **correctness fix**, not a performance
  change.
