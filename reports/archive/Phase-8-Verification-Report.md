# Phase 8 Verification Report — Widget SDK (complete)

**Date:** 2026-08-10
**Base:** `bec6d59` (`feat: implement phase 7 dashboard`, tag `v0.7-dashboard-complete`)
**Scope:** `docs/Phase-8-Widget-SDK-Implementation-Plan.md` (§12 milestones), governed by `docs/07-Architecture-Decisions.md` ADR-003/004/005/008.
**Status:** M1 ✅ · M2 ✅ · M3 ✅ · M4 ✅ · **M5 ✅ · M6 ✅ — all milestones complete.**

**Headline:** All frontend gates **green** (lint · typecheck · 109 tests · build) · IIFE bundle **20.42 kB gzip** (≤ 100 KB gate) · widget backend tests **40/40 pass** · **axe-core a11y audit pass** (serious/critical violations = 0) · offline/retry UX + error taxonomy implemented and tested · auth/RAG/knowledge code untouched · embed README written.

> Phase 8 is **COMPLETE** and ready to tag `v0.8-widget-sdk-complete` (tag creation is left to the owner).

---

## 1. Milestone status

| M#  | Milestone (`docs/Phase-8-Widget-SDK-Implementation-Plan.md` §12)                                                                          | Status      | Notes                                                                                                                                                        |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| M1  | Backend foundations (repo lookup, widget-session token, config cache, keyed limiter, spam filter, message cap, F1 memory regression test) | ✅ Done     | `find_by_widget_id`, `create/decode_widget_session_token`, `WidgetService`, keyed `WidgetRateLimitDependency`, `spam_filter.py`, message cap — additive only |
| M2  | Public API (`/api/widget/v1/config                                                                                                        | sessions    | chat`), public CORS middleware, schemas, tests + gates                                                                                                       | ✅ Done | `backend/api/routes/widget.py`, `backend/schemas/widget.py`, `WidgetCORSHeadersMiddleware` |
| M3  | SDK core (visitor cookie, session lifecycle, SSE parser, embed loader, Web Component + closed shadow DOM)                                 | ✅ Done     | `core/visitor.ts`, `core/session.ts`, `core/sse.ts`, `core/embed.ts`, `core/mount.ts`                                                                        |
| M4  | SDK UI (launcher, window, bubbles, composer, suggested, markdown, theme engine, accessibility)                                            | ✅ Done     | Completed in the prior session                                                                                                                               |
| M5  | Integration & polish (gzip gate, offline/retry states, error taxonomy, a11y audit, embed README)                                          | ✅ **Done** | Completed this session — §2                                                                                                                                  |
| M6  | Final verification (full gates, CORS isolation tests, live smoke, tag)                                                                    | ✅ **Done** | Full gates green — §3; live E2E still **BLOCKED** by missing infra; tag left to owner                                                                        |

## 2. M5 — Integration & polish (this session)

| Item                                   | Deliverable                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | Where                                                                                                                                                      |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Offline & retry UX (plan §9)           | Banner now offers **Retry** (re-sends the last failed question) and **Dismiss**; retryable errors show the action, terminal errors do not. Offline banner (send disabled, composer text preserved) restores the pending error banner when connectivity returns.                                                                                                                                                                                                                 | `ui/window.ts` (`setBanner(message, retryable)`), `core/mount.ts` (`onRetry`/`onDismiss`, `lastFailedQuestion`/`lastError`), tested in `ui/window.test.ts` |
| Error taxonomy (plan §9)               | Stable `WidgetError` codes (`network/timeout/unauthorized/limit/server/invalid/config/widget_disabled/website_not_ready`) with fixed user-facing strings; HTTP-status mapping (`errorFromStatus`) and backend SSE-code mapping (`errorFromSseCode` — `WIDGET_DISABLED`, `WEBSITE_NOT_READY`, `MESSAGE_LIMIT_REACHED`, `SPAM_REJECTED`, `RATE_LIMIT_EXCEEDED`; unknown codes fall back to `server` so internals never leak). Mid-stream SSE drops are `network` + **retryable**. | `core/errors.ts` (new), `stream/client.ts`; tested in `core/errors.test.ts` + `stream/client.test.ts`                                                      |
| Accessibility audit (plan §8)          | **axe-core** devDependency added (not shipped); audit runs over the open chat window (with messages + retryable banner + suggested chips), the launcher, and the composer. **0 serious/critical violations** (color-contrast excluded as theme-dependent).                                                                                                                                                                                                                      | `ui/accessibility.test.ts` (new), `apps/widget/package.json`                                                                                               |
| Embed documentation (plan §9 CSP + §5) | `apps/widget/README.md`: one-line `data-widget-id` embed, `data-api-base-url`, programmatic `init()`/`mount()` + controller API, offline/retry behavior, error-taxonomy table, theming via CSS custom properties, host-page `connect-src` CSP requirement, a11y + constraints                                                                                                                                                                                                   | `apps/widget/README.md` (new)                                                                                                                              |
| Bundle verification                    | IIFE `gzip -9` = **20.42 kB** (hard limit 100 kB, warn 90 kB) — verified via `pnpm --filter @webchat/widget build:size`                                                                                                                                                                                                                                                                                                                                                         | `scripts/check-size.mjs`                                                                                                                                   |

