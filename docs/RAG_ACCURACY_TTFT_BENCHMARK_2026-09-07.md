# RAG Accuracy + TTFT Benchmark — RAG-ACC-01 (measurement phase)

- **Date:** 2026-09-07
- **Measurement kind:** SYNTHETIC (deterministic in-memory fakes, dev box)
- **Scope:** measurement ONLY. No production code, retrieval algorithms, ranking, chunking, prompts, caches, embeddings, or LLM configuration were changed.
- **Method:** deterministic golden-fixture retrieval via `stream_answer` on the current `RagService` (hybrid keyword+vector + RRF; F-02 schema-2 retrieval cache; F-03 `asyncio.to_thread` lexical offload). Relevance is defined by predeclared golden chunk titles, never derived from model output. Latency percentiles are computed from raw per-request `done` timing frames (nearest-rank), not bucket estimates.
- **Artifact:** `/tmp/opencode/rag_accuracy_bench_results.json` (all N>=30 raw samples aggregated; per-query accuracy rows retained).

> **IMPORTANT:** every latency/TTFT number below is **SYNTHETIC** — it was measured against in-memory fakes (`FakeVectorRepository`, `FakeEmbeddingClient`, `FakeGenerationClient`) on this dev box. It is NOT production latency and must not be presented as such. Real-provider TTFT could not be measured (no LLM provider credentials/services in this environment); see **Production limitations**.

## 1. Executive summary

- **Accuracy (deterministic, synthetic retrieval):** exact, short, paraphrase, follow-up = perfect (Recall@3 = MRR = 1.000). Typo queries recover all golden chunks at Recall@3 (1.000) but rank weaker at position 1 (Recall@1 = 0.625, MRR = 0.875). Broad queries are the weakest category (Recall@5 = 0.389): surface token overlap drives the deterministic proxy, so plural/absent-token broad phrasings retrieve nothing or only a subset. Multi-source queries fuse both required sources at Recall@5 (1.000).
- **Cross-site isolation:** ZERO leakage between websites A/B, between tenants, or across corpus versions; correct per-site grounding (₹80,000 vs ₹65,000) verified. No `CRITICAL` failures.
- **Retrieval latency (synthetic):** total retrieval P50 ≈ 2.0 ms, P95 ≈ 3.1 ms (100-chunk corpus); target `retrieval P95 < ~500 ms` **PASS (synthetic-only)**.
- **Cache hit vs miss (synthetic):** F-02 retrieval-cache hit returns directly with all retrieval stages at 0 ms — hit P95 = 0.0 ms vs miss P95 = 3.6 ms (≈100% retrieval-stage elimination).
- **TTFT:** synthetic provider yields first token in ≈ 0.01 ms P50–P99; the engineering targets (P50 ≤ 2 s, P95 ≤ 3 s, P99 ≤ 5 s) trivially **PASS under the synthetic provider only**. Real-provider TTFT is **UNMEASURED/UNAVAILABLE** — these targets are NOT validated end-to-end.
- **Major bottleneck (synthetic):** with the FAKE provider the retrieval stage dominates end-to-end time; within retrieval, **lexical corpus load + keyword pass** dominates and grows with corpus size (at 5,000 chunks: lexical load P50 ≈ 58 ms and keyword pass P50 ≈ 75 ms of ≈ 100 ms retrieval total). With a REAL provider, LLM time-to-first-token + embedding/network latency would dominate (unmeasurable here).

## 2. Accuracy by category (Recall@1 / Recall@3 / Recall@5 / MRR)

| Category     | Queries | Recall@1 | Recall@3 | Recall@5 |   MRR |
| ------------ | ------: | -------: | -------: | -------: | ----: |
| exact        |       4 |    1.000 |    1.000 |    1.000 | 1.000 |
| short        |       3 |    1.000 |    1.000 |    1.000 | 1.000 |
| broad        |       3 |    0.167 |    0.278 |    0.389 | 0.444 |
| paraphrase   |       5 |    1.000 |    1.000 |    1.000 | 1.000 |
| typo         |       4 |    0.625 |    1.000 |    1.000 | 0.875 |
| followup     |       3 |    1.000 |    1.000 |    1.000 | 1.000 |
| multi-source |       3 |    0.500 |    0.833 |    1.000 | 1.000 |
| no-answer    |       3 |        — |        — |        — |     — |

Notes (per-query detail is in the JSON artifact):

- **no-answer:** Recall/MRR are undefined (empty golden set). Measured behavior: `What is the MBA tuition fee?` surfaced `bca-fee`/`bca-scholarship` (partial on-topic evidence, fact absent — an answerability/LLM judgment is required downstream); `What are the MBA admission requirements?` surfaced `bca-admission`; `What is the capital of France?` retrieved nothing and the pipeline emitted the `context_empty` fallback. 2/3 no-answer queries produced evidence touching the site corpus; none produced out-of-corpus evidence.
- Retrieval here is a strict lexical-overlap proxy (deterministic replacement for the semantic `similarity_search`), so categories that need semantics/embeddings without surface token overlap (e.g. `What courses are available?` vs the `specialization electives` chunk) under-measure versus a real embedding index.

