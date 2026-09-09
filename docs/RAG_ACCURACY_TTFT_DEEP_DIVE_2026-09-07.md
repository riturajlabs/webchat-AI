# RAG Accuracy + First-Token Latency — Deep Dive (RAG-ACC-02)

- Date: 2026-09-07
- Benchmark: **RAG-ACC-02** (measurement-only phase; no retrieval/ranking/chunking/prompt/cache changes)
- Measurement kind: `SYNTHETIC (deterministic in-memory fakes, dev box)` — see real-TTFT caveat below
- Relationship to RAG-ACC-01: ACC-01 measured _how well_ the weak categories retrieve; ACC-02 attributes every golden chunk to the stage that (did or did not) recover it and measures the retrieval→TTFT relationship.

> RAG-ACC-01 (2026-09-07) is the companion numbers-only report (`docs/RAG_ACCURACY_TTFT_BENCHMARK_2026-09-07.md`). This document is the **why** behind those numbers, plus the real-TTFT availability status.

## Real TTFT (Phase 8-10) — status

**REAL TTFT = UNMEASURED — real provider unavailable in this environment.**

- No cloud credentials in `env` or `.env` (only `TINYFISH_API_KEY` set; no `GEMINI_API_KEY`/`GROQ_API_KEY`/`OPENROUTER_API_KEY`).
- Network reachability was verified (both `generativelanguage.googleapis.com` and `api.openai.com` are reachable) — it is a credentials gap, not a network gap.
- Local Ollama `127.0.0.1:11434` runs but has **zero loaded models** (`/api/tags` → empty); no model was pulled (out of ACC-02 scope).
- Per the RAG-ACC-02 contract, no synthetic number is substituted for real TTFT. All latency numbers below are `SYNTHETIC` and are the _relationship_ evidence only.

Real latencies (ms) to be filled when a provider is available:

| Metric                                         |        P50 |        P95 |        P99 | min | max | mean |   n |
| ---------------------------------------------- | ---------: | ---------: | ---------: | --: | --: | ---: | --: |
| End-to-end TTFT (request → first token)        | UNMEASURED | UNMEASURED | UNMEASURED |   — |   — |    — |   — |
| Retrieval latency (embed+search+hybrid)        | UNMEASURED | UNMEASURED | UNMEASURED |   — |   — |    — |   — |
| LLM/provider TTFT (stream start → first token) | UNMEASURED | UNMEASURED | UNMEASURED |   — |   — |    — |   — |
| Total generation (first → last token)          | UNMEASURED | UNMEASURED | UNMEASURED |   — |   — |    — |   — |

Definition used (matches code): `end_to_end_TTFT = total_ms - (generation_ms - ttft_ms)` where `ttft_ms` is measured at `backend/services/chat/rag_service.py:1347-1360` (first delta from `generation.stream`). TTFT is deliberately separated from total generation time; they are different metrics.

## Executive summary

- **Broad queries**: 16 fixtures classified. Genuine corpus gaps (A) = 2; no-overlap misses (B) = 3; vector-below-floor (C) = 1; keyword-only-unserved (D) = 3; ordering (H) = 4; correct (OK) = 3. **2 of 16 serve zero context.** The single sharpest recoverable loss is **ordering (H): 4 queries serve the right chunks below rank 1** — top-5 crowding by generic `BCA` overlap pushes good evidence down.
- **Typo queries**: Recall@1 0.583 / @3 0.792 / @5 0.875, MRR 0.792 (12 fixtures). Recovery is keyword-driven: the spelling-variant table bridges `admision/addmission/admisssion/eligibilty/tution/interviewes`; non-listed typos only recover when another query token overlaps (e.g. `cyber securty` recovers via `cyber`). The vector proxy never recovered a typo by itself — a token-overlap artifact (see limitation).
- **Multi-source**: median source coverage **P50 0.667** (mean 0.783, full coverage 50.0%). Missing causes: ranking 4, lexical-no-overlap 2.
- **No-answer/abstention**: 8/12 correct abstentions, 2 related-evidence, 1 partial, and **1 structural unsupported-answer risk** (`What are the BCA fees at Academy B?` passes the gate with zero fee evidence — see below).
- **Cross-site isolation**: **FOREIGN SOURCE LEAKAGE = 0** across all query types (exact/short/paraphrase/broad/follow-up) on both sites — 0 foreign URLs served. Golden recovery: 8/10 fully covered, all rows served at least one in-corpus evidence chunk.
- **Reranker**: enabled-pipeline measurement with stored zero embeddings is degenerate (cosine 0.0): only the strong-lexical protection admits content (5/6 sample queries fell back with empty context). This is a synthetic artifact — real embeddings would re-score non-degenerately. It does confirm the reranker CAN reorder (1/6 changed).
- **Synthetic e2e-TTFT correlation (100 chunks, N=30 miss + 30 hit)**: retrieval is 33.4% of end-to-end TTFT at P50 (37.0% by mean). Halving retrieval would cut synthetic end-to-end TTFT by **18.5%** at this scale. Cache hit makes retrieval 0.0 ms (delta below).