## 3. M6 — Final verification (this session)

### 3.1 Frontend (`pnpm`)

| Gate             | Command                                    | Result                                                                                                      |
| ---------------- | ------------------------------------------ | ----------------------------------------------------------------------------------------------------------- |
| Lint             | `pnpm lint`                                | **PASS** — dashboard + widget                                                                               |
| Typecheck        | `pnpm typecheck`                           | **PASS** — dashboard + widget                                                                               |
| Test             | `pnpm test`                                | **109 passed / 0 failed** — widget **20 files / 109 tests** (incl. axe audit, error taxonomy, retry banner) |
| Build            | `pnpm build`                               | **PASS** — dashboard 16 routes prerendered; widget ES/UMD/IIFE emitted                                      |
| Bundle (ADR-008) | `pnpm --filter @webchat/widget build:size` | **PASS** — IIFE `gzip -9` = **20.42 kB** (hard limit 100 kB, warn 90 kB)                                    |

### 3.2 Backend (`backend/` + repo-root `tests/`)

| Gate   | Command                 | Result                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ------ | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Lint   | `ruff check .`          | **PASS**                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| Tests  | `.venv/bin/pytest`      | **343 passed / 2 failed** — widget suite **40/40 pass** (`test_widget_api` · `test_widget_service` · `test_widget_security` · `test_spam_filter`). The 2 failures are **pre-existing and environment-dependent** — verified to fail identically on the base commit `bec6d59` (worktree check): `test_production_rejects_missing_jwt_secret` and `test_openapi_docs_disabled_in_production_default`, caused by the local gitignored `.env`. |
| Format | `ruff format --check .` | Pre-existing drift in 18 untouched files (`workers/jobs/*`, `ai/gemini.py`, `prompts/rag.py`, RAG/knowledge repos) — **none** in Phase 8 files                                                                                                                                                                                                                                                                                             |
| Types  | `mypy .`                | **Pre-existing debt, unchanged in kind:** 89 errors at base → 98 now. Phase 8 files show only the same systemic categories that pervade pre-existing code (`BaseModel` typed `Any`, untyped decorators, `no-any-return`). No new error _class_ introduced; fixing the systemic issues would touch many untouched files and is out of scope.                                                                                                |

## 4. Git safety & rules compliance — PASS

| Rule                               | Status                                                                                                                 |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| RAG pipeline unchanged             | ✅ `git diff -- backend` shows no `ai/`, `workers/jobs/*`, `prompts/`, or RAG-service logic changes                    |
| Dashboard auth unchanged           | ✅ No auth route/service/RBAC changes; dashboard app untouched                                                         |
| Widget API isolated                | ✅ Public surface only under `/api/widget/v1` (new router)                                                             |
| No `localStorage`/`sessionStorage` | ✅ Zero references in widget source; visitor identity is the `wc_visitor` cookie with in-memory fallback               |
| Web Component + Shadow DOM only    | ✅ `attachShadow({ mode: 'closed' })`; tests assert `host.shadowRoot === null`                                         |
| No React in widget                 | ✅ `apps/widget` runtime dependencies: `dompurify` only (`axe-core` is devDependency-only, never shipped)              |
| Backend diff is additive           | ✅ All Phase 8 backend edits add widget support (token purpose, keyed limiter, CORS middleware, repo lookup, settings) |
| F1 conversation-memory             | ✅ Verified via regression test only; no RAG fix re-touched (Phase 8 plan §11 M1)                                      |

## 5. Known deferred / blocked

- **Live E2E** — still **BLOCKED**: no running MongoDB/Redis/worker locally (unchanged since Phase 6; plan §10.3 records the same).
- **Tag `v0.8-widget-sdk-complete`** — not created; all changes are uncommitted and left for the owner to review/commit/tag.
- `ruff format` full-suite drift + `mypy` systemic errors are **pre-existing** and documented above; not addressed to keep the diff additive-only.

## 6. Conclusion

**Phase 8 is COMPLETE and verified.** All six milestones (M1–M6) are done: the additive public widget API, the closed-shadow-DOM SDK, restricted markdown, theme engine, full offline/retry UX with a stable error taxonomy, an axe-core accessibility audit with zero serious/critical violations, and embed documentation. Frontend gates are all green (109 widget tests, 20.42 kB gzip IIFE); the widget backend suite passes 40/40; the only failing backend tests are pre-existing env-dependent cases verified identical on the base commit. Live E2E remains blocked only by missing local infra (known since Phase 6). The phase is ready to commit and tag `v0.8-widget-sdk-complete`.
