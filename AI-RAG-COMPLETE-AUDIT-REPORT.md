# AI RAG Complete Audit Report — WebChat AI

**Date:** 2026-08-21 · **Scope:** end-to-end production RAG pipeline · **Mode:** read-only audit (live probes against the production Atlas cluster `cluster0.ghf4ner.mongodb.net / webchat_ai`, container `webchat-api`, logs 96h)

---

# Executive Summary

| Area                     | Verdict                                                                                                                                         |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Pipeline completeness    | All stages present and wired (validate → sanitize → persist → embed → ANN → hybrid → rerank → confidence → context → prompt → stream → persist) |
| Retrieval accuracy       | Functional; correct doc ranked #2 (not #1) for the reported symptom; Recall@K 64.7% on golden set                                               |
| Answer faithfulness      | Guardrails present; model can parrot the fallback phrase (prompt Rule 2), indistinguishable in DB from pipeline fallback except by token counts |
| Wrong "could not find"   | 5/51 golden false-fallbacks (9.8%) + **13 chunks invisible to queries** (mixed embedding space, BUG-1)                                          |
| Latency                  | total p50 ≈ 7.6–7.7 s; TTFT p50 ≈ 1.65 s; Groq generation dominates; persist_ms ≈ 1.4 s is anomalously high                                     |
| Cache correctness        | 3 confirmed defects (monotonic clock in Redis, dead size limits, no invalidation on provider switch)                                            |
| Tenant/website isolation | **Solid** — enforced at ANN filter, brute-force query, session binding, cache keys                                                              |
| Embedding compatibility  | **BROKEN IN PRODUCTION DATA** — 13/67 chunks embedded with `jina-embeddings-v3`, rest with `gemini-embedding-001` (BUG-1)                       |
| Hybrid search quality    | Works as designed but is reorder-only over the ANN top-5 (recall ceiling)                                                                       |
| Reranking quality        | Good: true query↔chunk cosine on stored vectors, ~22 ms, no extra API calls                                                                     |

**Current completion percentage:** ~80% (pipeline complete and serving; correctness/robustness defects open)

**RAG quality score:** 72 / 100
(retrieval 16/20 · faithfulness 14/20 · fallback precision 12/15 · latency 12/15 · isolation 10/10 · cache 4/10 · tests realism 4/10)

**Production readiness:** CONDITIONAL GO — safe to serve (isolation + abstention solid), but fix P0 items before scaling content or trusting coverage.

---

# Phase 1 — Flow Map (verified against code)

```
User Question
 → Normalization            sanitize_question()          prompts/rag.py:85-103
 → Website lookup           RagService.stream_answer     rag_service.py:444-450
 → Session resolve          _ensure_session              rag_service.py:985-1010
 → Persist user turn        messages.create              rag_service.py:478-488
 → Embedding (+cache)       _embed_question              rag_service.py:188-226   [Redis ns "embed", TTL 3600s]
 → Vector search            MongoVectorRepository.similarity_search   repositories/vector/mongodb.py:109-221
                            $vectorSearch limit=top_k(5) numCandidates=max(10·top_k,100)=100
                            filter: tenant_id, website_id, embedding_provider/model/dims/version
 → Hybrid/RRF               HybridRetrievalStrategy      retrieval_strategy.py:106-137
                            keyword_search over vector candidates only  hybrid.py:309
                            reciprocal_rank_fusion k=60  hybrid.py:34-77
 → Reranker                 EmbeddingReranker.rerank     repositories/vector/reranker.py:60-145
                            true cosine(query_vec, stored chunk emb), top 5, no API call
 → Confidence gate          assess_confidence            confidence.py:26-49
                            0.50·mean + 0.30·hit_ratio + 0.20·peak vs threshold 0.65
 → Context build            _build_context               rag_service.py:1045-1161
                            min_score=0.56 filter, dedup, budget 12000 chars, chunk cap 2500 chars
 → Prompt build             get_system_prompt v1 + build_user_prompt   prompts/rag.py:39-56,148-169
 → LLM generation           router → groq (stream)       rag_service.py:701-726
 → SSE streaming            sources → message* → done    api/sse.py buffered 50 ms
 → Persistence              assistant msg + latency + usage   rag_service.py:755-800
```

