# RAG TTFT: Controlled Groq Provider Probe — Measurement-Only (RAG-PERF-09)

Date: 2026-09-09 (probe window 02:33Z–02:35Z) · Branch `main` · Stack: production docker compose
(Upstash Redis, Atlas Mongo, OpenRouter/Groq adaptive routing). Continuation of the
RAG-PERF-06/07/08 critical-path TTFT audit toward `client.first_msg P95 < 3000 ms`.

Scope: an **explicitly labelled, read-only, out-of-band provider probe** to separate three hypotheses
before any routing change is considered:

```text
Groq is intrinsically faster
        VS
Groq is only faster during a low-load window
        VS
Groq cannot sustain our production request rate
```

**NO production code/routing/config was changed in this step.** No provider order, weights, cooldown,
health thresholds, fallback behavior, billing/quota, or tenant data were touched.

Number labels: **MEASURED** (real production stack, real provider key), **DERIVED** (composed from
measured), **UNMEASURED** (reasoned). No SYNTHETIC numbers.

---

## Controlled Groq Probe

### Methodology

- Ran inside the production `webchat-api` container (real env, real `GROQ_API_KEY`,
  `model=openai/gpt-oss-20b`, `AI_PROVIDER_ROUTING_MODE=adaptive`, order
  `[gemini, groq, openrouter]`).
- Used the **exact production provider client** `GroqGenerationClient` (`backend/ai/providers/groq.py`)
  directly — same wire format, same `build_chat_payload`, same `iter_openai_first_token_guarded`,
  same `shared_http_client`, same `map_openai_http_error` normalization.
- Deliberately **bypassed the router** so the probe wrote **zero** provider-health state, zero billing,
  zero Redis/DB writes: the probe never called `record_success`/`record_failure`/`is_available`.
- **Fresh, independent prompts** (33 general-knowledge questions, BCA-free, distinct from the routing
  benchmark set) with a fixed concise system instruction.
- **Conservative pacing**: 1.2 s between requests (probe runtime 46.1 s for 33 attempts).
- No aggressive retry was implemented; the client's own error normalization surfaced the status
  (HTTP 429 → `GenerationUnavailableError("Groq rate limit exceeded (HTTP 429).")`).

Per-request captured: request start, first/second/third delta timestamps, stream end,
`provider_ttft_ms`, `first_to_second_ms`, `second_to_third_ms`, `generation_duration_ms`,
`output_tokens`, `tokens_per_second`, model, and any error.

### Provider Conditions

- The probe inherited a Groq quota bucket that earlier production routing traffic
  (`before_perf09` benchmark, 02:16Z–02:23Z) had recently consumed; the Groq key is a
  rate-limited token at this request volume.
- **Zero production chat requests were in flight during the probe window** (container log shows 0
  `chat_embedding`/`chat_stage`/`ai_provider_selected` events 02:30Z–02:36Z). The 429s are intrinsic
  to the Groq key rate limit, not concurrent app contention.
- Health state **unchanged** before vs after the probe (read from Redis both sides): groq still
  `cooldown` (last_failure 02:22:07Z from the routing benchmark, `average_latency_ms 769.88`),
  openrouter `healthy` (EMA 2170.23), gemini `cooldown` (EMA 4198.66). The probe wrote nothing.

### Results (MEASURED, out-of-band, n=33)

| Attempt | Result | TTFT (ms) | generation (ms) |
| ------- | ------ | --------- | --------------- |
| 0       | OK     | 3615.8    | 3649.6          |
| 1–3     | 429    | —         | —               |
| 4       | OK     | 1287.7    | 1353.4          |
| 5–32    | 429    | —         | —               |

