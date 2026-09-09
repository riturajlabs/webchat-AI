# RAG TTFT Streaming Waterfall — 2026-09-08

**Task:** TTFT-PERF-03 — Client First-Delta Waterfall Audit
**Date:** 2026-09-08 (UTC)
**Repository:** main @ `5718ac4` (`chore: fix Ruff formatting`) — no code files modified by this audit

---

## 1. Executive Summary

The true, client-visible time from request start to the **first `message` SSE delta** (the only
meaningful TTFT) is:

| Metric (N=32 real production requests, 2 tenants) | P50        | P95        | P99        |
| ------------------------------------------------- | ---------- | ---------- | ---------- |
| Client e2e TTFT → first message delta             | **3.42 s** | **4.49 s** | **5.35 s** |

The previously reported "client e2e TTFT" (~4.9 s P50 / ~8.3 s P95) was a **client instrumentation
artifact** — it measured stream _completion_, not first delta (see §6).

The waterfall is dominated by **pre-generation RAG/auth work, not the streaming path**:

- request → first SSE frame (`sources`) ≈ **2.08 s** (61% of TTFT)
- first frame → first `message` delta ≈ **1.28 s** (contains provider TTFT ≈ 0.81 s + ~0.42 s of
  per-request adaptive-router Redis health reads)
- Streaming/HTTP/SSE transport + client parse ≈ **<0.10 s** (proved by isolated transport probe)

**DECISION: RAG PRE-GENERATION BOTTLENECK IDENTIFIED**

The client-visible first-delta P95 (4.49 s) does **not** meet the < 3.0 s target. The bottleneck is
request→provider-start: authentication/deps/quota/usage checks + retrieval + per-request
serialized Redis health reads over a Redis with **65–500 ms round-trips**.

---

## 2. Objective & Scope

Measure exactly where latency is spent between four events:

1. client request start
2. provider first token (server side)
3. server SSE first `message` delta (server side)
4. client first `message` delta (client side)

Deliver a measured waterfall, classify each segment, and state a root cause and recommended next
change. **No optimization was performed.** No production behavior was changed. All instrumentation
lived in `/tmp/opencode/*.py` (host) and `/tmp/*.py` (inside the api container).

## 3. Environment & Deployment Facts

- API: FastAPI + Starlette `StreamingResponse` (SSE) via `backend/api/sse.py`,
  event loop runs Apr-2026 codebase (`main @ 5718ac4`).
- `sse_buffer_ms = 50.0` (event coalescing buffer), `perf_timing_log_enabled = True`,
  `generation_first_token_timeout_seconds = 10.0`, `ai_provider_routing_mode = adaptive`.
- Providers registered: **gemini, groq, openrouter** (generation). Gemini was on
  **cooldown** (quota/failure) during the measurement window → effectively skipped; serving
  providers: **groq (21) and openrouter (11)**.
- Redis and Mongo are high-latency (hosted) services: Redis round-trip measured **65–500 ms**
  (bursty); Mongo RTT consistent with multi-tens-of-ms per op (see §13).
- Local Mongo has no Atlas `$vectorSearch` → exact brute-force cosine fallback is the real
  retrieval path.
- Benchmark corpus: two BCA Academy tenants (A fee Rs 80,000; B fee Rs 65,000; 23 chunks each)
  - one decoy website. Load was the same in use for REAL-TTFT-02.

## 4. Method & Instrumentation

Three probes in addition to existing per-request instrumentation:

- **Probe C** (`/tmp/opencode/benchmark_waterfall.py`, host): corrected SSE client that parses
  SSE in-flight, stamps every event frame on its own arrival, sends a per-request `X-Request-ID`,
  and records client times from `time.perf_counter()` at request start.
- **Probe A** (`/tmp/opencode/probe_provider.py`, in-container): provider-only TTFT over the real
  fallback chain, N=12, server-side.
- **Probe D** (`/tmp/opencode/probe_sse_transport.py`, in-container): standalone FastAPI on
  `127.0.0.1:8123` (container-internal only, removed afterward) streaming a deterministic
  schedule through the **same** production SSE helpers (`buffered_stream_with_disconnect`,
  `with_heartbeats`, `ensure_terminal_done`) to isolate transport/buffer/parse overhead.
