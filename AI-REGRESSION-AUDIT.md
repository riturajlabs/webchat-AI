# AI Regression Audit

Date: 2026-08-19  
Scope: read-only investigation of the AI/RAG, streaming, Docker, and widget changes in the working tree.

## 1. Executive Summary

The backend serving port 8000 is the `webchat-api` Docker container. It is healthy, has no source-code bind mount, and its hashes for the audited AI files exactly match the current checkout. The deployed process is therefore running the current AI code, not an older image or an unmodified local server.

The available evidence does not confirm a current backend outage: `/health` responds successfully, the focused Python suite passes (117 tests), mypy passes for the audited modules, and the recent API log tail contains no matching traceback, provider, Redis, Mongo, or SSE error signature. The generic widget message is intentional: unknown SSE error codes are mapped to the user-facing `server` message in `apps/widget/src/core/errors.ts`.

There is one confirmed production-code defect and one configuration risk:

1. **P1: hybrid retrieval is not compatible with the production vector repository.** `RagService._load_all_chunks()` reads `self._vector.chunks`, but `VectorRepository` declares no `chunks` member and `MongoVectorRepository` has no such member. Enabling hybrid search in a real request will raise `AttributeError`, which becomes an SSE `INTERNAL_ERROR` and can appear as the generic widget error.
2. **P1: Docker compose does not forward several new AI settings.** In particular, `ENABLE_HYBRID_SEARCH` and `HYBRID_RRF_K` are absent from the backend environment block, as are newer context, cache, retry, and SSE-buffer settings. The container silently uses `Settings` defaults rather than values in the selected env file.

The live container currently reports `GENERATION_PROVIDER_ORDER=["gemini","groq","openrouter"]`, `EMBEDDING_PROVIDER_ORDER=["gemini","jina","cohere"]`, `EMBEDDING_DIMENSIONS=1024`, `ENVIRONMENT=production`, and `LOCAL_PRODUCTION_TEST=true`. Hybrid was not present in the container environment and therefore resolves to the default `false`. The hybrid defect is latent unless enabled through another deployment mechanism or an explicit constructor override.

## 2. Environment Verification

### Repository state

- Branch: `main`, HEAD `a6322d8` (`fix: complete production audit hardening and verification`).
- 43 changed paths are present: 25 modified tracked files and 18 untracked files.
- The working tree contains 25 modified tracked files, including the widget stream, API/SSE, configuration, AI provider, vector repository, RAG service, and tests.
- Untracked AI-related material includes `backend/repositories/vector/hybrid.py`, `backend/services/chat/retrieval_strategy.py`, `backend/benchmark/`, performance scripts, evaluation reports/data, and benchmark/retrieval tests.
- `git diff --check` is clean.
- No commit or code edit was made by this audit. This report is the only newly created audit artifact.

### Docker and port ownership

- `webchat-api` is healthy and maps `0.0.0.0:8000 -> 8000`.
- MongoDB, Redis, worker, dashboard, widget, and Mailpit are running and healthy according to `docker compose ps`.
- Port 8000 is owned by Docker's published port; no separate host Uvicorn process was found.
- The API container has no mounts. Its image was created at `2026-08-19T11:46:19Z` and the current container started at `2026-08-19T14:14:03Z`.
- SHA-256 hashes for `rag_service.py`, `retrieval_strategy.py`, `hybrid.py`, `router.py`, `gemini.py`, and `sse.py` match between the checkout and `/app` in the container. Current local AI changes are loaded in Docker.
- A local `uv run python` import check succeeded (`backend.main:app` imports and settings instantiate). A 15-second Uvicorn probe on port 8001 timed out during initialization, so startup latency was not fully measured; this is not a confirmed startup failure.

### Configuration findings

`docker/compose.yml` passes many environment values but does not pass all fields introduced in `backend/core/config.py`. Missing or drift-prone values include:

- `ENABLE_HYBRID_SEARCH`, `HYBRID_RRF_K`
- `CHAT_CONTEXT_MAX_CHARS`, `CHAT_CONTEXT_MIN_SCORE`
- `EMBEDDING_CACHE_SIZE`, `EMBEDDING_CACHE_TTL_SECONDS`
- `CHAT_RETRIEVAL_CACHE_SIZE`, `CHAT_RETRIEVAL_CACHE_TTL_SECONDS`
- `CHAT_EMBEDDING_MAX_RETRIES`, `GENERATION_FIRST_TOKEN_TIMEOUT_SECONDS`
- `SSE_BUFFER_MS`, `GEMINI_EMBEDDING_DIMENSIONS`

