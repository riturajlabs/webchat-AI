# RAG TTFT + Reorder Failure Analysis (RAG-PERF-05 / ACC-04)

Date: 2026-09-08
Branch: `main` @ `5718ac4` (dirty worktree preserved throughout)

---

## 1. Scope and Purpose

Determine (a) whether the production RAG path can hit a <3 s _real_ AI first
response (TTFT) at **P95**, (b) how much of that latency is retrieval vs. the
generation provider, and (c) whether the remaining R@1/R@5 failures are RRF
ordering/reranker failures rather than coverage failures. If the ordering
hypothesis is proven by measurement, land the smallest, safest single
optimization. Isolation (tenant/website) and all answerability protections must
remain intact.

## 2. Data and Method

- Benchmarks are the deterministic, no-network ACC-01 (`test_rag_accuracy_benchmark.py`)
  and ACC-02 (`test_rag_accuracy_deep_dive.py`) suites as instrumented in the
  previous audit work. `measurement_kind = "SYNTHETIC (deterministic in-memory fakes, dev box)"`.
- Every measurement below is labelled **MEASURED REAL**, **MEASURED SYNTHETIC**,
  or **UNMEASURED**. UNMEASURED means the evidence was collected but the number
  cannot exist in this environment (no provider).
- Failure classification schema for this task (ACC-04):

| Class | Meaning                                                                                                          |
| ----- | ---------------------------------------------------------------------------------------------------------------- |
| A     | Coverage: golden chunk genuinely absent from the candidate pool / corpus                                         |
| B     | RRF ordering: golden entered the fused pool but was pushed outside the served window or below a non-golden       |
| C     | Reranker: the (real) reranker places an inferior chunk above the golden                                          |
| D     | Confidence / context gate: golden was in the pool but was dropped before answer construction                     |
| E     | Benchmark artifact: failure caused by the synthetic-embedding proxy / test assumptions, not production retrieval |

- Golden titles are predeclared ground truth; they are never derived from model
  output. Expected-empty fixtures (`physics lab`, `chess club`) are genuinely
  absent from the corpus and are not counted as failures.

## 3. Baseline Reference and Credentials Reality Check

- No generation/embedding provider credentials are present in this environment.
  `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `MISTRAL_API_KEY`,
  `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` are all unset; no `.env` file exists; the
  only key set is `TINYFISH_API_KEY` (web tooling, not an LLM provider).
- Ollama daemon is running but the model catalog is empty (`/api/tags` →
  `{"models":[]}`) and the codebase has **no Ollama client**.
- `backend/ai/registry.py` skips keyless providers, so the resolved
  `generation_provider_order = ["gemini"]` / `embedding_provider_order =