- Server instrumentation already present in production logs:
  - `ai_generation_request` (router-level TTFT, provider, fallback count) — origin = fallback
    chain start.
  - `sse_transport` (`first_event_ms`, `first_token_ms`, `sse_transport_ms`, `buffer_ms`) —
    origin = SSE wrapper start (`sse_started`), i.e. **after** auth/deps/quota.
  - RAG `timing` block in the `done` frame (`website_lookup_ms`, `session_resolution_ms`,
    `retrieval_ms`, `embedding_ms`, `load_chunks_ms`, `user_message_persist_ms`,
    `prompt_construction_ms`, `ttft_ms`, `total_ms`, …).

32 real requests (tenant A: 16, tenant B: 16; each 8 cold + 8 cache-warm). 100% HTTP 200, 100%
semantically correct answers, 0 cross-tenant leakage. All 32 requests matched 1:1 to their
server-side log lines by `request_id`.

## 5. Clock Model & Measurement Discipline

- Client timestamps originate at host `time.perf_counter()` (client origin).
- Server timestamps originate at container `time.perf_counter()` (server origin).
- **Cross-origin arithmetic is prohibited.** Only within-origin deltas are compared.
  Consequences: client-side segments and server-side segments are reported in separate tables;
  the "request → SSE open" client segment is _derived_ (client first-frame minus server
  `first_event_ms` minus loopback network), not directly instrumented, and labeled as such.
- All percentiles are sample percentiles (nearest-rank interpolation) over N=32.

## 6. Corrected Prior Measurement (finding)

`scripts/perf/benchmark_live.py` runs `parse_sse_lines(buffered, res)` **after** the full stream
completes; therefore its `msg_first_ms` was stamped at stream completion. Verified on this run by
re-deriving the same behavior:

- Client `done_event` P50 = 4.26 s, P95 = 10.16 s (this run), matching the previously reported
  "client e2e TTFT" (4.92 s / 8.28 s) — i.e. the old number was stream-_completion_ time.
- The valid in-loop first-frame metric (`e2e_ttft_ms`) from the old dataset (tenant A P95 ≈ 3.81 s)
  is consistent with Probe C's `client.first_frame` P50 = 2.08 s / P95 = 2.55 s.

**Conclusion of this section:** no unexplained multi-second "provider → SSE" gap exists. The prior
report's largest gap was a client measurement artifact. The real TTFT is the pre-generation +
provider TTFT shown in §7–§9.

## 7. Client-Side Waterfall (Segment Table 1)

Client origin (all ms; N=32):

| Segment                                        |        P50 |        P95 |        P99 |      N |
| ---------------------------------------------- | ---------: | ---------: | ---------: | -----: |
| A1 request start → first SSE frame (`sources`) |     2075.5 |     2552.3 |     2692.8 |     32 |
| A2 first frame → first `message` delta         |     1282.6 |     2771.7 |     3422.4 |     32 |
| C/D first `message` → `done` event             |      555.7 |     6331.6 |     9972.8 |     32 |
| E `done` → client marshal/close                |      292.0 |      415.9 |      518.2 |     32 |
| **Client first-`message` TTFT (= A1+A2)**      | **3423.5** | **4486.6** | **5345.2** | **32** |

Server origin (all ms; N=32; origin = SSE wrapper `sse_started`, **excluding** auth/deps/quota):

| Segment                                                          |    P50 |    P95 |     P99 |   N |
| ---------------------------------------------------------------- | -----: | -----: | ------: | --: |
| S1 wrapper start → `sources` yield                               | 1138.7 | 1715.0 |  1832.9 |  32 |
| S2 `sources` yield → first `message` yield                       | 1282.1 | 2771.5 |  3420.7 |  32 |
| S3 full SSE transport (wrapper → stream done)                    | 3707.3 | 9565.7 | 14443.8 |  32 |
| router TTFT (fallback chain start → first provider delta)        |  809.9 | 2257.8 |  2893.3 |  32 |
| RAG TTFT (`t2` → first provider delta; includes adaptive health) | 1225.8 | 2718.3 |  3367.3 |  32 |
| Derived adaptive-health overhead ≈ RAG TTFT − router TTFT        |  ≈ 416 | ≈ 460* |  ≈ 474* |  32 |

\* derived from per-request differences; subject to Redis RTT variance (§13).

The A2 client segment (1282.6) matches S2 (1282.1) within ~0.5 ms + loopback, confirming the
server emits the first `message` frame essentially coincident with the client seeing it.

