# AI RAG MongoDB Vector Inspection Report

## Scope

This change adds temporary DEBUG-only diagnostics immediately after the MongoDB vector-search call in `RagService._retrieve()`. It does not modify retrieval behavior.

## Logged Diagnostics

For each vector search request, DEBUG logs now include:

- user question
- raw vector result count
- each raw result's chunk ID
- vector score returned by MongoDB Atlas
- title
- source URL
- first 200 characters of chunk text

The diagnostics are emitted before hybrid retrieval, RRF fusion, reranking, context filtering, or score normalization. Chunk previews are limited to 200 characters and are emitted only when the application logger is at DEBUG level, which is controlled by the existing debug logging configuration.

## Behavior Unchanged

- MongoDB Atlas `$vectorSearch` pipeline
- tenant and website filtering
- embedding provider and dimensions
- `top_k`, `numCandidates`, and thresholds
- hybrid candidate restriction
- RRF fusion
- reranking
- context construction

The Mongo repository API was left unchanged because it receives the query embedding, not the user question. The service call site is the narrowest boundary that has both the raw MongoDB results and the original question.

## Interpretation Guide

For an unrelated question, inspect the raw entries from:

```text
mongodb_vector_search_debug
mongodb_vector_search_result
```

If high-ranked unrelated chunks have low or tightly clustered vector scores, Atlas is returning low-confidence nearest neighbors and the existing score floor can be evaluated separately. If the scores are high despite unrelated content, inspect embedding consistency, Atlas index configuration, and the stored document-to-embedding relationship. If results violate the expected tenant or website scope, investigate the Atlas filter/index configuration immediately.

These logs are intentionally placed before later ranking stages so they distinguish MongoDB vector behavior from hybrid or reranker behavior.

## Validation

- Focused logging and Mongo tests: passed
- Full test suite: run after this report change
- Ruff and mypy: run after this report change
