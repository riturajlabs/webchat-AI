# RAG Confidence Scoring & Hallucination Prevention — Implementation Report

## Overview

Added a pre-generation confidence check that evaluates retrieval quality _before_
the LLM is called. When retrieved context scores fall below a configurable
threshold, the pipeline returns a safe fallback response instead of generating
an answer — preventing hallucinations when the knowledge base lacks relevant
content.

## Problem

Without confidence gating, the LLM receives weak/irrelevant context and may
generate plausible-sounding but unsupported answers (hallucinations). The
existing post-generation faithfulness check only _warns_ — it never blocks.

## Solution

### Confidence Calculator

New module: `backend/services/chat/confidence.py`

Computes a 0.0–1.0 score from existing retrieval/rerank scores using three
signals:

| Signal     | Weight | What it measures                              |
| ---------- | ------ | --------------------------------------------- |
| Mean score | 0.50   | Average relevance of top results              |
| Hit ratio  | 0.30   | Fraction of results above `min_score`         |
| Peak score | 0.20   | Highest individual score (top result quality) |

```
confidence = 0.50 × mean + 0.30 × hit_ratio + 0.20 × peak
```

No LLM calls, no external dependencies — pure arithmetic on existing scores.

### Integration Point

The check runs in `stream_answer()` **after** `_retrieve()` but **before**
context building and generation:

```python
retrieval_scores = [r.score for r in results]
if self._confidence_check_enabled:
    confidence_score = calculate_confidence(retrieval_scores, min_score=self._min_score)
    if confidence_score < self._confidence_threshold:
        # Return safe fallback — never call the LLM
        yield fallback_response
        return
```

### Feature Flag

```python
enable_rag_confidence_check: bool = False  # opt-in, off by default
rag_confidence_threshold: float = 0.3  # minimum to proceed
```

**Backward compatible**: disabled by default, zero overhead when off.

## Files Changed

| File                                   | Change                                                                                  |
| -------------------------------------- | --------------------------------------------------------------------------------------- |
| `backend/services/chat/confidence.py`  | **New** — confidence score calculator                                                   |
| `backend/core/config.py`               | Added `enable_rag_confidence_check` + `rag_confidence_threshold`                        |
| `backend/services/chat/rag_service.py` | Confidence check in `stream_answer()`; `confidence_score` in timing dict + logger extra |
| `tests/test_confidence.py`             | **New** — 12 unit tests for the calculator                                              |
| `tests/test_rag_accuracy.py`           | 8 integration tests (high/low/disabled/custom threshold)                                |
| `tests/test_rag_service.py`            | Added `confidence_score` to expected timing keys                                        |

## Test Results

- **12 confidence calculator unit tests** — all passing
- **8 confidence integration tests** — all passing
- **1360+ full suite tests** — all passing (2 skipped)
- **ruff** — clean
- **mypy** — clean

## Design Decisions

1. **Pre-generation, not post-generation**: The faithfulness check already
   exists post-generation as a warning. Confidence gating is _pre-generation_ and
   _blocking_ — it prevents the LLM call entirely, saving latency and tokens.

2. **Weighted formula**: Mean score captures overall relevance; hit ratio
   captures how many results pass the context filter; peak score captures the
   best single result. Equal weighting (50/30/20) balances these signals
   without over-indexing on any one.

3. **Threshold of 0.3**: Conservative default — only blocks clearly
   irrelevant retrieval. Operators can raise it for stricter gating.

4. **No LLM dependency**: The confidence check is pure math. No extra API
   calls, no latency, no cost.
