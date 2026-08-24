# AI RAG Retrieval Fix Report

## Executive Summary

The irrelevant retrieval was caused by hybrid keyword search being allowed to search the full website candidate set and introduce documents that were not present in the semantic vector results. RRF then fused those unrelated keyword-only documents with the vector ranking. With a single crawled website, this allowed generic documentation chunks to compete directly with the semantically relevant chunk.

## Root Cause

The production path loaded up to the configured hybrid candidate limit (`50`) into `all_chunks` and passed that collection to `HybridSearcher`. `keyword_search()` ranked those chunks independently, and `reciprocal_rank_fusion()` merged the keyword ranking with the vector ranking by chunk ID. A chunk could therefore enter the final result solely because it shared query terms, even when its vector similarity was not in the top results.

RRF emits rank-based scores rather than preserving cosine magnitude. The hybrid strategy now uses RRF only for ordering and restores each candidate's original vector score before context filtering and confidence evaluation. This prevents a weak nearest neighbor from becoming an artificial `1.0` solely because it ranked first in the fused list.

## Implemented Fix

- Restricted keyword scoring to `vector_results` in `HybridSearcher`.
- Kept `all_chunks` as a compatibility parameter, but it no longer expands the retrieval candidate set.
- Removed full-site chunk loading from both normal and cached chat retrieval paths.
- Updated retrieval metrics so `keyword_result_count` and `hybrid_candidate_count` describe the vector candidate set.
- Added debug-only retrieval diagnostics containing, for vector, keyword, and final top five results:
  - `chunk_id`
  - score
  - source URL
  - title
- Diagnostics never include chunk text.
- Added a regression test proving a keyword-only chunk cannot enter fused results.

## Resulting Pipeline

```text
Question
  -> embedding
  -> MongoDB Atlas vector search
  -> top vector candidates
  -> keyword reranking of those candidates only
  -> RRF fusion
  -> reranking
  -> context builder
  -> LLM
```

For the reported production pattern, the keyword candidate count should now track the vector result count (for example, `5` rather than `50`), and keyword search cannot replace a vector hit with an unrelated website chunk.

## Validation

- `uv run pytest tests/`: **1417 passed, 3 skipped**
- `uv run ruff check backend/`: **passed**
- `uv run mypy backend/`: **passed**
- Focused hybrid, retrieval strategy, and RAG service tests: **passed**

Three existing test warnings remain from the Gemini client fixtures and one Starlette/httpx deprecation warning; they do not fail the suite.

## Explicitly Unchanged

- Gemini embeddings and dimensions
- MongoDB schema and Atlas vector index
- Crawler data and ingestion
- LLM provider
- Prompts
- RRF constant and score normalization behavior
- RRF constant; RRF ordering remains unchanged, but score normalization was removed