## 8. Server-Side Breakdown of the Pre-Generation Window

RAG-internal component timings (server, p50/p95 ms, N=32, from `done` timing block):

| Component                            |   P50 |   P95 | Notes                  |
| ------------------------------------ | ----: | ----: | ---------------------- |
| website lookup (Mongo)               |  70.7 |  95.4 |                        |
| session resolution (Mongo)           |  73.2 |  85.0 |                        |
| retrieval (vector search, cacheable) | 101.5 | 313.0 | miss: p50 241.2        |
| embedding (cacheable)                |  34.9 | 153.0 | miss: p50 85.1; hit: 0 |
| chunk loading                        |  86.6 | 261.6 |                        |
| user-message persist (Mongo)         |  74.4 |  83.0 |                        |
| prompt construction                  |   1.2 |   3.2 |                        |

These six components total ~400–480 ms (p50) and each is dominated by one Mongo/Redis round-trip
(§13). The remainder of S1 (1138.7) is un-instrumented stage/serialization work between those
operations (dict/JSON building, model conversion, event dispatch) and RTT variance.

The **derived server pre-wrapper window** (client request arrival → `sse_started`) ≈
`client.first_frame (2075.5)` − `S1 (1138.7)` − loopback (≈1 ms) ≈ **~935 ms**. This window
holds: FastAPI dispatch, middleware, JWT principal, Redis rate limiter, API-key rate limit,
quota check (Mongo), RagService construction, and `usage.check_limit` (Mongo) — i.e. several
high-latency Redis/Mongo round-trips. It is not directly instrumented and is the least certain
estimate in this report.

Sources-citation confidence work, usage accounting, and persistence all occur **after** the first
`message` delta (in the `done` frame), so they do not contribute to TTFT. No response buffering
exists apart from the 50 ms first-event coalescing buffer (§10).

## 9. Segment Classification (A–E)

| Class                                                                                  | Definition                           | Client-visible (P50, N=32) |                                    Share of TTFT |
| -------------------------------------------------------------------------------------- | ------------------------------------ | -------------------------: | -----------------------------------------------: |
| **A. RAG / pre-generation** (request start → first provider delta & its orchestration) | A1 (2075.5) + adaptive health (≈416) |               **≈ 2.49 s** |                                       **≈ 73 %** |
| **B. Provider** (fallback chain start → first provider delta)                          | 809.9                                |                   ≈ 0.81 s |                                           ≈ 24 % |
| **C. Server streaming** (provider delta → SSE yield)                                   | ≈ 0.05 s                             |                    ≈ 1.5 % | (the 50 ms coalescing buffer + event conversion) |
| **D. Network / HTTP / SSE transport** (server yield → client frame)                    | < 0.01 s                             |                    < 0.5 % |                            ssd proven by Probe D |
| **E. Client parsing** (frame arrival → `message` stamped)                              | < 0.01 s                             |                    < 0.5 % |                                       same probe |

A2 (1282.6) = **B (809.9) + C (≈50) + adaptive-health (≈416)** + small event overhead; the
measured sum reconciles to A2 within a few ms.

## 10. Transport Isolation Probe (Probe D)

Deterministic schedule: `sources` at +0, first `message` at +1400 ms, then 10 tokens every 150 ms,
`done` at the end — pushed through the exact production SSE helpers with `buffer_ms=50`:

- Scheduled sources→message gap: **1450 ms**
- Observed (10/10 trials): 1458.9 – 1464.9 ms → **≈ +10 ms** total for SSE framing +
  FastAPI/StreamingResponse + loopback + client parse.
- Full stream completed within ~2920 ms of schedule (2950 ms expected) → **no hidden buffering,
  no gzip, no middleware holding the stream, no proxy.**

The 50 ms coalescing buffer adds at most ~50 ms to the first `message` (and on average ~50 ms given
token gaps > 50 ms); Probe D confirms this is the only streaming-side delay and it is small.

## 11. Provider Analysis

Provider table (from this run; provider TTFT = router-level, client TTFT = client first-`message`):

| Provider   |   N | Provider TTFT P50/P95 (ms) | Client TTFT P50/P95 (ms) | Client Δ (frame→message) P50/P95 |
| ---------- | --: | -------------------------: | -----------------------: | -------------------------------: |
| groq       |  21 |             711.2 / 1055.2 |          3430.9 / 4215.4 |                  1191.0 / 1539.6 |
| openrouter |  11 |            1144.5 / 2837.7 |          3416.2 / 5182.3 |                  1691.6 / 2989.2 |

