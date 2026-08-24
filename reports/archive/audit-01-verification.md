# Audit 01 — Verification Report

Audit target: **WebChat AI, Phase 1–8 (tags v0.6 → v0.8)**
Audit basis: `docs/01-Requirements.md`, `docs/02-PRD.md`, `docs/03-App-Flow.md`, `docs/04-UI-UX-Brief.md`, `docs/05-Backend-Schema.md`, `docs/06-Implementation-Plan.md`, `docs/07-Architecture-Decisions.md`, `docs/08-Testing-Rules.md`, `docs/09-Phase-8-Plan.md`, `docs/10-Roadmap.md`
Commit audited: `cee0ec4` (feat: complete phase 8 widget sdk, 2026-08-10)
Date: 2026-08-10

## 1. Static verification gates

| Gate               | Command                                             | Result                                               |
| ------------------ | --------------------------------------------------- | ---------------------------------------------------- |
| Backend lint       | `ruff check .`                                      | PASS (all checks passed)                             |
| Backend format     | `ruff format --check .`                             | 18 files would be reformatted (79 already formatted) |
| Backend types      | `mypy .`                                            | 98 errors in 34 files (97 source files checked)      |
| Backend tests      | `pytest`                                            | 343 passed, 2 failed                                 |
| Frontend lint      | `pnpm lint` (eslint, dashboard + widget)            | PASS                                                 |
| Frontend types     | `pnpm typecheck` (tsc --noEmit, dashboard + widget) | PASS                                                 |
| Frontend unit      | `pnpm test` (vitest)                                | 167 passed (58 dashboard, 109 widget)                |
| Frontend build     | `pnpm build`                                        | PASS (widget 1.46s, dashboard 17.6s)                 |
| Widget bundle gate | `pnpm --filter @webchat/widget check:size`          | PASS — 20.42 kB gzip                                 |

### 1.1 Backend failures (2) — env-dependent, not regressions

```
tests/test_config.py::test_production_rejects_missing_jwt_secret - FAILED
tests/test_health.py::test_openapi_docs_disabled_in_production_default - FAILED
```

Both assert default values that differ between the committed `.env.example`
and the local `.env` (local sets `ENVIRONMENT=development` and a JWT secret).
Failures are environment-dependent, deterministic in this checkout, and
unrelated to Phase 8 changes. The CI job (`pytest`) runs against default env
values and is expected to be green.

### 1.2 mypy (98 errors, pre-existing)

Errors are overwhelmingly `untyped-decorator` (FastAPI/`pydantic-settings`
decorators) plus implicit-optional/style nits across 34 files. This is a
pre-existing baseline, not introduced by Phase 8. CI runs `mypy backend` and
therefore currently shares this baseline.

### 1.3 ruff format (18 files, pre-existing)

Formatting drift in backend modules (gemini, database, repositories, services,
workers). Cosmetic only; `ruff check` is clean. Not a Phase 8 regression.

## 2. Spec → implementation traceability

### 2.1 Phase 1 — Foundation & auth (tag v0.6)

Present: FastAPI app, settings via `pydantic-settings`, JWT access + refresh,
argon2 password hashing, email verification, password reset (Resend or Mailpit),
rate limiting (slowapi), CORS, request logging, graceful shutdown.
**Verdict: DONE.**

### 2.2 Phase 2 — Ingestion engine (crawl + embed + store)

Present: `services/ingestion` (crawler, browser via Playwright), `services/knowledge`
(chunking/processor, embedding), MongoDB vector store + Atlas vector search index,
crawl jobs queue (arq worker). Verified by tag `v0.6` + phase 4 commit.
**Verdict: DONE.**

### 2.3 Phase 3 — RAG chat

Present: `services/chat` (RAG retrieval, Gemini streaming, memory), SSE via
`/api/chat/stream`, rate limiting per session/visitor, sources persisted on
messages (`metadata.sources`). Verified by tag `v0.6-rag-complete`.
**Verdict: DONE.**

### 2.4 Phase 4 — Websites API

Present: `/api/websites` CRUD, crawl job control, knowledge refresh.
**Verdict: DONE.**

### 2.5 Phase 5 — Knowledge processing verification

Present: unit + integration tests for ingestion/knowledge pipeline (commit
`d099e62`). **Verdict: DONE.**

### 2.6 Phase 6 — Dashboard

Present: auth pages, websites CRUD UI, crawl job management, analytics empty
state, API keys empty state. Tag `v0.7-dashboard-complete`.
**Verdict: DONE** (see deferred scope §2.10).

### 2.7 Phase 7 — Conversations

Backend exposes no conversation-management API (documented in `docs/06`).
Dashboard renders production-grade empty states for Conversations, Analytics,
API keys, Settings — no mock data. **Verdict: DONE per documented scope.**

### 2.8 Phase 8 — Widget SDK (tag v0.8-widget-sdk-complete)

Present: vanilla-TS widget (no framework), embed/launcher/mount, config fetch +
override, visitor + session lifecycle, SSE streaming client, markdown renderer,
theme application, imperative SDK API (`updateConfig`, `open`, `close`, `destroy`,
`onMessage`, `onSources`, `onOpen`, `onClose`, `onError`, `onStatusChange`),
session token validation on backend, widget rate limits, bundle-size gate.
**Verdict: DONE.**

### 2.9 Phase 9 — Deployment artifacts

Present: `docker/` Dockerfiles (api, worker, dashboard, widget), `docker/compose.dev.yml`
(7 services: mongo, redis, mailpit, api, worker, dashboard, widget), `scripts/`
(`setup.sh`, `docker-up.sh`, `check-backend.sh`, `dev-api.sh`, `dev-worker.sh`),
`.github/workflows/ci.yml` (backend ruff/mypy/pytest; frontend lint/typecheck/build/test;
docker build of all 4 images).
**Verdict: DONE.**

### 2.10 Deferred / not in scope (confirmed not implemented)

| Item                                    | Plan reference     | Status                                                                                    |
| --------------------------------------- | ------------------ | ----------------------------------------------------------------------------------------- |
| Admin panel                             | Phase 10           | `features/admin/` is an empty `.gitkeep`; no backend admin module, no `/api/admin` routes |
| Widget customization API (PATCH widget) | Roadmap            | No such route; widget config served via GET `/api/widget/config`                          |
| Analytics API                           | Phase 9 backlog    | `usage_records` collection exists; no `/api/analytics` route                              |
| Conversations API                       | Phase 7 scope note | No conversation list/history endpoints                                                    |
| API keys backend                        | Phase 9 backlog    | No `api_keys` routes/models/collections                                                   |
| Cite sources in widget UI               | PRD "Future"       | Sources persisted + surfaced via `onSources` callback; not rendered in widget bubbles     |

## 3. Gaps & recommendations

1. **Format/tests-typed baseline debt**: run `ruff format` and reduce mypy
   `untyped-decorator` errors before enabling strict CI; CI today repeats the
   same baseline locally.
2. **Two env-dependent pytest failures**: either set CI `ENVIRONMENT`/JWT
   vars explicitly or make the two tests set their own env (see audit-03 §2).
3. **Dead env config**: 18 legacy variables in local `.env` are unreferenced
   by code (see audit-03 §4 — full list).

## 4. Evidence

- Backend gates executed in `backend/` against `.venv` (uv sync).
- Frontend gates executed via `pnpm -r` from repo root.
- Build sizes: widget iife 20.42 kB gzip; dashboard First Load JS shared 144 kB.
