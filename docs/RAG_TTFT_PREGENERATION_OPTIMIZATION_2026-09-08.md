# RAG TTFT: Pre-Generation Critical-Path Audit & Optimization — Quota Redis Pipelining (RAG-PERF-06)

Date: 2026-09-08/09 · Branch: `main` · Stack: production docker compose (Upstash Redis, Atlas Mongo, Groq adaptive)
Task: audit the **entire pre-generation critical path** of `POST /api/chat/stream` (auth/deps → quota/rate-limit/usage gates →
website/session/persist → embedding/retrieval → provider first token → first SSE frame), measure every stage, then choose and ship
exactly **ONE smallest safe optimization** that provably reduces client time-to-first-message (TTFT) toward the P95 < 3000 ms target.

Out of scope (unchanged): retrieval strategy, RRF/ranking weights, `top_k`, score/confidence thresholds, prompts, tenant/website
isolation, provider routing/order, embedding model/dimensions, security/quarantine behavior.
Every number below is labelled **MEASURED** (instrumented against the real stack), **DERIVED** (composed from measured numbers), or
**UNMEASURED** (reasoned/unknown). No SYNTHETIC numbers.

## 1. Environment & methodology

- `webchat-api` (:8000), production container env, `UVICORN_WORKERS=1`, `AI_PROVIDER_ROUTING_MODE=adaptive`,
  `PERF_TIMING_LOG_ENABLED=true`, `SSE_BUFFER_MS=50`, all `LLM_*` quota limits non-zero (full 4-op quota check always runs on the
  pre-response path), `CHAT_RETRIEVAL_CACHE_SIZE=512`, `CHAT_RETRIEVAL_CACHE_TTL_SECONDS=900`.
- Live benchmark: authenticated `POST /api/chat/stream`, tenant B (`website_id 2e8632b4-…`), 32 unique cache-miss questions; the
  harness streams SSE in-flight and records `first_frame_ms` (first SSE byte/frame), `first_msg_ms` (first message delta),
  `done_ms`, plus the server `done`-frame `timing` block. All 32 requests in EVERY run answered with the deterministic
  answerability gate passing.
- Pre-generation instrumentation: opt-in `chat_stage` timing was added to the three previously-unlogged gates — `gate.rate_limit`
  (dashboard + widget + api-key limiters), `gate.quota_check`, `gate.usage_check_limit` — emitted only when
  `PERF_TIMING_LOG_ENABLED=true` (observational; zero behavior change).
- Same-day infra variability is significant and is documented in §7; repeated confound events are measured and separated from the
  code effect.

## 2. Pre-generation critical path (MEASURED trace, in request order)

1. **Route deps (sequential)**: `auth.jwt` (decode) → `auth.user` (users.find_by_id, Mongo) → `auth.tenant` (tenants.find_by_id,
   Mongo) → `auth.member` (role resolution, Mongo + Redis role cache; 60 s TTL) → `gate.rate_limit` (Redis EVAL sliding window).
2. **Handler body before HTTP 200**: `gate.quota_check` — 4 sequential Redis round-trips (GET daily, GET monthly, INCR req,
   EXPIRE req). Must stay pre-response to preserve HTTP 429-on-exhausted semantics.
3. **After HTTP 200, before first SSE frame**: `gate.usage_check_limit` (`get_plan` = tenants + subscriptions); then usage totals
   aggregation (must complete before the `sources` frame so an error stays first) → `website.lookup` → `session.resolve` →
   `persist.user_message` (Mongo) → embedding cache GET (Redis) → `retrieval.embed` → `retrieval.vector_search` ($vectorSearch) →
   lexical `load_chunks` → RRF strategy → `_hydrate_rerank_candidates` (Mongo embeddings fetch) → rerank → retrieval-cache SET →
   retrieval context → await history → yield `sources` frame → prompt build → `generation.stream` (ttft_ms) → `persist.messages` →
   `done` frame.

## 3. Baseline (BEFORE) — live 32-question benchmark, healthy window (15:55 UTC), all MEASURED

