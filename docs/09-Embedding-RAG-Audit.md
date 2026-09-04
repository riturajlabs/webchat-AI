# Embedding and RAG Production Audit

**Scope:** `embedding.py`, provider routing/health, knowledge workers, retrieval, chunking, reranking, and RAG prompting. This is a code audit of the repository state reviewed on 2026-09-03, not a measured production-SLO result. A 90–95% answer-quality target needs a tenant-specific labelled evaluation set; sub-two-second latency must be enforced at p95 time-to-first-token (TTFT), not only as a mean end-to-end target.

## Executive assessment

### Implementation status (2026-09-03)

The P0 controls are now implemented: MongoDB atomically acquires a fenced
`embedding_run`; document and retry jobs carry and validate its run ID; provider
health is namespaced as `embedding:<provider>` and `generation:<provider>`; and
the API RAG service resolves a query embedder from the website's persisted
identity without cross-provider fallback. The active hybrid path already uses
`max(hybrid_candidate_limit, effective_top_k * 4)` rather than `limit=0`, and
the existing prompt already enforces the exact abstention string and citations.

The remaining items in this report are production rollout work, not safe
application-code defaults: create/validate the Atlas Search index in the Atlas
control plane, establish a labelled tenant evaluation set, and tune thresholds
against measured p95 TTFT/recall. Those outcomes cannot be guaranteed solely
by source changes.

The code has strong foundations: chunks carry a full embedding identity; Atlas vector queries filter by tenant, website, and identity; ingestion retries resolve an existing website lock; batch concurrency is capped; and the answer prompt contains an exact abstention string. `process_website_documents()` also chooses and persists a provider before its normal fan-out.

However, the required **provider state lock is not atomic**, health selection is not integrated with `provider_health.py`, and the chat path uses an unrestricted `FallbackEmbeddingClient`. With `EMBEDDING_PROVIDER_ORDER=["jina", "gemini", "cohere"]`, this allows a chat query to be embedded by Gemini/Cohere while a website is locked to Jina. The identity filter correctly rejects that query, but the customer experiences an error/no answer rather than a controlled, compatible fallback. Do not permit a query-provider fallback across embedding spaces.

The highest-priority production changes are:

1. Atomically acquire an immutable `embedding_identity` plus an ingestion-run id before queue fan-out.
2. Select that identity from the configured order using one embedding-health service, and record embedding successes/failures there.
3. Make each document retry carry the run id and resolve only its locked identity. On terminal provider failure, either defer with backoff or perform an explicit, fenced delete-and-reindex run; never silently switch a subset of pages.
4. Resolve the chat embedder from the website identity. Cache query vectors by identity and invalidate them on reindex.
5. Replace bounded-but-arbitrary in-memory keyword loading with Atlas Search/BM25 (or a materialized lexical index); retain a small candidate and context budget.

## Findings and remediation priority

