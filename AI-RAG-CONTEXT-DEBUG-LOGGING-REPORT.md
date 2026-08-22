# RagService Context Building — Debug Logging

## Problem

Production needed visibility into what context `_build_context()` assembles for
each chat request — the question, which chunks survive dedup/filtering, and what
text actually gets sent to the LLM. No such logging existed; the only signal was
the aggregate `chat_prompt` info line (item count + char totals).

## Change

Added temporary `logger.debug()` statements in `RagService.stream_answer()`
immediately after `_build_context()` returns (line ~578).

### What is logged

| Field            | Source                          | Notes                                 |
| ---------------- | ------------------------------- | ------------------------------------- |
| `question`       | `stream_answer` parameter       | Full question text (`%r` repr)        |
| `context_count`  | `len(context_items)`            | Number of items after dedup + budget  |
| `idx`            | Loop index                      | 0-based position in final context     |
| `chunk_id`       | `sources[idx]["chunk_id"]`      | Original chunk ID from knowledge base |
| `citation`       | `sources[idx]["citation"]`      | 1-based citation number               |
| `score`          | `sources[idx]["score"]`         | Final RRF / vector score              |
| `url`            | `context_items[idx].url`        | Source page URL                       |
| `title`          | `context_items[idx].title`      | Source page title                     |
| `chunk_text_300` | `context_items[idx].text[:300]` | First 300 chars of context text       |

### Guard

All logging is behind `if logger.isEnabledFor(logging.DEBUG):`, which evaluates
to `False` unless `DEBUG=true` is set in the environment (see
`backend/core/logging.py:84`). In production with `debug=false`, the guard
short-circuits — zero overhead, zero string formatting, zero function calls.

### Example output (DEBUG=true)

```
DEBUG webchat_ai chat_context_build question='What courses does Indira offer?' context_count=3
DEBUG webchat_ai chat_context_chunk idx=0 chunk_id=abc123 citation=1 score=0.8543 url=https://indira.ac.in/courses title=Courses | Indira University chunk_text_300='Indira University offers Bachelor of Arts (BA)...'
DEBUG webchat_ai chat_context_chunk idx=1 chunk_id=def456 citation=2 score=0.7211 url=https://indira.ac.in/admissions title=Admissions | Indira University chunk_text_300='The admission process for the 2025-26...'
```

## Files Changed

| File                                   | Lines   | Change                                             |
| -------------------------------------- | ------- | -------------------------------------------------- |
| `backend/services/chat/rag_service.py` | 578-593 | Added debug logging block after `_build_context()` |

No logic, no scoring, no retrieval changes. The debug block is purely additive
and conditionally executed.

## Test Results

```
pytest tests/ -q              → 1360 passed, 2 skipped
ruff check backend/            → All checks passed
mypy backend/                  → Success: no issues found in 182 source files
```

## Removal

This logging is intended as temporary production diagnostics. When no longer
needed, remove the `if logger.isEnabledFor(logging.DEBUG):` block at
`rag_service.py:578-593`.