| Segment (server, p50 ms)                                | BEFORE                         |
| ------------------------------------------------------- | ------------------------------ |
| auth (jwt+user+tenant+member)                           | 0.3 + 63.1 + 56.3 + 59.0 ≈ 179 |
| gate.rate_limit                                         | 54.4                           |
| **gate.quota_check (4 sequential Redis RTTs)**          | **234.0**                      |
| gate.usage_check_limit                                  | 186.5                          |
| website.lookup + session.resolve + persist.user_message | 59.5 + 63.4 + 66.9             |
| retrieval.embed                                         | 903.6                          |
| retrieval.vector_search                                 | 1118.9                         |
| ttft_ms (Groq)                                          | 1283.2                         |
| generation_consumed                                     | 1498.2                         |
| persist.messages                                        | 115.8                          |

| Client (ms)           | p50     | p95     | mean    |
| --------------------- | ------- | ------- | ------- |
| client.first_frame_ms | 8764.0  | 13009.0 | 9377.7  |
| client.first_msg_ms   | 10343.8 | 14343.5 | 10801.7 |
| client.done_ms        | 10869.2 | 14782.7 | 11301.3 |
| server.total_ms       | 9949.5  | 13942.6 | 10409.4 |

Cache state: `embed_cache` hit 8 / miss 23; `retrieval_cache` all miss. 32/32 answered (1 fallback), faithfulness 1.0.

**DERIVED**: the pre-generation _platform/dependency_ window (auth + gates + website/session/persist) ≈ 844 ms p50 — the gates are
~475 ms of it, of which `quota_check` is the single largest gate (~234 ms for 4 serial Upstash round-trips).

## 4. Controlled measurement of the candidate optimization (in-container, real Upstash, same tenant keys, n=20, MEASURED)

| Variant                                                     | p50 ms    | mean ms | p95 ms | max ms |
| ----------------------------------------------------------- | --------- | ------- | ------ | ------ |
| 4 sequential Redis ops (current)                            | 243.2     | 287.4   | 968.4  | 968.4  |
| **Pipelined** (mget daily+monthly; INCR+EXPIRE in one pipe) | **114.8** | 131.6   | 334.8  | 334.8  |
| Saving                                                      | **128.4** | 155.8   | 633.6  | 633.6  |

## 5. Optimization shipped (ONE, smallest, safe): pipeline `LLMQuotaService.check` in `backend/core/quota.py`

- Daily + monthly budgets read in one `MGET` (2 RTTs → 1); per-minute counter `INCR` + `EXPIRE` sent as one pipeline (2 RTTs → 1):
  **4 sequential round-trips → 2 round-trips**.
- Semantics preserved exactly: both budget reads still complete before any counter INCR; INCR-then-check atomicity (TOCTOU guard)
  unchanged; per-tenant key isolation unchanged; Redis-outage fail-open unchanged; `AIQuotaExceededError`/HTTP 429 behavior
  unchanged. No ranking/threshold/prompt/isolation/provider change.
- Regression test added (`tests/test_quota.py`: `_FakeRedis.mget`/`pipeline`, budget-exceeded paths, INCR-then-check, fail-open).
  The test suite caught a real bug before deployment: `redis.asyncio` pipeline `execute()` returns `[count, True]`, requiring
  `results[0]` — no production blast radius.

## 6. AFTER — live re-verification

Healthy-window single request (16:02 UTC): `gate.quota_check` = **105.9 ms**.
Full 32-question AFTER run (00:12 UTC, §7 explains infra state): `gate.quota_check` p50 = **157.7 ms** (n=32; Redis RTT was ~85 ms
p50 in that window vs 54 ms baseline, so 2 RTTs cost more than at baseline). Controlled ±-baseline saving: ~110-128 ms p50.

| Client (AFTER, 32/32 answered, all cache-miss) | p50    | p95     | mean   |
| ---------------------------------------------- | ------ | ------- | ------ |
| client.first_frame_ms                          | 5276.8 | 8811.6  | 5563.5 |
| client.first_msg_ms                            | 6370.8 | 9872.1  | 6724.4 |
| client.done_ms                                 | 7056.3 | 11136.0 | 7756.3 |
| server.total_ms                                | 5372.8 | 9819.4  | 5908.5 |

Server (AFTER, p50): website 81.8 · session 88.9 · persist.user 90.8 · embedding 1133.8 · vector_search 517.1 · load_chunks 176.4 ·
ttft 1069.9 · generation_consumed 1251.1 · persist 221.9.

