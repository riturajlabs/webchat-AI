# RAG Manual Regression — Crawl Coverage Diagnosis

**Date:** 2026-09-09
**Commit under test:** `e5048799bb72461e928707cd1a26443da4afa50a`
**Mode:** Read-only diagnosis (no production code/crawler/chunker/retrieval/reranker/confidence/config/DB changes; no commits/pushes/deletes)

---

## 1. Objective

Diagnose why the Indira University RAG corpus dropped from **1000+ chunks** to **141 chunks**, and why manual RAG queries (course listing, admission process, dean/SOIT) fail. Produce a single verifiable verdict.

## 2. Scope & Constraints

- **Read-only.** No production code, crawler, chunker, retrieval, reranker, confidence, provider routing, cache, embedding, prompts, or DB schema was modified. No commits, pushes, or deletes.
- Production DB: MongoDB Atlas `webchat_ai`. Indira website `03fdcef6-97ec-497f-b0e1-89a31b6ec71c` (tenant `2a80b6c3-5a67-48e9-a3e3-32b2b54909b8`, `https://indirauniversity.edu.in/`).
- Local `webchat-mongo` holds only test/benchmark data — not relevant.

## 3. The 1000+ → 141 Chunk Reduction: Not a Coverage Loss

The headline "drop from 1000+ to 141" is **intentional chunking/deduplication**, NOT lost crawl coverage. Verified:

- Old corpus: **2162 chunks from the SAME 43 source URLs** currently in the corpus (confirmed by `.audit-tmp/P1_DRY_RUN_RESULTS.json` → `simulated_new_chunks: 141`). The P1 gate produced exactly the 141-chunk corpus currently live.
- Same 43 sources both before and after → reduction is entirely due to the improved chunker + dedup, not to fewer pages crawled.
- Old problems removed: 744 tiny chunks (<40 tokens, 34%), 1015 exact-duplicate extra chunks (312 groups), 1425 chunks (66%) with "Learning Experiences" heading pollution. Avg token/chunk rose from **86.67 → 546.1**.
- New corpus state (verified live): **43 docs, 141 chunks, 141/141 embedded**, 0 checksum mismatches, no chunk-index gaps, all docs `ready`.

**Conclusion:** The chunk-count reduction is healthy and intentional. It does NOT explain the manual query regressions.

## 4. Crawl Coverage: The Real Gap

The crawler is **capped at `crawl_max_pages = 50`**. The crawl job `86589a5e-2dbf-4501-b84e-e9d74dae7750`:

- status = `completed`, `pages_total = 50`, `pages_completed = 50`, `errors = 0`
- but only **43 docs persisted** (`pages_indexed = 43`) → 7 pages collapsed via URL-dedup upsert.

The 50-page budget was consumed by the high-fan-out content cluster. The live 43-doc corpus is dominated by:

- **22 × `/course/*`** pages (B.Sc/B.Tech AI-DS, B.Sc CS, Cyber Security, 6× BBA, 4× B.Com, B.Pharm, Psychology, ...)
- **13 × `/event/*`** pages (club/student events)
- **7 × `/school/schoollisting*`** school pages + homepage

### MISSING dedicated authoritative pages (verified live, content-rich, reachable over HTTP):

| URL                  | Status | Live content                                                                               | In corpus? |
| -------------------- | ------ | ------------------------------------------------------------------------------------------ | ---------- |
| `/admissions`        | 200    | Full admission process; "online for all programmes"; Rs. 600 (UG) / Rs. 1000 (PG) form fee | **NO**     |
| `/admission-process` | 200    | 5-step portal admission via `admissions.indirauniversity.edu.in`                           | **NO**     |
| `/courses`           | 200    | Course/school overview                                                                     | **NO**     |
| `/about`             | 200    | About page                                                                                 | **NO**     |
| `/faculty`           | 200    | Faculty page (dean info normally lives here)                                               | **NO**     |
| `/apply`             | 200    | Apply page                                                                                 | **NO**     |
| `/undergraduate`     | 200    | UG programs page                                                                           | **NO**     |

These are precisely the pages that answer "which courses", "admission process", and "dean". **None were captured** because the 50-page budget ran out on 38 course/event pages before the BFS reached these top-level navigation pages (they are linked in the persistent site nav "Admissions / Apply Now / Pay Fees / Merit List").

**This is a genuine crawl coverage regression** for a site that exposes hundreds/thousands of course URLs.

## 5. Retrieval Behavior on the Failing Queries (measured end-to-end)

