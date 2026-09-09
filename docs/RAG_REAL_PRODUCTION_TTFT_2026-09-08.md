# RAG Real-Production TTFT Benchmark — 2026-09-08

Objective: **RAG-PERF-07 / REAL-TTFT-02** — measure the complete real production RAG path
(FastAPI → RagService → real Redis → real embedding provider → real MongoDB vector search → hybrid
retrieval → rerank → context construction → real streaming LLM → first token) end-to-end, on the
actual running production stack, to determine whether real e2e TTFT P95 < 3000 ms.

Status: **COMPLETE**

## Decision

- Client-observed end-to-end TTFT (first `message` SSE delta) — the metric a user actually feels —
  is **P95 ≈ 8.3 s, P50 ≈ 4.9 s, mean ≈ 5.5 s** (N=64). **The `< 3000 ms` P95 target is NOT met.**
- Server-reported provider TTFT (time until first token leaves the LLM provider) is
  **P95 ≈ 2.1 s, P50 ≈ 1.4 s** — comfortably under 3000 ms.
- The gap is dominated by pre-generation pipeline cost on **cache miss**: real embedding
  (mean ≈ 1.5 s for first occurrence of each question) + brute-force cosine scan (~300 ms) + chunk
  load (~170 ms) + rerank, ON TOP of provider TTFT, plus SSE-stage overhead. Cache hits cut total
  server latency ~32% (mean 5358 → 3636 ms).
- Verdict: with a warm retrieval cache the server approaches the target but still misses it on the
  client side; cold starts are ~2x further out. Optimization priority: reduce real embedding latency
  on cache miss (vector store / better index), and reduce the delta between provider TTFT and
  client-visible first token (SSE/pipeline overhead).
- Correctness holds: 64/64 correct, 60/64 state the exact round figure, **0 cross-tenant leakage**,
  0 HTTP errors, 0 RAG confidence rejections.

## Environment & Configuration

- Stack: docker compose `docker/compose.yml` with `.env.production` (`ENVIRONMENT=production`),
  7 containers (api, worker, widget, dashboard, mongo, redis, mailpit), `UVICORN_WORKERS=1`.
  Git commit under test: `5718ac4`.
- Real providers (live probes before run): generation `gemini-2.5-flash` (first delta 3447 ms),
  embedding `gemini-embedding-001` (747.7 ms, 1024-dim), identity `gemini/1024/v1` matches the
  ingestion corpus.
- Pipeline flags (production values): `GENERATION_PROVIDER_ORDER=[gemini,groq,openrouter]`,
  `EMBEDDING_PROVIDER_ORDER=[gemini,jina,cohere]`, `ENABLE_HYBRID_SEARCH=true`,
  `ENABLE_RERANKING=true`, `ENABLE_RAG_CONFIDENCE_CHECK=true`, `CHAT_TOP_K=5`, `RERANK_TOP_K=5`,
  `CHAT_RETRIEVAL_CACHE_TTL_SECONDS=900` (15 min), `EMBEDDING_DIMENSIONS=1024`.
- Rate limits: `chat_limiter` 60 req/min; API-key rate limit applies only to `wc_*` keys (this run
  used the owner JWT path); LLM daily/monthly/min per-second token quotas default to 0 = unlimited.
- Provider free-tier cap observed live: Gemini generation quota (~20/day) was exhausted mid-run, and
  the production fallback chain automatically served the remainder via Groq and OpenRouter — exactly
  the designed behavior (0 failures, 3 requests recorded one fallback attempt).

## Methodology

- **Corpus**: two distinct benchmark tenants, each with a single production website and 23
  real, multi-section markdown documents (1 chunk each) ingested through the REAL worker path
  (`process_website_documents` → `process_document` → chunker → `gemini-embedding-001` →
  knowledge_chunks), not through a mock. Ground truths: Tenant A "BCA Academy A" annual BCA fee
  **Rs 80,000**; Tenant B "BCA Academy B" annual BCA fee **Rs 65,000**. A third same-tenant decoy
  website (Commerce College) exists in the corpus to exercise scoping.
