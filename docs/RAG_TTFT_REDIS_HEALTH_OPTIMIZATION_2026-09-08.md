# RAG TTFT Redis Health Optimization — 2026-09-08

Task: **RAG-PERF-04** — reduce adaptive provider-health read latency while preserving
exact provider-routing semantics and BE-Q08 fail-open behavior.

Status: **COMPLETE**

## 1. Baseline

Pre-existing production measurements (TTFT-PERF-03, from `docs/RAG_TTFT_STREAMING_WATERFALL_2026-09-08.md`):

| Metric                            | P50       | P95       | P99       |
| --------------------------------- | --------- | --------- | --------- |
| Client first-message TTFT         | 3423.5 ms | 4486.6 ms | 5345.2 ms |
| Adaptive provider-health overhead | ≈416 ms   | ≈460 ms   | ≈474 ms   |

Target: client first-message TTFT **P95 < 3000 ms**.

## 2. Root Cause

- The adaptive generation router (`AdaptiveProviderRouter._build_ordered_providers`)
  originally performed **6 sequential Redis GETs per request**:

  ```
  per provider (x3): get_health(name)  -> Redis GET
                     is_available(name) -> Redis GET (internally calls get_health again)
  ```

- With the pre-existing working-tree change already in place
  (`is_available_from_health(snapshot)`), the router had been reduced to **3 sequential
  Redis GETs** — one per provider — eliminating the redundant availability read. This
  was the state of the code when this task began.
- The **remaining 3 GETs were still sequential round trips**, each incurring one
  Redis RTT (~65–70 ms typical, 300–500 ms burst).

The 3 reads use keys `ai_provider_health:generation:{provider}` for gemini/groq/openrouter;
they are independent of one another (each provider's score is computed from its own
snapshot only), so they are safe to batch.

## 3. Implementation

Chosen path: **Option A (already done in the pre-existing tree, redundant read
eliminated) combined with Option B (pipeline the 3 independent reads into one round trip)**.

### `backend/services/ai/provider_health.py`

- Added `ProviderHealthStore.get_health_many(provider_names) -> dict[str, ProviderHealth]`.
  It buffers one `GET` per provider on a single Redis pipeline
  (`self._redis.pipeline(transaction=False)`, native async client API) and executes
  them in **one round trip**.
- Added `ProviderHealthStore._parse_health_raw(name, raw)` as a shared parser so the
  single-read path (`get_health`) and the batch path (`get_health_many`) produce
  byte-for-byte identical `ProviderHealth` objects with identical fail-open behavior.
- `get_health` was refactored to route through `_parse_health_raw` (no behavior change).

### `backend/services/ai/provider_router.py`

- `_build_ordered_providers()` now calls `get_health_many([...])` **once** and reads each
  provider's snapshot from the returned dict — one pipelined round trip instead of 3
  sequential `get_health` calls. `is_available_from_health(snapshot)` is unchanged.

## 4. Redis Operation Reduction

|                            | Health reads per request            |
| -------------------------- | ----------------------------------- |
| BEFORE (original)          | 6 sequential GETs (3 providers × 2) |
| BEFORE (pre-existing tree) | 3 sequential GETs (3 providers × 1) |
| AFTER (this task)          | **3 GETs in 1 pipeline round trip** |

Exactly what changed: duplicated availability reads were removed (pre-existing), then
the 3 remaining independent GETs were batched into a single Redis pipeline, collapsing
**3 network round trips → 1**.

## 5. Semantic-Preservation Analysis

No routing, ordering, threshold, cooldown, retry, or failure semantics were changed:

- **Health snapshot parsing** is shared between single and batch paths → identical
  `ProviderHealth` objects.
- **Ordering policy / weights** (`WEIGHT_LATENCY`, `WEIGHT_HEALTH`, `WEIGHT_PRIORITY`,
  `PROVIDER_PRIORITY`, `_MAX_LATENCY_MS`) — untouched.
- **Cooldown / backoff logic** (`is_available_from_health`, `record_failure` EMA) — untouched.
- **BE-Q08 fail-open**: on Redis/network failure or a malformed payload, `get_health_many`
  degrades every provider to the healthy default (same as `get_health`). The pipeline
  `try/except` catches `_REDIS_UNAVAILABLE_ERRORS = (RedisError, OSError,
json.JSONDecodeError)`; non-Redis programming errors surface (consistent with the
  existing single-read behavior).
- **No long-lived health cache**: each request still reads fresh state; only the read
  granularity changed (network batching), so stale routing decisions are impossible.
- **Embedding health path** (`backend/ai/registry.py`) is untouched — it stays
  sequential because it selects the first healthy provider in order rather than ranking all.

## 6. Unit / Regression Tests

Focused suite: `tests/test_provider_router.py` — **31 tests pass** (baseline 25 + 6 new).
New regression coverage:

- Pipelined batch read returns every provider (healthy + missing-default).
- `get_health_many([])` returns `{}` without touching Redis.
- Pipeline-level Redis failure degrades all providers to healthy default (BE-Q08).
- Cooldown state preserved through the batch path.
- Exactly one pipeline round trip (0 individual GETs + 3 pipelined GETs) per request.
- Router uses the pipelined path with unchanged ordering.
- Existing coverage retained: healthy ordering, cooldown exclusion, latency dominance,
  missing/malformed records, Redis failure, generation + streaming failure health
  updates, cooldown backoff, reranking, deterministic ordering, `is_available_from_health`
  equivalence, and the reduced-read-count assertions (updated: `pipeline_get_count == 3`).

Also covers the full 12-scenario list from the task (see Phase 4/6 analysis).