| Priority | Finding                                                                 | Evidence and impact                                                                                                                                                                                                                                                                                                                          |
| -------- | ----------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| P0       | Lock acquisition is a read/modify/`replace_one`, not compare-and-set.   | `KnowledgeProcessor._persist_ingestion_lock()` and `MongoWebsiteRepository.update()` can race when duplicate crawl/knowledge jobs begin. Two unlocked workers may choose different healthy providers and last writer wins. The chunk identity conflict guard limits corruption, but leaves partial failures and non-deterministic ingestion. |
| P0       | `provider_health.py` is generation-only.                                | `AdaptiveProviderRouter` reads/writes `ProviderHealthStore`, while `select_ingestion_embedding_provider()` calls each client’s direct `health()` and does not record results in the store. Thus `provider_health.py` does not meet the requested pre-flight health contract for Jina/Gemini/Cohere.                                          |
| P0       | Chat embedding provider is independent of corpus identity.              | `backend/api/deps.py` builds `build_embedding_fallback()` for `RagService`; its provider can fail over from Jina to Gemini/Cohere. `MongoVectorRepository` then rejects identity mismatch. This is safe from silent corruption but breaks availability and can defeat the latency goal through failed attempts.                              |
| P1       | Retry is provider-consistent but final policy is incomplete.            | The worker reloads `website.embedding_identity` and calls `select_ingestion_embedding_provider(force_provider=...)`, so ordinary retries retain provider identity. After retry exhaustion it marks one document permanently failed. There is no website-level run state, provider-outage policy, or atomic wipe-and-restart option.          |
| P1       | The worker startup client is misleading/dead on the normal locked path. | `workers/app.py` builds `ctx["embedding_client"]`, but `_resolve_ingestion_provider()` constructs a selected provider independently and `KnowledgeProcessor` uses that resolver. This wastes initialization and makes intended routing less obvious.                                                                                         |
| P1       | Hybrid keyword recall is bounded but biased.                            | `_load_all_chunks()` calls `list_chunks_light(..., limit=50)` without a relevance ordering, so it scores an arbitrary first 50 Mongo documents, not the website corpus. It avoids full vector transfer but can miss a key term and adds a DB read plus Python scoring on every uncached query.                                               |
| P1       | Atlas index definition is not validated at startup.                     | `$vectorSearch` uses index `default`, path `embedding`, and filters on identity fields. The code only probes for a path after empty results; it does not assert an Atlas definition with `numDimensions`, `similarity`, and every filtered field. A missing filter field can make queries fail or become slow.                               |
| P2       | Context and TTFT budgets remain high for an interactive widget.         | Defaults allow 20,000 retrieved characters, 12 history turns, 4,096 output tokens, 10 s first-token timeout and 10 s embedding provider timeout. Streaming begins only after embedding, retrieval, hybrid load/rerank, history, and prompt construction.                                                                                     |
| P2       | Reranking itself is cheap, but hydration adds I/O.                      | The cosine reranker correctly reuses query vectors and stored candidate vectors. Hybrid keyword-only candidates trigger `get_chunks_by_ids()`, an additional serial Mongo round trip. It should be conditional on a small candidate pool and measured separately.                                                                            |

## Required ingestion architecture

Persist an explicit immutable ingestion run rather than only four independent fields. A minimal website document state is:

```json
{
  "embedding_run": {
    "id": "run_01...",
    "state": "running",
    "identity": {
      "provider": "jina",
      "model": "jina-embeddings-v3",
      "dimensions": 1024,
      "version": "1"
    },
    "attempt": 0,
    "started_at": "...",
    "next_retry_at": null
  }
}
```

Treat the existing `ingestion_embedding_*` fields as the published corpus identity after a successful run, or retain them as denormalized copies of `embedding_run.identity`. Every queued page must contain `website_id`, `document_id`, and `run_id`. A worker must reject a stale job whose run id differs from the active run. This stops an old retry from writing after a destructive reindex.

### Atomic acquisition and provider health

Add a repository operation using `find_one_and_update`; do not use `WebsiteRepository.update()`/`replace_one()` for lock acquisition. The operation is the concurrency boundary.

```python
# backend/repositories/website_repository.py
from pymongo import ReturnDocument


async def acquire_embedding_run(
    self, tenant_id: str, website_id: str, identity: EmbeddingIdentity
) -> Website | None:
    now = utcnow()
    run = {
        "id": new_id(),
        "state": "running",
        "identity": identity.as_dict(),
        "attempt": 0,
        "started_at": now,
        "next_retry_at": None,
    }
    doc = await self._collection.find_one_and_update(
        {
            "_id": website_id,
            "tenant_id": tenant_id,
            "$or": [
                {"embedding_run": {"$exists": False}},
                {"embedding_run.state": {"$in": ["completed", "failed"]}},
            ],
        },
        {"$set": {"embedding_run": run, "knowledge_status": "processing", "updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    return Website.from_doc(doc) if doc else None
```