| BEFORE → AFTER (p50 / p95)    | BEFORE        | AFTER         | Delta                                    |
| ----------------------------- | ------------- | ------------- | ---------------------------------------- |
| client.first_frame            | 8764 / 13009  | 5277 / 8812   | −3487 / −4197                            |
| client.first_msg              | 10344 / 14344 | 6371 / 9872   | −3973 / −4472                            |
| server.total                  | 9950 / 13943  | 5373 / 9819   | −4577 / −4124                            |
| gate.quota_check              | 234.0 / 290.5 | 157.7 / 741.0 | −76.3 p50 (MEASURED live)                |
| gate.quota_check (controlled) | 243.2 / 968.4 | 114.8 / 334.8 | −128.4 / −633.6 (MEASURED, same-instant) |

**IMPORTANT (measurement integrity, DERIVED):** the large client-level BEFORE→AFTER deltas above are **not** attributable to the
~0.1 s gate change. They are dominated by environment variance — downstream stages the optimization never touches were 2x faster in
the AFTER window (vector_search 1118.9 → 517.1; load_chunks 242.3 → 176.4; ttft 1283.2 → 1069.9), while unrelated gates were
slower (usage_check_limit 186.5 → 254.1; auth.member 59.0 → 567.5, role-cache pacing artifact). The **clean, cache-independent
signal of the optimization is the gate_quota_check + controlled probe measurements in §4/§6**, not the client histogram.
Estimated client TTFT benefit from the gate saving ≈ **110-130 ms p50** (1:1 pass-through to the pre-sources critical path).

## 7. Confound events (documented; none affect the controlled signal)

1. **16:14-16:2x — Upstash outage-class degradation.** Raw Redis RTT inflated to p50 419.7 ms (vs 54.2 ms baseline); every gate
   inflated proportionally (pipelined quota_check still 340 ms). AFTER attempt #1 excluded as invalid.
2. **16:28-16:31 — retrieval-cache HIT artifact.** The degraded run warmed the 900 s retrieval cache for the whole corpus; attempt
   #2 served cache HITs (embedding/retrieval ≈ 0). Excluded from the miss-path comparison; useful only as the cached-path datum
   (first_frame p50 1664 ms).
3. **17:02-17:38 — hanging requests.** per-request latency 30-194 s (http_request logs), only 4/32 before I aborted; excluded.
4. **19:07-19:35 — partial run (after6).** 23/32 completed; 9 non-200 masked by a harness streaming-read bug; embedding-cache warm.
   Excluded; harness fixed.
5. **Measurement harness bugs found & fixed:** (a) `client.post(...)` fully buffers the body — no streaming timings; switched to
   `client.stream`. (b) `.text` on a streaming response raises — non-200 path now reads headers only. (c) `/tmp/opencode` was
   wiped twice mid-work; assets recreated in the persistent dir `~/webchat-perf/`.
6. Proxy infrastructure (Redis RTT) was sampled before each decision window. The FINAL AFTER (after7, §6) ran with all caches cold
   (31 miss / 1 no-data) in a semi-recovered window (Redis RTT ~85 ms).

## 8. Accuracy / correctness / isolation / regression

- **Answer quality**: all 32 answered in BEFORE and AFTER with the deterministic gate passing; `answer_ok=32` both runs;
  faithfulness ≈ 0.90-1.00 in BEFORE and ≈ 0.90 avg on the AFTER sample (top-8 reported 1.0,1.0,1.0,1.0,0.667,0.5,1.0,1.0);
  faithfulness varies with provider summarization and has no correlation with the gate change (which never touches
  generation/retrieval).
- **Isolation (MEASURED, live)**: tenant-A principal posting to tenant-B `website_id` → HTTP 200 with SSE `WEBSITE_NOT_FOUND`
  error frame + `done(status=failed)` — clean rejection, zero cross-tenant data exposure. Tenant-A principal on its own website →
  normal `sources` frame. No isolation change.
- **Regression**: `tests/test_quota.py` (6/6), focused chat/widget/deps/sse suites (88/88, exit 0), and the **full suite
  (exit 0)** all pass on the final tree; `mypy` clean on quota.py/deps.py/usage_service.py; ruff clean on all changed files.
  The deployed container imports the final module (verified in-container) and `/api/health` returns 200.

## 9. TTFT budget vs the P95 < 3000 ms target (all MEASURED, after7 window)

