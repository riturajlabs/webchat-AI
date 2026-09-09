# RAG TTFT: Embedding Stage Optimization — Write-Behind Cache SET (RAG-PERF-05)

Date: 2026-09-08 · Branch: `main` · Stack: production docker compose (Upstash Redis, Atlas Mongo, Gemini embedding)
Task: measure the real cost of the RAG cache-miss **embedding stage** and, if proven reducible without
changing retrieval/ranking/thresholds/prompts/isolation, ship the **single smallest safe optimization**.

---

## 1. Scope & objective

- Client-first-message TTFT target: **P95 < 3000 ms**.
- RAG-PERF-05: is **embEDDING on the RAG cache-miss path** still a seconds-level bottleneck, is it safely
  reducible, and if so what is the smallest correct change?
- Explicitly out of scope (unchanged): retrieval strategy, RRF/ranking weights, `top_k`, score/confidence
  thresholds, prompts, tenant/website isolation, provider order/routing, embedding model/dimensions.
- Every number below is labelled **MEASURED** (instrumented against the real stack), **DERIVED**
  (composed from measured numbers), or **UNMEASURED** (reasoned/unknown). No SYNTHETIC numbers are used.

## 2. Environment & methodology

- API container `webchat-api` (:8000), production settings loaded from the container env:
  `EMBEDDING_PROVIDER_ORDER=['gemini','jina','cohere']`, `gemini-embedding-001`, 1024 dims,
  `EMBEDDING_VERSION=1`, cache size 256, TTL 3600 s, `UVICORN_WORKERS=1`.
- Two independent measurement rigs:
  - **Controlled in-container probe** — real `RedisCacheStore` + real fallback chain, fresh question per
    iteration (genuine cache-miss), times the full embedding stage and/or its sub-operations.
  - **Live client-facing benchmark** — authenticated `POST /api/chat/stream` on tenant B
    (`website_id 2e8632b4-…`), fresh paraphrases of canonical corpus questions so each request is a real
    cache-miss AND passes the deterministic answerability gate; captures client first-delta TTFT and the
    server `done`-frame timing block (`embedding_ms`, `ttft_ms`, …).
- Deployment for the AFTER phase: the single changed source file was copied into the container
  (`docker cp`) and `webchat-api` restarted; confirmed the running interpreter imports the new module and
  the health endpoint returns 200.

## 3. Baseline (BEFORE)

**Measured — cache-miss embedding stage = the `_embed_question` call**, same path in every run:

| Embedding stage (ms)                      | N   | mean | p50      | p95  | notes                                         |
| ----------------------------------------- | --- | ---- | -------- | ---- | --------------------------------------------- |
| Controlled in-container (BEFORE)          | 12  | 1866 | **1586** | 3030 | includes synchronous cache SET                |
| Live `done`-frame `embedding_ms` (BEFORE) | 10  | 2811 | **2475** | 4549 | cache-miss answered requests; row 1 cold 6199 |

**Derived (referenced)** earlier production audit REAL-TTFT-02: embedding mean ≈ 1494 ms, p95 ≈ 2634 ms on
cache-miss — consistent with the controlled 1586 ms p50.

## 4. Decomposition of the cache-miss embedding stage (MEASURED, in-container, N=12)

| Sub-operation                                | p50 (ms) | mean (ms) | p95 (ms) |
| -------------------------------------------- | -------- | --------- | -------- |
| GET (cache miss, upstash RTT)                | 328      | 424       | 869      |
| Provider call (Gemini, `batchEmbedContents`) | 544      | 717       | 1439     |
| GET (single-flight re-check)                 | 295      | 295       | 309      |
| **SET (synchronous write-back)**             | **417**  | 429       | 488      |
| **Stage total (before change)**              | **1586** | 1866      | 3030     |

- The provider itself is fast (~540 ms p50); the 3 sequential Redis round-trips dominate (~1.04 s ≈ 66%).
- **DERIVED**: the cache SET (~417 ms, 26% of the stage) is inside the critical path of `_embed_question`,
  yet its result is consumed **only by future callers** — the current request never reads it back. It is
  pure future-benefit work placed in front of retrieval, load_chunks, rerank, context build, and generation.