- Provider TTFT is a minority of client TTFT (≈0.81 s of 3.42 s pooled).
- OpenRouter is consistently slower on TTFT (+433 ms p50) and drives the P95/P99 tail on both
  TTFT (client P95 5182 vs 4215) and full-stream duration (client `done` P95 14.1 s vs 4.8 s).
- Gemini was skipped for all 32 (cooldown/quota; `ai_circuit_skipped` log lines confirmed).
  Post-window health snapshot: gemini cooldown (failures=1), groq cooldown (failures=1, latency
  704 ms), openrouter healthy — state is live-mutable and shown only for context.
- Provider-only control probe (Probe A, N=12, server): groq TTFT P50 **741 ms**, P95 5502 ms
  (P95 inflated by the first-call cold HTTP connection, 6.4 s outlier) — consistent with what the
  production router reports for groq (711 ms). No per-delta batching in any provider client.

## 12. Cache Miss vs Hit Analysis

| Cache state |   N | client `sources` frame P50/P95 | client first-`message` P50/P95 | server RAG TTFT P50 |
| ----------- | --: | -----------------------------: | -----------------------------: | ------------------: |
| miss        |  16 |                2289.6 / 2682.0 |                3614.8 / 4228.7 |              1197.2 |
| hit         |  16 |                1709.7 / 1905.2 |                3039.0 / 4967.9 |              1263.1 |

- Warm cache saves **~580 ms** (p50) on the client **frame** (embedding 85 + vector search 241 +
  cache GET over Redis RTT), i.e. purely in pre-generation.
- The streaming/provider segment (frame→message) is **identical** for miss vs hit (1282 vs 1319 ms
  server-side) — the first-`message` gap is **not** caused by retrieval latency.
- Hit P95 is worse than miss only because the hit pool contains more OpenRouter requests
  (provider TTFT dominates the p95), not because of the cache.

## 13. Redis/Mongo Latency Evidence

Measured inside the api container (same Redis client as the app, no URL exposed):

- Single Redis GET round-trip: **65–70 ms** steady-state; first call 123–553 ms; burst spikes to
  **300–500 ms** per call observed in a second sample window.
- 6 sequential GETs: 416 ms (favourable window) or 1834 ms (burst window); a single 6-GET
  **pipeline: 67 ms**.
- `ProviderHealthStore.is_available()` **re-reads** health via `get_health()` → `_build_ordered_providers()`
  issues **6 sequential Redis GETs per request** (3 providers × 2 reads). This is included in RAG
  TTFT but **before** the router TTFT starts: derived overhead ≈ 416 ms p50, and it tracks the
  Redis RTT window (can exceed 1.8 s under burst).
- Pipelineing the six reads would collapse this to ~1 RTT (~70 ms), saving ≈ 0.35 s p50 and up to
  ~1.7 s under Redis burst, with zero behavior change.

## 14. Root Cause & Decision

**ROOT CAUSE: The client-visible first-`message` delay is dominated by RAG pre-generation
latency (request→provider-first-delta ≈ 2.5 s of the 3.42 s P50), composed of:**

1. ~0.94 s auth/deps/quota/usage/RateLimit window before SSE open (5+ Redis/Mongo round-trips;
   derived, not directly instrumented);
2. ~1.14 s inside the SSE wrapper before `sources` (website + session + retrieval + persist =
   6+ round-trips on 65–500 ms RTT services);
3. ~0.42 s adaptive-router health reads (6 serialized Redis GETs, `is_available()` re-reading
   health) before the provider is even called;
4. - provider TTFT 0.81 s.

**The streaming path is clean** (Probe D: +10 ms). Provider TTFT is a minority contributor. The
previously feared "provider→SSE gap" does **not** exist beyond the 50 ms coalescing buffer.

**EVIDENCE:** client `sources` frame p50 2075.5 (731) / `first message` p50 3423.5; server
wrapper→sources 1138.7; adaptive health ≈416 (Redis seq-6 = 416 ms); router TTFT 809.9; Probe D
transport +10 ms; `msg_first` artifact (§6) reproduced.

**MEASURED CLIENT VISIBLE LATENCY:** P50 3423.5 ms, P95 4486.6 ms, P99 5345.2 ms (N=32).
Target (< 3000 ms P95) **NOT met**.