### Stage table (input / output / failure points / protections / missing)

| Stage         | Input → Output                   | Failure points                        | Existing protections                                                            | Missing protections                                                                                        |
| ------------- | -------------------------------- | ------------------------------------- | ------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Sanitize      | raw q → cleaned q (≤ max chars)  | empty/injection                       | control-char strip, injection _detection+log_, length cap                       | detection warns but never blocks (by design?)                                                              |
| Embedding     | q text → 1024-dim vec + identity | provider outage, quota, dim drift     | retries+backoff+jitter, `ensure_vector_dimensions`, identity stamp              | **no cache invalidation on provider switch** (BUG-5); fallback chain silently changes space (BUG-1 source) |
| Vector search | vec → top-5 chunks+scores        | no index, tier quirks, mixed spaces   | identity filter, tenant/website filter, empty-result probe, brute-force degrade | probe broken (BUG-2); brute force raises on mixed spaces instead of degrading                              |
| Hybrid/RRF    | 5 candidates → reordered 5       | keyword noise                         | restricted to vector candidates; vector score preserved for gating              | recall ceiling = ANN@5; `keyword_count` metric misreports (BUG-8)                                          |
| Rerank        | candidates → top-5 by cosine     | missing chunk embeddings (scored 0.0) | stored-vector fast path, failure → original order                               | none material                                                                                              |
| Confidence    | scores → generate/fallback       | threshold miscalibration              | measured thresholds (0.56/0.65), metrics logged                                 | model-side "fallback phrase" bypasses gate (Risk R1)                                                       |
| Context       | results → items+sources          | oversized/dup text                    | exact dedup, per-chunk 2500 cap, 12000 budget                                   | heading always None (metadata has no section field)                                                        |
| Generation    | prompt → deltas                  | provider failure mid-stream           | try/except → SSE error event; usage captured                                    | none material                                                                                              |
| Streaming     | events → client                  | disconnect mid-generation             | skip persistence on disconnect; 50 ms coalescing                                | httpcore GeneratorExit log noise (cosmetic)                                                                |
| Persistence   | answer → Mongo                   | write latency (~1.4 s observed)       | user turn persisted up-front                                                    | persist before `done` adds tail latency (Risk R6)                                                          |

---

# Confirmed Bugs

### BUG-1

- **ID:** BUG-1
- **Severity:** P0 (retrieval correctness)
- **File:** `backend/services/knowledge/processor.py:194,245,294-297` (stamping) + `backend/core/config.py:520-542` (validation only checks dimension equality across providers) + `backend/services/knowledge/embedding.py` (provider fallback chain)
- **Function:** `KnowledgeProcessor.process_document` / `_build_chunks`
- **Root cause:** when Gemini embedding fails/quota-limits during ingestion, the provider chain falls back to Jina/Cohere. Because all providers are configured to 1024 dims, the dimension gate passes and chunks are stored stamped with the _fallback_ provider identity. One website ends up with multiple embedding spaces.
- **Evidence (live, production cluster):**
  ```
  knowledge_chunks (tenant d98aefd7…, website b57841fb…): 67 chunks
  embedding_provider distinct = ['gemini', 'jina']
  gemini chunks: 54 · jina chunks: 13  (all 13 = "Test card numbers | Stripe Documentation")
  ```
  The `$vectorSearch` identity filter excludes those 13 chunks for every gemini query → that page is **unanswerable** (guaranteed false fallback for card-testing questions). Conversely, if the whole site were jina, a gemini query would hit BUG-2's path and raise `EmbeddingCompatibilityError` at the user.
- **Fix required:** make ingestion fail-and-retry with the _same_ provider instead of falling back to a different embedding space (or quarantine + re-index the website when identity changes). Then re-index the affected website so all chunks share one identity.

### BUG-2