This is a deployment/configuration mismatch, not proof that the current incident is caused by hybrid search. The live container has hybrid disabled by omission/default.

## 3. Request-Path Audit

### Widget -> route -> SSE

`apps/widget/src/stream/client.ts` obtains a widget token, POSTs `/chat`, retries one 401, parses SSE, and treats `done`/`error` as terminal. Unknown backend SSE codes are mapped to `server` in `apps/widget/src/core/errors.ts`, whose user message is `Sorry, I couldn’t process that. Please try again.` This explains the generic symptom when the backend emits `INTERNAL_ERROR`, `GENERATION_FAILED`, `GENERATION_UNAVAILABLE`, or `EMBEDDING_UNAVAILABLE`.

`backend/api/routes/widget.py` and `backend/api/routes/chat.py` validate the request, construct the RAG stream, and pass it through `stream_answer_with_usage`. The route contracts remain compatible: the stream is HTTP 200 with SSE error frames for pipeline failures.

`backend/api/sse.py` preserves event serialization and disconnect checks. The new buffered path coalesces `message` deltas and flushes non-message events immediately. One residual behavior risk is that its `finally` block yields a buffered partial frame even after disconnect; this is covered by tests but weakens the documented guarantee that no further output is sent after disconnect. It does not explain a generic error by itself.

### RAG service

`backend/services/chat/rag_service.py` performs the expected sequence: website lookup, sanitization, session resolution, user persistence, retrieval, context/history loading, `sources`, generation deltas, assistant persistence, usage rollup, and `done`.

- `_retrieve()` now returns seven values, adding embedding/retrieval cache-hit flags and `RetrievalMetricsInfo`. Its call site was updated consistently.
- Retrieval cache entries contain the vector and raw vector results; strategy application occurs after cache lookup. Cache corruption is ignored and falls back to a fresh retrieval.
- Vector-only strategy passes results through unchanged, preserving baseline behavior when hybrid is false.
- Hybrid strategy causes `_load_all_chunks()` to run after vector search. `_load_all_chunks()` accesses `self._vector.chunks` at `backend/services/chat/rag_service.py:671`, but the protocol and Mongo implementation do not expose that attribute. This is the confirmed hybrid failure path.
- Context filtering still applies `chat_context_min_score`. Hybrid scores are rescaled, but rescaling the top result to 1.0 changes the meaning of the cosine-score threshold and can admit weak results. This is a retrieval-quality risk, not a confirmed crash.
- Generation and persistence exceptions are converted to stable SSE error events. Non-`AppError` exceptions intentionally become `INTERNAL_ERROR`, which the widget displays generically.

### Retrieval strategy and hybrid search

`backend/services/chat/retrieval_strategy.py` has a compatible synchronous strategy protocol and correct vector pass-through. `HybridRetrievalStrategy` invokes keyword search and RRF, then rescales scores. `backend/repositories/vector/hybrid.py` handles empty rankings and keyword misses, but `keyword_weight` is declared and never used. The keyword scorer also scans every candidate supplied by `_load_all_chunks`; a large site can add a full collection read and CPU ranking to every uncached question.

RRF itself handles empty lists, duplicate chunk IDs, and rank ordering. No empty-result crash was found in the focused tests.

### Provider generation and embedding

`backend/ai/router.py` adds pre-first-token generation fallback and atomic embedding fallback. `backend/ai/gemini.py` awaits the SDK stream, applies model/config/timeouts, and normalizes SDK exceptions. `GenerationUnavailableError` inherits `GenerationError`, so first-token timeout fallback is compatible with the router's catch clause.

Observed risks:

- `_fallback_count` is cumulative on a client instance, so `fallback_attempts` is not a per-request metric after the first failed request. This distorts observability but does not fail generation.
- A provider that emits some deltas and then fails is deliberately not retried. That avoids duplicated answers but surfaces an SSE error after partial output; the widget marks the stream failed.
- Provider and dimension configuration is validated at settings/import time, and the import check passed locally.