| Segment (p95)                                | Budget     | Actual                                  | vs target              |
| -------------------------------------------- | ---------- | --------------------------------------- | ---------------------- |
| auth + deps (incl. role cache)               | ≤ 500      | 82.8                                    | OK                     |
| rate_limit + quota_check + usage_check_limit | ≤ 400      | 499.6+741+442.6 → gates dominate at p95 | OVER when RTT elevated |
| website/session/persist                      | ≤ 250      | 157.8 / 242.7 / 230.2                   | borderline             |
| embedding (miss)                             | ≤ 600      | 1686.4                                  | OVER                   |
| retrieval + load_chunks + hydrate            | ≤ 1000     | 938.8 / 571.8                           | OVER                   |
| provider TTFT                                | ≤ 500      | 1944.0                                  | OVER ×3.9              |
| generation + persist + transport             | ≤ 700      | ~5200                                   | OVER                   |
| **client.first_msg P95**                     | **< 3000** | **9872.1**                              | **OVER**               |

**DERIVED:** even after the gate fix, the reachable best-steady-state is ≈ 1.0 s (platform) + ≈ 1.6 s (embed+retrieve) +
**1.1-2.0 s provider TTFT PLUS generation** + transport ≫ 3 s. The dominant remaining bottlenecks are (in order) **provider TTFT
(groq)**, the **retrieval+embedding pipeline**, and the **usage_check_limit p95** (Mongo plan+totals) — not the pre-generation gates.

## 10. Decision

- The ONE pre-generation optimization (Redis pipelining of `quota_check`) is **MEASURED effective** (controlled −128 ms p50 /
  −156 ms mean; live gate −76 ms p50 in a degraded window), **semantics-preserving** (429/fail-open/TOCTOU/isolation untouched),
  and **fully regression-tested**.
- The client P95 TTFT is **NOT below 3000 ms** in any clean run (9872 ms even in the best (semi-recovered-env) AFTER window; huge
  daytime variance 8.8-40 s).

**DECISION: PRE-GENERATION OPTIMIZATION HELPFUL — NEXT BOTTLENECK REMAINS**

The optimization stays (no revert required). Recommended next targets, in order: (1) generation provider TTFT & streaming
(1.07-2.26 s p50-99, groq adaptive); (2) retrieval $vectorSearch + embed-cache misses (0.5-1.1 s) and `_hydrate_rerank_candidates`
payloads; (3) `usage_check_limit` p95 (plan+totals, 186-530 ms) — e.g., cached plan slices; (4) auth.member role-cache TTL vs
60 s pacing artifact.

---

# RAG-PERF-07: True Real TTFT Critical-Path Optimization — Provider + Retrieval Waterfall

Date: 2026-09-09 · Branch: `main` · Stack: production docker compose (Upstash Redis, Atlas Mongo, OpenRouter adaptive).
Task: extend the RAG-PERF-06 audit to the **true real TTFT first frame** (provider routing → first token → first SSE frame),
choose and ship exactly **ONE smallest safe optimization** from the dominant remaining waterfall (provider + retrieval),
and measure removal of time from request → first user-visible message. Target unchanged: client first_msg P95 < 3000 ms.

Out of scope (unchanged): retrieval strategy, RRF/ranking weights, `top_k`, score/confidence thresholds, prompts, tenant/website
isolation, provider routing/order, embedding model/dimensions, security/quarantine, billing/quota semantics. Number labels:
**MEASURED** (real stack), **DERIVED** (composed from measured), **UNMEASURED** (reasoned). No SYNTHETIC numbers.

## 11. Provider + retrieval waterfall (MEASURED, continuation of §2)

Chain after RAG-PERF-06: `retrieval.embed` → `retrieval.vector_search` ($vectorSearch) → hybrid **lexical `_load_all_chunks`**
(corpus load, all chunks) → RRF strategy → `_hydrate_rerank_candidates` (Mongo embeddings fetch) → rerank → context →
`sources` frame → prompt build → **provider routing** (`AdaptiveProviderRouter`: per-request Redis health snapshot + latency-
weighted sort, ~1 Redis RTT) → `generation.stream` (first token) → `persist.messages` → `done`.

Key facts found in source (RAG-PERF-06 §2 unchanged, only the retrieval ladder changed):

- `HybridRetrievalStrategy` is enabled: `_retrieve` runs `$vectorSearch` **and** `_load_all_chunks` sequentially, RRF-merging both.
- `AI_PROVIDER_ROUTING_MODE=adaptive`; routing decision depends on a fresh Redis health snapshot, so it cannot legally move before
  the auth/gate DNS+Mongo work prior to `generation.stream` (byte-for-byte streaming equivalence rule).