- **Successes 2/33 (6.1%); failures 31/33 (93.9%)**, all `GenerationUnavailableError … HTTP 429).
- Successful TTFT: 3615.8 ms, 1287.7 ms (p50/p95 = 3615.8 given n=2 — see honesty note below).
- Successful generation: 3649.6 ms, 1353.4 ms.
- `tokens_per_second` recorded 486 / 599, but `output_tokens` (1775 / 810) is anomalous for 89–157
  output chars — likely a cumulative/misattributed usage read; **not used for any conclusion.**
  Throughput conclusions rest on generation duration, which is well-measured.

### Rate-Limit Behavior (MEASURED)

- **Aggressive and immediate**: 30 consecutive 429s at the end (idx 5→32), plus idx 1–3 near the start.
- Even at 1.2 s pacing the key returns 429 after the initial budget is spent — far below any
  production request rate.
- No partial streams, no stream stalls, no separate timeouts observed: the dominant failure mode is
  the 429 reject before first token. Exactly one mode captured, and it is external.

### Sustainability (classification, MEASURED evidence)

| Regime            | Evidence                          | Verdict                                     |
| ----------------- | --------------------------------- | ------------------------------------------- |
| Early (idx 0–4)   | 2 OK (TTFT 1288–3616 ms) + 3× 429 | some capacity, but already 429 by request 1 |
| Middle (idx 5–19) | 15/15 × 429                       | exhausted                                   |
| Late (idx 20–32)  | 13/13 × 429                       | exhausted                                   |

**Classification: FAST BUT RATE-LIMITED / UNSTABLE at production request rates.** The isolated fast
routing-benchmark window (9 samples, TTFT p50 774.5 ms, p95 928.4 ms) is a recovery artifact of a
just-recovered EMA, not a steady-state capability. Under sustained/out-of-band use Groq rejects
~94% of requests; when it does answer, TTFT (1288–3616 ms) is not better than OpenRouter.

### Comparison With OpenRouter

**Comparison is explicitly NOT a causal A/B** (different models + different providers + the demo key is
rate-limited; identical prompts were not provided to both during the probe).

| Metric           | Groq (probe, MEASURED) | Groq (routing bench, MEASURED) | OpenRouter (BEFORE, MEASURED) | Note                                     |
| ---------------- | ---------------------: | -----------------------------: | ----------------------------: | ---------------------------------------- |
| TTFT P50         |        3615.8 ms (n=2) |                 774.5 ms (n=9) |              1189.5 ms (n=22) | probe n=2 — not statistically meaningful |
| TTFT P95         |              3615.8 ms |                       928.4 ms |                     2056.4 ms | probe successes all pre-exhaustion       |
| generation P50   |              3649.6 ms |                       953.1 ms |                     2508.5 ms | probe n=2                                |
| generation P95   |              3649.6 ms |                      1118.0 ms |                     5429.9 ms | —                                        |
| error rate (429) |         93.9 % (31/33) |                              — |                    0 % (0/22) | Groq threshold binding                   |
| 429 rate         |  30 consecutive by end |                      1 mid-run |                             0 | —                                        |

DERIVED: even using the _generous_ routing-benchmark groq numbers (774 ms p50), the 93.9% probe 429
rate means the effective routed success latency is `0.939 × (429 → openrouter fallback ≈ 1189 ms

- fallback overhead) + 0.061 × 774 ms` ≈ **>1.2 s p50 with severe tail risk** — no better than the
  current openrouter-primary steady state, and a _downgrade_ in reliability.

### Materiality

- **CASE B applies: Groq is clearly faster in isolated windows (routing-bench p50 774 ms) BUT its 429
  rate (93.9% under out-of-band load) is material and external.** The bottleneck is the provider's
  key/tier capacity, not our router.
- A routing change to prefer Groq more often would **increase** 429s → openrouter fallback churn →
  worse score (`score=0.363 … cooldown_count=1` observed when groq flipped to cooldown mid-benchmark),
  a well-measured negative-reinforcement loop. This is exactly the "NOT SAFE" case.
- **No production routing/provider optimization is justified by measurement.** The P95 < 3000 ms
  client target remains blocked by external provider TTFT/capacity (OpenRouter 1189/2056 p50/p95) plus
  generation streaming, consistent with RAG-PERF-06/07/08.

### Routing Safety Assessment (P9.4, read-only)

Verified in source that the existing protection chain is intact and functioning:

```text
Groq HTTP 429
   → map_openai_http_error → GenerationUnavailableError (401/402/403/429 → "unavailable")
   → FallbackGenerationClient.stream_generate catches, records failure, advances to next provider
   → record_provider_failure (metrics) + health.record_failure → cooldown (60 s base,
     doubling, capped 300 s) via ProviderHealthStore
   → AdaptiveProviderRouter ranks cooldown providers below healthy ones next request
   → OpenRouter serves the request
```

Observed in the routing benchmark (`before_perf09`): groq 429 at 02:22:04Z →
`generation provider 'groq' failed … trying next` → openrouter served `ttft_ms 1345.69, total 2548`
with `health.record_failure` (`cooldown_seconds=60`); the next request ranked openrouter
`score=0.363 … cooldown_count=1`. **Fallback works and must NOT be modified.**

### Decision

- The controlled probe **does not clear the bar** for any production change:
  1. material latency improvement — ✗ (groq advantage is windowed, not sustained),
  2. acceptable rate-limit behavior — ✗ (93.9% 429),
  3. acceptable reliability — ✗,
  4. safe fallback — ✓ (existing chain confirmed, unchanged),
  5. acceptable answer quality — not reached (unmeasurable at 6% success).
- No cooldown tuning, no provider reorder, no weight change, no health-threshold change is made.
- The residual bottleneck is **external provider TTFT + capacity** (OpenRouter first-token p95 ≈
  2056 ms), not the router.

**DECISION: GROQ FASTER BUT RATE-LIMITED — NO SAFE ROUTING CHANGE**

---

## Safety Check (final)

- `git status --short` count and `git rev-parse HEAD`: the only new workspace change is this report
  document (the measurement artifact). Mock probe/harness artifacts live outside the repo
  (`/tmp/opencode`, `/tmp` in-container) and are not part of the tree.
- NO production routing change · NO provider order change · NO cooldown change · NO weight change ·
  NO commit · NO push · NO destructive Git.
- Health state (Redis) verified unchanged by the probe.
- `/api/health` still returns 200.