The selector should use `ProviderHealthStore` for pre-flight availability and also perform a bounded readiness probe; a cached circuit state alone cannot prove credentials or a provider endpoint is usable. It must select only in `.env` order—do not use latency scoring for ingestion because the order is a policy decision.

```python
# backend/services/knowledge/embedding.py (or a new embedding_router.py)
async def select_healthy_embedding_provider(
    order: list[str], health: ProviderHealthStore
) -> EmbeddingClient:
    for name in order:
        provider = build_embedding_provider(name)  # raises if key/model config is invalid
        if not await health.is_available(f"embedding:{name}"):
            continue
        started = time.perf_counter()
        try:
            if not await asyncio.wait_for(provider.health(), timeout=2.0):
                raise EmbeddingUnavailableError("readiness probe returned unhealthy")
        except Exception:
            await health.record_failure(f"embedding:{name}")
            continue
        await health.record_success(f"embedding:{name}", (time.perf_counter() - started) * 1000)
        return provider
    raise EmbeddingUnavailableError("No healthy configured embedding provider")
```

Namespace health keys (`embedding:jina` versus `generation:jina`) so an embedding quota event does not take a generation provider out of service. Wrap every successful/failed embedding batch with `record_success`/`record_failure`, including 429s, and emit provider/model/run-id metrics.

### Same-provider retries and deliberate reindex

When a page retry starts, load the active run and instantiate **only** `run.identity.provider`; verify model, dimensions, and version match before embedding. Defer on rate limit/unavailability with jittered exponential backoff and retain the run. Do not fall through to the next provider.

```python
# backend/workers/jobs/knowledge.py
async def process_document(ctx: dict[str, Any], document_id: str, run_id: str) -> dict[str, Any]:
    processor = _processor(ctx)
    website = await processor.website_for_document(document_id)
    run = website.embedding_run
    if run is None or run["id"] != run_id or run["state"] != "running":
        return {"status": "stale_job"}
    embedder = await build_locked_embedding_provider(EmbeddingIdentity(**run["identity"]))
    try:
        return await processor.process_document(document_id, embedder=embedder, run_id=run_id)
    except (EmbeddingRateLimitedError, EmbeddingUnavailableError):
        delay = bounded_full_jitter(run["attempt"], base=5, cap=300)
        await processor.defer_run(run_id, delay)
        await enqueue_process_document_deferred(document_id, run_id, delay)
        return {"status": "retry_scheduled", "run_id": run_id, "delay": delay}
```

If business policy permits a new provider after an outage, transition the whole run with a fenced operation: mark old run `restarting`, delete _all_ website chunks in a Mongo transaction (or mark them by `run_id` and exclude them from retrieval), clear the lock, acquire a new run/identity, then enqueue every current document. Never delete/reindex one failed page into a different space. Prefer waiting unless an operator or a documented threshold (for example, 30 minutes plus all pages retried) explicitly triggers restart.

## Retrieval, latency, and quality

### Vector and hybrid retrieval

Create/validate the Atlas Search index outside normal Mongo B-tree index creation. The filter fields must be declared `filter`; the vector dimensions must exactly equal the selected model output.

```json
{
  "fields": [
    { "type": "vector", "path": "embedding", "numDimensions": 1024, "similarity": "cosine" },
    { "type": "filter", "path": "tenant_id" },
    { "type": "filter", "path": "website_id" },
    { "type": "filter", "path": "embedding_provider" },
    { "type": "filter", "path": "embedding_model" },
    { "type": "filter", "path": "embedding_dimensions" },
    { "type": "filter", "path": "embedding_version" }
  ]
}
```

Keep `limit=8–12` and `numCandidates=100–200`, then tune recall@10 from a golden set. `max(top_k * 20, 100)` is reasonable at the current small `top_k`, but it should be configurable and measured by corpus size. In production, treat brute-force cosine fallback as an availability diagnostic, not an acceptable chat path: it can scan an entire tenant website and cannot meet p95 latency.

