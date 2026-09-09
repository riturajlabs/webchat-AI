# RAG Real-TTFT Benchmark (RAG-PERF-06 / REAL-TTFT-01)

Date: 2026-09-08
Branch: `main` @ `5718ac4` (dirty worktree preserved)
Measurements: REAL provider TTFT through the production streaming path; retrieval leg is the ACC-01/02 harness proxy.

## 1. Environment / Provider

- Dev box; no containerized app running. `mongo:27017` / `redis:6379` hostnames are **unresolvable** from this shell; no local Mongo/Redis; app not running. Local Ollama catalog empty.
- Provider credentials exist **by name** in `.env.development` (values never printed): `GEMINI_API_KEY` (present), `GROQ_API_KEY` (present), `OPENROUTER_API_KEY` (present); Jina/Cohere absent. Provider chain resolves to `['gemini', 'groq', 'openrouter']`.
- Backing-store limitation: the real MongoDB vector search + Redis retrieval cache (production path) cannot be exercised here; retrieval in this run uses the deterministic ACC-01/02 lexical proxy (in-memory, no network). **Retrieval/TTFT contributions from the true Mongo/embedding index are therefore MEASURED SYNTHETIC / UNMEASURED, as labelled.**

## 2. Model

`gemini-2.5-flash` (first in `generation_provider_order`). Primary candidate used by the production streaming path; groq/openrouter act as configured fallbacks only.

## 3. Sample Count

- **22 real generation requests** that reached a first provider delta (N target was ≥30; hard stop: the gemini **free tier caps at 20 `generate_content` requests/day**, and the run itself hit that cap — see §11). `N=22` is the largest safe sample today; further sampling is impossible until the window resets or a paid key is configured.
- Additional non-TTFT calls: 2 no-answer (1 abstained with no provider call, 1 went to provider), 1 gated-typo observation (abstained, no provider call), 1 cross-site guard (call).
- Cost: all on the operator's configured key; no models downloaded; nothing manufactured.

## 4. TTFT Definition

**TTFT = time from the production generation request being initiated until the first real provider-generated streaming delta/token is received.**

Two clocks recorded per request:

- `service_ttft_ms` — RagService's own `t2 → first delta` (provider wait only).
- `e2e_ttft_ms` — request start (retrieval + context) → first provider delta (this is the reported "real TTFT").

This does NOT redefine TTFT to drop production work; the e2e clock includes retrieval/context/confidence before the provider call.

## 5. Benchmark Questions / Categories

| category                   | question                                                      |
| -------------------------- | ------------------------------------------------------------- |
| exact                      | What is the annual BCA tuition fee?                           |
| short                      | BCA fee?                                                      |
| broad                      | Tell me about admissions and fee at BCA                       |
| typo                       | hosptel for BCA students                                      |
| multi-source               | BCA courses and placement support                             |
| follow-up (2-turn session) | How much does BCA charge annually? → Is that per year?        |
| no-answer                  | What is the capital of France? / What is the MBA tuition fee? |
| gated-typo observation     | teach me about BCA addmission                                 |
| cross-site guard           | Who is the dean of the BCA program at Academy B?              |

## 6. P50 / P95 / P99 (real TTFT)

### Raw — all 22 real generation requests

| metric        | value            |
| ------------- | ---------------- |
| Real TTFT P50 | **2053 ms**      |
| Real TTFT P95 | **5193 ms**      |
| Real TTFT P99 | **5437 ms**      |
| min / max     | 610 ms / 5437 ms |
| mean          | 2646 ms          |

### Two observable operating regimes

| regime                                                                         |   n |  P50 |      P95 |  P99 | mean |
| ------------------------------------------------------------------------------ | --: | ---: | -------: | ---: | ---: |
| Normal (no quota stall, <3000 ms)                                              |  15 | 1543 | **2471** | 2471 | 1510 |
| Quota-stalled (gemini free-tier 20/day cap → 429 + in-client retry + fallback) |   7 | 5041 |     5437 | 5437 | 5081 |

Interpretation: in the normal regime the real provider TTFT is **below the 3 s budget** (P95 2471 ms). Every ≥3000 ms sample (7/22) is caused by the gemini free-tier **daily request cap**, i.e. a provider availability + latency problem — the same configured provider the production path would use. Measured real behavior therefore fails the target once the cap is reached (at just 20 requests/day).

## 7. Retrieval vs Provider Split

- Retrieval total (harness leg — **MEASURED SYNTHETIC**): P50 0.24 ms, P95 0.41 ms, P99 0.60 ms, mean 0.23 ms.
- Provider first-token (service `ttft_ms` — **MEASURED REAL**): P50 2048 ms, P95 5191 ms, P99 5435 ms, mean 2644 ms.
- Retrieval contribution to raw real TTFT: ≈ **0.0 %** in this measurement leg. The provider is ~100 % of the e2e TTFT. (Caveat: real Mongo/embedding index cost was not measurable here — see §14; even a non-trivial index cost is secondary to a 2–5 s provider wait.)

## 8. Cache Hit vs Miss (F-02 schema-2 verification)

- Miss samples (n=7): real TTFT P50 2079 ms, P95 5437 ms (includes quota stalls).
- Hit samples (n=15): real TTFT P50 1612 ms, P95 5193 ms.
- F-02 behavior confirmed in-vivo: cache-hit requests skip embedding/vector/keyword/RRF/reranking (retrieval-stage times collapse; `retrieval_cache=hit`) — the generation/wait-to-first-token still runs the real provider on every request, as designed.
- Hit vs miss difference in this leg is driven by provider/regime variance rather than by retrieval (retrieval is sub-ms either way).

