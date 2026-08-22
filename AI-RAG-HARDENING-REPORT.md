# AI RAG Production Hardening Report

**Date:** 2026-08-20
**Scope:** Targeted production hardening fixes from `AI-RAG-FULL-PRODUCTION-AUDIT-REPORT.md`
**Constraint:** No redesigns — only fix identified low/medium bugs and mark dead code.

---

## 1. Faithfulness Scoring Fix

**File:** `backend/services/chat/rag_service.py:1230`
**Bug:** `_check_faithfulness()` returned `1.0` for empty answers and counted trivial short sentences (no significant words) as faithful.

### Changes

| Condition                                         | Before               | After                  |
| ------------------------------------------------- | -------------------- | ---------------------- |
| Empty answer `""`                                 | `1.0`                | `0.0`                  |
| Sentence with no words > 3 chars (e.g. "Hi. Ok.") | Counted as supported | Counted as unsupported |
| Sentence with significant words                   | Unchanged            | Unchanged              |

**Rationale:** An empty answer cannot be faithful to anything. Sentences with no significant words (alpha, >3 chars) contribute no verifiable content and should not inflate the score. This is a monitoring-only signal (not a generation gate), but inaccurate scores degrade alert quality.

### Tests Updated

- `test_faithfulness_empty_answer` — now asserts `== 0.0` (was `== 1.0`)
- `test_faithfulness_short_sentences_supported` → renamed `test_faithfulness_short_sentences_unsupported` — now asserts `== 0.0`
- **New:** `test_faithfulness_short_sentence_with_long_words_supported` — sentences with enough significant words still score `1.0`

---

## 2. Retrieval Cache Invalidation on Crawl Completion

**Files:**

- `backend/workers/jobs/crawl.py` — `_run_crawl_job()` now accepts `cache: CacheStore | None`
- `backend/core/cache.py` — `CacheStore` protocol + `RedisCacheStore` gain `delete_by_prefix(namespace, prefix)`

### Design

- After a crawl completes successfully, the worker calls `cache.delete_by_prefix("retrieval", f"{website_id}:")` to evict all stale retrieval cache entries for that website.
- The call is **best-effort**: wrapped in `try/except` so a Redis outage never fails the crawl job.
- Only the affected `website_id` is invalidated — no global cache flush.
- `_build_cache()` in `crawl.py` constructs a `RedisCacheStore` from `settings.redis_url`, returning `None` on failure.

### CacheStore Protocol Change

```python
# Added to CacheStore Protocol (backend/core/cache.py)
async def delete_by_prefix(self, namespace: str, prefix: str) -> int: ...
```

Returns the count of deleted keys. Uses Redis `SCAN` with `match` + `count=100` to avoid blocking on large key sets.

### Fake Implementations Updated

- `FakeCacheStore` — in-memory prefix match + delete
- `FakeBrokenCacheStore` — raises `ConnectionError` (tests best-effort path)

### Tests Added

- `test_worker_invalidates_retrieval_cache_on_completion` — seeds cache with 3 entries (2 for target website, 1 for other), verifies only target entries are evicted after crawl
- `test_worker_cache_invalidation_is_best_effort` — injects `BrokenCache` that always raises, verifies crawl still completes

---

## 3. Dead Code Deprecation

### `_load_all_chunks` (rag_service.py:1007)

**Status:** Dead code. The production `_retrieve()` flow always passes `all_chunks=None` to the retrieval strategy. `HybridSearcher` ignores the `all_chunks` parameter (marked as "Deprecated compatibility parameter" at `hybrid.py:297`). Keyword search is restricted to `vector_results` only.

**Action:** Added `.. deprecated::` docstring noting it is dead code, retained for potential future full-scan keyword mode.

### `list_chunks_light` (base.py:37, mongodb.py:92, fakes.py:852)

**Status:** Dead code. No production code path calls it. Keyword scoring was refactored to operate on vector-search results only, making the lightweight chunk load unnecessary.

**Action:** Added `.. deprecated::` docstring in Protocol (`base.py`), MongoDB implementation (`mongodb.py`), and `FakeVectorRepository` (`fakes.py`).

---

## 4. Verification

| Check                                  | Result                     |
| -------------------------------------- | -------------------------- |
| `uv run pytest tests/`                 | **1362 passed**, 2 skipped |
| `uv run ruff check backend/`           | All checks passed          |
| `uv run ruff check tests/`             | All checks passed          |
| `uv run mypy backend/` (changed files) | Success: no issues found   |

---

## 5. Files Modified

| File                                     | Change                                                                                             |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `backend/services/chat/rag_service.py`   | Fix `_check_faithfulness()` empty/trivial sentence handling; deprecate `_load_all_chunks`          |
| `backend/core/cache.py`                  | Add `delete_by_prefix` to `CacheStore` protocol + `RedisCacheStore`                                |
| `backend/repositories/vector/base.py`    | Deprecate `list_chunks_light` in Protocol                                                          |
| `backend/repositories/vector/mongodb.py` | Deprecate `list_chunks_light`                                                                      |
| `backend/workers/jobs/crawl.py`          | Add cache invalidation after successful crawl; add `_build_cache()`                                |
| `tests/fakes.py`                         | Add `delete_by_prefix` to `FakeCacheStore` + `FakeBrokenCacheStore`; deprecate `list_chunks_light` |
| `tests/test_rag_accuracy.py`             | Fix faithfulness tests; add `test_stale_retrieval_prevented_after_cache_invalidation`              |
| `tests/test_crawl_worker.py`             | Add `test_worker_invalidates_retrieval_cache_on_completion` + best-effort test                     |

---

## 6. What Was NOT Changed (by design)

- Embedding models or providers
- Atlas Vector Search index configuration
- Retrieval algorithm (RRF, hybrid scoring, reranker)
- Prompt templates or system instructions
- LLM provider configuration
- Confidence formula or thresholds
- Cache TTL values
- Min-score filtering logic

---

## 7. Outstanding Items (not addressed — out of scope)

| Item                                              | Severity | Rationale                                                                                  |
| ------------------------------------------------- | -------- | ------------------------------------------------------------------------------------------ |
| `_load_all_chunks` full removal                   | LOW      | Dead code but removing it requires updating the Protocol which affects all implementations |
| `list_chunks_light` full removal                  | LOW      | Same as above — deprecation markers are sufficient for now                                 |
| Confidence formula degradation when `min_score=0` | LOW      | Monitoring-only signal; primary defense is pre-generation confidence gate                  |
| Injection detection logging-only                  | LOW      | By design — system prompt rule 5 is primary defense                                        |
