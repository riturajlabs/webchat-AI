# Audit 03 — Testing & Coverage Report

Target: WebChat AI Phase 1–8, commit `cee0ec4`.
Date: 2026-08-10

## 1. Executed test suites

| Suite              | Command                                 | Result                           |
| ------------------ | --------------------------------------- | -------------------------------- |
| Backend (pytest)   | `.venv/bin/pytest`                      | **343 passed, 2 failed** (79.6s) |
| Dashboard (vitest) | `pnpm --filter @webchat/dashboard test` | 10 files, 58 passed              |
| Widget (vitest)    | `pnpm --filter @webchat/widget test`    | 20 files, 109 passed             |
| Frontend total     | `pnpm test`                             | 167 passed, 0 failed             |
| Widget bundle gate | `check:size`                            | 20.42 kB gzip                    |

## 2. Backend failures — detailed

```
tests/test_config.py::test_production_rejects_missing_jwt_secret
tests/test_health.py::test_openapi_docs_disabled_in_production_default
```

Both fail deterministically in this checkout because the local `.env` sets
`ENVIRONMENT=development` and a JWT secret, whereas the tests assert the
_default_ (production) behavior. The tests mutate/assert env defaults and do
not reset `ENVIRONMENT` themselves. Fix recommendation (2 lines each):
set the target env var inside the test and restore it in a fixture, so the
tests are hermetic regardless of the developer's `.env`.

## 3. Coverage assessment

### Backend

Tests cover auth (register/login/verify/refresh/reset), rate limiting,
websites CRUD, crawl jobs, chat/stream, RAG retrieval, embedding, ingestion
processor, config, health, and widget session validation. CI runs
`pytest --cov=backend` so the coverage gate is configured (threshold not
evaluated here).

### Frontend

- **Dashboard**: 10 files / 58 tests — auth pages, layout, nav, empty states
  (`unsupported/empty-states.test.tsx`).
- **Widget**: 20 files / 109 tests — embed, mount (integration), session,
  visitor, network, SSE, config fetch + overrides, theme apply, markdown
  renderer, accessibility, launcher, composer, suggested, bubbles, window.

### Coverage gaps

1. **No UI E2E (Playwright)** — `playwright` is only a Python dependency for
   the crawler; there is no browser-driven E2E of widget↔API↔Mongo flow. CI has
   no E2E job. Recommend a small Playwright E2E for: embed → open widget →
   stream message → sources callback → session token 401 on reuse.
2. No explicit tests for `services/chat` rate-limit integration against Redis
   (covered by unit tests but not against live Redis).
3. No dashboard test asserting `NEXT_PUBLIC_API_URL` fallback
   (`http://localhost:8000`).

## 4. Environment audit (`.env` vs `.env.example` vs `config.py`)

### 4.1 Unused legacy variables in local `.env` (0 code references — dead config)

```
APP_VERSION, CHAT_MAX_HISTORY_MESSAGES, CHAT_MAX_MESSAGE_LENGTH,
CHAT_SESSION_EXPIRE_DAYS, GEMINI_MAX_OUTPUT_TOKENS, GEMINI_TEMPERATURE,
GEMINI_TOP_P, LOG_FORMAT, LOG_LEVEL, MAINTENANCE_MODE, RAG_ENABLE_STREAMING,
RAG_MAX_CONTEXT_TOKENS, RAG_MEMORY_MAX_MESSAGES, RAG_MIN_SIMILARITY_SCORE,
RAG_TOP_K, SSE_HEARTBEAT_SECONDS, SSE_TIMEOUT_SECONDS, VECTOR_SEARCH_INDEX_NAME
```

All are absent from `backend/config.py`. They are leftovers of an earlier
design (chat tunables were later consolidated into the `CHAT_*`/`RAG_*`/
`WIDGET_*` families). **Recommendation: delete from local `.env`** (and any
other env copies) to prevent drift.

### 4.2 `.env.example` variables missing from local `.env` (fall back to `config.py` defaults)

```
CHAT_CONTEXT_CHUNK_CHARS, CHAT_MAX_OUTPUT_TOKENS, CHAT_MEMORY_TURNS,
CHAT_QUESTION_MAX_CHARS, CHAT_RETENTION_DAYS, CHAT_TEMPERATURE, CHAT_TOP_K,
GENERATION_TIMEOUT_SECONDS, WIDGET_CONFIG_CACHE_SECONDS,
WIDGET_MAX_MESSAGES_PER_SESSION, WIDGET_PER_VISITOR_LIMIT, WIDGET_PER_WIDGET_LIMIT,
WIDGET_RATE_LIMIT_ENABLED, WIDGET_SESSION_ISSUE_LIMIT, WIDGET_SESSION_TOKEN_MINUTES,
WIDGET_SESSION_VALIDITY_HOURS
```

These are optional settings with sane defaults; tests pass without them.
**Recommendation:** add the widget + chat families to local `.env` for
explicitness, or document that local dev relies on defaults.

### 4.3 Documentation gap

- `USAGE_RETENTION_DAYS` exists in `config.py` (used for usage-record TTL) but
  is missing from `.env.example`. Add it with its default.
- `NEXT_PUBLIC_API_URL` (dashboard) and `WIDGET_API_BASE_URL`/`WIDGET_SCRIPT_URL`
  are only defined in the frontend/example; ensure they are documented in one
  place (env matrix) in `docs/06`.

### 4.4 Verified-good

All remaining `.env.example` variables have exactly 2+ code references
(`config.py` + test/usage), meaning `.env.example` is an accurate manifest of
consumed settings.

## 5. Recommendations (priority order)

1. **Hermetic env tests** — fix the 2 pytest failures (fix-local config), so a
   clean checkout is fully green.
2. **`ruff format`** all backend modules (18 files) to clear format drift.
3. **Reduce mypy `untyped-decorator`** count or document the baseline before
   enforcing strict typing in CI.
4. **Add one Playwright E2E** job for the widget happy path (highest-value
   missing coverage).
5. **Prune the 18 dead `.env` vars** and add the missing `CHAT_*`/`WIDGET_*`
   families + `USAGE_RETENTION_DAYS` to keep `.env`/`.env.example`/`config.py`
   in sync.