## 9. Accuracy / Isolation Verification (during real benchmark)

- **No-answer**: "What is the capital of France?" → correct abstention. `fallback=True`, no provider call, ~1 ms e2e. The plausible-but-absent MBA query followed the existing documented `unsupported_answer_risk` path (faithfulness warning logged) — unchanged from ACC-02's recorded behavior (risk=1), not a regression.
- **Cross-site**: "…dean… at Academy B?" produced only site-A sources (`sources_A_only=True`) → **zero cross-website leakage**.
- **Gated-typo**: "teach me about BCA addmission" abstained under the production confidence gate (`answerability_blocked … confidence 0.218`) → the gate remains active; short-query/typo leniency did not over-authorize.
- **Typo improvements intact**: "hosptel for BCA students" generated a grounded answer (clean ~1543 ms sample).
- No confidence thresholds relaxed; answerability/context gate active; no candidate-pool broadening.

## 10. Reranker Status

**REAL RERANKER QUALITY: UNMEASURED.** The pure/synthetic env uses stored zero-vectors (degenerate cosine), and the true Mongo + real-embedding index is unavailable; the reranker was not exercised non-degenerately here. No conclusion about reranker quality is drawn.

## 11. Bottleneck Analysis (ranked)

| component                                             |                    P50 |                   P95 |     P99 |           contribution |
| ----------------------------------------------------- | ---------------------: | --------------------: | ------: | ---------------------: |
| provider first-token (gemini)                         |                2048 ms |               5191 ms | 5435 ms |         ~100 % of TTFT |
| provider rate cap (free tier, 20/day) → 429 stall     |                      — | 4.9–5.4 s when active |       — | pushes P95 over budget |
| retrieval (synthetic leg)                             |                0.24 ms |               0.41 ms | 0.60 ms |                  ≈ 0 % |
| embedding / vector / lexical / RRF / rerank / context | sub-ms (synthetic leg) |                     — |       — |                  ≈ 0 % |

```
PRIMARY BOTTLENECK: provider first-token + provider rate-limit (gemini-2.5-flash free-tier, 20 requests/day → 429 retry stalls of 5+ s)
SECONDARY BOTTLENECK: none measured (retrieval ≈ 0 in the exercised leg)
OPTIMIZATION JUSTIFIED: NO (retrieval is not responsible; this is a provider-side availability/latency problem)
```

No speculative retrieval optimization was implemented. The remedy is operational: a paid/rate-ample gemini key, or prefer the faster fallback provider (groq observed at ~0.6–1.5 s first token) — a provider-selection/config decision, not a RAG-pipeline change.

## 12. <3 s P95 — PASS/FAIL

**FAIL** under the actually-configured provider: **real TTFT P95 = 5193 ms ≥ 3000 ms**, provider-dominated. In the normal (non-quota) regime P95 = 2471 ms, which would pass — but the configured free-tier key cannot sustain that regime past 20 requests/day.

## 13. Optimization Decision

- **No retrieval/RAG code optimization.** Retrieval measured ≈ 0 contribution; modifying it would be speculative.
- Provider-side recommendation (operator decision, no benchmark-config change made): use a paid/rate-ample generation key and/or order the faster provider first; re-run this benchmark after.

## 14. Limitations

- Retrieval leg is NOT the production Mongo/embedding index (`mongo:27017`/`redis:6379` unresolvable) — absolute index/search/cache costs are UNMEASURED; labelled SYNTHETIC throughout.
- N=22 < 30 (gemini free-tier 20/day cap), so P99/P95 at small n are nearest-rank; 7/22 samples include 429-retry stalls that dominate P95.
- Per-row provider attribution (gemini vs groq fallback after circuit-open) is inferred from logs/order, not stored per row.
- Follow-up turn-2 produced no provider samples (gated abstention — correct no-fabrication behavior), so follow-up TTFT is not represented.
- Single-day run; repeatability limited by the daily cap.

## 15. Reproduction Command

```bash
# Load the configured provider env into the subprocess (never prints values),
# then run the ACC-06 real-TTFT benchmark (production RagService + real chain).
# Paced 12 s; ~8–9 min; will exhaust the 20/day free-tier cap.
.venv/bin/python /tmp/opencode/acc06_real_ttft.py
# SMOKE=1 .venv/bin/python ...   # 1-request sanity mode
```

Artifacts: `/tmp/opencode/acc06_real_ttft_results.json`.

## 16. Git Safety / Status

- No repository files were modified for this benchmark (scripts and artifacts live in `/tmp/opencode`); nothing committed or pushed.
- Worktree remains the pre-existing dirty `main` @ `5718ac4` (104 dirty entries untouched).
- No production configuration was changed; `.env.development` was only **read** into the benchmark subprocess (secret values never printed).
- Phase 10 regression after the work: full non-e2e suite **2194 passed, 7 skipped**; `mypy backend` clean (199 files); Ruff clean on changed files.

---

# Final Decision

```
DECISION: REAL TTFT TARGET FAILED — BOTTLENECK IDENTIFIED
Real TTFT P50: 2053 ms
Real TTFT P95: 5193 ms
Real TTFT P99: 5437 ms
Sample count: 22
Provider: gemini-2.5-flash (free tier; groq/openrouter configured fallbacks)
Model: gemini-2.5-flash
Primary bottleneck: provider first-token latency + provider free-tier 20-requests/day rate cap (5+ s stalls)
Optimization performed: NONE (retrieval not materially responsible; provider-side fix required)
```
