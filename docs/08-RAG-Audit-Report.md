# RAG Pipeline Audit Report

**System:** WebChat AI
**Scope:** ingestion, embeddings, vector and hybrid retrieval, reranking, context construction, query rewriting, Gemini generation, and RAG prompts
**Date:** 2026-09-03
**Target:** 90-95% answer accuracy and sub-2-second user-perceived latency

## Implementation Status

The code fixes from this audit are implemented and regression-tested:

- Hybrid corpus loading is bounded in both retrieval-cache branches.
- Startup probes for the Atlas `default` vector index and warn on missing or incompatible definitions.
- HTML is cleaned before chunking; boilerplate tags are removed and semantic headings are preserved.
- Dense, lexical, and exact-match evidence are represented separately; context gating no longer treats RRF as cosine.
- The RAG prompt now requires claim-level citations and evidence-proportional answers.

The Atlas Search index itself remains an infrastructure action: it must be provisioned in Atlas with the configured dimension and filter fields. Corpus re-crawling/re-embedding and replacing the temporary in-memory lexical fallback with Atlas Search text/BM25 remain data and deployment work, not safe automatic application-startup changes.

## Executive Summary

The pipeline has good defensive foundations: tenant and website filters are applied to vector search, embedding identities and dimensions are checked, query embeddings are cached and single-flighted, stored vectors are used by the fast reranker, and the model is not called when retrieval returns no usable context.

The target is not credible with the current defaults without measurement and corpus work. The most important issues are:

1. **P0 latency:** hybrid retrieval performs a full website corpus read and an O(N) Python keyword scan on every cache miss and cache hit. The current code uses `list_chunks_light`, which avoids transferring embeddings, but `_load_all_chunks` is still called with `limit=0`; the configured candidate limit is not used to bound the corpus. This is still a substantial network and CPU cost for large websites.
2. **P0 retrieval correctness:** hybrid search is not BM25. It is a simple stop-word-filtered term-frequency score followed by RRF. It has no document frequency, field weighting, phrase matching, stemming, or persistent inverted index. RRF also does not normalize the dense and lexical scores, so score thresholds must not be applied to fused scores.
3. **P1 accuracy:** the confidence gate is a heuristic over retrieval scores, not an answerability test. It can reject an answerable query because a top result is moderately scored, while accepting an unanswerable query when the corpus contains semantically adjacent text. The threshold must be calibrated against labeled queries.
4. **P1 corpus quality:** 700 approximate tokens with 100-token overlap is a defensible starting point for `gemini-embedding-001`, but the chunker is still token-window based. It cannot prevent boilerplate, navigation, testimonials, or repeated page chrome from becoming high-ranking chunks. Ingestion quality is the likely accuracy ceiling.
5. **P1 TTFT:** the first token cannot arrive until website lookup, session resolution, user-message persistence, retrieval, context construction, and history retrieval complete. Generation itself streams correctly, but the pre-generation critical path is too long for a sub-2-second total response unless retrieval is kept very small and warm.

Treat 90-95% as a measured acceptance criterion, not a promise from parameter tuning. Define a representative tenant-specific golden set, measure retrieval recall and answer faithfulness separately, and load-test p50/p95/p99 latency under concurrency.

## Findings and Severity

