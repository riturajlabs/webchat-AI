# Phase 12.6 — Chat Latency Optimization: Before/After Report

Date: 2026-08-16

## Problem

A simple question could take 2-5 minutes because a slow or hung embedding /
generation provider was retried 5x with a 60 s timeout each, history was
loaded sequentially after retrieval, there was no total context budget, no
retrieval-result cache, and no bound on the time to the first answer token.

## Changes

| Area                                  | Before                           | After                                                                              |
| ------------------------------------- | -------------------------------- | ---------------------------------------------------------------------------------- |
| Provider timeout (all)                | `AI_PROVIDER_TIMEOUT_SECONDS=60` | `10`                                                                               |
| Generation stall bound                | `GENERATION_TIMEOUT_SECONDS=60`  | `30` (per-chunk), + new `GENERATION_FIRST_TOKEN_TIMEOUT_SECONDS=10`                |
| Embedding timeout / retries / backoff | `60 s` / `5` / `500 ms`          | `10 s` / `3` / `300 ms`                                                            |
| Chat embedding retries                | 5                                | 1 (`CHAT_EMBEDDING_MAX_RETRIES`)                                                   |
| First-token stall                     | unbound                          | 10 s -> `GenerationUnavailableError` so the router falls back to the next provider |
| History load                          | sequential after retrieval       | started in parallel with embedding+search (`asyncio.create_task`)                  |
| Retrieval cache                       | none                             | bounded LRU, `(website, question)` keyed, 15-min TTL, answers never cached         |
| Context budget                        | unlimited                        | `CHAT_CONTEXT_MAX_CHARS=12000` (+ optional `CHAT_CONTEXT_MIN_SCORE` filter)        |
| Latency data                          | not recorded                     | per-stage ms persisted on every assistant message + `rag_timing` log               |
| Performance API                       | response-time only               | + `avg_embedding_ms` / `avg_retrieval_ms` / `avg_generation_ms`                    |

## Load test

`k6 run scripts/perf/load-test.js` against the isolated perf API (`:8001`,
mock AI providers, native MongoDB, seeded dataset: 3 websites, 150 chunks).
**10 concurrent users, 3 minutes sustained** (`PERF_SCENARIO=sustained10vu`),
5-question pool with session reuse.

| Metric              | Before     | After      | Delta |
| ------------------- | ---------- | ---------- | ----- |
| Stream duration avg | 779 ms     | 623 ms     | -20%  |
| Stream duration p95 | 1270 ms    | 908 ms     | -28%  |
| TTFB avg            | 251 ms     | 199 ms     | -21%  |
| TTFB p95            | 446 ms     | 333 ms     | -25%  |
| Throughput          | 12.8 req/s | 16.0 req/s | +25%  |
| Error rate          | 0.00%      | 0.00%      | -     |

Notes:

- Measured wins come from the retrieval cache (the repeat-question pool skips
  embedding + search) and the context cap. The "before" run used the pre-
  optimization knobs: no retrieval cache, no context budget, 60 s timeouts.
- The mock providers never hang, so the fail-fast timeouts / retry reductions
  (the biggest real-world win: 2-5 min worst case -> seconds) are not
  observable in this harness; they are covered by unit tests
  (`test_gemini_client.py`, `test_config.py`).

## Verification

- `pytest`: 909 passed, 1 skipped
- `ruff check backend`: clean
- `mypy backend/`: clean
- k6 thresholds (`chat_error_rate < 0.01`): passed

## Files touched

Backend: `backend/services/chat/rag_service.py`, `backend/ai/gemini.py`,
`backend/ai/registry.py`, `backend/api/deps.py`, `backend/models/chat_message.py`,
`backend/core/config.py`, `backend/repositories/analytics_repository.py`,
`backend/schemas/analytics.py`, `backend/services/analytics/analytics_service.py`,
`backend/api/routes/analytics.py`, `.env.example`.
Perf harness: `scripts/perf/load-test.js`, `scripts/perf/seed.py`.
Tests: `tests/test_rag_service.py`, `tests/test_gemini_client.py`,
`tests/test_ai_registry.py`, `tests/test_config.py`, `tests/test_analytics_api.py`,
`tests/fakes.py`, `tests/analytics_helpers.py`.