- **Cross-tenant isolation**: websites `_id` is globally unique, so "same website across two
  tenants" is impossible by schema; the real substitute is A-vs-B (different tenants, different
  websites): Tenant A answers must never contain 65,000 and Tenant B answers must never contain
  80,000 (verified → 0 leaks either direction).
- **Workload**: 8 questions per tenant, 4 repeats each → 64 real streaming requests (≥30 required),
  paced ≥1 s apart. First occurrence of each question is a retrieval-cache **miss**, the next three
  within the 900 s TTL are **hits**.
- **Measurement definitions**:
  - `client_first_frame_ms` — client time to the first SSE frame of any kind.
  - `client_first_delta_ms` (the reported **e2e TTFT**) — client time to the first `message`
    content delta; includes the entire server pre-generation pipeline + provider TTFT + network.
  - `server_ttft_ms` — server-side time to first token from the LLM provider (`ttft_ms` timing
    field).
  - `server_total_ms` — server total until the stream completes (`total_ms`).
  - Per-stage fields captured from the `done` frame timing block (`latency_*` equivalents):
    embedding, retrieval, load_chunks, context, history, website_lookup, session_resolution,
    user_message_persist, prompt_construction, rerank, generation, persist, delta_overhead.
- **Deviations (documented)**: (1) live web crawl of benchmark sites is blocked by the in-place
  SSRF guard by design — documents were seeded directly and then processed by the real worker
  pipeline; (2) local MongoDB 7.0.40 has no Atlas `$vectorSearch`, so vector retrieval runs the
  repo's exact brute-force cosine fallback — this is the real behavior of this deployment.

## Results (N = 64, 0 errors)

| metric                                | mean     | p50      | p95      | p99       | max       |
| ------------------------------------- | -------- | -------- | -------- | --------- | --------- |
| server_ttft_ms (provider first token) | 1492     | 1382     | 2080     | 2603      | 4453      |
| generation_ms (stream duration)       | 2435     | 1714     | 5376     | 9490      | 11140     |
| server_total_ms (until stream ends)   | 4067     | 3573     | 6851     | 12236     | 12265     |
| client_first_frame_ms                 | 2316     | 1792     | 3832     | 6473      | 10694     |
| **client_first_delta_ms (e2e TTFT)**  | **5469** | **4920** | **8282** | **13731** | **14035** |

Per tenant (e2e TTFT, ms):

| tenant          | N   | mean | p50  | p95  | max   |
| --------------- | --- | ---- | ---- | ---- | ----- |
| A (gold 80,000) | 32  | 5637 | 5343 | 8456 | 14035 |
| B (gold 65,000) | 32  | 5300 | 4644 | 8091 | 13553 |

### Retrieval-cache miss vs hit (900 s TTL)

| stage                        | miss (n=16) mean | miss p95 | hit (n=48) mean | hit p95  |
| ---------------------------- | ---------------- | -------- | --------------- | -------- |
| embedding_ms (real provider) | 1494             | 2634     | 0               | 0        |
| retrieval_ms (cosine scan)   | 298              | 398      | 0               | 0        |
| load_chunks_ms               | 170              | 469      | 98              | 117      |
| website_lookup_ms            | 81               | 104      | 84              | 150      |
| rerank_ms                    | 5                | 8        | 5               | 11       |
| generation_ms                | 2019             | 3269     | 2574            | 5737     |
| persist_ms                   | 264              | 521      | 208             | 246      |
| user_message_persist_ms      | 88               | 141      | 84              | 112      |
| **server_total_ms**          | **5358**         | **8081** | **3636**        | **6837** |

Cache hits cut total server latency by ~32% (mean); the entire embedding + retrieval cost is
eliminated, and chunk load nearly halves.