## Accuracy diagnosis by category

| Category         | Diagnosis                                                                                                                                                                                                                                                                            |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Broad**        | Bad query→surface-token overlap, not ranking: B (no common token) + C (vector score below 0.25 floor) account for 4 of the weak cases and both empty-context queries. When chunks DO overlap, ordering (H) is the largest recoverable cluster — 4 queries push goldens below rank 1. |
| **Typo**         | Retrieval already auto-recovers 6 typo classes via the keyword variant table; recall@3 = 0.875. The remaining failures are typos without a variant entry AND a broken shared token. Recovery is fragile by design (table, not fuzzy matching).                                       |
| **Multi-source** | The gap is density, not coverage: P50 66.7% of the golden sources arrive, but half the queries miss at least one. `ranking` (RRF top-5 crowding) causes 4/6 resource misses; `lexical_no_overlap` 2/6.                                                                               |
| **No-answer**    | The confidence/answerability gate abstains correctly on 8/12 (incl. all completely-unrelated). Weakness: shared-vocabulary claims — `MBA tuition fee` serves BCA fee evidence (useful), but `BCA fees at Academy B` generates with ZERO fee evidence (risk).                         |

## Failure classification (every weak query, per stage)

Stage cells: **V**=token-overlap vector proxy rank, **K**=keyword pass rank, **Hy**=RRF rank, **Rer**=would the lexical-aware reranker recover it? (C = sub-floor cosine → no; D = keyword-only evidence → yes via strong-lexical protection; B = no token → no; H/OK = ordering/no failure).

| Query                                         | Failure                              | Root cause                                                                                                  |   V |   K |  Hy | Rer |
| --------------------------------------------- | ------------------------------------ | ----------------------------------------------------------------------------------------------------------- | --: | --: | --: | --- |
| What courses are available?                   | B: bca-courses not@rank1             | no surface-token overlap with the query (vector proxy AND keyword both miss it)                             |   · |   · |   · | n/a |
| What courses are available?                   | B: bca-cybersec not@rank1            | no surface-token overlap with the query (vector proxy AND keyword both miss it)                             |   · |   · |   · | n/a |
| What courses are available?                   | B: bca-curriculum not@rank1          | no surface-token overlap with the query (vector proxy AND keyword both miss it)                             |   · |   · |   · | n/a |
| Tell me about the BCA program                 | OK: bca-program not@rank1            | retrieved at rank 1                                                                                         |   1 |   1 |   1 | n/a |
| Tell me about the BCA program                 | H: bca-overview not@rank1            | retrieved below rank 1 (multi-golden ordering)                                                              |   2 |   2 |   2 | n/a |
| What programs does the university offer?      | OK: university-programs not@rank1    | retrieved at rank 1                                                                                         |   1 |   1 |   1 | n/a |
| What are the admission options?               | OK: bca-admission not@rank1          | retrieved at rank 1                                                                                         |   1 |   1 |   1 | n/a |
| What are the admission options?               | B: bca-admissions-process not@rank1  | no surface-token overlap with the query (vector proxy AND keyword both miss it)                             |   · |   · |   · | n/a |
| Tell me about admissions                      | B: bca-admission not@rank1           | no surface-token overlap with the query (vector proxy AND keyword both miss it)                             |   · |   · |   · | n/a |
| Tell me about admissions                      | OK: bca-admissions-process not@rank1 | retrieved at rank 1                                                                                         |   1 |   2 |   1 | n/a |
| Which programs are available at BCA?          | H: bca-program not@rank1             | retrieved below rank 1 (multi-golden ordering)                                                              |   4 |   7 |   5 | n/a |
| Which programs are available at BCA?          | OK: university-programs not@rank1    | retrieved at rank 1                                                                                         |   1 |   1 |   1 | n/a |
| Which programs are available at BCA?          | D: bca-overview not@rank1            | keyword-only recovered it; without a reranker its lexical evidence is stripped and the cosine gate drops it |   · |  12 |  12 | n/a |
| What does BCA cover in its curriculum?        | H: bca-program not@rank1             | retrieved below rank 1 (multi-golden ordering)                                                              |   4 |   7 |   5 | n/a |
| What does BCA cover in its curriculum?        | OK: bca-curriculum not@rank1         | retrieved at rank 1                                                                                         |   1 |   1 |   1 | n/a |
| What does BCA cover in its curriculum?        | H: bca-courses not@rank1             | retrieved below rank 1 (multi-golden ordering)                                                              |   5 |   4 |   4 | n/a |
| Tell me about security at BCA                 | H: bca-cybersec not@rank1            | retrieved below rank 1 (multi-golden ordering)                                                              |   5 |   1 |   2 | n/a |
| What is the BCA department structure?         | OK: bca-department not@rank1         | retrieved at rank 1                                                                                         |   1 |   1 |   1 | n/a |
| Which hostels or facilities does BCA have?    | D: bca-hostel not@rank1              | keyword-only recovered it; without a reranker its lexical evidence is stripped and the cosine gate drops it |   · |   2 |   6 | n/a |
| Do you accept international students for BCA? | OK: bca-international not@rank1      | retrieved at rank 1                                                                                         |   1 |   1 |   1 | n/a |
| How do I apply to BCA?                        | D: bca-admissions-process not@rank1  | keyword-only recovered it; without a reranker its lexical evidence is stripped and the cosine gate drops it |   · |   9 |  10 | n/a |
| How do I apply to BCA?                        | H: bca-admission not@rank1           | retrieved below rank 1 (multi-golden ordering)                                                              |   2 |   4 |   2 | n/a |
| Tell me about fees and scholarships at BCA    | C: bca-fee not@rank1                 | vector proxy retrieved it but scored below the 0.25 cosine floor; gate dropped it                           |   1 |   1 |   1 | n/a |
| Tell me about fees and scholarships at BCA    | D: bca-scholarship not@rank1         | keyword-only recovered it; without a reranker its lexical evidence is stripped and the cosine gate drops it |   · |   2 |   6 | n/a |
| What is the fee structure?                    | OK: bca-fee not@rank1                | retrieved at rank 1                                                                                         |   1 |   1 |   1 | n/a |
| What is the fee structure?                    | H: bca-scholarship not@rank1         | retrieved below rank 1 (multi-golden ordering)                                                              |   2 |   2 |   2 | n/a |