## 5. Root cause

1. `_embed_question` awaits `cache.set(...)` inline (MEASURED ~417 ms) before the retrieval pipeline can
   continue. The write is not needed to answer the current question.
2. Two up-stack effects amplify it: `embedding_ms` gates the first SSE `sources`/`message` frame on the
   client; and the whole embedding stage is serialized with `retrieval_ms`, `history_task` overlap only
   covering the history read.

## 6. Candidates considered (and disposition)

| Candidate                                                  | Expected saving   | Disposition                                                                                    |
| ---------------------------------------------------------- | ----------------- | ---------------------------------------------------------------------------------------------- |
| **A. Defer the embedding cache SET (write-behind)**        | ~420 ms p50 stage | **CHOSEN (below)**                                                                             |
| B. Drop the single-flight re-check GET                     | ~295 ms           | **Rejected** — breaks BE-Q01 completion-boundary race; dedicated test pins it                  |
| C. Reorder: consult `_embed_inflight` before the first GET | ~320 ms           | **Rejected** — only helps concurrent-identical requests; does not help the single-request path |
| D. Provider/model/dimension changes                        | variable          | Forbidden by scope (rules)                                                                     |
| E. Remove per-request client construction                  | ~0 measured       | Measured not material; genai transport is shared process-wide                                  |

**Chosen (A)**: eliminate the synchronous SET from the critical path by running it as a background task,
while keeping the single-flight key claimed until the write settles.

## 7. Chosen optimization — write-behind cache SET

Location: `backend/services/chat/rag_service.py` → `_embed_question`.

- Resolve the single-flight future immediately after the provider returns the vector; waiters are no longer
  blocked by Redis.
- Schedule `self._cache.set("embed", key, payload, ttl)` as a background `asyncio.Task`.
- **Keep the single-flight key in `_embed_inflight` until the write settles**: a caller arriving mid-write
  shares the already-resolved future instead of opening a duplicate provider call (BE-Q01 coalescing window
  is preserved — the re-check/coalescing guarantee is unchanged).
- Done-callback: swallow/log write errors (cache is fail-open by design), release the key (success, error,
  or cancellation), remove the task from the tracked set.
- Tasks are held by strong ref (`self._embedding_write_tasks`) so the event loop does not GC a pending task.

### Safety semantics preserved (all verified by tests)

- Exactly-one-embed for concurrent identical misses (BE-Q01) — `test_*_coalesce_*` still passes.
- Owner re-checks the cache after winning the key — `test_owner_rechecks_cache_after_claiming_key_*`.
- Failure propagation to owner + waiters; no stale in-flight entry — `test_single_flight_failure_*`.
- Cache write is **eventually** consistent: a mid-write caller shares the flight (not the cache entry, so
  `cache_hit=False` reporting is unchanged and accurate).
- `_embedding_write_tasks == set()` and `_embed_inflight == {}` after every settled path.

## 8. Implementation & diff

Files touched (3):

| File                                   | Change                                                                                                                                                             |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `backend/services/chat/rag_service.py` | `__init__`: add `_embedding_write_tasks`. `_embed_question`: write-behind SET + done-callback key release + `write_pending` guard in `finally`. Docstring updated. |
| `tests/fakes.py`                       | `BlockingWriteCacheStore`, `WriteFailureCacheStore` (inherits `FakeCacheStore`); `import asyncio`.                                                                 |
| `tests/test_rag_service.py`            | 3 new regression tests (no-block+coalescing, fail-open, cancellation) + imports.                                                                                   |

Full re-run baseline (BEFORE-DEPLOY): container file == working-tree file exactly except the PERF-05 edits
(verified by container diff). All other working-tree modifications are pre-existing (repo was already 81
files dirty; untouched).

## 9. Regression & static checks

- Focused: single-flight, coalescing, re-check, write-behind, cache hit/miss/TTL, no-cache fallback — pass.
- RAG suites (`test_rag_service.py`, `test_rag_baseline_benchmark.py`,
  `test_rag_perf_f02_cached_results.py`, `test_rag_perf_f03_offload_lexical.py`, `test_embedding.py`,
  `test_hybrid_search.py`): **152 passed**.
