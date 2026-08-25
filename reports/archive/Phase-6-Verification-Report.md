# Phase 6 Verification Report — RAG Pipeline

**Date:** 2026-08-09
**Scope:** Read-only production-readiness audit of Phase 6 (RAG Pipeline) against `00-AI-Development-Rules.md`, `docs/01-PRD.md`, `docs/02-TRD.md`, `docs/03-App-Flow.md`, `docs/05-Backend-Schema.md`, `docs/06-Implementation-Plan.md`, `docs/07-Architecture-Decisions.md` (ADR-004/005/008). **No application code was modified.**
**Baseline:** `main` = `d1d3e85`; all Phase 5 + Phase 6 work remains uncommitted.

## Recommendation

**READY FOR PHASE 7** (completion ≈ 95%).

All automated gates are green (302 backend tests, ruff, mypy, 31 frontend tests, lint, typecheck, build). The RAG pipeline is sound: always retrieve-before-generate, tenant-scoped retrieval, versioned prompts, Gemini SSE streaming, token capture, and a hard hallucination guard. **Live E2E is BLOCKED** by missing infrastructure (no MongoDB/Redis/worker, local Mongo lacks Atlas `$vectorSearch`). One Medium functional bug (conversation-memory ordering, F1) and four Low items (F2–F5) are recorded below; none block Phase 7 (dashboard), but F1 should be fixed before the widget-facing chat API (Phase 8) or the conversations page relies on memory.

---

## Verification results (fresh runs, project venv `.venv/bin`)

| Check          | Command                        | Result                                      |
| -------------- | ------------------------------ | ------------------------------------------- |
| Lint           | `ruff check backend tests`     | All checks passed                           |
| Types          | `mypy backend`                 | Success: no issues found in 92 source files |
| Backend tests  | `pytest tests/`                | **302 passed**, 0 failures in 58.80s        |
| Frontend lint  | `pnpm lint`                    | clean                                       |
| Frontend types | `pnpm typecheck`               | clean                                       |
| Frontend tests | `pnpm test` (vitest)           | **31 passed** (5 files)                     |
| Frontend build | `pnpm build` (Next, turbopack) | green                                       |

Phase 6 test suites: `test_prompts.py` 12 · `test_gemini_client.py` 5 · `test_rag_service.py` 13 · `test_chat_api.py` 6 · `test_database.py` +3 = **39 new tests** (263 → 302).

---

## 1. RAG Architecture — PASS

The full pipeline documented in `docs/03-App-Flow.md §8` and `docs/06 Phase 6` exists end-to-end in `backend/services/chat/rag_service.py::stream_answer`:

| Step                     | Location                                                          | Verified |
| ------------------------ | ----------------------------------------------------------------- | -------- |
| Website ownership check  | `rag_service.py:109-112` (`find_by_id(tenant_id, website_id)`)    | PASS     |
| Sanitize question        | `rag_service.py:113` + `prompts/rag.py::sanitize_question`        | PASS     |
| Session ensure/validate  | `rag_service.py:114-120` + `_ensure_session`                      | PASS     |
| Persist user turn        | `rag_service.py:127-134` (docs/05 §10)                            | PASS     |
| Question embedding       | `rag_service.py:148-153` (`GoogleEmbeddingClient` reuse, Phase 5) | PASS     |
| Tenant-filtered Top-5    | `rag_service.py:155-162` (`$vectorSearch` filter tenant+website)  | PASS     |
| Context + dedup + memory | `rag_service.py:175-191` + `prompts/rag.py`                       | PASS     |
| Gemini streaming (SSE)   | `rag_service.py:193-204` + `ai/gemini.py`                         | PASS     |
| Persist answer+sources   | `rag_service.py:210-221` (tokens, latency, sources)               | PASS     |
| Session touch + usage    | `rag_service.py:222-234` (ADR-005 §5.5/§5.8)                      | PASS     |

- **Retrieval-before-generate (docs/06 rules):** enforced in code — the model is invoked only after a non-empty retrieval (lines 164-173); see Hallucination Prevention.
- **No-context fallback** (`_emit_fallback`), **error-event uniformity** (`_error_event`), and **never-leak internals** (`_safe_message`) verified by tests.

## 2. Retrieval Security — PASS

| Requirement               | Implementation                                                                                                                                                                | Result |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| tenant_id filtering       | `tenant_id` on every model/repo query (`chat_sessions`, `messages`, `usage_records`, `knowledge_chunks`)                                                                      | PASS   |
| Website ownership         | `find_by_id(tenant_id, website_id)` before any work; foreign website → `WEBSITE_NOT_FOUND`                                                                                    | PASS   |
| Vector search isolation   | `$vectorSearch` `filter: {tenant_id, website_id}` (`vector/mongodb.py:84-87`)                                                                                                 | PASS   |
| No cross-tenant retrieval | Question is embedded and searched only within the principal's tenant; verified by `test_chat_isolates_websites_between_tenants` and `test_foreign_tenant_website_is_rejected` | PASS   |
| Session ownership         | `find_by_session_id(tenant_id, session_id)` + `website_id` re-check (`_ensure_session`); foreign/unknown → `SESSION_NOT_FOUND`                                                | PASS   |