### Prompt and persistence

Question sanitization remains before embedding and generation. Context is delimited as untrusted data, the model is not called with empty retrieval, and usage/token/latency fields are persisted after a complete answer. No backward-incompatible prompt or message interface was found.

## 4. Runtime Checks

| Check                        | Result                                                                     | Interpretation                                                                                                                       |
| ---------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Docker compose service state | Passed                                                                     | API and dependencies healthy                                                                                                         |
| Port 8000                    | Passed                                                                     | Published by `webchat-api`                                                                                                           |
| `/health`                    | Passed                                                                     | Live API responds                                                                                                                    |
| Source hash comparison       | Passed                                                                     | Docker contains current audited code                                                                                                 |
| Backend import/settings      | Passed                                                                     | No immediate import/config crash                                                                                                     |
| Focused pytest suite         | Passed: 117 tests                                                          | RAG/router/SSE/hybrid/retrieval behavior covered by current tests                                                                    |
| Focused mypy                 | Passed: 19 files                                                           | No reported typing errors                                                                                                            |
| Ruff focused slice           | Failed: 5 test-only findings                                               | Import ordering and two line-length findings in `tests/test_retrieval_strategy.py`; no production Ruff finding in the selected slice |
| Host `pytest` command        | Initially unavailable                                                      | `uv run pytest` supplied the project environment and passed                                                                          |
| API log scan, last 24 hours  | No matching traceback/provider/Redis/Mongo/SSE error found in sampled tail | No runtime traceback can currently be correlated to the symptom                                                                      |
| Uvicorn 15-second probe      | Timed out                                                                  | Initialization exceeded the probe window; import check passed, so this is inconclusive rather than a startup failure                 |

## 5. Before/After Risk Table

| File                                            | Change                                                                         | Risk | Problem?                                                                                                                | Fix Required                                                              |
| ----------------------------------------------- | ------------------------------------------------------------------------------ | ---: | ----------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `backend/services/chat/rag_service.py`          | Added caches, timing fields, retrieval strategy, hybrid hook, provider metrics |   P1 | Yes: hybrid reads nonexistent `vector.chunks`; new cache/strategy paths increase failure surface                        | Yes, before enabling hybrid                                               |
| `backend/services/chat/retrieval_strategy.py`   | Added vector/hybrid strategy abstraction                                       |   P1 | Interface is locally coherent, but its hybrid dependency is not repository-compatible                                   | Yes, add a repository-owned tenant-scoped read API or disable until wired |
| `backend/repositories/vector/hybrid.py`         | Added keyword ranking and RRF                                                  |   P2 | No crash in tests; full-candidate scan and unused `keyword_weight` risk latency/quality                                 | Recommended before production enablement                                  |
| `backend/repositories/vector/mongodb.py`        | Added Atlas fallback/probing behavior                                          |   P2 | Local fallback is intentional; empty search/index probing can hide deployment index problems                            | Verify Atlas index and monitor fallback logs                              |
| `backend/ai/router.py`                          | Added provider fallback and latency metrics                                    |   P2 | Generation behavior is compatible; cumulative fallback counter makes metrics inaccurate                                 | Recommended, not chatbot-blocking                                         |
| `backend/ai/gemini.py`                          | Added SDK stream await, token timeout, generation config                       |   P1 | A first-token timeout can produce provider fallback/error if thresholds are too aggressive; no current runtime evidence | Verify provider latency and timeout values                                |
| `backend/api/sse.py`                            | Added disconnect-aware buffering and billing recording                         |   P2 | Buffered `finally` can yield after disconnect; otherwise tests pass                                                     | Harden disconnect finalization                                            |
| `backend/api/routes/chat.py`                    | Routed dashboard stream through usage/buffer adapter                           |   P2 | Adds billing gate and buffering to the existing route                                                                   | Verify plan limits and event ordering in an authenticated E2E test        |
| `backend/api/routes/widget.py`                  | Routed widget stream through same adapter                                      |   P2 | Same new gate/buffering path applies to public chat                                                                     | Verify widget E2E against deployed bundle                                 |
| `backend/core/config.py`                        | Added hybrid, cache, latency, and buffering settings                           |   P1 | Settings are not all forwarded by compose                                                                               | Yes, synchronize compose/env contract                                     |
| `backend/prompts/rag.py`                        | Prompt/sanitization refinements                                                |   P2 | No interface break found; prompt behavior can change answer style/length                                                | Validate against golden evaluation set                                    |
| `backend/ai/gemini.py`, `backend/ai/router.py`  | Provider names/usage metrics                                                   |   P2 | Error codes remain stable through `AppError` mapping                                                                    | Monitor actual provider responses                                         |
| `apps/widget/src/stream/client.ts`              | SSE terminal handling, retry, timing                                           |   P2 | Unknown backend codes intentionally become generic `server` message                                                     | Add explicit safe mappings for expected AI failure codes if desired       |
| `apps/widget/src/stream/chat.ts`                | Streaming state/stop/source handling                                           |   P3 | No failure found in inspected state transitions                                                                         | Existing tests are adequate for this change                               |
| `tests/*` and `apps/widget/src/stream/*.test.*` | Added regression coverage and fakes                                            |   P3 | Focused tests pass; new retrieval test file has five Ruff findings                                                      | Clean test lint before CI                                                 |

