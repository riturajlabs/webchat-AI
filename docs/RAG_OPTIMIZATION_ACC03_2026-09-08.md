# RAG Accuracy Optimization (RAG-ACC-03) — short-query gate + token normalization

- Date: 2026-09-08
- Benchmark: **RAG-ACC-03** (optimization phase: retrieval-accuracy fixes derived from ACC-02's recommendations)
- Measurement kind: `SYNTHETIC (deterministic in-memory fakes, dev box)` — see real-TTFT caveat below
- Target: RAG-PERF-04 / ACC-03 — close the ACC-02 recovery gaps (broad/typo/multi-source) without weakening isolation, answerability, caching, or latency.

> Relation to ACC-01/ACC-02: ACC-01 (`docs/RAG_ACCURACY_TTFT_BENCHMARK_2026-09-07.md`) measured the weak-category recall, ACC-02 (`docs/RAG_ACCURACY_TTFT_DEEP_DIVE_2026-09-07.md`) attributed every golden chunk to a stage and recommended two fixes: (1) expand the spelling-variant/morphology table, (2) make `chat_context_min_score` token-ratio-aware for short queries (class C / empty-context broad failures). This document measures both fixes and verifies the invariants.

## Real TTFT — status (unchanged)

**REAL TTFT = UNMEASURED — real provider unavailable in this environment.**

- No cloud credentials in `env`/`.env` (only `TINYFISH_API_KEY` set; no `GEMINI_API_KEY`/`GROQ_API_KEY`/`OPENROUTER_API_KEY`).
- Local Ollama `127.0.0.1:11434` runs but has **zero loaded models**; no model was pulled (out of scope).
- No synthetic number is substituted for real TTFT. All latency numbers in ACC-02/03 are the synthetic relationship evidence only.

| Metric                                  |        P50 |        P95 |        P99 | min | max | mean |   n |
| --------------------------------------- | ---------: | ---------: | ---------: | --: | --: | ---: | --: |
| End-to-end TTFT (request → first token) | UNMEASURED | UNMEASURED | UNMEASURED |   — |   — |    — |   — |
| Retrieval latency (embed+search+hybrid) | UNMEASURED | UNMEASURED | UNMEASURED |   — |   — |    — |   — |
| LLM/provider TTFT                       | UNMEASURED | UNMEASURED | UNMEASURED |   — |   — |    — |   — |
| Total generation                        | UNMEASURED | UNMEASURED | UNMEASURED |   — |   — |    — |   — |

## What changed

Two targeted retrieval fixes, both behind existing feature flags / scalars (no new configuration surfaces):

1. **Token normalization (Phase 3 + 7) — `backend/repositories/vector/hybrid.py`**
   Extended `_COMMON_TOKEN_VARIANTS` with the plural/morphology and typo variants that ACC-02 flagged:
   `admissions→admission` (keeps the singular canonical form already pinned by `test_rag_answerability`),
   `course/courses→courses`, `program/programme/programmes/progam/programs→programs`,
   `scholarship/scholarships→scholarships`, `department/departments→departments`,
   `curriculam→syllabus`, `securty→security`, `universty→university`, `hosptel→hostel`.
   The plural group (`admissions`, `course↔courses`, …) closes the _"stopword/plural under-weights `fees` vs `fee`"_ gap named in ACC-02. All targets are self-mapped so `tokenize` is idempotent.
   Verified by the new `test_tokenize_canonicalizes_morphology_and_typos` in `tests/test_hybrid_search.py`.

2. **Short-query context gate (Phase 4) — `backend/services/chat/confidence.py` + `backend/services/chat/rag_service.py`**
   `_build_context` now receives the user query and `usable(result, dense_floor=…, query=…)` applies a narrow leniency **below** the cosine floor:
   a below-floor chunk that the hybrid pass actually surfaced (i.e. it is already in the post-RRF result set) is preserved when the query has **≤ 3 independent content tokens** (`_SHORT_QUERY_MAX_REQUIRED_TOKENS`, excluding `_STRUCTURAL_WORDS`) and the chunk's text covers the required share (`_required_overlap`: 1 token → 1, 2 → 2, 3 → 2 of the content tokens).
   Queries with 4+ content tokens keep the strict dense-only floor untouched.
   The leniency only affects the RAG fast path; `query=None` preserves the exact legacy gate (used by the reranker-path safety tests → `tests/test_lexical_context_gate.py` still green). RRF ordering, `_strip_lexical_scores`, reranker, and the retrieval cache (schema-2) are unchanged.
   `departments` was added to `_FACTUAL_ATTRIBUTE_TERMS` so `department→departments` normalization cannot flip a factual query to OPEN.

## Method note: truly apples-to-apples baseline

The benchmark suites and the baseline code were **not in git** (pre-existing uncommitted working-tree state). To avoid hand-recalling the old aggregates, the baseline was re-measured deterministically: a scratch copy of the tree was made (git/worktree/venv excluded) and **only the ACC-03 edits were reverted** (variant table, `usable`, rag-service threading, deep-dive `_compute_tower` replica, unit tests). The scratch copy passed its assertion-encoded baselines (hybrid, confidence, benchmark, deep dive), proving the reconstruction is faithful, and its JSON artifacts were archived as `BASELINE_bench.json` / `BASELINE_deepdive.json` in `/tmp/opencode/`. The working tree was not touched.

## Measured deltas

### ACC-01 benchmark (suite: `tests/test_rag_accuracy_benchmark.py`)

| Category     | Metric                | BEFORE                    | AFTER                 | Δ          |
| ------------ | --------------------- | ------------------------- | --------------------- | ---------- |
| exact        | R@1 / R@3 / R@5 / MRR | 1.0 / 1.0 / 1.0 / 1.0     | 1.0 / 1.0 / 1.0 / 1.0 | flat       |
| short        | R@1 / R@3 / R@5 / MRR | 1.0 / 1.0 / 1.0 / 1.0     | 1.0 / 1.0 / 1.0 / 1.0 | flat       |
| broad        | R@1                   | 0.167                     | 0.167                 | flat       |
| broad        | R@3                   | 0.278                     | 0.444                 | **+0.167** |
| broad        | R@5                   | 0.389                     | 0.556                 | **+0.167** |
| broad        | MRR                   | 0.444                     | 0.444                 | flat       |
| paraphrase   | R@1 / R@3 / R@5 / MRR | all 1.0                   | all 1.0               | flat       |
| typo         | R@1 / R@3 / R@5 / MRR | 0.625 / 1.0 / 1.0 / 0.875 | unchanged             | flat       |
| multi-source | R@1 / R@3 / R@5 / MRR | 0.5 / 0.833 / 1.0 / 1.0   | unchanged             | flat       |
| no-answer    | R@1 / R@3 / R@5 / MRR | 0 / 0 / 0 / 0             | unchanged             | flat       |
| follow-up    | R@1 / R@3 / R@5 / MRR | all 1.0                   | all 1.0               | flat       |

Broad per-query proof of the gate:

- `Tell me about admissions and fee at BCA` → served `[bca-fee, bca-scholarship, bca-admission]` (bca-admission was keyword-only below the cosine floor; the 3-content-token query leniency admits it on 2/3 overlap). R@3 0.5 → **1.0**.
- `Tell me about BCA` → served 5 → 7 titles (bca-placement, bca-scholarship added beyond rank 5; R@3/R@5 already counted the earlier hits).

### ACC-02 deep dive (suite: `tests/test_rag_accuracy_deep_dive.py`)

| Measure                     | BEFORE                          | AFTER                           | Δ                      |
| --------------------------- | ------------------------------- | ------------------------------- | ---------------------- |
| Typo R@1 (12 q)             | 0.583                           | 0.708                           | **+0.125**             |
| Typo R@3 (12 q)             | 0.792                           | 0.833                           | **+0.042**             |
| Typo R@5 (12 q)             | 0.875                           | 0.875                           | flat                   |
| Typo MRR (12 q)             | 0.792                           | 0.896                           | **+0.104**             |
| Multi-source fully covered  | 50.0%                           | 60.0%                           | **+10 pp**             |
| Multi-source mean coverage  | 0.783                           | 0.817                           | **+0.034**             |
| Multi-source coverage P50   | 0.667                           | 1.0                             | **+0.333**             |
| Multi-source missing causes | lexical_no_overlap 1, ranking 5 | lexical_no_overlap 0, ranking 5 | **lexical gap closed** |

### Invariants (must not move — verified unchanged)

| Invariant                              | BEFORE                         | AFTER     |
| -------------------------------------- | ------------------------------ | --------- |
| No-answer: correct abstentions         | 8/12                           | 8/12      |
| No-answer: related evidence            | 2                              | 2         |
| No-answer: partial                     | 1                              | 1         |
| No-answer: **unsupported-answer risk** | 1                              | 1         |
| Cross-site foreign-source leak         | 0                              | **0**     |
| Exact/short/paraphrase/follow-up       | all 1.0                        | all 1.0   |
| Retrieval cache hit/miss paths         | unchanged (schema-2 untouched) | unchanged |

The unsupported-answer risk stays bounded by design: the leniency is capped at 3 content tokens, and every no-answer fixture (including `What are the BCA fees at Academy B?`) has 4+ content tokens, so the strict floor still applies there.

## Attribution of the gains

- `BCA progam details` (deep-dive, R@1 0 → 0.5): `progam→programs` lifts **keyword rank 6 → 1** and RRF 4 → 1 (no gate involvement; pure normalization).
- `teach me about BCA addmission` (deep-dive, R@1 0 → 1): `addmission→admission` lifts keyword evidence to RRF rank 1.
- `What are the admission process and program overview?` (multi-source, 0.667 → 1.0 coverage): below-floor keyword-recovered `bca-admissions-process` is **admitted by the short-query gate** (its text covers the required content tokens).
- `Tell me about admissions and fee at BCA` (ACC-01 broad): → 1.0 R@3 by **gate admission** of `bca-admission`.
- `hosptel` and `BCA curriculam`: `hosptel→hostel`, `curriculam→syllabus` now recover keyword rank 1, but the chunks land at RRF rank 2 / 6 — served (SOTA unchanged for hosptel) or beyond the rank-5 window; **recall is ordering-bound here, not coverage-bound** (upstream RRF reordering is deliberately out of scope for this phase).

## Files changed (ACC-03)

- `backend/repositories/vector/hybrid.py` — `_COMMON_TOKEN_VARIANTS` extension (Phase 3+7).
- `backend/services/chat/confidence.py` — `usable(dense_floor, query=…)` leniency, `_SHORT_QUERY_MAX_REQUIRED_TOKENS`, `_required_overlap`, `assess_result_confidence(…, query=…)` threading, `_FACTUAL_ATTRIBUTE_TERMS` `departments`.
- `backend/services/chat/rag_service.py` — `_build_context(…, query=…)` + routing `question` into the gate and confidence check.
- `tests/test_hybrid_search.py` — `test_tokenize_canonicalizes_morphology_and_typos`.
- `tests/test_confidence.py` — `TestShortQueryLeniency` (8 boundary tests).
- `tests/test_rag_accuracy_deep_dive.py` — `_compute_tower` gate replica updated to mirror the production rule (kept in lockstep so `served == tower["final"]` stays a real assertion).

Unit + benchmark suites green; full non-e2e test suite exits 0.

## Known limitations / out of scope

- RRF **ordering** is untouched → R@1-only ordering gaps (e.g. ACC-01 `teach me about BCA addmission` r1 still 0, `hosptel` served @2) remain by design. A reranker with real embeddings (currently degenerate in the pure env) is the follow-up.
- The leniency is deliberately conservative (≤ 3 content tokens, share-based overlap) — very long conversational queries and full-sentence no-answer fixtures are unaffected.
- Real TTFT remains UNMEASURED (credential/model gap).