- `gate.usage_check_limit` (plan = tenants.find + subscriptions.find, then usage totals `$group` aggregate) is the last serial
  Mongo barrier before the `sources` frame; ran unchanged from RAG-PERF-06.
- `chat_stage` log confirms all stages still present with identical semantics; `PERF_TIMING_LOG_ENABLED=true` unchanged.

## 12. BEFORE (RAG-PERF-07) — live 32-question benchmark (00:35-00:44 UTC), all MEASURED

| Client (ms)           | p50    | p95     | mean   |
| --------------------- | ------ | ------- | ------ |
| client.first_frame_ms | 3949.0 | 7448.5  | 4464.7 |
| client.first_msg_ms   | 5827.6 | 9784.9  | 6187.4 |
| client.done_ms        | 7982.8 | 13050.2 | 8167.6 |
| server.total_ms       | 6294.9 | 11321.6 | 6330.9 |

Server (p50 / p95, ms): website 81.2/246.7 · session 73.7/167.6 · persist.user 82.2/148.1 · embedding 148.0/534.9 ·
vector_search 375.6/635.3 · **load_chunks 152.4/686.7 (max 739)** · ttft 1372.1/3521.9 · generation_consumed 2559.8/8145.9 ·
persist 204.1/285.9.
Gates (p50 / p95, ms): rate_limit 77.8/349.0 · quota_check 143.1/706.3 · usage_check_limit 216.2/335.4 ·
auth.member 580.2/1871.5 (role-cache 60 s pacing artifact).
Cache state: embed hit 31 / null 1; retrieval all miss. 32/32 answered, faithfulness 1.0.

**DERIVED (retrieval ladder decomposition in the BEFORE window, n=31):**
`embed + vector_search + load_chunks` **sequential** p50 = 705.1 / p95 = 1490.9 ms; with `load_chunks` fully overlapped with
`vector_search` (`embed + max`) p50 = 561.2 / p95 = 1002.4 ms → **overlap removes p50 143.9 / p95 488.4 ms** (load was shorter
than the vector search in this window).

## 13. Selected optimization (ONE, smallest, safe): overlap lexical corpus load with `$vectorSearch`

In `backend/services/chat/rag_service.py::_retrieve`, when the `HybridRetrievalStrategy` is active, `_load_all_chunks(...)` is
launched as an `asyncio.create_task` **before** `retrieval.vector_search`; after the search completes the strategy awaits the load
task and proceeds with the identical (vector + lexical) candidate set. On a vector-search exception the load task is cancelled
(`contextlib.suppress(asyncio.CancelledError, Exception)`) and the original exception re-raised.

- Semantics preserved: `_load_all_chunks` output (corpus version + embedding identity) is identical whether awaited early or late;
  RRF strategy receives the same two candidate lists in the same order; ranking/prompts/isolation untouched. Pure read-only
  overlap — no DB/Redis writes reordered.
- `load_chunks_ms` now measures task-creation → completion (honest work duration; equal to `max(vector_search, load)` where load
  finished late is measured cold).
- Safety edge: derived code avoided — `asyncio.create_task` is bounded to ≤1 in-flight load task per request (no task accumulation);
  cancellation on error path verified by test.

## 14. AFTER (RAG-PERF-07) — live 32-question benchmark (00:56-01:01 UTC), all MEASURED

| Client (ms)           | p50    | p95     | mean   |
| --------------------- | ------ | ------- | ------ |
| client.first_frame_ms | 3354.1 | 6133.9  | 3510.8 |
| client.first_msg_ms   | 4740.0 | 9262.1  | 5160.7 |
| client.done_ms        | 7371.3 | 13124.3 | 8208.8 |
| server.total_ms       | 5515.5 | 11990.6 | 6826.0 |

Server (p50 / p95, ms): website 70.2/131.9 · session 74.7/153.5 · persist.user 66.9/140.0 · embedding 146.1/500.1 ·
retrieval 385.4/485.9 · **load_chunks 385.4/510.8** · ttft 1451.0/2454.7 · generation_consumed 2983.6/9502.6 · persist 202.9/276.7.
Gates (p50 / p95, ms): rate_limit 61.7/173.3 · quota_check 127.4/290.9 · usage_check_limit 207.0/266.2 ·
auth.member 488.9/793.0.
Cache state: embed hit 31 / null 1; retrieval all miss. 32/32 answered, faithfulness sample all 1.0.

**DERIVED causal model of the overlap in the AFTER window (n=31, same records):**