- **Full suite: 2209 passed, 8 skipped (84 s)**.
- `ruff check` on changed files: clean. `mypy backend` (CI gate): **Success, 199 files**.

## 10. AFTER measurements

**Measured — cache-miss embedding stage with write-behind live:**

| Embedding stage (ms)                     | N   | mean  | p50      | p95   | notes                                            |
| ---------------------------------------- | --- | ----- | -------- | ----- | ------------------------------------------------ |
| Controlled in-container (AFTER)          | 10  | 1518* | **1026** | 3640* | *cold-start 4812 + Redis jitter inflate mean/p95 |
| Controlled steady rows 7–10              | 4   | 862   | 861      | —     | quiescent tail                                   |
| Live `done`-frame `embedding_ms` (AFTER) | 9   | 919   | **898**  | 1066  | cache-miss answered requests                     |
| Live log `retrieval.embed` stage (AFTER) | 27  | 988   | **917**  | 1069  | all requests incl. fallbacks                     |

- **All 10/10 write-behind SETs landed in production Redis** (verified by reading the key back after the
  task settled) — the deferred write completes correctly and the cache remains warm.

## 11. Before / after comparison

| Metric (ms)                                        | BEFORE | AFTER | Δ                                  |
| -------------------------------------------------- | ------ | ----- | ---------------------------------- |
| Embedding stage p50 (controlled)                   | 1586   | 1026  | **−560 (−35 %)**                   |
| Embedding stage p50 (controlled, steady)           | ~1586  | ~862  | **~−46 %**                         |
| Embedding stage p50 (live `done`-frame)            | 2475   | 898   | −1577                              |
| Embedding stage p95 (live)                         | 4549   | 1066  | −3483                              |
| Embedding stage mean (controlled)                  | 1866   | 1518* | −348                               |
| Client first-delta TTFT p50 (answered, cache-miss) | 8933   | 8572  | **−361**                           |
| Client first-delta TTFT p95 (answered, cache-miss) | 12061  | 10304 | **−1757**                          |
| Client TTFT mean (answered)                        | 9310   | 8876  | −434                               |
| Server provider TTFT p50 (`done`-frame)            | 1190   | 1213  | ≈0 (unchanged — no provider edits) |

- **DERIVED attribution**: the deterministic floor saving is the removed synchronous SET ≈ **420 ms
  (p50, measured)** per cache-miss. In the live runs the embedding stage improved more than that because
  Redis/upstream RTT variability differed between sessions; the SAFE claim is ≥ ~420 ms removably.
- Client TTFT improvement (~360 ms p50, ~1.76 s p95) is consistent with the embedding-stage saving; the
  server provider TTFT is flat, so the delta is attributable to the request pipeline, not the model.

## 12. Accuracy & isolation verification (live, production stack)

- Tenant B, identical question twice: `embedding_cache=hit`, `retrieval_cache=hit`, answer contains
  **65,000** (Academy B figure). → cache write-behind works end-to-end.
- Tenant A (`website_id eb3eaeb8-…`, `bench-a@example.com`), Corpus-A question: `embedding_cache=miss`
  (distinct key text + identity gate) → answered with Academy-A figure **80,000**, **0 leakage** of the
  65,000 figure.
- Retrieval remains tenant-scoped (`retrieval_cache=miss` under tenant A for tenant-B-keyed text; separate
  keys). No retrieval/ranking/prompt/identity/threshold code was changed.
- Matrixed unit coverage for tenant+website isolation in the embedding/retrieval path remains green
  (`test_*_isolation*`, `test_tenant_*` in the RAG suite).

## 13. Client-visible TTFT analysis (honest read)

- Even with the embedding win, measured P95 client TTFT on cache-miss answered requests is **~10.3 s**
  (BEFORE ~12.1 s), both **far above the 3000 ms P95 target**.