- **ID:** BUG-2
- **Severity:** P0 (availability/correctness of the empty-result path)
- **File:** `backend/repositories/vector/mongodb.py:256-269`
- **Function:** `_probe_search_support` (via `_has_search_index`, called at mongodb.py:192)
- **Root cause:** the probe runs `db.command({"listSearchIndexes": "knowledge_chunks"})`. In this deployment that command fails (host pymongo: `command not found (code 59)`; in-container pymongo: `'list' object has no attribute 'update'`) while the `$listSearchIndexes` **aggregation stage works** and reports the index `READY/queryable`. The probe therefore always returns False.
- **Evidence (live):**
  ```
  db.command({'listSearchIndexes': …}) → ERR 'list' object has no attribute 'update'
  db.knowledge_chunks.aggregate([{$listSearchIndexes: {}}]) → name=default status=READY queryable=True
    definition: embedding numDimensions=1024 similarity=cosine + 6 filter fields ✓
  ```
  Consequence: any legitimately-empty `$vectorSearch` result degrades to the O(N) brute-force scan (`Atlas Search is unavailable… falling back to exact cosine scan` was logged live), which — with BUG-1 present — raises `EmbeddingCompatibilityError` mid-scan and surfaces an error to users instead of a graceful "not found" fallback.
- **Fix required:** use the `$listSearchIndexes` aggregation stage (or try/catch both forms) in `_probe_search_support`.

### BUG-3

- **ID:** BUG-3
- **Severity:** P1 (cache correctness)
- **File:** `backend/services/chat/rag_service.py:270,280,381`
- **Function:** `_retrieve`
- **Root cause:** retrieval-cache entries store `cached_at = time.monotonic()` (a **per-process, per-boot** clock) into Redis, and freshness is checked as `now - entry["cached_at"] < ttl` against _another_ process's monotonic clock after restart or in multi-worker deployments. Differences can be negative (entry treated as forever-fresh) or huge (always miss).
- **Evidence:** code read; Redis entries contain `cached_at` from monotonic base of the writing process. Real staleness is currently bounded only by the Redis `setex` TTL (900 s).
- **Fix required:** store `time.time()` (wall clock) in the entry, keep Redis TTL as the hard bound.

### BUG-4

- **ID:** BUG-4
- **Severity:** P1 (config integrity / memory)
- **File:** `backend/core/cache.py:28-98`; settings consumed at `rag_service.py:143-146`
- **Function:** `RedisCacheStore` (no size bound); `_embed_question` docstring claims "bounded per-process LRU"
- **Root cause:** `embedding_cache_size=256` and `chat_retrieval_cache_size=512` are **dead config** in the Redis path — nothing enforces a size limit; keys accumulate until TTL expiry. Docstrings document eviction semantics that don't exist.
- **Evidence:** code read — `set()` has no cardinality check; no eviction anywhere in `cache.py`.
- **Fix required:** either implement bounded keys (e.g., per-namespace ZSET ring or periodic SCAN-trim) or remove the size settings and fix the docstrings.

### BUG-5

- **ID:** BUG-5
- **Severity:** P1 (operational trap interacting with BUG-1/BUG-2)
- **File:** `backend/workers/jobs/crawl.py:215-223` (only invalidation site), `rag_service.py:199-226` (embed cache)
- **Function:** `_run_crawl_job` / `_embed_question`
- **Root cause:** the `"embed"` namespace is never invalidated anywhere. After an `EMBEDDING_MODEL`/provider change, cached vectors (TTL 3600 s) still carry the old identity; queries use them, the identity-filtered search returns empty, and via BUG-2 the request degrades to brute force and raises `EmbeddingCompatibilityError` at users for up to an hour.
- **Evidence:** grep shows `delete_by_prefix` called only for `"retrieval"`; embed entries embed `embedding_identity` (rag_service.py:205-212).
- **Fix required:** flush `"embed"` (and `"retrieval"`) on embedding-config change (startup guard comparing active identity vs a Redis-stamped "current identity" key).

### BUG-6

- **ID:** BUG-6
- **Severity:** P2 (data lifecycle / privacy retention)
- **File:** `backend/services/website/website_service.py:225-246`
- **Function:** `delete_website`
- **Root cause:** deleting a website removes widgets + website row only. `documents` and `knowledge_chunks` (which include full page text + embeddings) are orphaned forever, and the retrieval cache for that website is not flushed.
- **Evidence:** function body calls only `_widgets.delete_by_website_id` and `_websites.delete`; compare `MongoVectorRepository.delete_by_website` (mongodb.py:77-81) which exists but is unreferenced here.
- **Fix required:** cascade delete documents/chunks (or enqueue cleanup job) + `delete_by_prefix("retrieval", f"{website_id}:")`.

### BUG-7