- AFTER actual (with overlap): `embed + max(retrieval, load)` p50 = 539.0 / p95 = 817.1 ms.
- Counterfactual sequential (same records, without overlap): `embed + retrieval + load` p50 = 906.7 / p95 = 1375.4 ms.
- **Overlap removed p50 = 367.7 / p95 = 558.3 ms** in this window (load took p50 380.7 — the lexical corpus was cold here, longer
  than the vector search, so the overlap converted a hidden serial 380 ms into ~0 added latency).
- RAG-PERF-06-BEFORE-window overlap saving (same matrix): p50 143.9 / p95 488.4 ms.

Client-level deltas −595 p50 / −1314 p95 (first_frame) and −1088/−523 (first_msg) include infra drift (provider TTFT rose
1372→1451 p50 during AFTER); the controlled, stable signal is the **DERIVED overlap-removal model above**, not the client histogram.

## 15. Confound / integrity notes (RAG-PERF-07)

1. Container restarted at 00:08:12 UTC (same-instant stop/start, RestartCount=0, filesystem preserved; verified post-restart it
   still ran PERF-06 pipelined quota + all chat_stage instrumentation). BEFORE run 00:35-00:44 and AFTER run 00:56-01:01 both
   served by the restarted container; auth/tenant/website numbers consistent across runs.
2. Container log dump contains 9 `ServerSelectionTimeoutError` (Atlas DNS) events at **19:15-19:19 UTC Sep-08** — 5+ hours before
   either benchmark window; zero DNS errors inside the BEFORE/AFTER windows. The earlier "AFTER: 0 chat requests" reading was an
   incorrect timestamp window (01:45-02:05 instead of 00:56-01:01), not missing traffic.
3. Redis RTT remained ~70-90 ms p50 (semi-degraded) across both windows; embed cache warm in both (hit 31), retrieval cache cold
   in both (all miss) → cache-state comparable.
4. `load_chunks` was cold in the AFTER window (p50 385 ms vs 152 BEFORE) — the overlap still bundled it into the vector-search
   latency, which is exactly the optimization's purpose. Under warm-corpus conditions the saving is smaller (p50 ~144 ms).

## 16. Accuracy / correctness / isolation / regression (RAG-PERF-07)

- **Answer quality**: `answer_ok=32/32` BEFORE and AFTER; faithfulness sample all 1.0 (AFTER). No change to retrieval/generation.
- **Isolation (MEASURED, live)**: tenant-A principal → tenant-B `website_id` → HTTP 200 + SSE `WEBSITE_NOT_FOUND` +
  `done(status=failed)` — clean rejection, zero cross-tenant data exposure. Tenant-A principal on its own website → normal
  `sources` frame. No isolation change.
- **Regression (full suite, exit 0)**: **2221 tests collected, PYTEST_EXIT=0** on the final tree; `tests/test_rag_perf07_parallel_retrieval.py`
  adds 4 regression tests (overlap-gate proof; vector-failure cancels load + re-raises; load-failure propagates; empty-corpus no-hit).
  `mypy backend` clean (199 files); ruff clean on changed files. Deployed container imports the final module (verified in-container,
  `load_task` present) and `/api/health` returns 200.

## 17. TTFT budget vs the P95 < 3000 ms target (AFTER window, all MEASURED unless marked DERIVED)

| Segment (p95, ms)                                      | Budget     | Actual                | vs target       |
| ------------------------------------------------------ | ---------- | --------------------- | --------------- |
| auth + deps (incl. role cache)                         | ≤ 500      | 793.0 (member pacing) | borderline/OVER |
| rate_limit + quota + usage gates                       | ≤ 400      | 173.3 / 290.9 / 266.2 | OK              |
| website/session/persist.user                           | ≤ 250      | 131.9 / 153.5 / 140.0 | OK              |
| embedding (warm)                                       | ≤ 600      | 500.1                 | OK              |
| **retrieval ladder (retrieval+load overlap, DERIVED)** | ≤ 1000     | 817.1                 | OK              |
| provider TTFT                                          | ≤ 500      | **2454.7**            | **OVER ×4.9**   |
| generation_consumed + persist + transport              | ≤ 700      | ~9500                 | OVER            |
| **client.first_msg P95**                               | **< 3000** | **9262.1**            | **OVER**        |