| ID   | Severity           | Finding                                                                                                                                                     | Primary location                                                                                                        |
| ---- | ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| L-01 | Resolved           | Hybrid keyword-corpus loading is now bounded in both cache branches; a real lexical index is still recommended for recall at scale.                         | [rag_service.py](../backend/services/chat/rag_service.py#L440)                                                          |
| L-02 | Mitigated          | Startup now probes and warns about the Atlas vector index; provisioning remains an Atlas deployment action.                                                 | [database.py](../backend/core/database.py#L325)                                                                         |
| L-03 | P1                 | Hybrid lexical scoring is an in-memory overlap heuristic, not BM25, and it runs over the corpus on the event loop.                                          | [hybrid.py](../backend/repositories/vector/hybrid.py#L201)                                                              |
| L-04 | Resolved in code   | Dense, lexical, and exact-match evidence are now tracked separately and gated by provenance.                                                                | [confidence.py](../backend/services/chat/confidence.py#L29)                                                             |
| L-05 | Partially resolved | The unsafe mixed-score gate is fixed; answerability thresholds still require calibration against labeled production-like data.                              | [confidence.py](../backend/services/chat/confidence.py#L55)                                                             |
| A-01 | Partially resolved | HTML boilerplate is removed before chunking; repeated content and semantic corpus quality still require crawl/data cleanup.                                 | [chunker.py](../backend/services/knowledge/chunker.py#L50)                                                              |
| A-02 | P1                 | Optional near-duplicate and sentence compression is disabled by default and can remove useful repeated facts when enabled.                                  | [config.py](../backend/core/config.py#L479), [context_optimizer.py](../backend/services/chat/context_optimizer.py#L111) |
| A-03 | P1                 | Source diversification occurs after retrieval and can only rescue diversity from the bounded RRF pool; it cannot recover documents excluded by dense top-k. | [rag_service.py](../backend/services/chat/rag_service.py#L678)                                                          |
| L-04 | P2                 | History and persistence are partly overlapped, but the user turn is persisted before retrieval starts, adding a required serial write to TTFT.              | [rag_service.py](../backend/services/chat/rag_service.py#L775)                                                          |
| G-01 | Open               | Gemini streaming and first-token timeouts are implemented correctly, but output limits and retries can exceed a two-second total budget.                    | [gemini.py](../backend/ai/gemini.py#L99)                                                                                |

## 1. Current Request Path

The effective chat sequence is:

```text
website lookup
  -> session resolve/create
  -> persist user message
  -> start history read
  -> optional deterministic query rewrite (may await history)
  -> embed rewritten query
  -> Atlas vector search
  -> full/light corpus read for hybrid keyword search
  -> Python keyword scoring + RRF
  -> optional stored-vector rerank
  -> score gate, deduplication, context budget
  -> await history
  -> prompt construction
  -> streaming generation
  -> persist answer and usage
```

Embedding before vector search is an unavoidable dependency. The avoidable work is the full keyword corpus load after vector search, plus local tokenization/scoring for every chunk. History is correctly started before retrieval, but query rewriting makes retrieval wait for that task on context-dependent questions.

## 2. Latency Audit

### L-01: Hybrid corpus loading is the dominant avoidable cost

`RagService._load_all_chunks` calls `list_chunks_light`, so it avoids transferring embedding vectors, and it now receives a bounded limit in both the retrieval-cache hit and miss branches. This resolves the unbounded application-level read. A plain bounded `find()` is still not relevance-ranked, so it is only a temporary containment measure; Atlas Search text/BM25 or a persistent lexical index is required for scalable hybrid recall.

For a website with thousands of chunks, each question therefore performs:

- a Mongo read of all chunk text and metadata;
- Python tokenization and term-frequency construction for every chunk;
- a full sort of keyword candidates;
- synchronous CPU work on the async event-loop thread.

The configured limit is now honored, but a limit of 50 is not a safe approximation of keyword recall either: use a real lexical index, or explicitly accept the recall tradeoff and benchmark it. Do not treat an arbitrary Mongo document order as lexical relevance.

**Immediate patch pattern:**

```python
keyword_pool_limit = max(
    self._hybrid_candidate_limit,
    effective_top_k * 4,
)
all_chunks = await self._load_all_chunks(
    tenant_id,
    website_id,
    limit=keyword_pool_limit,
)
```

This is a short-term latency containment measure only. MongoDB `find()` without a deterministic sort does not produce a relevance-ranked candidate pool, so it can reduce recall. The production solution is Atlas Search text/BM25 or a tenant-scoped persistent lexical index, queried with the same top-k budget as vector search.

Cache the compact keyword result set or a versioned per-website lexical index. The current retrieval cache stores raw vector results but still loads the corpus on a cache hit, so a repeated question does not avoid hybrid work.

### L-02: Atlas vector index is a deployment prerequisite

`database.py` creates ordinary B-tree indexes for tenant, website, document, and chunk identity. It does not create an Atlas `$vectorSearch` index, which is managed through Atlas Search index administration rather than normal `create_index`. The repository uses index name `default`, path `embedding`, and a configured dimension, but there is no startup check that the definition matches those assumptions.

Provision an index like the following in Atlas, using the actual configured dimension:

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

Validate at deployment time that the index is `READY`, queryable, has the expected dimensions/similarity, and contains every filter field used by `similarity_search`. Keep the exact cosine scan only for development or emergency fallback. It reads the whole tenant corpus and cannot meet the latency target at scale.

`numCandidates=max(top_k * 20, 100)` is a reasonable starting point, but it must be benchmarked. Test 10x, 20x, and 50x candidate multipliers against Recall@K and p95 search latency. For filtered, multi-tenant data, candidate counts often need to be larger when a filter selects a small subset.

### L-03: Reranker and rewrite overhead

The configured reranker fast path is cheap: it uses the already available query vector and stored chunk vectors, so it does not call the embedding provider. Its CPU cost is O(candidate count * dimensions), normally milliseconds for a bounded pool. The legacy path is expensive because it embeds the query and every candidate again; ensure all production construction paths pass `query_embedding` as the current `RagService` path does.

The deterministic query rewrite adds no model call. Its cost is negligible, but it can wait for history and embeds a longer concatenated query. Cap history by tokens rather than characters, preserve entities and the last relevant assistant answer, and record rewrite hit rate plus Recall@K delta. A generic “prepend the last user turn” rewrite can introduce unrelated terms and hurt standalone retrieval.

### L-04: TTFT and serial work

`gemini.py` uses `generate_content_stream`, yields each non-empty delta, and applies a first-token timeout. That is the correct streaming primitive. `rag_service.py` also emits sources before generation, which lets the client render source state early.

The first token still waits for all pre-generation work. Recommended order:

1. Keep website authorization and session binding synchronous and tenant-scoped.
2. Start the history read as soon as the session is resolved.
3. Start user-message persistence as a background task if product semantics allow eventual audit persistence; otherwise retain the write but measure it separately.
4. For standalone questions, do not await history at all before retrieval or prompt construction.
5. For follow-ups, rewrite from a small bounded history snapshot, not the full memory window.
6. Bound context to the smallest tested budget and cap output tokens by answer class.
7. Stream the fallback provider only after a short provider first-token deadline; do not spend multiple retries on a request whose user-facing budget has expired.

The current `llm_max_retries=2`, first-token timeout of 10 seconds, and output budget of 4096 tokens are reliability-friendly but incompatible with a strict sub-2-second p95. Separate the reliability budget from the interactive widget budget and measure p95/p99 before changing defaults.

## 3. Accuracy and Relevance Audit

### A-01: Chunking

The chunker uses an approximate tokenizer, a 700-token target, 100-token overlap, sentence/paragraph preference, heading markers, and a 40-token fragment floor. For `gemini-embedding-001`, this is a defensible baseline. The embedding model supports larger input, but larger chunks dilute focused questions and increase prompt cost; smaller chunks improve pinpoint retrieval but need parent context.

The missing control is semantic document structure, not simply a different number. The chunker does not know whether a paragraph is navigation, a footer, a testimonial, a repeated cookie notice, or the canonical answer. Heading metadata is tracked, but it is only carried into the prompt; it is not used to filter or diversify retrieval.

Recommended ingestion changes:

- Remove boilerplate and repeated DOM regions before chunking using stable DOM selectors and content-density heuristics.
- Preserve `document_id`, URL, heading path, section ordinal, and content hash in every chunk.
- Split first on semantic sections, then pack sections up to approximately 300-600 embedding tokens; do not split tables, lists, or FAQ question-answer pairs.
- Use 30-80 token overlap only when a section must be split. Re-embed a representative corpus after each setting change.
- Add parent-child retrieval: embed focused child chunks, then provide the child plus a short parent-section window to the model.
- Deduplicate exact and near-identical boilerplate across documents before embedding, while retaining a canonical source URL.

The 700/100 baseline should be treated as a hypothesis. Compare 350/50, 500/75, and 700/100 on the golden set using Recall@5, MRR, context precision, prompt tokens, and ingestion cost.

### L-03: Hybrid retrieval is not BM25

`keyword_search` removes a fixed English stop-word list, counts query terms, divides by the square root of document token count, and sorts. Despite the comments, it does not calculate IDF: rare terms and common terms contribute equally. It also has no phrase, field, title/heading weighting, stemming, typo handling, or language-aware analysis.

RRF is appropriate for combining ranked lists, but `keyword_weight` is declared and never applied. More importantly, the final `score` is the original cosine for vector candidates and an RRF score for keyword-only candidates. The reranker improves this for candidates with stored vectors, but any confidence or minimum-score rule must be aware of score provenance. Do not interpret `0.25` as the same relevance signal across those paths.

Recommended production options:

- Use Atlas Search `$search` with a tenant/website compound filter and a `text` operator, then fuse its top 50 with vector top 50 using RRF.
- Or maintain a tenant-scoped lexical index outside the request path and query it directly.
- If keeping the Python implementation temporarily, pre-tokenize chunks at ingestion, calculate corpus IDF once per website version, weight title/heading exact matches, add phrase/entity matches, and run scoring in a worker thread. This is still a stopgap, not a scalable BM25 service.

Candidate policy to benchmark:

```text
dense top_k       = 30
lexical top_k     = 30
RRF pool          = 40-60
reranker input    = 20-40
final context     = 4-8 chunks
```

The present dense `chat_top_k=8` can be too shallow for hybrid recall, while the final context target is much smaller than the candidate pool. Retrieve broadly, rerank narrowly, and send only evidence-bearing chunks.

### A-02: Context optimization and filtering

The always-on filter removes exact duplicates and drops results below `CHAT_CONTEXT_MIN_SCORE`. Optional optimization removes chunks at 0.75 word Jaccard and removes sentences at 0.7 overlap against all earlier retained sentences. It is disabled by default. Enabling it may reduce prompt tokens, but sentence-level Jaccard can incorrectly remove repeated but independently important facts, especially policy statements and list items.

The stronger missing filter is evidence quality. Add these checks before context assembly:

- reject empty, very short, boilerplate, and navigation-only chunks;
- require either a calibrated dense score or a strong lexical/entity/phrase match;
- diversify by source URL and heading before the final context budget;
- cap one repeated fact family to one canonical chunk;
- keep a separate score field: `dense_score`, `lexical_score`, `rerank_score`, and `evidence_reason`;
- record rejected chunks and reasons for offline error analysis.

Illustrative gate:

```python
def usable(result: VectorSearchResult, *, dense_floor: float) -> bool:
    dense = result.dense_score
    lexical = result.lexical_score or 0.0
    strong_exact = result.evidence_reason == "exact_phrase_or_entity"
    return (
        (dense is not None and dense >= dense_floor)
        or (strong_exact and lexical >= 0.20)
    )
```

This requires extending `VectorSearchResult` instead of overloading `score`. The current implementation should at minimum stop using an RRF value as a cosine-like confidence input.

### A-03: Confidence and hallucination control

The prompt in `prompts/rag.py` is materially good: it says to answer only from context, treats crawled content as untrusted data, requires the exact fallback sentence, and the service never calls the model for empty context. Citation cleanup and the post-generation faithfulness heuristic are useful observability controls.

The prompt cannot fix irrelevant context. A non-empty context block still permits a model to answer from an adjacent chunk. The prompt has now been changed to evidence proportionality:

```text
Use only claims directly supported by the reference material.
For every factual claim, add its source marker. If the material supports only
part of the question, answer only that part and say exactly which part is not
found. If no source supports the answer, output exactly:
I couldn't find that information in the website's knowledge base.
Do not infer, generalize, or fill gaps from prior knowledge.
```

Calibrate fallback with labeled positive and negative questions. A better first gate is a combination of: top calibrated score, margin between top-1 and top-2, exact entity/phrase hit, and minimum evidence coverage. A small answerability classifier can be tested later, but it should not be added to the critical path until its latency and false-negative rate are known.

### Query rewriting

The rewrite is deterministic and safe from an added LLM latency perspective. Its conservative trigger list misses many follow-ups (“what about pricing for teams?” is covered, but implicit topic shifts are not) and can prepend an irrelevant user turn. Evaluate rewritten and raw queries side by side. Store only a hashed query and timing in production telemetry; never log the raw question or history.

## 4. Actionable Implementation Plan

### P0: latency, in this order

1. Provision and validate the Atlas vector index with the exact embedding dimension and filter fields.
2. Replace unbounded corpus loading with a real lexical index. As an interim guard, pass an explicit deterministic limit and measure Recall@K loss.
3. Cache a versioned compact lexical index or keyword result set; invalidate it after ingestion completes.
4. Keep hybrid candidate work bounded and off the event loop. Do not transfer embeddings for lexical scoring.
5. Add a request budget: retrieval deadline, first-token deadline, and provider fallback deadline. Track deadline-triggered fallbacks separately.

### P1: accuracy

1. Build a tenant-specific golden set with answerable, unanswerable, multi-hop, exact-entity, typo, multilingual, and prompt-injection cases.
2. Clean boilerplate and repeated page chrome; add section path and parent metadata; re-embed the changed corpus.
3. Benchmark chunk sizes and overlap rather than tuning by intuition.
4. Retrieve dense and lexical candidates broadly, rerank a bounded union, diversify by source and section, then gate evidence with calibrated score provenance.
5. Enable context optimization only after measuring answer recall; prefer structural deduplication over generic sentence deletion.
6. Tighten the prompt to require claim-level support and evidence-proportional answers.

### P2: observability and operations

Add structured metrics by tenant and website (without content):

- embedding cache hit rate and latency;
- vector search latency, candidate count, index name, and fallback-scan count;
- lexical search latency and corpus/index version;
- rerank input/output count and latency;
- context accepted/rejected counts and rejection reasons;
- TTFT, total stream time, generation tokens, provider/fallback attempts;
- Recall@K, MRR, nDCG@K, answer faithfulness, citation validity, and fallback precision/recall.

Alert when any production request uses the brute-force scan, when the Atlas index is not queryable, when p95 TTFT exceeds the widget budget, or when embedding identity mismatches occur.

## 5. Benchmark and Acceptance Protocol

The existing [evaluate_rag.py](../scripts/evaluate_rag.py) is a useful smoke test, but its in-memory fake retrieval and constant synthetic knowledge base cannot establish production accuracy or latency. It currently reports recall/MRR, fallback rates, confidence, and latency; extend it with p95 computed using a percentile method, not a direct list index that can exceed the final element for small samples.

Use the existing benchmark modules:

- [retrieval_comparison.py](../backend/benchmark/retrieval_comparison.py) for vector, keyword, and hybrid side-by-side results;
- [retrieval_metrics.py](../backend/benchmark/retrieval_metrics.py) for Precision@K and expected-source accuracy;
- [evaluation.py](../backend/benchmark/evaluation.py) for answer length, truncation, citations, and context coverage;
- [golden_dataset.json](../scripts/golden_dataset.json) as the seed set, expanded with tenant-specific expected sources and answer fragments.

Run four experiments against the same frozen corpus and query set:

| Experiment | Retrieval                       | Rerank          | Context                  | Purpose                                          |
| ---------- | ------------------------------- | --------------- | ------------------------ | ------------------------------------------------ |
| Baseline   | current vector/hybrid           | current         | current                  | establish a reproducible reference               |
| Latency    | indexed dense + bounded lexical | stored-vector   | 4-8 chunks               | isolate request-time improvements                |
| Retrieval  | dense 30 + lexical 30 + RRF     | bounded union   | 4-8 chunks               | measure Recall@K/MRR and source precision        |
| Accuracy   | best retrieval                  | calibrated gate | optimized, evidence-only | measure answer faithfulness and fallback quality |

Acceptance gates should be reported separately:

- **Retrieval:** Recall@5 >= 95% on answerable cases; MRR and nDCG tracked by query type.
- **Answer:** >= 90% grounded/correct answers under human or judge-reviewed labels; <= 5% unsupported-answer rate on negative cases.
- **Fallback:** high fallback precision on unanswerable queries and low false-fallback rate on answerable queries.
- **Latency:** p95 retrieval plus prompt preparation under 500 ms, p95 TTFT under 1.2 s, and p95 end-to-end stream completion under 2 s for short answers. Report cold-cache and warm-cache separately.
- **Isolation:** every retrieval and lexical query is tenant and website scoped; add cross-tenant regression tests.

Benchmark under concurrency representative of the widget, not only one sequential CLI run. Record provider, model, embedding identity, index readiness, cache state, corpus size, and query class with every run so results are comparable.

## Conclusion

The strongest immediate win is to eliminate unbounded hybrid corpus work and ensure the Atlas vector index is real, ready, and dimension-compatible. The strongest accuracy win is corpus hygiene plus calibrated evidence gating; changing `top_k` or adding more prompt text will not repair repeated boilerplate and score-scale confusion. Once those are fixed, the existing streaming Gemini client, embedding cache, stored-vector reranker, tenant filters, and benchmark foundation are sufficient for an iterative path toward the stated targets.