## 6. Confirmed and Suspected Issues

### Confirmed

- **P1 hybrid runtime crash when enabled:** `backend/services/chat/rag_service.py:671` accesses an attribute absent from `backend/repositories/vector/base.py:21-35` and `backend/repositories/vector/mongodb.py`. The exception is caught by `_retrieve()` and returned as `INTERNAL_ERROR` through SSE.
- **P1 compose configuration drift:** `backend/core/config.py` defines new AI settings that are not represented in `docker/compose.yml`'s `x-backend-env`. Values supplied in `.env.production` can be silently ignored.
- **P2 widget generic error mapping:** `apps/widget/src/core/errors.ts:148-151` maps all unrecognized SSE codes to `server`. This is expected behavior, but it prevents users from distinguishing generation, embedding, retrieval, and internal failures.
- **P2 test lint failure:** `tests/test_retrieval_strategy.py` has five Ruff findings. These do not affect runtime but can fail a strict CI lint job.

### Suspected or residual risks

- Provider/API failures may be occurring intermittently outside the sampled Docker log window; no traceback is currently available to prove this.
- A real Atlas vector index mismatch or dimension mismatch could cause retrieval failures; the local Mongo fallback can make development appear healthy while production Atlas behaves differently.
- Hybrid full-candidate loading may cause latency spikes even after the attribute contract is repaired.
- SSE buffering may emit a final buffered frame after disconnect.
- The live widget may use a stale built asset independently of the backend source; source inspection found generated `apps/widget/dist` bundles, but no browser/E2E request was run in this read-only audit.

## 7. Safe Recovery Plan

1. **Restore stable chatbot functionality.** Keep `ENABLE_HYBRID_SEARCH=false`; verify an authenticated dashboard and widget chat request end-to-end. Capture the exact SSE `error.code`, request ID, provider, and stage timing for any failure.
2. **Verify RAG correctness.** Confirm website ownership, session resolution, embedding dimensions, vector index availability, non-empty retrieval, context construction, and assistant persistence using a known-good website and question.
3. **Verify retrieval quality.** Run the existing golden/evaluation tests against vector-only retrieval. Confirm no-context fallback is only used for an actually empty or irrelevant result set.
4. **Verify latency instrumentation.** Enable timing only in a controlled environment, validate `done.timing`, provider TTFT, cache hit/miss, and persistence metrics, and fix the cumulative fallback counter before relying on dashboards.
5. **Enable hybrid safely.** First add a tenant-scoped `list_chunks`/keyword-search repository method to the abstraction and Mongo implementation, then test large, empty, duplicate, and cross-tenant datasets. Enable hybrid for a canary only after latency and score-threshold behavior are measured.
6. **Improve AI accuracy.** Compare vector and hybrid rankings against the benchmark/golden set, tune RRF/keyword scoring and context thresholds, then promote the configuration gradually.

No fixes are implemented in this audit. The first production action should be configuration and observability verification, followed by a targeted repository contract fix for hybrid search; broad refactoring or feature removal is not warranted by the current evidence.