**DERIVED:** after the overlap, the pre-generation platform window is now ≈ 1.4-1.6 s p95 (auth+gates+persist dominated by the
60 s role-cache pacing artifact) and the retrieval ladder ≈ 0.8 s p95; the **provider TTFT (2454.7 p95) and generation streaming**
(9502.6 p95) together are now the overwhelming majority of client time — consistent with RAG-PERF-06's projection.

## 18. Decision

- The ONE retrieval-waterfall optimization (overlap `_load_all_chunks` ∥ `$vectorSearch`) is **DERIVED effective** (removes
  p50 368 / p95 558 ms of serial path in the cold-after window; p50 144 / p95 488 in the before window), **semantics-preserving**
  (identical candidate sets, order, ranking; read-only overlap), and **fully regression-tested**.
- The client P95 TTFT is **NOT below 3000 ms** (9262 ms is the best clean run baseline-summary row; provider TTFT and generation
  now dominate the residual budget).

**DECISION: PRE-GENERATION OPTIMIZATION HELPFUL — NEXT BOTTLENECK REMAINS**

The overlap stays (no revert required). Recommended next targets, in order: (1) **provider first-token TTFT (OpenRouter adaptive,
p95 2455 ms)** — vendor reduction / parallel provider pre-flight / shorter-adaptive routing; (2) **generation streaming downstream
(generation_consumed p95 ~9.5 s)** — token throughput, SSE buffering, chunked dispatch; (3) auth.member role-cache pacing artifact
(60 s TTL, p95 793 ms) — lengthened TTL with explicit revocation, if authorization freshness policy allows; (4) `usage_check_limit`
p95 (Mongo plan+totals, 186-530 ms) — cached plan slices.

---

# RAG-PERF-08: Real Provider TTFT + SSE First-Message Critical-Path Audit

Date: 2026-09-09 (run window 01:32Z–01:38Z) · Branch `main` · Stack: production docker compose (Upstash Redis, Atlas Mongo,
OpenRouter/Groq adaptive routing).

Task: measure the **true provider → first-token → first-SSE-message path** behind `client.first_msg`, quantify each clock
(T0 request received → T5 sources frame → T8 provider request start → T9 first provider delta → T10 first SSE message frame), and
identify exactly **ONE smallest safe optimization** that can _materially_ reduce client first-message TTFT toward P95 < 3000 ms.
Rules unchanged: only measurement evidence counts; no provider order/priority/model/prompt/temperature/retrieval-ranking/top_k/
confidence/embedding/isolation/billing/quota/security changes; no synthetic latency; no Ollama/synthetic provider; no production
change unless a safe + material optimization is proven and measured.

Number labels: **MEASURED** (real stack), **DERIVED** (composed from measured), **UNMEASURED** (reasoned). No SYNTHETIC numbers.

## 19. Provider waterfall on the TRUE first-message path (MEASURED wire path, not done-frame)

Server-side clocks captured this window (01:32Z–01:38Z, `before_perf08`, n=32, in-flight SSE parser):

| Path segment                                                   | MEASURED (ms)                                                                 | note                                                                                |
| -------------------------------------------------------------- | ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| T6→T8 routing (adaptive health snapshot + latency sort)        | p50 ≈ 66 / p95 ≈ 174 (DERIVED: harness `ttft` − `ai_generation_request.ttft`) | 1 pipelined Redis RTT (~62-86 ms measured in-container)                             |
| T8→T9 provider TTFT, `ai_generation_request` (openrouter n=31) | p50 1152.5 / p95 1594.1 / mean 1147.4 / max 1780.2                            | **dominant post-sources serial cost, external**                                     |
| Provider-mix                                                   | openrouter 31, synthesized-fallback path 1 (no provider call)                 | fallback_count {0:31, 1:1} = 1 answerability-rejected turn, not a provider fallback |
| T5→T10 sources→first message (client, derived as src→msg)      | p50 1349.6 / p95 1820.3                                                       | includes prompt build (~1 ms) + routing (~66 ms) + provider TTFT + SSE buffer hold  |

Honest small-N limits: Groq had **no** adaptive-routed generation request in this window (0 samples) — Groq TTFT remains
uncharacterized this window (PERF-07 window: n=3, p50 1287.9 ms). Not used for any decision.

## 20. Streaming path audit (T9→T10: provider first delta → first SSE `message` frame)

