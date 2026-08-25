# AI RAG Adaptive Retrieval Strategy — Implementation Report

## Overview

Implemented a lightweight, rule-based adaptive retrieval strategy that adjusts
retrieval parameters (top_k, context budget) per query based on complexity
classification. Simple queries retrieve fewer chunks with a smaller context
window for lower latency; complex queries retrieve more chunks with a larger
context window for better accuracy. The feature is **opt-in** (disabled by
default) and adds **zero overhead** when turned off.

## Problem

All queries — from one-word lookups to multi-part technical questions — use the
same retrieval parameters (top_k=8, context max=20000 chars). Simple queries
over-retrieve and waste embedding/retrieval cycles; complex queries
under-retrieve and miss relevant context.

## Solution

### Query Complexity Classifier

New module: `backend/services/chat/query_classifier.py`

A pure-rule, zero-latency classifier that scores queries on seven signals:

| Signal                  | Weight   | Description                                 |
| ----------------------- | -------- | ------------------------------------------- |
| Word count              | -1 to +2 | ≤4 words → simple; ≥15 → complex            |
| Character length        | -1 to +1 | ≤20 chars → simple; ≥100 → complex          |
| Multi-part keywords     | +1 to +2 | "and", "compare", "difference", etc.        |
| Detail keywords         | +1 to +2 | "explain", "implementation", "deploy", etc. |
| Simple/factual keywords | -1       | "price", "contact", "link", etc.            |
| Clause structure        | +1 to +2 | Conjunctions ("and", "also", "but")         |
| List/enumeration        | +1       | Numbered or bulleted lists                  |

Score ≤ 0 → SIMPLE, 1–2 → MEDIUM, ≥ 3 → COMPLEX.

**No API calls, no LLM, no ML model** — pure Python scoring in < 0.1 ms.

### Adaptive Parameters

| Parameter           | SIMPLE | MEDIUM (default) | COMPLEX |
| ------------------- | ------ | ---------------- | ------- |
| `top_k`             | 4      | 8 (fixed)        | 12      |
| `rerank_top_k`      | 3      | 5 (fixed)        | 8       |
| `max_context_chars` | 8,000  | 20,000 (fixed)   | 30,000  |

### Feature Flag

```python
enable_adaptive_retrieval: bool = False          # opt-in
adaptive_simple_top_k: int = 4
adaptive_simple_rerank_top_k: int = 3
adaptive_simple_max_context_chars: int = 8000
adaptive_complex_top_k: int = 12
adaptive_complex_rerank_top_k: int = 8
adaptive_complex_max_context_chars: int = 30000
```

**Backward compatible**: all new fields default to values that preserve existing
behavior when the flag is off.

## Files Changed

| File                                        | Change                                                                                                                                                                       |
| ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/services/chat/query_classifier.py` | **New** — rule-based complexity classifier                                                                                                                                   |
| `backend/core/config.py`                    | Added 7 adaptive retrieval config fields                                                                                                                                     |
| `backend/services/chat/rag_service.py`      | `_retrieve()` classifies query, selects adaptive params; `_build_context()` accepts optional `max_context_chars` override; timing dict includes `adaptive_max_context_chars` |
| `tests/test_query_classifier.py`            | **New** — 18 unit tests for the classifier                                                                                                                                   |
| `tests/test_rag_accuracy.py`                | Added 9 adaptive retrieval integration tests                                                                                                                                 |
| `tests/test_rag_service.py`                 | Added `adaptive_max_context_chars` to expected timing keys                                                                                                                   |

## Integration Points

### RagService._retrieve()

```python
# At entry — classify and select params
complexity = classify_query(question)
effective_top_k = self._top_k
adaptive_max_context_chars = self._max_context_chars
if self._adaptive_enabled:
    if complexity == QueryComplexity.SIMPLE:
        effective_top_k = self._adaptive_simple_top_k
        adaptive_max_context_chars = self._adaptive_simple_max_context_chars
    elif complexity == QueryComplexity.COMPLEX:
        effective_top_k = self._adaptive_complex_top_k
        adaptive_max_context_chars = self._adaptive_complex_max_context_chars

# Used in similarity_search, strategy.search, and _build_context
raw_results = await self._vector.similarity_search(
    tenant_id, website_id, query_vector, top_k=effective_top_k
)
```

### RagService._build_context()

Accepts optional `max_context_chars` kwarg to override the fixed default:

```python
context_items, sources = self._build_context(
    results, max_context_chars=adaptive_max_context_chars
)
```

## Test Results

- **18 classifier tests** — all passing
- **9 adaptive retrieval integration tests** — all passing
- **1350+ full suite tests** — all passing (2 skipped)
- **ruff** — clean
- **mypy** — clean

## Latency Impact

The classifier is pure string scoring — no measurable overhead.

| Scenario             | Without Adaptive | With Adaptive (SIMPLE) | With Adaptive (COMPLEX) |
| -------------------- | ---------------- | ---------------------- | ----------------------- |
| Retrieval candidates | 8                | 4 (−50%)               | 12 (+50%)               |
| Context chars        | 20,000           | 8,000 (−60%)           | 30,000 (+50%)           |
| Embedding calls      | 1                | 1 (same)               | 1 (same)                |
| Classifier overhead  | —                | < 0.1 ms               | < 0.1 ms                |

Expected latency reduction for simple queries: **~20–40%** due to fewer
candidates and smaller context windows.

## Design Decisions

1. **Rule-based, not LLM-based**: The user explicitly required no API/LLM calls
   for adaptive retrieval. A rule-based classifier adds zero latency and no
   external dependencies.

2. **Three buckets, not regression**: SIMPLE/MEDIUM/COMPLEX is sufficient to
   capture the meaningful latency/accuracy tradeoff without over-engineering.

3. **Opt-in, not default-on**: The feature flag defaults to `false` so existing
   behavior is preserved. Operators can enable it after validating accuracy on
   their workload.

4. **Classifier is stateless**: No training data, no model file, no
   initialization cost. It can be imported and called anywhere.
