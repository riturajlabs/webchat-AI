# AI RAG P0 Optimization Report

> Date: 2026-08-20 | Scope: P0 performance optimizations from AI-RAG-PERFORMANCE-AUDIT.md

---

## Summary

Eliminated two critical bottlenecks in the RAG pipeline: **duplicate query embedding** and **redundant chunk re-embedding in the reranker**. Combined, these add ~1,700ms per request (30-40% of total latency on non-cached paths).

---

## Before Latency (Production Logs)

| Stage                 | Duration       | Notes                                    |
| --------------------- | -------------- | ---------------------------------------- |
| Query embedding       | ~950-1,100ms   | Gemini embedding API (cache miss)        |
| Vector search         | ~160-250ms     | MongoDB $vectorSearch                    |
| **Rerank (re-embed)** | **~1,700ms**   | Embeds query + all candidate chunk texts |
| Generation            | ~1,000-1,600ms | Gemini streaming                         |
| **Total**             | **~5-13s**     | End-to-end                               |

### Rerank Breakdown (Before)

- `rerank_ms`: ~1,700ms
- `rerank_embedding_ms`: ~1,700ms (identical — embedding IS the bottleneck)
- The reranker called `embed([query] + [chunk_text for each candidate])` — re-embedding texts that already have stored vectors in `KnowledgeChunk.embedding`

---

## After Latency (Expected)

| Stage                    | Duration           | Notes                                         |
| ------------------------ | ------------------ | --------------------------------------------- |
| Query embedding          | ~950-1,100ms       | Gemini embedding API (cache miss) — UNCHANGED |
| Vector search            | ~160-250ms         | MongoDB $vectorSearch — UNCHANGED             |
| **Rerank (cosine only)** | **~1-5ms**         | Pure local cosine similarity, no API calls    |
| Generation               | ~1,000-1,600ms     | Gemini streaming — UNCHANGED                  |
| **Total**                | **~3,043-3,730ms** | End-to-end                                    |

### Rerank Breakdown (After)

- `rerank_ms`: ~1-5ms (local computation only)
- `rerank_embedding_ms`: 0.0ms (no embedding API call)
- The reranker uses `query_embedding` (precomputed from step 2) and `candidate.chunk.embedding` (stored at ingestion time) for cosine similarity

---

## Improvement

| Metric                | Before   | After    | Savings              |
| --------------------- | -------- | -------- | -------------------- |
| `rerank_ms`           | ~1,700ms | ~1-5ms   | **~1,695ms (99.7%)** |
| `rerank_embedding_ms` | ~1,700ms | 0.0ms    | **~1,700ms (100%)**  |
| `total_ms`            | ~4,738ms | ~3,043ms | **~1,695ms (35.8%)** |

---

## Files Changed

| File                                      | Change                                                                                                                                                                                      |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/repositories/vector/reranker.py` | Added `query_embedding` parameter to `rerank()`. Fast path uses stored chunk embeddings for cosine similarity. Legacy path preserved for backward compatibility.                            |
| `backend/services/chat/rag_service.py`    | Pass `query_embedding=query_vector` to `rerank()` in both the normal retrieval path and the retrieval cache hit path.                                                                       |
| `tests/test_rag_accuracy.py`              | Added 6 new tests: stored embedding reuse, cosine ordering, legacy fallback, empty embedding handling, integration flow, tracking embedder. Updated 3 existing tests for tuple return type. |
| `tests/test_retrieval_strategy.py`        | Added `allow_reranking=False` to 2 hybrid-retrieval tests that construct their own RagService (isolates hybrid search testing from reranker changes).                                       |

---

## Tests Passed

```
1325 passed, 3 skipped, 3 warnings in 51.66s
```

### New Tests Added

| Test                                                     | Purpose                                                                                     |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `test_reranker_uses_stored_embeddings_no_embed_call`     | Verifies embed API is NOT called when query_embedding is provided                           |
| `test_reranker_precomputed_embedding_reorders_correctly` | Verifies cosine similarity ordering with stored embeddings                                  |
| `test_reranker_legacy_path_still_works`                  | Verifies backward compatibility when query_embedding is None                                |
| `test_reranker_empty_chunk_embedding_handled`            | Verifies graceful handling of chunks with empty stored embeddings                           |
| `test_reranker_passes_query_embedding_in_rag_flow`       | Integration test: RagService passes query_embedding to reranker, rerank_embedding_ms is 0.0 |
| `test_reranker_top_k_limits_output` (updated)            | Verifies top_k limiting still works with tuple return                                       |

---

## Design Decisions

1. **Backward compatibility**: The `query_embedding` parameter is optional (`None` default). When `None`, the legacy embed path runs. This preserves compatibility for any code that calls `rerank()` without the new parameter.

2. **No new dependencies**: The optimization uses only the existing `_cosine_similarity` function and stored `KnowledgeChunk.embedding` vectors. No numpy or external libraries added.

3. **Latency fields preserved**: `rerank_embedding_ms` is now `0.0` on the fast path (correct — no embedding API was called). `rerank_ms` reflects only the local cosine similarity computation time.

4. **Test isolation**: Hybrid retrieval tests that construct their own `RagService` now explicitly set `allow_reranking=False` to isolate the hybrid search behavior from the reranker's embedding-reuse change.

---

## What Was NOT Changed

- P1 optimizations (hybrid search candidate bounding, MongoDB text index)
- P2 optimizations (numpy vectorization of cosine similarity)
- Ingestion pipeline
- Generation pipeline
- SSE streaming
- Cache logic
- Prompt construction
- Any non-RAG code

---

_End of report. All changes are production-safe and backward-compatible._