- **ID:** BUG-7
- **Severity:** P2 (observability)
- **File:** `backend/services/chat/retrieval_strategy.py:130`
- **Function:** `HybridRetrievalStrategy.search`
- **Root cause:** `keyword_count = min(len(vector_results), top_k)` reports the number of candidates _fed_ to the keyword scorer, not the number that scored > 0 — the metric logged as `keyword_result_count` overstates keyword activity.
- **Evidence:** code read vs `keyword_search` which filters `s > 0.0` (hybrid.py:242).
- **Fix required:** return `len(kw_results)` from the searcher (it already computes it) through `HybridSearchResult`/metrics.

### BUG-8

- **ID:** BUG-8
- **Severity:** P2 (telemetry ambiguity feeding wrong analyses)
- **File:** `backend/prompts/rag.py:45-46` (Rule 2) + `rag_service.py:755-765`
- **Function:** system prompt v1 / answer persistence
- **Root cause:** the model is instructed to output the _exact_ fallback string when context lacks the answer. Those turns persist with real tokens/sources/latency and are indistinguishable from generated answers to any dashboard that doesn't parse content — while `_emit_fallback` rows have zero tokens. Coverage metrics built on message contents will miscount.
- **Evidence (live):** Atlas docs `02:54:46.673` and `03:03:01.570`: content == fallback string, `output_tokens`=99/120, sources=5, latency populated.
- **Fix required (minimal, no prompt change needed for audit scope):** flag such turns at persistence time (content equality check with `UNKNOWN_ANSWER_FALLBACK`) into a dedicated field, or accept and document the ambiguity. Prompt rewording is a separate decision.

---

# Possible Risks

