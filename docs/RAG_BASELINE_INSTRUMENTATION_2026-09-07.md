# RAG Pipeline Baseline Instrumentation Report

**Date:** 2026-09-07
**Scope:** Baseline (measurement-only) instrumentation of the WebChat AI
retrieval + generation pipeline. No production behavior was optimized or
changed in this run; writes to production data, ingestion, and real LLM calls
were not performed. All verification is synthetic (fakes).

---

## 1. Objective

Production-harden the RAG accuracy + latency stack by establishing a
repeatable baseline:

- **Product targets:**
  - TTFT P95 ≤ 3s
  - Retrieval P95 ≤ 500ms
  - Warm/cache-hit retrieval ≤ 100–200ms
  - Strict per-widget/customer corpus isolation (no cross-site content leaks)

- **Baseline deliverables:** per-stage Prometheus percentile histograms,
  cross-site isolation accuracy fixtures, corpus-scale latency benchmarks,
  event-loop blocking classification, and this report.

---

## 2. Changes Introduced

All changes are **measurement/instrumentation + test fixtures only**. No
ranking, retrieval, generation, or caching behavior was altered.

### 2.1 Per-stage Prometheus percentile histogram

`backend/core/metrics.py`:

- Added `RAG_STAGE_LATENCY_SECONDS` histogram
  (`rag_stage_latency_seconds`) with labels `(stage, cache_status)`.
- Discrete latency buckets tuned for the ms→seconds range:
  `0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0` seconds.
- Added `record_rag_stage_latency(stage, duration_seconds, cache_status="")`.
- The schema is fixed and tenant-safe (no tenant/website ids as label values),
  consistent with the existing registry's cardinality rules.

`backend/services/chat/rag_service.py` — in `stream_answer`, at the point where
the completed-turn timing data is already computed, each stage's measured
duration is observed into the histogram:

- `embedding` (cache_status = hit/miss)
- `vector_search` (cache_status = hit/miss)
- `load_chunks`
- `rerank`
- `context`
- `history`
- `generation`
- `persist`
- `total`

These reuse durations already captured by `stream_answer` (they feed the
`timing` dict / `_log_rag_timing`), so there is **no recomputation** — a pure
observation wire-in. Prometheus computes P50/P95/P99 from cumulative buckets.

### 2.2 Cross-site isolation accuracy fixtures

`tests/test_rag_baseline_accuracy.py` — a two-site corpus under the same
tenant (Site A: BCA home-loan fee ₹80,000; Site B: ICICI home-loan fee
₹65,000) exercising the exact-cross-site boundary:

- `test_cross_site_isolation_same_query_different_sources`
- `test_cross_site_no_content_leak` (Site A must not surface Site B's ICICI/₹65,000)
- `test_cross_site_opposite_direction` (Site B must not surface Site A's BCA/₹80,000)
- Query-type retrieval tests: exact-match, short, broad, paraphrase, follow-up
- Recall@k and MRR metric helpers

### 2.3 Corpus-scale benchmarks

`tests/test_rag_baseline_benchmark.py` — synthetic corpora at 100 / 500 / 1K /
5K chunks with mock backends, recording latency bounds and hybrid-keyword and
cache-hit path behavior. All use `install_relevance_scoring` for deterministic
retrieval.

---

## 3. Event-Loop Blocking Classification

Each per-stage operation during a chat turn was classified by whether it runs
on the asyncio event loop (A = blocking, must move off-loop; B = off-loop;
C = on-loop but negligible).

| Stage          | Operation                                                | Class                       | Notes                                                                                                                                                                                                                                                                    |
| -------------- | -------------------------------------------------------- | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| embedding      | model inference (`_embed_question`)                      | A→await                     | network I/O, awaited (correct)                                                                                                                                                                                                                                           |
| vector search  | Atlas `$vectorSearch`                                    | await                       | Mongo I/O, on-loop await (correct)                                                                                                                                                                                                                                       |
| vector search  | brute-force cosine fallback (`mongodb.py:_score_corpus`) | **B (off-loop)**            | wrapped in `asyncio.to_thread` (audit A-02) — verified `mongodb.py:379`                                                                                                                                                                                                  |
| hybrid keyword | full-corpus tokenize + TF-IDF scoring                    | **B (off-loop)**            | `_run_retrieval_strategy` wraps `HybridRetrievalStrategy.search` in `asyncio.to_thread` (PERF-K01) — verified `rag_service.py:483-490`                                                                                                                                   |
| load_chunks    | lexical corpus load (`_load_all_chunks`)                 | **A ⚠️ on-loop**            | `json.loads(raw)` + `KnowledgeChunk(**item)` deserialization runs on the event loop (`rag_service.py:1725-1727`); a large cached corpus costs a single-thread JSON/Cython-obj parse on the loop. On a cold cache it is a `list_chunks_light` DB await. See Finding F-01. |
| rerank         | cosine over ≤ rerank_top_k candidates                    | **C (on-loop, negligible)** | small fixed candidate cap (`reranker.py`), no `to_thread`; bounded and cheap                                                                                                                                                                                             |
| context        | truncation / dedup / compression                         | C (on-loop, small)          | bounded by `max_context_chars`                                                                                                                                                                                                                                           |
| history        | DB read                                                  | await                       | background task, awaited (correct)                                                                                                                                                                                                                                       |
| faithfulness   | token-overlap check                                      | C (on-loop, small)          | bounded by answer+context length                                                                                                                                                                                                                                         |
| persist        | DB writes                                                | await                       | awaited (correct)                                                                                                                                                                                                                                                        |

**Classification legend:**

- **A** — pure-Python CPU or JSON-parsing work on the event loop that can
  stall the loop for all concurrent requests (not merely the current one).
- **B** — same class of work but already correctly off-loaded to a worker
  thread or awaited I/O.
- **C** — on-loop but tightly bounded in size, so it does not qualify as a
  stall risk.

### 3.1 Findings

- **F-01 (on-loop JSON deserialization):** on a lexical-corpus cache hit,
  `_load_all_chunks` deserializes the full website corpus
  (`json.loads` + Pydantic object construction) directly on the event loop.
  For a ~2162-chunk production corpus this is tens of ms of single-thread CPU
  on the loop on every uncached-keyword chat turn. It is **not** moved to a
  worker thread (unlike the cosine fallback and hybrid keyword pass).

- **F-02 (cache-hit still re-runs keyword search):** on a retrieval-cache hit
  the pipeline still loads the full lexical corpus and runs hybrid keyword
  search + potential rerank (100–300ms) — the same cost as a miss. This is a
  latency target for the 100–200ms warm-hit requirement.

- **F-03 (no before/after latency baseline):** the new
  `rag_stage_latency_seconds` histograms are the first percentile-capable
  per-stage sink; nothing prior recorded these with Prometheus percentiles.

---

## 4. Baseline Targets vs. Instrumentation Coverage

| Target                     | Instrumented?                                | Histogram                                          |
| -------------------------- | -------------------------------------------- | -------------------------------------------------- |
| TTFT P95 ≤ 3s              | ✅ (SSE `first_token_ms`)                    | `ai_ttft_seconds`                                  |
| Retrieval P95 ≤ 500ms      | ✅                                           | `rag_stage_latency_seconds{stage="vector_search"}` |
| Warm/cache-hit ≤ 100–200ms | ✅ (embedding/vector_search hit/miss series) | `rag_stage_latency_seconds{cache_status="hit"}`    |
| Cross-site isolation       | ✅ (fixtures + existing validation tests)    | n/a                                                |

---

## 5. Verification Summary

- `ruff check` — clean on all modified files.
- `mypy` — no issues on `metrics.py` / `rag_service.py`.
- New fixtures + benchmarks: all pass.
- Existing RAG / metrics suites: all pass (no regressions).
- No production writes, no real LLM/embedding calls, no external API calls;
  no commits or pushes made.

---

## 6. Suggested Next Steps (behavioral, out-of-baseline)

- Move the lexical-corpus JSON deserialization in `_load_all_chunks` off the
  event loop (parallel to `_run_retrieval_strategy`) — addresses F-01.
- Short-circuit the cache-hit path to skip corpus load + keyword search when
  scores are already cached (addresses F-02) and verify against
  `rag_stage_latency_seconds{cache_status="hit"}`.
- Rebuild pre/post comparisons against this baseline once those land.
