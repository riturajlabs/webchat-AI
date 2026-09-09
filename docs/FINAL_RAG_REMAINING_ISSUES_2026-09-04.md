# FINAL RAG Remaining Issues Audit — 2026-09-04

**Scope:** Read-only audit reconciling prior P0/P1/P1.1 reports against the CURRENT working tree (HEAD `d7f56a9a`). No Atlas/Redis writes, no crawl, no embedding/LLM calls, no re-ingestion, no commit/push, no architectural change. All six P1.1 corpus-quality gates now PASS on the simulated-new corpus.

**Reconciliation headline:**

- **P0_LATENCY claim** (`_load_all_chunks` returns the full corpus via `list_chunks_light`) — **CONFIRMED in current tree**: `rag_service.py:1554` `list_chunks_light(tenant_id, website_id, limit=0)` loads the whole corpus. The `limit=50` first-50 slice that `COMPLETE_RAG_PIPELINE_AUDIT` measured **is no longer present** — reconciled as fixed.
- **P0_HYBRID claim** (full-corpus keyword fix present) — **CONFIRMED**: keyword scoring runs over the full loaded corpus (`hybrid.py:328`, `rag_service.py:580`/`1554`); `hybrid_search_candidate_limit=50` caps keyword _output_ and RRF pool, NOT corpus loading.
- **P1.1 G1** (the one blocker) — **RESOLVED** by re-scoping G1 to within-document exact-duplicate extras (see §A). Six-gate dry-run now **PASS**.

---

## A. G1 re-scope (this-task change, primary deliverable)

**Change made:** `backend/services/knowledge/corpus_quality.py` `compute_metrics` now computes exact-duplicate groups/extras **within a single source document** (keyed `(source, normalized_text)`) instead of globally across all documents. Rationale (explicit user directive): per-document ingestion keeps one copy per document for correct source attribution, so identical text repeated ACROSS documents is legitimate content, not stored noise. Per-document dedup in `processor.py` (`_dedupe_text_chunks`) is unchanged; no global cross-document dedup was added.

**Effect on the production dry-run** (read-only, `--structural-heading Curriculum`, 9 probes incl. "School of Information Technology"):

| Gate                      | old                            | simulated-new                                | outcome  |
| ------------------------- | ------------------------------ | -------------------------------------------- | -------- |
| G1 duplication_reduction  | exact-dup extra=1 (within-doc) | extra=**0**, adj >0.80 frac 0.0000           | **PASS** |
| G2 tiny_chunk_reduction   | 744 below 40 tokens            | 0                                            | PASS     |
| G3 heading_pollution      | 1425                           | 38 (0.0638 ≤ 0.10)                           | PASS     |
| G4 factual_preservation   | 9/9                            | 9/9 (incl. School of Information Technology) | PASS     |
| G5 deterministic_chunking | —                              | identical re-chunk                           | PASS     |
| G6 source_coverage        | 2162 / 43 src                  | 141 / 43 src                                 | PASS     |

**All six gates PASS. Production re-ingestion is now unblocked by G1.** Re-ingestion itself is still an operational data change and was NOT performed (per instructions).

**Tests added (all pass):**

- `test_metrics_count_exact_duplicate_groups_within_document` (updates the old global-semantics test to within-document).
- `test_metrics_cross_document_identical_not_counted_as_duplicate` (the exact G1 fix: identical "Learning Experiences" text on 3 different docs → NOT a duplicate).
- `test_metrics_within_document_duplicate_still_counted` (a dup within one doc → still counted, still fails G1).
- Existing G1 gate tests (`test_gates_duplication_fails_when_simulation_keeps_duplicates`, `test_dry_run_report_compares_old_vs_simulated_new`) remain valid (their fixtures collide within a single source). Ruff + mypy clean on `corpus_quality.py`, the dry-run script, and tests.

---

## 1. Confirmed defects (verified in the current working tree)