| ID  | Severity | Why risky                                                                                                                                                                                                                                                                             | How to verify                                                                                                                           |
| --- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| R1  | High     | **Recall ceiling of hybrid**: keyword stage only re-ranks the ANN top-5 (`hybrid.py:309`, `all_chunks=None` from `rag_service.py:392-398`). If the right page isn't in ANN@5, nothing downstream can recover it. Symptom's historical ordering (correct doc #4) consistent with this. | Re-run golden eval with `CHAT_TOP_K=8→20` shadow mode; measure Recall@K lift.                                                           |
| R2  | Medium   | `numCandidates=max(top_k·20,100)=100` unvalidated against corpus growth; ANN recall may silently drop as chunks grow beyond hundreds.                                                                                                                                                 | Quarterly recall harness: brute-force top-20 vs ANN top-5 overlap on sampled questions.                                                 |
| R3  | Medium   | Chunk metadata carries only `{document_id, language, source_url, title, website_id}`; `ContextItem.heading` hardcoded `None` (`rag_service.py:1092`). Multi-section pages lose section context in citations and prompt.                                                               | Inspect `metadata` keys (done — no heading field); pilot heading-preserving chunking on one site.                                       |
| R4  | Medium   | Model-parroted fallback (BUG-8) plus genuine fallbacks means "could not find" rate can be understated/overstated depending on measurement method.                                                                                                                                     | Count both patterns separately (tokens==0 vs content match).                                                                            |
| R5  | Low      | No stampede protection on retrieval-cache misses (thundering herd on cold popular question). At current scale negligible.                                                                                                                                                             | Load test single hot question with flushed cache.                                                                                       |
| R6  | Low      | `persist_ms` p50 ≈ 1.4 s (sharded cluster, majority write concern) delays the `done` event; users wait on persistence.                                                                                                                                                                | Sample `writeConcern` timings; consider moving usage rollup off the critical path (already gathered) and measuring pure message insert. |
| R7  | Low      | Faithfulness check is word-overlap heuristic, warning-only (`rag_service.py:1252-1284`) — fine as signal, not a guarantee.                                                                                                                                                            | Track `faithfulness_low` warnings vs human review sample.                                                                               |
| R8  | Low      | `list_chunks_light` / `_load_all_chunks` are documented dead code (mongodb.py:92-107, rag_service.py:1016-1034) — deletion candidates that confuse future audits.                                                                                                                     | grep confirms no production callers.                                                                                                    |

---

# Working Correctly (verified)

1. **Atlas vector index** — `$listSearchIndexes` shows `default`, type `vectorSearch`, `embedding` @1024 dims, `cosine`, READY/queryable, with filter fields exactly matching the pipeline's filter (`tenant_id`, `website_id`, `embedding_provider/model/dimensions/version`). Live ANN returns correctly filtered results.
2. **Tenant/website isolation** — enforced in four independent layers: ANN filter (old-tenant query returned 0 hits even though other tenants' data exists on the same cluster), brute-force find filter (mongodb.py:289), session binding (`_ensure_session` rejects cross-website session ids, rag_service.py:1005-1010), and cache key prefix `website_id:` (invalidation scoped per website, verified by test `test_invalidation_removes_only_target_website`).
3. **Embedding identity gating in ANN path** — the 13 jina chunks were excluded from gemini queries (no cross-space scoring occurred in the observed traces).
4. **Confidence gate behavior** — live trace: _"What is my database password?"_ → all 5 reranked cosines 0.46-0.47 < min_score 0.56 → confidence 0.3293 < 0.65 → **FALLBACK** (correct abstention, adversarial-safe). _"What are Stripe payments?"_ → confidence 0.768 → GENERATE with the Payments page at #1. _"How do I create a Stripe account?"_ → confidence 0.7822 → GENERATE.
5. **RRF fusion** — order-only; original vector scores restored post-fusion for filtering/confidence (`_preserve_vector_scores`, retrieval_strategy.py:140-156). Worked example captured (Phase 4 below).
6. **Reranker** — uses precomputed query vector + stored chunk embeddings; zero extra API calls; ~22 ms observed; genuinely re-orders (Get-started promoted by RRF was re-scored honestly by cosine).
7. **Chunker** — token-bounded (p50=582, max=699 ≤ 700 cap), sentence-boundary-preferred cuts, 100-token overlap, zero duplicate prefixes across the 67-chunk KB; no oversized mixed-topic chunks found in production data.
8. **Crawl → cache invalidation** — `crawl.py:215-223` flushes `retrieval:{website_id}:*` on completion (best-effort, fail-open).
9. **Fallback path** — never calls the LLM; persists assistant row; emits exactly `sources(empty) → message(fallback) → done(fallback=true)`; counters rolled up.
10. **Prompt-injection defenses** — question sanitization + injection detection logging, context delimited and labelled untrusted, output validation (log-only), fixed hallucination-guard rule in system prompt.
11. **Golden eval (go-live, real Atlas)** — 46/51 positives answered (90.2%), 40/40 guards abstained, 0 false answers, MRR 1.0, fallback accuracy 94.5%.

---

# Phase 3/4 Worked Example (live, production path)

Question: **"How do I create a Stripe account?"** — production params: `top_k=5`, `rrf_k=60`, `rerank_top_k=5`, `min_score=0.56`, threshold 0.65.

| Stage                     | Results (chunk id, title, score)                                                                                                                                                                                          |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Vector ANN @5             | v1 `91e16020` Accept simple payments for a startup **0.8638** · v2 `7a21aef9` **Get started** 0.8519 · v3 `bd5d92e1` Send invoices 0.8242 · v4 `e68ffa65` Common use cases 0.8220 · v5 `c16bbffb` Accept in-person 0.8218 |
| Keyword (over the 5 only) | k1 Get started 2.05 · k2 Accept in-person 1.57 · k3 Accept simple 1.43 · k4 Send invoices 1.12 · k5 Common use 0.44                                                                                                       |
| RRF fused                 | h1 **Get started** (v2+k1) 0.03252 · h2 Accept simple (v1+k3) 0.03227 · h3 Accept in-person 0.03151 · h4 Send invoices 0.03150 · h5 Common use 0.03101                                                                    |
| Rerank (true cosine)      | r1 Accept simple **0.7275** · r2 **Get started 0.7039** · r3 Send invoices 0.6483 · r4 Common use 0.6441 · r5 Accept in-person 0.6437                                                                                     |
| Outcome                   | all ≥ 0.56 kept; confidence 0.7822 → GENERATE. **Correct doc ranked #2**, edged out by a startup-payments chunk whose text overlaps "create/account" vocabulary.                                                          |

With a wider candidate window (`limit=20` probe), dev-env/CLI pages enter via keyword matches and RRF — matching the historically observed ordering (dev-env, CLI, get-started #4). Root cause of imperfect ranking is therefore **not** an RRF/score bug (scores are preserved; fusion is rank-only) but: (a) ANN@5 candidate ceiling, (b) chunk-granularity cosine favoring lexically-similar marketing pages over the procedural page, (c) no heading/section metadata to disambiguate.

Negative control: _"What is my database password?"_ → every candidate dropped by min_score → confidence 0.3293 → FALLBACK. ✅

---

# Phase 8 — Latency (evidence)

Current container (`rag_timing`, n=2, Groq): embedding 1197 ms · retrieval 472 ms · rerank 22 ms · context 4 ms · **generation 3560 ms** · **ttft 3148 ms** · **persist 1413 ms** · total 7566 ms.
Go-live golden eval (n=46 answered): TTFT p50 1655 / p95 2867 ms; total p50 7697 / p95 23827 ms (one 75 s outlier). Load test: TTFB p95 1.96 s cold / 262 ms warm-cache.

**Bottleneck ranking (evidence-based):** 1) Groq generation (~47%), 2) Gemini embedding on miss (~16%), 3) Mongo persist (~19% here — anomalously high, see R6), 4) ANN retrieval (~6%). Reranking and context building are negligible. **No generation-provider change is justified by this data.**