I exercised the full production retrieval path (vector→keyword→RRF→rerank→confidence→answerability) with the **exact production config** (`CHAT_TOP_K=5`, `ENABLE_HYBRID_SEARCH=true`, `HYBRID_SEARCH_CANDIDATE_LIMIT=50`, `ENABLE_RERANKING=true`, `RERANK_MAX_CHUNKS_PER_SOURCE=2`, `CHAT_CONTEXT_MIN_SCORE=0.56`, `RAG_CONFIDENCE_THRESHOLD=0.65`) and the live Gemini embeddings.

### Query: "what is the admission process"

- Reranked top-5 (cosine): `0.5752 B.Tech AI-DS`, `0.5733 B.Sc Psych`, `0.5483 B.Pharm`, `0.5478 B.Com Bus-Admin`, `0.5453 BBA Innovation`.
- `CHAT_CONTEXT_MIN_SCORE = 0.56` **drops the 3 lowest** → context = only **2 unrelated course pages** (AI-DS + Psychology).
- The homepage FAQ that explicitly states "The admission process includes online application, eligibility verification, and selection through Indira CET..." does **not** make the reranked top-5 (fused ~10th).
- Confidence `0.514 < 0.65` — but answerability `allowed=True / strong_entity_evidence` rescues generation. Net result: the LLM is handed two generic per-course pages and cannot describe the general admission process accurately.
- `/admissions` and `/admission-process` — the pages that **would** answer this — are not in the corpus at all.

### Query: "who is the dean of SOIT"

- Reranked top-5: `0.6457 SOIT`, `0.5633 Eng`, `0.5536 student-conference event`, `0.5514 Business`, `0.5506 Commerce`.
- The **only chunk containing the dean ("Dr. Janardan Pawar, Dean, School of Information Technology")** is the `0.5536` student-conference event chunk — which falls **below the 0.56 floor and is dropped from context**.
- Remaining context (SOIT school page + Engineering page) does **not** name the dean → the bot cannot answer and falls to the safe fallback / partial answer.
- A dedicated `/faculty` page (never crawled) is the correct source.

## 6. Root-Cause Synthesis

The manual regression is **not** the chunk-count reduction. It is a combination of:

1. **Crawl coverage regression (primary).** The `crawl_max_pages=50` cap under-crawls a large site; dedicated `/admissions`, `/admission-process`, `/courses`, `/about`, `/faculty`, `/apply` pages were never captured.
2. **Retrieval threshold regression (secondary, within the crawled corpus).** `CHAT_CONTEXT_MIN_SCORE = 0.56` plus `CHAT_TOP_K = 5` plus `RERANK_MAX_CHUNKS_PER_SOURCE = 2` causes the exact chunks that carry general answers (homepage admission FAQ; dean event chunk at 0.5536) to fall below the floor and be excluded, while semantically-generic course pages fill the small context window.
3. **"Only 5 courses" symptom** is directly explained by `CHAT_TOP_K = 5` + rerank 2-per-source: the model is only ever shown ≤5 course pages, so an exhaustive course listing is impossible even though 38 course pages exist in corpus.

## 7. Evidence Artifacts

- `scripts/.tmp_retrieval_test.py` — end-to-end retrieval scores for all 10 queries (vector/keyword/RRF/rerank/confidence/answerability).
- `scripts/.tmp_diag_indira.py`, `scripts/.tmp_diag_admission.py`, `scripts/.tmp_diag_jobs.py` — corpus/job/checksum diagnostics (dead-tmp scripts, not production code).
- Live HTTP probes show `/admissions`, `/admission-process`, `/courses`, `/about`, `/faculty`, `/apply`, `/undergraduate` all return 200 with real content.
- 43-doc URL inventory confirms none of those paths is in the corpus.

## 8. Not Changed (Constraint Compliance)

Diagnosis only. No crawler/chunker/retrieval/reranker/confidence/config/schema changes were made. No production DB writes. No commits or pushes.

## 9. DECISION

**DECISION: MIXED CRAWL AND RETRIEVAL REGRESSION**

- **Crawl:** `crawl_max_pages=50` under-crawls a large site and misses dedicated `/admissions`, `/admission-process`, `/courses`, `/about`, `/faculty`, `/apply` pages — the primary reason general admission / course-overview / dean queries fail.
- **Retrieval:** high `CHAT_CONTEXT_MIN_SCORE=0.56` floor + `CHAT_TOP_K=5` + rerank 2/source drops the answer-bearing chunks (homepage admission FAQ, dean event chunk at 0.5536) and limits the visible course set to ~5, producing the "only 5 courses" and degraded admission/dean answers.
- The 1000+→141 chunk reduction is **healthy** (intentional chunking/dedup of the same 43 sources) and is **not** the cause.

## DECISION DOCUMENTATION TRAIL

_Decision string: **DECISION: MIXED CRAWL AND RETRIEVAL REGRESSION**._