Replace the arbitrary 50-document keyword pool with an Atlas Search text/BM25 query, tenant/website/identity filters, and `limit=20–40`; fuse that bounded result with vector top-k. If Atlas text search is not available, materialize a per-website inverted index or disable hybrid for large websites rather than claiming full-corpus keyword recall from an unordered subset.

### Chunking and context

`chunker.py` appropriately removes common navigation/footer tags, prefers `main`/`article`, tracks headings, and splits on headings/sentences. The defaults (700 tokens / 100 overlap) are viable for broad web pages but should be benchmarked against the selected model and answer style. For concise support FAQs, start with 350–500 tokens and 50–75 overlap; preserve heading + parent heading in every chunk. Add boilerplate deduplication across a website (cookie banners, repeated headers), URL canonicalization, and a minimum information-density rule before embedding.

Use a score calibration set per provider. A global `chat_context_min_score=0.25` is not meaningful across Jina/Gemini/Cohere, and RRF scores are not cosine scores. Gate dense-only chunks with a calibrated dense threshold; gate lexical matches by exact-token/entity evidence; require at least one strong result before generation. Keep 3–5 diversified chunks and a 6–10k-character prompt budget for the widget’s fast lane; send complex queries to a separately measured slower lane.

The current prompt is already strict and has a non-LLM fallback when retrieval/context is empty. Strengthen enforcement by requireing source citations for each sentence and post-validating that the answer contains a citation when it is not the exact fallback. Do not rely on prompt text alone for abstention.

### TTFT plan

The current generator streams tokens, but first token is delayed by serial user-message persistence, optional query-rewrite history await, query embedding, vector search, hybrid corpus load, rerank hydration, context, and final history await. For p95 <2 s:

- Start session/history load concurrently with the website lookup and persist the user message asynchronously after validation, with a durable outbox if strict ordering is required.
- Keep query embedding to one provider and set a widget fast-path timeout around 500–800 ms; do not wait 10 seconds before a cross-space fallback.
- Run vector and lexical Atlas queries concurrently after query embedding; avoid the current second `get_chunks_by_ids()` by returning embeddings for only the small fused candidate set.
- Emit `sources` as soon as retrieval completes, begin provider streaming immediately after prompt construction, and record TTFT from request receipt through first emitted SSE `message` event.
- Set a small output cap for the widget (for example 512–768) and use a model/provider with measured p95 TTFT below the remaining budget.

## Benchmark and release gate

Use the existing `backend/benchmark/` tools: `golden_eval.py`/`evaluation.py` for labelled retrieval metrics, `retrieval_comparison.py` and `ab_evaluation.py` for vector-versus-hybrid comparison, and `llm_evaluation.py` for answer quality. Add cases for every tenant, rare product names, negatives (must abstain), multi-hop/ambiguous questions, and conversational follow-ups.

Release only when a representative staged corpus meets: recall@10 >= 0.95 for answerable questions; grounded-answer/citation precision >= 0.90; abstention precision >= 0.95 for unanswerable questions; p50/p95 retrieval and TTFT split by cache hit/miss and provider; and no mixed `embedding_identity` within a website/run. Alert on identity mismatch, brute-force fallback, provider circuit opens, retry age, hybrid corpus size, rerank hydration time, no-context rate, and unsupported-answer rate.

## Safe rollout order

1. Add atomic run acquisition, run-id job fencing, embedding health namespace, and locked chat query embedding. Add unit/integration tests for concurrent fan-out, 429 retry, stale retry, and forced provider outage.
2. Build the Atlas vector/text index and fail deployment health checks if its definition differs from configured dimensions/filter fields.
3. Measure baseline and new configurations on the golden set; tune chunks, candidate counts, thresholds, and prompt/context budgets per provider identity.
4. Reindex one tenant at a time. Do not change `EMBEDDING_PROVIDER_ORDER`, model, dimensions, or embedding version for an active corpus without creating a new whole-website run.