### Provider mix

- groq: 35, openrouter: 29 (gemini exhausted its free-tier daily quota mid-run; automatic fallback).
- `retrieval_method=hybrid` on all 64 requests; `reranked=true` on all 64 (`rerank_input_count` 20–23).
- 0 HTTP errors, 0 empty answers, 0 SSE protocol failures.

## Correctness & Isolation

- **64/64 answers semantically correct** (BCA fees quoted correctly for the right tenant).
- **60/64 state the exact round figure.** The 4 that omit the total are still correct: 2 for the
  installments question ("two equal installments of Rs 40,000" = halves of the A fee), 2 for the
  refundability question where "full refund of the annual fee" answers the question directly.
- **Cross-tenant leakage: 0 of 64** (no Tenant A answer mentions 65,000; no Tenant B answer
  mentions 80,000; decoy-tenant content never surfaced).
- Faithfulness: 49/64 at 1.0; 15 at ≤0.5 (some answers cite a supporting fact beyond the exact
  question — not factual errors, but worth reviewing in a follow-up).
- RAG confidence: all 64 above their dynamic `confidence_minimum_score` (0 rejections); input
  token range ~1176–1272, output 37–284, context ~3.6–3.9k chars.

## Bottleneck Classification

1. **Embedding (cache miss)** — real provider call averages ~1.5 s (p95 2.6 s); the single largest
   pre-generation block and only necessary on first ask per question.
2. **Generation / provider latency** — generation stream alone averages ~2.4 s; with Gemini-quota
   note that provider affects TTFT and tails (max generation 11.1 s).
3. **Retrieval + load** — ~460 ms combined on miss (brute-force cosine scan of 23 tenant chunks +
   chunk fetch), near-zero on hit.
4. **Pipeline overhead** — website lookup + session resolution + user-message persist ≈ 250 ms,
   invariant to cache; persist ~200 ms.

## Regression Suite

- Targeted RAG-path subset (rag_service, chat_api, retrieval cache, vector_mongodb, hybrid_search,
  confidence, chunker, answerability, query_classifier, reranker, source_diversity, retrieval
  strategy/comparison): **all pass**.
- Full suite: **2201 collected, 0 failures** (6 skipped). No code changes were made for this
  benchmark; the gate exists to confirm the measured path is the shipped one.

## Limitations

- Provider mix varies (gemini/groq/openrouter) due to free-tier caps; TTFT across providers is
  pooled in the headline numbers.
- Brute-force cosine fallback means retrieval numbers are for this deployment's actual vector path,
  not Atlas `$vectorSearch`.
- Benchmark corpus is synthetic-but-real (real docs, real ingestion worker, real embeddings).
- No live crawl by design (SSRF guard).

## Re-run

```
# Tenant A cold (32 req) then Tenant B cold (32 req)
.venv/bin/python scripts/perf/benchmark_live.py --tag a \
  --tenant-id 5310b4f9-34dd-4e24-9677-5c022c5f04f2 \
  --website-id eb3eaeb8-af4d-442d-acfc-f27a00eb7b57 \
  --email bench-a@example.com --questions 8 --repeats 4 --phase cold \
  --output /tmp/opencode/bench_a_cold.ndjson
.venv/bin/python scripts/perf/benchmark_live.py --tag b \
  --tenant-id 00149338-9123-4542-b739-d0d2349db786 \
  --website-id 2e8632b4-ea98-4a22-8f23-52c45c0cab22 \
  --email bench-b@example.com --questions 8 --repeats 4 --phase cold \
  --output /tmp/opencode/bench_b_cold.ndjson
```

Corpus is idle-recreated idempotently by the seeder (`/tmp/opencode/seed_prod_corpus.py` in the
`api` container); re-seeding requires resetting the `embedding_run` fence first
(`/tmp/opencode/reset_fence.py`) because terminal fence states gate the worker.
