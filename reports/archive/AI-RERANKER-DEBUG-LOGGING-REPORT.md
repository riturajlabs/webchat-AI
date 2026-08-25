# Reranker Debug Logging Report

## Change Summary

Added temporary debug logging to `EmbeddingReranker.rerank()` in
`backend/repositories/vector/reranker.py`.

## What Was Added

### Before-rerank logging (lines 91-106)

Logged once per `rerank()` call when `DEBUG=true`:

| Field             | Description                            |
| ----------------- | -------------------------------------- |
| `query`           | Full query text (repr-encoded)         |
| `candidate_count` | Number of candidates entering reranker |

Per candidate:

| Field            | Description                                    |
| ---------------- | ---------------------------------------------- |
| `idx`            | Original position (0-based)                    |
| `chunk_id`       | `KnowledgeChunk.id`                            |
| `title`          | `chunk.metadata["title"]`                      |
| `score`          | Score before reranking (4 decimal places)      |
| `chunk_text_150` | First 150 chars of `chunk_text` (repr-encoded) |

### After-rerank logging (lines 206-224)

Logged once per successful reranking (fast path and legacy path) when
`DEBUG=true`:

| Field            | Description                       |
| ---------------- | --------------------------------- |
| `query`          | Full query text (repr-encoded)    |
| `reranked_count` | Number of results after reranking |

Per result:

| Field            | Description                                      |
| ---------------- | ------------------------------------------------ |
| `idx`            | New position after reranking (0-based)           |
| `chunk_id`       | `KnowledgeChunk.id`                              |
| `title`          | `chunk.metadata["title"]`                        |
| `score`          | Final cosine similarity score (4 decimal places) |
| `chunk_text_150` | First 150 chars of `chunk_text` (repr-encoded)   |

### Implementation details

- Uses `logger.isEnabledFor(logging.DEBUG)` guard — zero overhead when DEBUG
  is disabled.
- Before-rerank logging is inline in the method (runs once per call).
- After-rerank logging extracted to `_log_rerank_after()` helper to avoid
  duplication across the fast path (line 139) and legacy path (line 197).
- No logic changes. No scoring changes. No retrieval changes.
- Fallback returns (embed failure, count mismatch, empty candidates) do not
  emit after-rerank logs since no actual reranking occurred.

## Files Changed

| File                                      | Lines                     | Change              |
| ----------------------------------------- | ------------------------- | ------------------- |
| `backend/repositories/vector/reranker.py` | 91-106, 139, 197, 206-224 | Added debug logging |

## Test Results

```
1340 passed, 2 skipped in 63.82s
ruff check: All checks passed
```

## Example Output (DEBUG=true)

```
DEBUG:webchat_ai:rerank_before query='What courses does Indira offer?' candidate_count=5
DEBUG:webchat_ai:rerank_candidate_before idx=0 chunk_id=abc123 title=Courses score=0.8543 chunk_text_150='Indira University offers Bachelor of Arts...'
DEBUG:webchat_ai:rerank_candidate_before idx=1 chunk_id=def456 title=Admissions score=0.7211 chunk_text_150='The admission process for the 2025-26...'
...
DEBUG:webchat_ai:rerank_after query='What courses does Indira offer?' reranked_count=5
DEBUG:webchat_ai:rerank_candidate_after idx=0 chunk_id=def456 title=Admissions score=0.9127 chunk_text_150='The admission process for the 2025-26...'
DEBUG:webchat_ai:rerank_candidate_after idx=1 chunk_id=abc123 title=Courses score=0.8543 chunk_text_150='Indira University offers Bachelor of Arts...'
...
```

## Removal

This logging is temporary. To remove, delete:

1. Lines 91-106 (before-rerank inline logging)
2. The `_log_rerank_after(query, reranked)` calls on lines 139 and 197
3. The `_log_rerank_after()` function on lines 206-224