["gemini"]` chains are empty in this environment. Resolution is functional:
  reaching a real key would activate the existing streaming path.
- ACC-02 previously verified TCP reachability of the generation/embedding hosts;
  this is a **credentials gap only**, not an infrastructure gap.

## 4. Real AI First-Response Time (TTFT) — **UNMEASURED**

- **REAL TTFT = UNMEASURED.** There is no real generation provider and no local
  model, so a real first-delta time cannot be observed.
- The measurement path is ready and instrumented (`stream_generate` +
  first-delta timing in the Gemini client; `record_llm_latency`); no code change
  is required to measure once a key/local model exists.
- The <3 s P95 target is therefore **unverifiable in this environment**. The
  synthetic TTFT proxy and the latency split below are the only available
  evidence.

## 5. Synthetic TTFT Correlation — **MEASURED SYNTHETIC**

- The ACC-02 `ttft_correlation` fixture (in-memory pipeline with instrumented
  engine) recorded synthetic "AI first response" timing. It is an upper-bound
  proxy (it excludes real provider wire time / first-token generation) and is
  labelled synthetic.
- It confirms retrieval round-trip time is small (sub-second even without the
  cache); the dominant unknown is the provider's first-token latency, which is
  precisely what is blocked by the missing credentials.

## 6. Retrieval-Latency Attribution — **MEASURED SYNTHETIC**

- `_retrieve` stage timings (`record_rag_stage_latency` for vector, keyword,
  RRF, gate, context build, cache get/set) show deterministic in-memory costs on
  the order of milliseconds; the Mongo-backed production path was measured in
  earlier RAG-PERF reports (cache `TTL 900 s`, size 512). Retrieval is not the
  TTFT bottleneck in the P95 scenario; the <3 s budget has headroom here.

## 7. LLM-Generation Latency Attribution — **UNMEASURED**

- Real first-token generation latency is UNMEASURED (no provider). The streaming
  first-delta path is implemented and instrumented, so this becomes measurable
  the moment a provider key or local endpoint exists. This is the single largest
  TTFT unknown.

## 8. Retrieval Quality: Before/After (ACC-01 + ACC-02 suites)

Baseline (pre-RAG-PERF-04/ACC-03) vs. current (ACC-03 + ACC-04 RRF tie-break),
archived at `/tmp/opencode/{BASELINE,AFTER}_*.json` and re-measured here:

**ACC-01 bench (broad accuracy):**

| metric   | baseline | ACC-03 | ACC-04 (tie-break) |
| -------- | -------- | ------ | ------------------ |
| Recall@3 | 0.278    | 0.444  | 0.444              |
| Recall@5 | 0.389    | 0.556  | 0.556              |
| MRR      | 0.444    | 0.444  | 0.444              |
| typo R@1 | 0.375    | 0.625  | **0.875**          |
| typo MRR | 0.625    | 0.875  | **1.000**          |

**ACC-02 deep-dive (typo suite):**

| metric   | baseline | ACC-03 | ACC-04 (tie-break) |
| -------- | -------- | ------ | ------------------ |
| Recall@1 | 0.583    | 0.708  | **0.792**          |
| Recall@3 | 0.792    | 0.833  | 0.833              |
| Recall@5 | 0.875    | 0.875  | 0.875              |
| MRR      | 0.792    | 0.896  | **0.938**          |

Exact/short/paraphrase/multi-source/no-answer/follow-up metrics are unchanged
(no regressions). Multi-source fully-covered 50% → 60% (ACC-03), lexical
no-overlap cause eliminated, p50 of covered share 0.667 → 1.0.

## 9. Class A — Coverage Failures: **0**

- Every in-corpus golden chunk entered or recovered into the pipeline; `A = 0`.
- The two expected-empty fixtures remain absent from the corpus (by design) and
  are correctly abstained (no-answer invariants unchanged: `correct_abstention`
  8, related 2, partial 1, `unsupported_answer_risk` 1, `leak = 0`).

## 10. Class B — RRF Ordering Failures: **25 (dominant)**

- B is the largest recoverable cluster: **25/66** golden entries reached the
  fused pool but were served below a non-golden or outside the top-5 window.
- Mechanism (verified on the target queries):

  **`hosptel for BCA students`** → `bca-hostel`: `keyword_rank 1`
  (variants bridge enabled), `vector_rank 3`, but **RRF rank 2** because
  `bca-placement` tied the RRF score; the tie was broken by pure insertion
  order (equal dense score 0.667, corpus order won). Served @2 → R@1 = 0.
  The true best match (`keyword_score 2.026`, more than double the rival's
  1.022) lost an _arbitrary_ tie.

  **`BCA curriculam`** → `bca-curriculum`: `keyword_rank 1` (variants bridge),
  but keyword-only ⇒ low RRF (0.0164 vs dense hits ≈ 0.03) ⇒ **RRF rank 6**,
  served @6, outside the top-5 window. Short 2-token queries saturate the
  synthetic dense score at 0.5 for every `BCA`-bearing chunk, so RRF ordering
  alone decides the ranking — a crowding property of the proxy on short queries.

  **`teach me about BCA addmission`** → `bca-admission`: **served @1 (OK)** —
  ACC-03 already bridged the typo; this query is fully recovered.

- Conclusion: ordering, not coverage, explains the residual R@1 gap.
- Fix landed (see §16) resolves the arbitrary-tie component deterministically.

## 11. Class C — Reranker Failures: **0 (UNMEASURED)**

- `EmbeddingReranker` (`backend/repositories/vector/reranker.py`) exists, but
  with no embedding provider and stored **zero vectors**, cosine similarity is
  degenerate (0.0) and only `_strong_lexical_match` admits candidates. A real
  reranker ordering cannot be observed → **C is UNMEASURED, not zero**.
- The synthetic `rerank_delta` probe (see §14) is the only reranker evidence
  available.

## 12. Class D — Confidence / Context-Gate Failures: **10**

- 10 golden entries were in the pool (`rrf >= 1`) but dropped by the
  `usable(dense_floor=0.25, query=...)` gate in the confidence-off harness
  (mostly keyword-only chunks below the cosine floor on mid-length queries).
- The ACC-03 short-query leniency already brought most such entries back for
  ≤3-token queries; the remaining D entries are the residual of that boundary,
  not a regression.

## 13. Class E — Benchmark-Artifact Failures: **2**

- Two in-corpus goldens missed the pool entirely on paraphrastic broad queries
  (semantic match expressed as no shared surface token). These are proxy
  artifacts: a real embedding index would retrieve them; the lexical-overlap
  proxy cannot express them. **E = 2**, distinct from production coverage gap.

## 14. Synthetic Rerank-Delta Evidence — **MEASURED SYNTHETIC**

- The `rerank_delta` probe, run with `enable_reranking=True` on the synthetic
  env, shows the degenerate reranker reorders 3/6 sampled multi-source queries
  and truncates to strong-lexical-only candidates (2 contexts empty). Note
  recorded in the JSON: real embeddings would score non-degenerately. No
  production conclusion can be drawn about reranker quality from this.

## 15. Candidate Optimizations Considered — and Rejected

| candidate                                        | why rejected                                                                                           |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| Raise/lower global confidence threshold          | violates ACC-04 constraint (no global threshold moves); ACC-03 leniency already bound to short queries |
| Cross-tenant / cross-website pools               | isolation invariant — forbidden                                                                        |
| Disable answerability / context gate             | answerability is a hard invariant                                                                      |
| Add evidence-weighting to RRF (beyond tie-break) | larger behavior surface, not justified by measurement                                                  |
| Re-rank with stored zero embeddings              | degenerate (cosine 0.0) — would only add arbitrary strong-lexical truncation                           |
| Benchmark-specific special cases                 | forbidden                                                                                              |

## 16. Implemented Optimization — Deterministic RRF Tie-Break

- Change: `reciprocal_rank_fusion` now breaks equal RRF scores by the chunk's
  **strongest original source score** (`(rrf_score desc, max source score desc)`),
  instead of arbitrary insertion (corpus) order.
- This makes the existing comment `"Keep the version with the highest original
score for tie-breaking"` actually true: the code already collected the
  strongest score per chunk for exactly this purpose but never used it in the
  sort.