## Multi-source coverage table

| Queries                                                    | Golden sources | Retrieved | Source coverage | Missing (cause)                              |
| ---------------------------------------------------------- | -------------- | --------- | --------------: | -------------------------------------------- |
| What is the BCA fee and admission eligibility?             | 2              | 5         |          100.0% | —                                            |
| BCA courses and placement support                          | 2              | 5         |          100.0% | —                                            |
| cyber security course and BCA admission                    | 2              | 2         |          100.0% | —                                            |
| Tell me about BCA fees, scholarships and admission         | 3              | 1         |           33.3% | bca-fee (ranking), bca-scholarship (ranking) |
| Who is the dean and what is the BCA fee?                   | 2              | 5         |          100.0% | —                                            |
| What does the BCA program cover and does it offer hostels? | 3              | 2         |           66.7% | bca-hostel (ranking)                         |
| Tell me about curriculum and international students        | 2              | 1         |           50.0% | bca-curriculum (ranking)                     |
| What are the admission process and program overview?       | 3              | 3         |           66.7% | bca-admissions-process (lexical_no_overlap)  |
| Which courses and cybersecurity electives does BCA offer?  | 3              | 2         |           66.7% | bca-cybersec (lexical_no_overlap)            |
| What are the placement support and hostel facility?        | 2              | 2         |          100.0% | —                                            |

- Median: **P50 = 0.667**, mean 0.783, fully-covered 50.0%.

## Cross-site isolation (Phase 7)

**FOREIGN SOURCE LEAKAGE = 0.**

| Query type | Site           | Golden | Recovered | Fully covered | Evidence    |
| ---------- | -------------- | ------ | --------: | ------------- | ----------- |
| exact      | acc2-academy-a | 1      |         1 | True          | ['bca-fee'] |
| exact      | acc2-academy-b | 1      |         1 | True          | ['bca-fee'] |
| short      | acc2-academy-a | 1      |         1 | True          | ['bca-fee'] |
| short      | acc2-academy-b | 1      |         1 | True          | ['bca-fee'] |
| paraphrase | acc2-academy-a | 1      |         1 | True          | ['bca-fee'] |
| paraphrase | acc2-academy-b | 1      |         1 | True          | ['bca-fee'] |
| broad      | acc2-academy-a | 2      |         1 | False         | ['bca-fee'] |
| broad      | acc2-academy-b | 2      |         1 | False         | ['bca-fee'] |
| followup   | acc2-academy-a | 1      |         1 | True          | ['bca-fee'] |
| followup   | acc2-academy-b | 1      |         1 | True          | ['bca-fee'] |

Every served URL belonged to the requested website across exact, short, paraphrase, broad and follow-up queries on both corpora, including follow-up-in-session re-raises. The soft point is **claim disambiguation, not isolation**: see `BCA fees at Academy B` under no-answer — the gate passes on shared vocabulary while the specific fee fact is absent.