**EXPECTED IMPACT (not yet implemented — see §15):** pipeline/batch the six Redis health reads
(−0.35 s p50, −1.7 s tail) and defer/cache the ~0.94 s auth+quota+usage window → ~1.5–2.1 s
client `message` P95, meeting the target.

**RISK:** any batching of health reads must preserve fail-open semantics (BE-Q08 audit); caching
quota results must never over-allow credits (idempotency concerns).

**RECOMMENDED NEXT CHANGE (audit only):**

1. Merge `is_available` into a single read (drop the second `get_health`) and/or issue the six
   health reads as one Redis pipeline per request in `_build_ordered_providers`.
2. Instrument `request-received → sse_started` explicitly (one perf_counter pair in the route
   handler + wrapper) so the ≈0.94 s auth/deps/quota window becomes directly measurable.
3. Then re-run Probe C N≥30.

**DECISION: RAG PRE-GENERATION BOTTLENECK IDENTIFIED**

## 15. Recommended Next Change (precise, not implemented)

| #   | Change                                                                                                                           | Location                                                                                 | Est. client TTFT saving        | Risk                       |
| --- | -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------ | -------------------------- |
| 1   | Pipeline the 6 per-request Redis health reads (or single-snapshot read with batched GET)                                         | `backend/services/ai/provider_router.py:_build_ordered_providers` + `provider_health.py` | −0.35 s p50, up to −1.7 s tail | Low (keep fail-open)       |
| 2   | Add explicit request→sse_started instrumentation                                                                                 | route handler + `stream_answer_with_usage`                                               | measurable, ~0.9 s window      | None (measurement only)    |
| 3   | (Later, separate task) move auth/quota/usage checks to overlap RAG/stream start; consider per-request snapshot caching for quota | `backend/api/deps.py`, `stream_answer_with_usage`                                        | up to −0.9 s                   | Medium (credit accounting) |

Nothing in this list was implemented. The only change to the working tree is this report.

## 16. Regression & Verification

- Same tree previously passed full suite (2201 collected, 0 failures) for REAL-TTFT-02;
  the tree is unmodified since (HEAD `5718ac4`).
- Full suite re-invocation for this audit: **`pytest -p no:cacheprovider -q` → 2201 collected,
  2194 passed, 7 skipped, 0 failed, exit 0**; **`mypy backend` → success (199 files, 0 issues)**;
  **`ruff check backend tests` → 9 pre-existing findings, all in files this audit did not touch
  (`confidence.py`, `test_confidence.py`, `test_hybrid_search.py`, `test_rag_accuracy_deep_dive.py`,
  `test_rag_answerability.py`); no repo `.py` file was modified by this audit, so the modified-files
  gate is trivially clean.**
- Data-quality checks this run: 32/32 HTTP 200; 32/32 semantically correct answers (fee figures,
  installments, refund, coverage all accurate); 0 cross-tenant leakage; 32/32 request_ids matched
  to server logs; 0 `fallback_attempts>0` rows that changed provider mid-stream (fallback is
  pre-stream only, confirmed by code and Probe A logs).

## 17. Git Safety, Cleanup & Limitations

- **Git:** no `reset`/`clean`/broad `restore`/`stash`/commit/push executed. Working tree preserved
  (108 pre-existing modified files from earlier work — untouched). Only new repo file:
  `docs/RAG_TTFT_STREAMING_WATERFALL_2026-09-08.md`.
- **Container:** probe files (`/tmp/probe_provider.py`, `/tmp/probe_sse_transport.py`,
  `/tmp/probe_health.py`, `/tmp/probe_redis_latency.py`) remain inside the `webchat-api` container
  as measurement-only artifacts; Probe D's server bound `127.0.0.1:8123` in-container only and was
  never exposed. No endpoint was added to the production app.
- **No secrets** appear in this report or any probe output (Redis URL / API keys never printed).
- **Limitations:** the request→sse_started window is _derived_ (~0.94 s) rather than directly
  instrumented; Redis RTT is bursty, so adaptive-health overhead is reported as a range; N=32 for
  the pooled client/server tables (N=21/11 per provider) is adequate for P50/P95 but not P99.0+
  precision.

---

_Decision string: **DECISION: RAG PRE-GENERATION BOTTLENECK IDENTIFIED**._