| ID  | Severity | Defect                                                                                                                                                                                                                                                                                   | Evidence                                           |
| --- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| D1  | P0       | `get_chunks_by_ids` filters by document `_id` **only**; the Mongo query itself has no tenant/website predicate, so hydration is scoped only by the (correctly tenant-scoped) candidate pool preceding it. Not exploitable given current call path, but a missing defense-in-depth guard. | `mongodb.py:148`; called from `rag_service.py:723` |
| D2  | P1       | Config flag misnomer: `hybrid_search_candidate_limit=50` is documented as capping loaded corpus, but the load always fetches the full corpus (`limit=0`). The limit only caps keyword output + RRF pool. Harmless functionally but misleading to operators tuning memory/latency.        | `config.py:414` vs `rag_service.py:1554`           |
| D3  | P2       | `insert_chunks` upsert (`mongodb.py:47-70`) does not itself re-assert embedding identity on the composite key; it relies on the earlier processor identity guard. Acceptable given guard ordering; noted to prevent future reorders from silently mixing identities.                     | `mongodb.py:47-70`, `processor.py:379-406`         |
| D4  | P2       | Chunker `_iter_boundaries` (`chunker.py:151-167`) reconstructs token spans from whitespace-split substring math; minor position imprecision on glued-punctuation tokens. Not correctness-breaking.                                                                                       | `chunker.py:151-167`                               |
| D5  | docs     | Multiple stale comments say hybrid is "vector-only default / disabled": `retrieval_strategy.py:7`, `hybrid.py:5`, `.env.production:319-320`. Config default `enable_hybrid_search=True` and prod `.env:321` are `true`; hybrid is ON in dev and prod.                                    | `config.py:408`, `.env.production:321`             |
| D6  | docs     | `.env.production.example:178` keeps `EMBEDDING_PROVIDER_ORDER=["gemini","jina","cohere"]` while live `.env.production:193` is `["jina","gemini","cohere"]` — example is inconsistent with deployment.                                                                                    | `.env.production` vs example                       |

---

## 2. Already-fixed defects (reconciled against the current tree; no action needed)

| Finding from prior reports                                      | Status                                                    | Evidence in current tree                                                                   |
| --------------------------------------------------------------- | --------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Full-corpus keyword recall (first-50 slice)                     | FIXED — full corpus loaded every request                  | `rag_service.py:1554` `list_chunks_light(limit=0)`                                         |
| Ingestion replacement zero/partial-chunk crash window           | FIXED — `replace_by_document` insert-first/delete-stale   | `mongodb.py:72-93`, `vector/base.py:39-52`, used in `processor.py`                         |
| Per-website embedding-identity lock / no silent provider switch | FIXED — single-provider ingestion + locked chat retrieval | `registry.py:190-210,244-299`, `deps.py:296`, `website.py:101-107`, `processor.py:451-505` |
| Within-document duplicate pollution                             | FIXED — `_dedupe_text_chunks` before embedding/replace    | `processor.py:70-87,251`                                                                   |
| Tiny/trailing <40-token chunks                                  | FIXED — chunker min-token merge                           | `chunker.py:196-203,270-283`                                                               |
| Heading near-duplicate sliver chain                             | FIXED — heading-aware boundaries                          | `chunker.py:239,263-264`                                                                   |
| Retrieval/embedding/lexical cache tenant+site isolation         | FIXED — all tenant:website: scoped                        | `rag_service.py:436,289-295,1523`                                                          |
| Cache invalidation on new ingestion                             | FIXED — `_invalidate_retrieval_cache` delete_by_prefix    | `processor.py:507-520`, `cache.py:76-100`                                                  |
| Confidence gate, min-score context gate, context-empty/refusal  | FIXED — multi-gate before any LLM call                    | `rag_service.py:941-998,1623-1628`, `confidence.py:122`                                    |
| Policy/attribution citations in prompt + sources event          | FIXED                                                     | `prompts/rag.py:50,119-148,166-187`, `rag_service.py:1027,1650-1717`                       |
| Chat embedding 429/rate-limit retry + fallback                  | FIXED                                                     | `ai/router.py:299-371`, `embedding.py:410-472`                                             |

---

## 3. Remaining defects, ranked (P0 / P1 / P2)

**P0 (should fix before/with any next deploy):**

- **D1 — `get_chunks_by_ids` lacks tenant/website guard in the query.** Add tenant+website (or at least website) to the `_id` filter's security boundary; the pool is scoped today but the repository method should not silently serve arbitrary `_id`s.

**P1 (important, address in the next phase):**

- **D2 — hybrid corpus loading/metric naming.** Either honor `hybrid_search_candidate_limit` as a documented memory cap or rename the setting/comment and keep full-corpus load. Do NOT change retrieval/RRF/reranker formulas; this is housekeeping that affects operator tuning only.
- (**Operational, not code — decision needed before re-ingesting production:** the embedding provider order differs dev→prod: dev `["gemini",...]` (effectively Gemini), prod `["jina",...]`. Re-ingestion of already-indexed content under a different identity triggers the identity-lock guard. Plan a controlled reindex under the locked (Jina) identity for the target tenant before relying on prod retrieval.)