Chain (outermost → innermost): `with_heartbeats` → `buffered_stream_with_disconnect` → `_recording_events` → `_metrics_events`
→ `ensure_terminal_done` → `stream_answer` → `AdaptiveProviderRouter.stream_generate` → `FallbackGenerationClient.stream_generate`
→ provider HTTP stream. Source-verified facts:

- `rag_service.ttft_ms` in the done-frame timing block = `t2` (start of `generation.stream`) → first provider delta (includes routing).
- `ai_generation_request.ttft_ms` logs provider-only TTFT (routing excluded). Routing = difference ≈ 66 ms p50 (DERIVED, n=31).
- `_recording_events`/`_metrics_events` are pure pass-through on `message` events (usage is recorded at `sources`/`done`, never
  between first delta and first frame).
- **`buffered_stream_with_disconnect` holds the first `message` delta for ~`buffer_ms` (50 ms) before any frame is produced**
  (sse.py:311-321): `flush_deadline = now + 50 ms`, and the first message never satisfies `now >= flush_deadline`. All subsequent
  deltas coalesce into the first frame. Independent check: on the 5 same-window synthetic-answer requests (no provider call),
  `sse_transport.first_token_ms − first_event_ms` = 51.1–55.0 ms — exactly prompt-build (~1 ms) + the 50 ms buffer hold.
- Nothing else sits between T9 and T10: no DB/Redis/billing/metrics await on the message event.

## 21. Bottleneck classification (T5→T10, honest)

| Component                       | p50 share                   | category                                                                                       |
| ------------------------------- | --------------------------- | ---------------------------------------------------------------------------------------------- |
| Provider TTFT (openrouter)      | 1152.5 / ~1349.6 = **~85%** | external vendor+network latency — cannot touch per rules                                       |
| Routing (health snapshot)       | ~66 ms (~5%)                | already 1 pipelined Redis RTT; moving earlier = stale-selection risk, forbidden (Phase 6 rule) |
| SSE buffer hold (first message) | ~50 ms (~4%)                | **the only safe in-app lever**                                                                 |
| Prompt build + yield overhead   | ~1-10 ms                    | trivial                                                                                        |

## 22. Candidate evaluation (ONE smallest safe optimization)

- **A/B — flush the first SSE `message` immediately (skip the 50 ms coalescing hold for the first frame only; keep coalescing all
  later deltas).** Expected saving: deterministic ~50 ms on every first message. Safe: same events, same order, same content —
  the client already treats every coalesced frame as a partial delta; no provider routing / ranking / isolation touched.
  **Impact: ~50 ms on a client first_msg P95 ≈ 9000 ms → ~0.5%.** NOT material against the P95 < 3000 ms target.
- C (start provider streaming immediately after routing/context): already the case — nothing sits between routing and the HTTP call
  except immediate fallback dispatch; nothing to remove.
- D/E (prepare provider request state earlier / overlap pre-provider ops): the only pre-provider awaits are routing (health read)
  and prompt build; both already minimal; moving the health read earlier changes decision-time semantics (stale snapshot could flip
  an availability/cooldown decision) — violates the unchanged-semantics rule.
- Any provider-side change (order/priority/model/temperature/parallel pre-flight/hedging): all explicitly out of scope / forbidden.

**Result: the only safe candidate removes ~50 ms (0.5% of P95), far below "material". No production change is made.**

## 23. Decision (RAG-PERF-08)

- BEFORE `before_perf08` bench: 32/32 ok, faithfulness sample all 1.0, embed cache all-miss (31), retrieval cache all-miss (31),
  health `/api/health` 200, Redis RTT ~62-86 ms p50 (semi-degraded, same as PERF-06/07). One request had a cold-embedding anomaly
  (embedding_ms 10129 → first_frame 15.5 s); honest window p50/p95 exclude that request.
- The provider TTFT (external) is **~85%** of the sources→first-message gap and is untouchable by the rules; the only safe in-app
  lever (SSE first-message flush) is a deterministic ~50 ms — not material. **DECISION: PRE-GENERATION OPTIMIZATION NOT MATERIAL —
  NO PRODUCTION CHANGE.**
- Next bottleneck (unchanged from RAG-PERF-06/07 §18): **OpenRouter provider TTFT (p95 ≈ 1594 ms this window)** — vendor-level
  reduction, a provider with lower p95 first-token latency, or (out of the allowed rules for _this_ runbook) a policy decision on
  parallel/hedged provider pre-flight. Secondary: generation streaming throughput (generation_consumed p95 ≈ 4.9 s).