---

# Phase 9 — Test Quality

- `tests/test_confidence.py` — formula-level unit tests, correct arithmetic coverage. Fine.
- `tests/test_embedding_compatibility.py` — covers identity pass/block and dimension gate. Missing: the _ingestion-side_ scenario that produced BUG-1 (provider fallback mid-crawl creating mixed spaces) — no test asserts a website cannot end up with two identities.
- `tests/test_rag_validation.py` — realistic _structure_ (positive/negative/adversarial parametrized cases incl. XSS/injection), **but** every retrieval-dependent test installs `install_relevance_scoring` (tests/chat_helpers.py:166-203), replacing cosine with lexical token-overlap ratios (0..1). Threshold interactions (0.56/0.65) are therefore validated against a score distribution that cannot occur in production (real related-chunk cosines cluster 0.60-0.90; unrelated 0.45-0.75). The default fake returns constant 0.9 — worse. These tests can pass while production calibration is broken (and did during the 0.69-threshold era).
- `tests/test_rag_accuracy.py` — good coverage of wiring (reranker paths, adaptive, faithfulness, confidence e2e) using fakes; same unrealistic-score caveat; no test exercises `$vectorSearch` empty-result + broken-probe degradation (BUG-2) or monotonic-clock cache entries across processes (BUG-3).
- **Realistic coverage exists** in `scripts/staging_golden_eval.py` (real Atlas + real embeddings, 91-question golden set) — this is the trustworthy harness; the unit/e2e fakes are for wiring regressions only.

---

# Recommended Fix Order

**P0**

1. BUG-1: stop cross-provider embedding fallback during ingestion (fail/retry same-provider; quarantine on identity change); re-index the affected website (currently 13 invisible chunks).
2. BUG-2: fix `_probe_search_support` to use the `$listSearchIndexes` aggregation stage; add a regression test for the empty-result path.

**P1** 3. BUG-3: wall-clock timestamps in retrieval-cache entries. 4. BUG-5: invalidate/embed-identity guard on provider change (startup identity stamp check). 5. BUG-4: enforce or remove cache-size settings; align docstrings. 6. R1 (shadow): evaluate `CHAT_TOP_K=8-10` + `numCandidates≥200` against the golden eval to quantify recall lift before changing prod config.

**P2** 7. BUG-6: cascade-delete documents/chunks + cache flush on website delete. 8. BUG-7: accurate `keyword_result_count`. 9. BUG-8/R4: persist an explicit `model_said_fallback` flag (content equality with `UNKNOWN_ANSWER_FALLBACK`) for clean analytics. 10. R3: add heading/section metadata at crawl time; surface in `ContextItem.heading`. 11. R6: measure/adjust persist write concern; move non-critical rollups off the streaming critical path. 12. R8: delete documented dead code (`list_chunks_light`, `_load_all_chunks`).

---

_Audit performed read-only. Live probes: index introspection, chunk statistics, three full stage traces, repository-path reproduction inside the production container, and 96h log analysis. No code, prompts, thresholds, or data were modified._