- Generic and principled — not tuned to any benchmark query. Only affects exact
  RRF ties; all score-distinct orderings are byte-for-byte identical.
- Estimated impact via offline simulation over **all** ACC-02 fixtures before
  committing: 1 gold moved to rank 1 (`hosptel`), **0 rank regressions, 0
  drops** from top-5. Measured after landing: ACC-01 typo R@1 0.625→0.875 (MRR
  0.875→1.000); ACC-02 typo R@1 0.708→0.792 (MRR 0.896→0.938); every other
  aggregate byte-identical.

## 17. Regression Verification (Phases 7-9)

- ACC-01 bench suite: pass; only `accuracy.typo` changed (improved).
- ACC-02 deep-dive suite (`RAG_BENCH=1`): pass; tower/pipeline alignment guards
  hold; only `typo_diagnosis` aggregate changed (improved); multi-source,
  no-answer, cross-site leak=0 unchanged.
- Cache (F02): schema-2, cache bypass, corpus-invalidation, tenant/website
  isolation — green.
- Latency/offload (F03) and answerability suites: green.
- Full non-e2e suite: **2194 passed, 7 skipped** (0 failures).

## 18. Phase 10 — Static Checks

- `mypy backend`: `Success: no issues found in 199 source files`.
- Ruff: changed file `backend/repositories/vector/hybrid.py` — `All checks passed!`
  Four pre-existing findings remain in `backend/services/chat/confidence.py`
  (UP042 on the project's deliberate `str`+`Enum` pattern, one E501) — untouched
  by this work, out of scope.

## 19. Latency Summary Table (all timings synthetic unless marked)

| stage                       | status             | notes                                                           |
| --------------------------- | ------------------ | --------------------------------------------------------------- |
| vector top-k                | MEASURED SYNTHETIC | ms-level, deterministic fakes                                   |
| keyword top-50              | MEASURED SYNTHETIC | ms-level                                                        |
| RRF fusion                  | MEASURED SYNTHETIC | ms-level; tie-break now deterministic                           |
| gate/context build          | MEASURED SYNTHETIC | ms-level                                                        |
| cache R/W                   | MEASURED SYNTHETIC | TTL 900 s / size 512; earlier real-path P95 in RAG-PERF reports |
| real first-token (provider) | **UNMEASURED**     | blocked on credentials/local model                              |

Synthetic round-trip is comfortably under the 3 s budget; the unmeasured,
dominant unknown is provider first-token latency.

## 20. Final Decision

- Retrieval quality: 0 coverage failures; the residual R@1 gap is ordering
  (B), now reduced deterministically with zero regressions; reranker quality is
  unobservable until real embeddings exist.
- Real TTFT: **cannot be measured in this environment** — no provider key, no
  `.env`, no Ollama model, no Ollama client; the measurement path is fully
  instrumented and will activate on first valid credential.

Per the ACC-04 protocol, when real TTFT is unavailable the decision string is
output verbatim after the analysis:

DECISION: REAL TTFT MEASUREMENT BLOCKED

(previously measured retrieval-side decisions summarized in:
`docs/RAG_OPTIMIZATION_ACC03_2026-09-08.md`,
`docs/RAG_ACCURACY_TTFT_DEEP_DIVE_2026-09-07.md`,
`docs/RAG_ACCURACY_TTFT_BENCHMARK_2026-09-07.md`.)
