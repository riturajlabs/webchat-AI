# RAG Context Quality Optimization — Implementation Report

## Overview

Added near-duplicate chunk removal and sentence-level context compression to
the RAG context building pipeline. Reduces unnecessary tokens sent to the LLM
while preserving unique information from each source. No LLM calls, no external
dependencies.

## Problem

The existing `_build_context` performs exact dedup (same doc_id, same text)
but misses near-duplicate chunks from different sources (e.g. re-crawled pages
with minor wording differences).

## Solution

### Context Optimizer Module

New module: `backend/services/chat/context_optimizer.py`

- **Near-duplicate removal** — Word-level Jaccard similarity; chunks with >=75%
  word overlap to an already-kept chunk are dropped.
- **Sentence-level compression** — Each sentence checked against an accumulated
  set from earlier chunks. Redundant sentences stripped, unique content kept.
- **Metrics** — `OptimizationMetrics` tracks original/optimized chars, removed
  chunks, removed sentences, and savings percentage.

### Integration in `_build_context`

Refactored into three phases:

```
Phase 1: Exact dedup + min-score filter (always runs)
Phase 2: Context optimization (opt-in)
  2a. Near-duplicate removal (Jaccard >= 0.75)
  2b. Sentence-level compression (cross-chunk dedup)
Phase 3: Budget capping (always runs)
```

When disabled (default), Phase 2 is skipped entirely.

### Feature Flag

```python
enable_context_optimization: bool = False
```

### Tracked Metrics (in timing dict)

| Metric                    | Description                       |
| ------------------------- | --------------------------------- |
| `original_context_chars`  | Total chars before optimization   |
| `optimized_context_chars` | Total chars after optimization    |
| `removed_chunks_count`    | Chunks dropped as near-duplicates |

All three are `None` when optimization is disabled.

## Files Changed

| File                                         | Change                                                                        |
| -------------------------------------------- | ----------------------------------------------------------------------------- |
| `backend/services/chat/context_optimizer.py` | **New** — similarity, dedup, compression, metrics                             |
| `backend/core/config.py`                     | Added `enable_context_optimization` flag                                      |
| `backend/services/chat/rag_service.py`       | Refactored `_build_context` into 3-phase pipeline; metrics in timing + logger |
| `tests/test_context_optimizer.py`            | **New** — 25 unit tests                                                       |
| `tests/test_rag_accuracy.py`                 | 7 integration tests                                                           |
| `tests/test_rag_service.py`                  | Added optimization metric keys to expected timing set                         |

## Test Results

- 25 context optimizer unit tests — all passing
- 7 integration tests — all passing
- 1409 full suite tests — all passing (3 skipped)
- ruff — clean
- mypy — clean

## Design Decisions

1. **Three-phase pipeline**: Separating exact dedup, optimization, and budget
   capping makes each phase independently testable and the disabled path zero-cost.
2. **Jaccard 0.75 threshold**: Conservative; catches near-duplicates while
   preserving legitimately different content.
3. **Frozen ContextItem**: Compression creates new ContextItem instances rather
   than mutating the frozen dataclass.
4. **Cross-chunk compression**: The `seen_sentences` set accumulates across
   chunks so duplicate sentences across different sources are also stripped.