No cross-tenant data path found. All unique indexes embed `tenant_id`.

## 3. Hallucination Prevention — PASS

| Requirement                   | Implementation                                                                                                                               | Result |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| No answer without context     | Model call only after non-empty `results` (lines 164-173)                                                                                    | PASS   |
| Empty knowledge base fallback | `website.knowledge_chunks == 0` → `_emit_fallback`, zero model calls                                                                         | PASS   |
| Zero search hits fallback     | `not results` → `_emit_fallback`, zero model calls                                                                                           | PASS   |
| System prompt rules           | `_SYSTEM_PROMPT_V1` rule 1 "Never invent, guess, or use outside knowledge"; rule 2 fixed fallback; rule 3 same-language; rule 4 cite sources | PASS   |
| Untrusted context delimiter   | `render_context` wraps material in `<context>…</context>` + "untrusted data" label                                                           | PASS   |
| Prompt-injection defense      | Rule 5 ignores embedded instructions; `sanitize_question` strips control chars; schema validator strips whitespace/blanks                    | PASS   |

Tests: `test_fallback_when_knowledge_base_empty_no_model_call`, `test_fallback_when_no_search_hits_no_model_call`, `test_question_is_sanitized_before_generation`, `test_internal_errors_do_not_leak_details`.

## 4. Gemini Integration — PASS

- **Key handling:** `GEMINI_API_KEY` read from settings only, lazily (`gemini.py:87-95`); `GenerationUnavailableError` when absent; never logged/exposed. Tracked tree is secret-free (scanned `AQ…`, `AIza…`, `sk-…` patterns; `.env` gitignored).
- **Model config:** `GEMINI_MODEL=gemini-2.5-flash`, `max_output_tokens=1024`, `temperature=0.2`, `generation_timeout_seconds=60` (per-`anext` `asyncio.wait_for`), system_instruction.
- **Streaming:** `client.aio.models.generate_content_stream`; deltas yielded; role map user→user, assistant→model, system→user.
- **Error handling:** raw SDK errors normalized to `GenerationError(502)`; `GenerationUnavailableError` re-raised unmodified; `GenerationError`/`EmbeddingUnavailableError` surfaced as SSE `error` events with stable codes, internal detail redacted.
- **Token capture:** `usage_metadata` → `GenerationUsage` (`gemini.py:129-134`); per-message `input_tokens`/`output_tokens` on `messages` (ADR-005 §5.8) + atomic `$inc` into `usage_records`.
- **No secret leakage:** errors never include the key or SDK internals; `_safe_message` returns generic text for non-`AppError`.

## 5. Database Verification — PASS (1 Low finding)

Collections `chat_sessions`, `messages`, `usage_records` — schema matches `docs/05 §9-10` + ADR-005 §5.5-5.8 (superset: added `website_id`, `user_id`, `schema_version`, `expires_at`, tokens):

- `chat_sessions`: `session_id` (unique), `tenant_id`, `(tenant_id, website_id)`, TTL `expires_at` — all present (`database.py:136-141`).
- `messages`: `tenant_id`, `session_id`, `(tenant_id, session_id, created_at)`, TTL `created_at` — all present (`database.py:142-149`).
- `usage_records`: unique `(tenant_id, website_id, date)`, `tenant_id`, `date`, TTL `updated_at` (3y) — all present (`database.py:150-157`).
- Tenancy: all repos query with `tenant_id`; atomic `$inc` upsert converges on the unique date key.
- **Finding F3 (Low):** chat-session TTL double-counts retention — see Findings.

## 6. API Verification — PASS

`POST /api/chat/stream` (`backend/api/routes/chat.py`):

- **Authentication:** `Depends(current_user)` (bearer JWT) → 401 unauth (tested).
- **RBAC:** router-level `Depends(require_role("owner","admin"))` → 403 for `viewer` (tested).
- **Request validation:** `ChatRequest` (pydantic) — `website_id`/`session_id` bounded, `question` required, ≤2000 chars, whitespace-blank → 422 (tested).
- **SSE headers:** `media_type=text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no` (tested).
- **Rate limiting:** `chat_limiter` (60/min sliding window, Redis, fails closed → 503) (deps.py:233).
- **Error responses:** streaming errors as `error` SSE events with stable codes (`WEBSITE_NOT_FOUND`, `SESSION_NOT_FOUND`, `INVALID_QUESTION`, `GENERATION_FAILED`, `INTERNAL_ERROR`); pre-stream failures use the standard JSON error envelope.
- Tenant always from `Principal`, never from the body.

## 7. Live E2E Verification — BLOCKED

A `GEMINI_API_KEY` **is present** in the local, gitignored `.env`, but the full flow cannot be exercised:

- `MONGODB_URI=mongodb://localhost:27017` — **no `mongod` running** (no process, port 27017 closed).
- **No Redis** running (rate limiter / ARQ worker require it).
- `similarity_search` requires an **Atlas `$vectorSearch` index**, which the local community MongoDB cannot provide.
- No ARQ worker/Playwright running to crawl a website.
- Local `.env` has a malformed multiline `CORS_ORIGINS=[` value that breaks pydantic-settings parsing (the documented `mv .env` workaround was used for pytest; the live app cannot boot from it as-is).

**Recommended live test (Phase 7 pre-flight, when infra is available):** start Mongo (Atlas with vector index) + Redis + worker → register → add website → crawl → process knowledge → `POST /api/chat/stream` → assert answer text contains the retrieved source and the `done` event reports `input_tokens`/`output_tokens` > 0.

## 8. Documentation Drift (docs/06 + docs/07 vs implementation)

| Item                                       | Claim                                                                                                                  | Reality                                                                                                                               | Result |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| docs/06 Phase 6 completion notes           | "the fixed TRD §8 fallback"                                                                                            | Fallback string differs from TRD §8 literal ("I couldn't find that information in the website's knowledge base." vs implemented text) | **F2** |
| docs/06 Phase 6 completion notes           | "the last `CHAT_MEMORY_TURNS` turns are fed into the prompt"                                                           | Mongo `list_recent` returns the **first** N turns (ordering bug)                                                                      | **F1** |
| docs/06 Phase 6 completion notes           | test counts, endpoint, pipeline description                                                                            | Accurate (302 measured, endpoint verified)                                                                                            | PASS   |
| docs/07 ADR-008 Phase 6 row                | "Tenant-filtered retrieval (Top-5), versioned prompts, Gemini SSE streaming, token usage capture, hallucination guard" | All five implemented and tested                                                                                                       | PASS   |
| docs/07 ADR-005 §5.5 `usage_records`       | 7 counters                                                                                                             | Schema + 5 counters populated; `embeddings_created` and `crawl_pages` never incremented                                               | **F4** |
| docs/07 ADR-005 §5.7 TTL table             | sessions 90d / messages 90d / usage 3y                                                                                 | Implemented (sessions effectively ~180d — see F3)                                                                                     | **F3** |
| docs/07 — Phase 6 completion notes section | —                                                                                                                      | Missing (§11/§12 exist for Phases 4/5; add §13 mirroring the pattern)                                                                 | **F5** |

---

## Findings summary

| #   | Severity | Type      | Item                                                                                                                                                                                                                                                                                                                                                                                           |
| --- | -------- | --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F1  | Medium   | Bug       | `MongoChatMessageRepository.list_recent` (`chat_message_repository.py:48-52`) sorts `created_at` ASCENDING and `.limit(limit)` → returns the **oldest** turns, not the most recent. Fake returns `recent[-limit:]`; docs/06 claim of "last `CHAT_MEMORY_TURNS` turns" is not honored once a session exceeds `memory_turns`. Fix: sort DESC, `limit`, then reverse. Untested (>8-turn sessions) |
| F2  | Low      | Docs/Req  | `UNKNOWN_ANSWER_FALLBACK` differs from the literal TRD §8 fallback string (internally consistent; system prompt rule 2 uses the same text). Align TRD or the string                                                                                                                                                                                                                            |
| F3  | Low      | DB/Config | `chat_sessions` TTL double-counts retention: `expires_at = now + 90d` with `expireAfterSeconds=90d` → docs survive ~180d, not 90d. Also `usage_retention_days` config is unused (hardcoded 3y constant). Fix: `expireAfterSeconds=0` on `expires_at` (or TTL on `created_at`)                                                                                                                  |
| F4  | Low      | Feature   | `usage_records.embeddings_created` and `crawl_pages` counters (ADR-005 §5.5) are never incremented anywhere (RAG correctly increments chats/messages/tokens/vector_queries) — Phase 9 analytics would read 0 until Phase 5/9 worker rollups land                                                                                                                                               |
| F5  | Low      | Docs      | docs/07 has no Phase 6 Completion Notes section (add §13)                                                                                                                                                                                                                                                                                                                                      |
| O1  | Info     | Design    | `MongoChatSessionRepository.create` DuplicateKeyError convergence updates `{"_id": session.id}` which can never match a concurrent doc (different `_id`) — effectively a no-op. Harmless: RAG generates `session_id` via `new_id()`, collisions impractical                                                                                                                                    |

**Security:** no secrets exposed (key only in gitignored `.env`); embedding/generation keys never logged or returned; all chat/retrieval data tenant-scoped; session ownership re-checked against `website_id`; fail-closed rate limiting; sanitization + untrusted-context labeling against prompt injection. **No security defects found.**

**Database verification:** all three collections, indexes, unique keys and TTLs match docs/05 §9-10 + ADR-005 §5.5-5.8 (with F3 retention caveat).

## Completion

- Code + tests + gates: **100%** green.
- Live E2E: **BLOCKED** (missing infra) — not counted as complete.
- Docs/records accuracy: ~85% (F2–F5 open).
- **Overall ≈ 95% — READY FOR PHASE 7.** (Resolve F1 before the widget chat API / conversations surface depend on memory ordering.)