**P2 (quality-of-life / doc):**

- D3 — address the identity-mix future risk in `insert_chunks` (documented only).
- D4 — chunker boundary token-span precision (cosmetic).
- D5, D6 — stale doc-comments and `.env.production.example` inconsistency.

---

## 4. Smallest safe fix for each remaining defect

| ID  | Smallest safe fix (no architecture change)                                                                                                                                                                                                              |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | In `mongodb.py:get_chunks_by_ids`, add a Mongo filter `{ "_id": {"$in": ids}, "tenant_id": tenant_id, "website_id": website_id }` (or `website_id`) mirroring the caller's scope; update the protocol signature if it must take scope. ~3 lines + test. |
| D2  | Rename `hybrid_search_candidate_limit` → e.g. `hybrid_candidate_top_k` and fix the comment to "keyword output / RRF pool size", OR add an explicit corpus-load cap only if latency/memory demands it. Config-only; no retrieval formula change.         |
| D3  | Add an identity assertion inside `insert_chunks` (reuse `ensure_embedding_compatibility`) or a comment + future-reorder guard in `processor.py`.                                                                                                        |
| D4  | Accept as-is or refine the boundary token-span reconstruction. Optional.                                                                                                                                                                                |
| D5  | Update the three stale comments / `.env.production` comment to reflect `enable_hybrid_search=true`.                                                                                                                                                     |
| D6  | Align `.env.production.example:178` to the live order or add a comment.                                                                                                                                                                                 |

---

## 5. Files likely to change (for the above)

- `backend/repositories/vector/mongodb.py` (D1 guard, D2 if pulling a cap), `backend/repositories/vector/base.py` (D1 protocol), `backend/core/config.py` (D2 rename/comment), `backend/repositories/vector/hybrid.py` (D5 doc), `backend/services/chat/retrieval_strategy.py` (D5 doc), `.env.production.example` (D6).
- No change expected to `processor.py`, `chunker.py`, confidence/reranker/RRF formulas, cache keys, or provider thresholds.

---

## 6. Tests required

- **D1:** `tests/test_vector_mongodb.py` — a `get_chunks_by_ids` call with an `_id` belonging to a different tenant/website returns nothing.
- **D2:** config test asserting the documented semantics of the candidate-top-k flag (or a note that full-corpus load is intentional).
- **G1 regression (already added this task):** within-document dup → FAIL; cross-document identical → PASS; within-document extra counted.
- Re-run: focused `test_corpus_quality`, `test_vector_mongodb`, `test_knowledge_processor`, `test_rag_service`, `test_retrieval_strategy`; Ruff + mypy strict on changed files.

---

## 7. Benchmark / validation plan (for the next phase)

Re-ingestion is UNBLOCKED (all six gates PASS). Recommended sequence, each only after the previous is green and all READ-ONLY:

1. Re-run the read-only dry-run against production exactly as this task did; require 6/6 gates PASS each run.
2. Perform a **controlled re-crawl + re-embed** of the Indira tenant under the locked Jina identity; confirm the website record persists `ingestion_embedding_provider/model/dimensions/version` and the corpus converges to ≈141 chunks (0 tiny, 0 within-doc dup, ≤10% top heading, 43 sources).
3. Re-run the read-only keyword-recall validation (`p0_readonly_validation.py`) against the re-ingested corpus to confirm full-corpus recall holds on the new chunks.
4. Re-run the Phase 3/3.5 latency benches to confirm TTFT/streaming behavior on Atlas `$vectorSearch` (prod) rather than local brute-force cosine, and that the full-corpus load (`load_chunks_ms`) is acceptable at the new corpus size.
5. Apply P0 D1 (tenant-guard), P1 D2 (naming/doc), P2 docs; re-run the relevant tests + lint/typecheck.

---

## Scope compliance (final)

- Production Atlas writes: **0** · Redis writes: **0** · crawl: **0** · re-embedding: **0** · commit/push: **0**.
- HEAD unchanged at `d7f56a9`. Working-tree changes this task = `corpus_quality.py` (G1 within-document metric) + `tests/test_corpus_quality.py` (G1 regression tests) + `.audit-tmp/` artifacts (`P1_1_DRY_RUN_RESULTS_G1_FIX.json`, this report, `_run_dry_run.py` runner). All other modified files are prior-phase working-tree changes, untouched.
- No retrieval/RRF/reranker/provider/config/threshold formula changed. G1 change is confined to the validation tools (`corpus_quality.py` + tests) as directed.