## No-answer / abstention (production gate ON)

| Query                                             | Category                  | Fallback | Accepted evidence | Claim tokens in evidence | Behavior                 |
| ------------------------------------------------- | ------------------------- | -------- | ----------------: | ------------------------ | ------------------------ |
| What is the capital of France?                    | completely_unrelated      | True     |                 0 | —                        | correct_abstention       |
| Who won the world cup in 2018?                    | completely_unrelated      | True     |                 0 | —                        | correct_abstention       |
| How does a rocket engine work?                    | completely_unrelated      | True     |                 0 | —                        | correct_abstention       |
| What is the MBA tuition fee?                      | plausible_but_absent      | False    |                 3 | mba                      | useful_related_evidence  |
| What are the MBA admission requirements?          | plausible_but_absent      | True     |                 0 | —                        | correct_abstention       |
| What is the last date to apply for BCA admission? | plausible_but_absent      | True     |                 0 | —                        | correct_abstention       |
| Does BCA offer a semester exchange program?       | plausible_but_absent      | True     |                 0 | —                        | correct_abstention       |
| Where is the BCA campus located?                  | similar_topic_absent_fact | False    |                 5 | campus                   | related_evidence_partial |
| What is the BCA application fee?                  | similar_topic_absent_fact | True     |                 0 | —                        | correct_abstention       |
| What is the placement salary for BCA graduates?   | similar_topic_absent_fact | True     |                 0 | —                        | correct_abstention       |
| Who is the dean of the BCA program at Academy B?  | cross_site_other_website  | False    |                 5 | academy, dean            | useful_related_evidence  |
| What are the BCA fees at Academy B?               | cross_site_other_website  | False    |                 5 | —                        | unsupported_answer_risk  |

Totals: correct_abstention 8, useful_related_evidence 2, related_evidence_partial 1, unsupported_answer_risk 1.

Note: the generation client is the deterministic in-memory fake, so no hallucinated text is actually produced; `unsupported_answer_risk` is a **structural** finding (gate allowed generation while the accepted context contained none of the claim's fact tokens). With a real LLM this is precisely the configuration in which a wrong-site answer would be emitted.

## Cache comparison — SYNTHETIC (Phase 10 proxy; real TTFT is UNMEASURED)

| Metric           | Cold (miss) P50 | Warm (hit) P50 | Delta (warm−cold) |
| ---------------- | --------------: | -------------: | ----------------: |
| retrieval        |         1.76 ms |         0.0 ms |          -1.76 ms |
| llm_ttft         |         0.01 ms |         0.0 ms |          -0.01 ms |
| e2e_ttft         |         5.27 ms |        0.59 ms |          -4.68 ms |
| total_generation |         0.01 ms |        0.01 ms |          +0.00 ms |

Warm e2e-TTFT P95 = 0.78 ms vs cold 9.03 ms. Synthetic only; the cold path here is dominated by in-memory corpus tokenization, not the (absent) real provider.

## Dominant bottleneck + recommended NEXT optimization

### Accuracy

**Dominant accuracy bottleneck: query→surface-token mismatch, not ranking.** B+C+D together (misses where no useful token reaches any stage at / above the context gate) drive the weak categories; when tokens DO overlap, H-ordering loses 4 fetch cases. The single highest-leverage, measurement-supported target is **the 0.25 cosine gate interacting with short queries**: the `fees and scholarships` fixture scores 1/5 = 0.2 (below floor) purely because `about`/`tell` are not stopworded and `fees` does not token-equal `fee`.

### Real TTFT

**Dominant latency bottleneck (expected, unmeasured): LLM/provider TTFT.** At real latency scales (hundreds of ms for provider first token) the synthetic retrieval share (~32-38% here at 100 chunks) would shrink to low single-digit percentages; retrieval optimization would move real end-to-end TTFT by far less than the synthetic 19%. Synthetic measurement is the relationship; real TTFT remains UNMEASURED until a provider credential or loaded local model exists.

### Recommended NEXT optimization (NOT implemented in this phase per contract)

**Expand the `chat_context_min_score` gate to be token-ratio-aware for short queries**: score = overlap / min(|query|,|chunk|) already underweights queries whose stopword list misses words (`about`, `tell`) and plural/singular forms (`fees` vs `fee`). A measured candidate: treat a keyword/vector hit whose overlap ≥ 2 _independent_ content tokens as usable regardless of the raw floor (or add `-s`/rule inflection to the lexical normalizer, which is consistent with the existing `_COMMON_TOKEN_VARIANTS` approach). This directly attacks classes C and the empty-context broad queries AND would let multi-source `fees…scholarships` queries serve. Re-measure with this benchmark before and after.