## 3. No-answer queries — retrieval behavior (not a score)

| Query                                    | Sources returned         | Grounding intact | Fallback |
| ---------------------------------------- | ------------------------ | ---------------- | -------- |
| What is the MBA tuition fee?             | bca-fee, bca-scholarship | yes              | False    |
| What are the MBA admission requirements? | bca-admission            | yes              | False    |
| What is the capital of France?           | (none)                   | n/a              | True     |

The system is not judged on returning zero chunks; the benchmark records what it actually retrieved. For an absent-at-relevant-chunks query nothing is invented: evidence is either absent (→ `context_empty` safe fallback) or present-but-about-a-neighboring-topic (→ downstream confidence/faithfulness decides).

## 4. Cross-site / tenant / corpus-version isolation

- Query: `What is the annual BCA tuition fee?`
- Site A (`academy-a`, fee ₹80,000) sources: `5`
- Site B (`academy-b`, fee ₹65,000) sources: `3`
- **Leakage B→A: `0`; A→B: `0` ⇒ ZERO cross-site leakage — PASS (no CRITICAL failures).**

- Tenant isolation: tenant A served `5` Academy-A sources; tenant B dedicated retrieval-cache key ⇒ `retrieval_cache=miss` (identical query under tenant B did NOT reuse tenant A's cached result). (Note: two tenants sharing one website _id_ cannot exist in production — `Website.id` is the global Mongo `_id`; the fake repo keys by id, so tenants are isolated by distinct ids + tenant-scoped cache keys, both asserted.)

- Corpus-version isolation: after bumping `website.updated_at`, the same query was served from a fresh retrieval (`retrieval_cache=miss`) with `5` correct `academy-a` sources — no stale cross-version evidence.

## 5. Retrieval latency by stage (SYNTHETIC, 100-chunk corpus, N=30 miss queries, ms)

| Stage                      |       P50 |       P95 |       P99 |       min |       max |      mean |
| -------------------------- | --------: | --------: | --------: | --------: | --------: | --------: |
| embedding                  |     0.060 |     0.080 |     0.080 |     0.040 |     0.080 |     0.056 |
| vector search              |     0.690 |     1.330 |     1.880 |     0.600 |     1.880 |     0.836 |
| lexical load               |     1.190 |     2.090 |     2.250 |     0.930 |     2.250 |     1.333 |
| keyword/hybrid (kernel)    |     1.153 |     1.946 |     2.243 |     1.047 |     2.243 |     1.279 |
| context                    |     0.070 |     0.150 |     0.200 |     0.050 |     0.200 |     0.078 |
| rerank (when enabled)      |     0.000 |     0.060 |     0.060 |     0.000 |     0.060 |     0.006 |
| **retrieval total**        | **1.980** | **3.080** | **3.450** | **1.670** | **3.450** | **2.226** |
| e2e total (incl. fake gen) |     5.990 |     6.960 |     9.310 |     4.660 |     9.310 |     5.988 |

- `keyword/hybrid` is measured as the direct `keyword_search` kernel over the corpus because `RagService` does not separately instrument the keyword/RRF pass (it runs off-loop via `asyncio.to_thread` under PERF-K01). `vector search` is the pipeline's `retrieval_ms`. `rerank` used the deterministic embedding reranker (stored zero-vector embeddings ⇒ cosine contributes nothing; strong-lexical protection and ordering were still exercised; RERANK numbers are accordingly SYNTHETIC and near-zero).

## 6. Cache hit vs miss (SYNTHETIC, 100-chunk corpus, N=30 each, ms)

| Metric              | Cache Miss P50 | Cache Miss P95 | Cache Miss P99 | Cache Hit P50/P95/P99     | Improvement (P50) |
| ------------------- | -------------: | -------------: | -------------: | ------------------------- | ----------------: |
| embedding           |          0.050 |          0.100 |          0.110 | 0.000 / 0.000 / 0.000     |              100% |
| vector search       |          0.710 |          1.750 |          1.800 | 0.000 / 0.000 / 0.000     |              100% |
| lexical load        |          1.140 |          2.360 |          2.700 | 0.000 / 0.000 / 0.000     |              100% |
| rerank              |         0.000* |         0.000* |         0.000* | 0.000 / 0.000 / 0.000     |               n/a |
| **retrieval total** |      **1.910** |      **3.610** |      **3.840** | **0.000 / 0.000 / 0.000** |          **100%** |
| e2e total           |          5.830 |          8.970 |         10.280 | 1.200 / 2.040 / 2.780     |               79% |

F-02's schema-2 cache-hit path returns the FINAL post-strategy, post-rerank result directly; retrieval-structure assertions confirm embedding/vector-search/lexical load are skipped on a hit (`embedding_ms = retrieval_ms = load_chunks_ms = 0`). Improvement ≈100% of the retrieval stage at all percentiles (SYNTHETIC).

## 7. Corpus-scale retrieval (SYNTHETIC, N=30 per size, ms)

| Chunks | Stage                   |     P50 |     P95 |     P99 |
| -----: | ----------------------- | ------: | ------: | ------: |
|    100 | lexical load            |   1.240 |   3.470 |   5.440 |
|    100 | keyword/hybrid (kernel) |   1.239 |   2.219 |   2.514 |
|    100 | retrieval total         |   2.100 |   4.850 |   6.220 |
|    100 | e2e total               |   5.950 |  10.230 |  10.590 |
|    500 | lexical load            |   4.900 |   9.720 |  65.770 |
|    500 | keyword/hybrid (kernel) |   6.120 |   9.966 |  10.909 |
|    500 | retrieval total         |   9.480 |  13.100 |  69.150 |
|    500 | e2e total               |  18.840 |  24.580 |  79.950 |
|   1000 | lexical load            |  10.530 |  15.390 |  79.410 |
|   1000 | keyword/hybrid (kernel) |  13.549 |  22.352 |  27.194 |
|   1000 | retrieval total         |  18.330 |  34.550 |  88.110 |
|   1000 | e2e total               |  36.290 |  55.530 | 106.750 |
|   5000 | lexical load            |  60.390 | 126.050 | 135.340 |
|   5000 | keyword/hybrid (kernel) |  75.213 | 133.532 | 147.367 |
|   5000 | retrieval total         |  99.840 | 166.990 | 176.040 |
|   5000 | e2e total               | 184.210 | 256.940 | 265.920 |

Retrieval grows with corpus size (5K ≈ 100 ms P50 vs 100 ≈ 2.4 ms — dominated by the lexical corpus load + keyword pass; F-01/F-03 keep the parse off the event loop, F-02 cache hits bypass it entirely). Absolute values are dev-box/in-memory; real Mongo ANN + embedding provider latency are not represented. P99 tail is inflated by in-process thread-scheduling jitter.

## 8. TTFT / retrieval targets

TTFT values are in **µs** (from the `ttft_ms` timing frame), i.e. the SYNTHETIC
provider's time to a first token:

| Metric            | P50 | P95 | P99 | Target                | Verdict          |
| ----------------- | --: | --: | --: | --------------------- | ---------------- |
| TTFT (cache miss) |  10 |  20 |  20 | ≤ 2 s / ≤ 3 s / ≤ 5 s | PASS (SYNTHETIC) |

| TTFT (cache hit) | 10 | 20 | 20 | ≤ 2 s / ≤ 3 s / ≤ 5 s | PASS (SYNTHETIC) |

| Retrieval P95 (< ~500 ms) | — | 3.080 ms | — | < 500 ms | PASS (SYNTHETIC) |

TTFT here is `time from request/generation start to first assistant token` (`ttft_ms` in the `done` frame). With the synchronous fake generation client the first token is produced in microseconds — every target trivially passes. This is **not** evidence for real-provider performance.

## 9. Bottleneck analysis (measured, SYNTHETIC)

- **Fake-provider environment (what was measured):** `retrieval total` dominates e2e. Within retrieval the bottleneck is **lexical retrieval (corpus load 60% of retrieval total at 5K) + keyword/hybrid pass (75% at 5K)**, scaling with corpus size. Vector search here is in-memory (trivial ms). Caching (F-02) removes all of it on hit.
- **Real LLM environment (not measured):** the dominant cost would shift to **LLM time-to-first-token + provider/network** and, per-hit, to **embedding provider latency**; these are UNMEASURED — no credential/services. No latency number in this report should be used as a production estimate.

Classified bottleneck summary: `lexical retrieval` (measured, synthetic) ; `LLM TTFT + provider/network` (expected dominant in production, UNMEASURED); `context/history` negligible; `reranking` negligible (fake embeddings); `embedding`/`vector search` negligible in synthetic harness.

## 10. Production limitations

| Item                 | Status                                                                                                                                                                                                                                                 |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Latency/TTFT numbers | **SYNTHETIC** — dev box, in-memory fakes, no network/DB/real ANN index                                                                                                                                                                                 |
| Accuracy numbers     | Deterministic **proxy** — `similarity_search` replaced by a lexical-overlap scorer; reflects current retrieval _structure_ (hybrid keyword/RRF, min-score gate, follow-up rewrite, F-02/F-03) on synthetic golden sets, not semantic embedding quality |
| Real provider TTFT   | **UNAVAILABLE** — no LLM/embedding provider credentials or services reachable in this environment; specifically NOT invented                                                                                                                           |
| Corpus               | Synthetic fixtures only; no production/customer data crawled or re-ingested                                                                                                                                                                            |
| Re-run               | `RAG_BENCH=1 .venv/bin/pytest tests/test_rag_accuracy_benchmark.py` regenerates `rag_accuracy_bench_results.json`                                                                                                                                      |