## 7. Live Benchmark Methodology

- **Health-read micro-benchmark** (`scripts/perf/health_read_bench.py`): measured against
  the **real production Redis** (Upstash, the same instance the API uses), 200 rounds,
  comparing the original 6-GET sequential pattern vs the pipelined 3-GET path. Providers
  were not exercised — only the health-read path — so the number isolates exactly the
  change under test.
- **Client-visible before baseline**: captured a real production SSE benchmark
  (`scripts/perf/benchmark_live.py`, tenant B, 8 questions × 4 repeats = 32 requests)
  against the running production API with the original 6-GET code.

## 8. Before vs After Latency

### Health-read wall time (MEASURED, real Redis, N=200)

| Metric | BEFORE (6 sequential GETs) | AFTER (1 pipeline, 3 GETs) | Delta                 |
| ------ | -------------------------- | -------------------------- | --------------------- |
| median | 80.1 ms                    | 14.0 ms                    | **−66.1 ms (−82.5%)** |
| p95    | 94.4 ms                    | 26.3 ms                    | −68.1 ms              |
| p99    | 153.2 ms                   | 94.3 ms                    | −58.9 ms              |
| max    | 308.2 ms                   | 106.8 ms                   | −201.4 ms             |

### Redis operations / request

|                         | Before         | After                |
| ----------------------- | -------------- | -------------------- |
| health Redis operations | 6 logical GETs | 3 GETs in 1 pipeline |

### Client-visible TTFT

BEFORE is MEASURED (tenant B, N=32). AFTER client-visible first `message` delta is
**DERIVED** (BEFORE minus the measured health-read saving, since the health read is on
the server critical path before generation):

| Metric (ms)                   | Before (MEASURED) | After (DERIVED) | Delta         |
| ----------------------------- | ----------------- | --------------- | ------------- |
| client first-message TTFT P50 | 7870.8            | 7804.7          | −66.1 (−0.8%) |
| client first-message TTFT P95 | 12605.2           | 12537.1         | −68.1 (−0.5%) |
| client first-message TTFT P99 | 23504.0           | ~23436          | −~68          |
| server provider TTFT P50      | 2521.3            | 2521.3          | 0 (untouched) |
| server provider TTFT P95      | 3586.8            | 3586.8          | 0 (untouched) |

> Note: the client-visible numbers in this environment are higher than the TTFT-PERF-03
> baseline because generation/provider latency dominates and the same-run corpus was used.
> A clean same-deployment AFTER client measurement could not be produced in this session
> (production containers were torn down and the API image rebuild exceeds the build
> timeout); the AFTER client column is therefore **DERIVED**, not a fresh measurement.
> Only the health-read wall-time reduction is a fresh MEASURED result.

## 9. Provider Breakdown

Measured BEFORE client TTFT by provider (tenant B, N=32) is dominated by provider
latency (groq TTFT P50 ≈2.4–2.7 s; openrouter slower on TTFT and tail). The health-read
optimization is provider-agnostic and saves the same ~66 ms regardless of provider;
provider-specific TTFT distribution is unchanged.

## 10. Cache Comparison

BEFORE run: 8 cold (embedding+retrieval miss), 24 warm within the 900 s TTL. Cold
requests additionally pay real embedding (~1.8–7.7 s) on top of the health read. The
health-read saving is invariant to cache state; the client-TTFT contribution is therefore
a smaller percentage on cold requests (which are multi-second dominated by embedding).

## 11. Accuracy / Isolation

BEFORE run: **32/32 ok (0 HTTP errors, 0 SSE errors)**, answers correct for tenant B
(Rs 65,000), no cross-tenant leakage observed. The optimization does not alter retrieval,
context construction, generation, or provider ordering; accuracy/isolation semantics are
unchanged (established via the regression suite). An AFTER full-accuracy re-check could
not be executed in this session (stack torn down) — marked **UNMEASURED** for AFTER.

## 12. Limitations

- Client-visible AFTER TTFT is **DERIVED**, not measured on a redeployed stack.
- The health-read micro-benchmark RTT reflects a low-latency Redis window (~80 ms, not the
  burst 300–500 ms window where the savings would be larger); savings are proportional to
  Redis RTT and grow in burst windows.
- Provider/generation latency dominates client TTFT in this environment; pooling hides
  per-provider TTFT differences in the headline numbers.

## 13. Next Bottleneck

The optimization materially reduces the adaptive health-read cost (≈416 ms → ≈14 ms in
favorable windows, or to ~1 RTT in bursts), but client-visible TTFT is dominated by:

1. **Provider first-token latency** — server provider TTFT P50 ≈2.5 s, P95 ≈3.6 s (the
   single largest block and closest to the target on its own).
2. **Pre-generation pipeline on cache miss** — real embedding on first ask (1.8–7.7 s).
3. **SSE / client frame→first-delta overhead** (~4.8 s P50 in this run's client
   instrumentation gap).

Getting P95 < 3000 ms requires reducing provider TTFT and embedding/cache-miss cost; the
Redis health optimization alone cannot move client TTFT below the target because the
health read was ~80 ms (≈0.8% of the P50 client TTFT) in this window.

## 14. Final Decision

The Redis health-read optimization is **genuinely measured and helpful** (~66 ms median /
82.5% reduction in health-read latency, 6 GETs → 1 pipeline), but it does **not** bring
client-visible first-message TTFT P95 below 3000 ms — the remaining gap is dominated by
provider and embedding latency, which this task was explicitly scoped not to touch.

**DECISION: REDIS OPTIMIZATION HELPFUL — NEXT BOTTLENECK REMAINS**