- Server provider TTFT (~1.2 s p50) plus the pre-generation window (auth/quota/website/session/persist ≈
  0.9–1 s, from prior audits) and SSE buffering dominate the residual client TTFT. The **embedding stage
  is no longer the cheapest safe win available** on the request pipeline.
- **DERIVED**: eliminating embedding entirely (~900 ms now) would still not meet the target; the client-
  first-delta includes provider stream + transport overhead beyond `embedding_ms`.

## 14. Safety-rules compliance

- No `git reset/clean/restore/checkout -- . /stash`, no `docker prune`, no destructive DB operations.
- No commit/push made. All 114 dirty working-tree files preserved; only the 3 intended files modified.
- No retrieval ranking, thresholds, prompts, isolation, provider routing, model, or dimension changed.
- No secrets/keys reproduced in this report or in commit content.

## 15. Limitations & confounders

- Upstash Redis RTT and Gemini embedding latency are externally variable (observed 230–1500 ms GET bursts,
  cold-start outlier ~2.6–4.8 s on the first call after process start). Single-session comparisons carry
  that noise; the deterministic floor (a synchronous SET removed from the path) is the conservative claim.
- BEFORE/AFTER client-TTFT used different question sets (both cache-miss, both answered) due to a template
  wording change that flipped the deterministic answerability gate; the comparison is consistent but not
  perfectly paired. First-delta capture definitions differ slightly between rigs (conservative for AFTER).
- The write-behind changes the _observable_ embedding stage timing (lower) — dashboards/logs will show a
  step change; that is intended and accurate (the request no longer waits on the write).
- Cross-request single-flight is per-`RagService`, which is constructed per request by FastAPI deps —
  identical text arriving concurrently across two requests is still coalesced by Redis cache-write timing,
  not by the in-process future map (unchanged from BEFORE; not a regression).

## 16. Re-run / reproducibility

```
# Controlled BEFORE (replicate with pre-change code) / AFTER (current code)
source .venv/bin/activate
python /tmp/opencode/decompose_embed.py          # BEFORE op decomposition
python /tmp/opencode/after_controlled.py         # AFTER real _embed_question (in-container)

# Live client-facing (answered, cache-miss)
python /tmp/opencode/bench_after_answered.py     # AFTER; for BEFORE run the same rig pre-change

# Regression
uv run ruff check backend/services/chat/rag_service.py tests/fakes.py tests/test_rag_service.py
uv run mypy backend
uv run pytest
```

## 17. Files changed (this task)

- `backend/services/chat/rag_service.py` — write-behind embedding cache SET.
- `tests/fakes.py` — write-behind fakes.
- `tests/test_rag_service.py` — write-behind regression tests.
- New: `docs/RAG_TTFT_EMBEDDING_OPTIMIZATION_2026-09-08.md` (this report).

## 18. Final decision

- Optimization landed: **remove the synchronous embedding-cache SET from the request critical path
  (write-behind)**, keeping the single-flight key until the write settles.
- Measured win: embedding stage p50 **1586 → 1026 ms** (controlled) / **2475 → 898 ms** (live done-frame),
  deterministic removal of **≈ 420 ms p50** per cache-miss; client first-delta TTFT p50 **8933 → 8572 ms**,
  p95 **12061 → 10304 ms**.
- Correctness: full suite 2209 pass; BE-Q01 single-flight, re-check race, fail-open, cancellation, and
  cross-tenant isolation all verified; trans-Tenant leakage live-checked at **0 of 2** targeted probes.
- **Client P95 TTFT (~10.3 s) remains far above the 3000 ms target.** Embedding is no longer the smallest
  safe win: the residual dominant latency is the pre-generation window (auth/quota/website/session/persist)
  plus provider TTFT (~1.2 s) and SSE transport, which this task was scoped not to change.
- **FINAL DECISION: EMBEDDING OPTIMIZATION (write-behind SET) SHIPPED — SAFE ~420MS STAGE WIN; P95 CLIENT
  TTFT STILL ≈10.3S >> 3000MS TARGET; NEXT BOTTLENECK = PRE-GENERATION PLATFORM WINDOW + PROVIDER TTFT +
  SSE TRANSPORT, NOT EMBEDDING.**
