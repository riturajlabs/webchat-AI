# WebChat AI Production Audit Report

**Audit date:** 2026-08-14
**Scope:** Backend (FastAPI + MongoDB + Redis + ARQ), Dashboard (Next.js), Widget SDK (Vite IIFE/ESM/UMD)
**Method:** full unit/integration suites, live-stack E2E (real MongoDB/Redis/Mailpit/Gemini), static analysis (ruff, mypy, eslint, tsc), production build + bundle inspection

---

## 1. Executive Summary

WebChat AI is production-ready. Every implemented feature was exercised against
the automated suites and, where meaningful, against a **live no-mock stack**
(docker compose: MongoDB, Redis, Mailpit, API, worker, widget, dashboard).

| Area                     | Result                                                                        |
| ------------------------ | ----------------------------------------------------------------------------- |
| Backend tests            | **631 passed**, 1 environmental skip                                          |
| Backend static analysis  | ruff clean, mypy clean (135 source files)                                     |
| Live E2E (browser + API) | **2 passed** (full widget customer flow + hostile-origin block)               |
| Dashboard                | **168 tests passed**, eslint clean, `tsc --noEmit` clean, production build OK |
| Widget SDK               | **170 tests passed**, production build OK, self-contained bundle              |
| Widget bundle            | IIFE 80.07 kB (gzip 26.52 kB) — inside the 100 kB gzip gate                   |

No security issues were found in the audited surface. One test was repaired
during the audit (E2E hostile-origin harness; product behavior was already
correct). One intermittent test flake was observed once and did not reproduce.

---

## 2. Completed Features

### Backend

- **Authentication** — register / login / refresh / logout / verify-email /
  resend-verification / forgot-password / reset-password; email verification is
  enforced (unverified accounts get `403 EMAIL_NOT_VERIFIED` and cannot reach
  authenticated routes); Argon2 password hashing; SHA-256 refresh-token hashing;
  CSRF defense; per-endpoint sliding-window rate limits.
- **API** — REST surface for websites, conversations, analytics, feedback,
  crawl jobs, API keys, admin; tenant-scoped access everywhere
  (00-AI-Development-Rules §7); consistent error envelope + audit logging.
- **RAG** — website ingestion (crawler → cleaner → chunker → embedder →
  vector store), top-k retrieval with `KNOWLEDGE_STRONG/EMBEDDING_ONLY` confidence
  thresholds, hallucination guard (no-context fallback), streaming SSE answers
  with source citations, usage rollups.
- **Security** — JWT access/refresh with rotation and reuse detection; widget
  session JWTs bound to widget+tenant+website+visitor; embed-origin allowlist
  with hostile-origin rejection; SSRF guard + URL validation + robots.txt;
  spam filter; XSS-safe markdown; API key authentication (`wc_*`) with
  per-key rate limiting and full audit trail; account/tenant suspension.
- **Database** — Motor/MongoDB repositories with schema-versioned models,
  unique indexes, TTL-based message expiry, vector indexes, fail-safe startup.
- **Workers** — ARQ workers for `crawl_website`, `process_website_documents`,
  `process_document`, `send_email`, `ping` with unified timeouts and retries.

### Dashboard

- **Auth UI** — login/signup/forgot/reset/verify-email with resend action;
  session restore with single silent refresh; unverified users routed to
  `/verify-email`.
- **Websites** — create/update/delete, embed-script delivery (one-time secret
  flow removed; embed tag is the single credential), widget customization
  builder.
- **API keys** — list / create (raw `wc_*` secret shown once) / revoke.
- **Analytics** — summary KPIs, daily timeseries, top websites, performance.
- **Conversations** — paginated list with search + website filter, detail view
  with message history, delete.
- **Admin** — tenant list/detail, user suspension, force-logout, crawl-job
  monitor, audit-log viewer, platform KPIs (owner-gated).

### Widget

- **Embed script** — one-line `<script data-widget-id ... defer>`, optional
  `data-api-base-url`; content-hashed immutable bundles + stable-name copies.
- **Chat UI** — launcher, window, bubbles, composer, suggested questions,
  markdown rendering, mobile-responsive layout, reduced-motion support.
- **Streaming** — SSE parsing, loading/typing states, offline + retry banner,
  error taxonomy mapped to stable user-facing messages.
- **Feedback** — thumbs up/down with category chips, per-message idempotency.
- **Security** — anonymous visitor cookie (no PII/localStorage), per-visitor +
  per-widget rate limits, closed shadow DOM, no external asset fetches
  (self-contained bundle), origin allowlist enforcement on the API.

---

## 3. Verified Features

Live-stack E2E and automated suites were run on **2026-08-14**. E2E ran against
`http://localhost:8000` (API), `:8080` (widget bundle), `:3000` (dashboard),
`:8025` (Mailpit), real MongoDB/Redis and a real `GEMINI_API_KEY`.

| Feature                                                | Status | Evidence                                                                                                          |
| ------------------------------------------------------ | ------ | ----------------------------------------------------------------------------------------------------------------- |
| Backend unit/integration suite                         | PASS   | `uv run pytest` → 631 passed, 1 skipped                                                                           |
| Backend static analysis                                | PASS   | `ruff check .` clean; `mypy backend` clean (135 files)                                                            |
| Backend CI coverage gate                               | PASS   | coverage threshold 85% enforced (pyproject)                                                                       |
| Registration + email verification                      | PASS   | `tests/test_auth_api.py`, `test_auth_service.py`                                                                  |
| Unverified-account lockout                             | PASS   | `EMAIL_NOT_VERIFIED` 403 on login/refresh/authenticate                                                            |
| Resend verification (anonymous, silent)                | PASS   | `test_auth_api.py`, `test_auth_service.py`                                                                        |
| API key mint/list/revoke                               | PASS   | `tests/test_api_keys_api.py`, `test_api_key_service.py`                                                           |
| API key auth (owner-scoped, per-key rate limit, audit) | PASS   | `tests/test_api_key_auth.py` (9 tests)                                                                            |
| Website CRUD + embed script                            | PASS   | `tests/test_websites_api.py`, `test_website_service.py`                                                           |
| Widget customization builder                           | PASS   | `tests/test_widget_config_api.py` (12 tests)                                                                      |
| RAG retrieval + no-context guard                       | PASS   | `tests/test_rag_service.py`, `test_chat_api.py`                                                                   |
| Streaming SSE + disconnect handling                    | PASS   | `tests/test_sse.py`, `test_chat_api.py`, `test_widget_api.py`                                                     |
| Conversations list/detail/delete                       | PASS   | `tests/test_conversations_api.py`                                                                                 |
| Analytics summary/timeseries/top/performance           | PASS   | `tests/test_analytics_api.py`                                                                                     |
| Admin panel (tenants/users/crawl/audit)                | PASS   | `tests/test_admin_api.py` (19 tests)                                                                              |
| Feedback capture + idempotency                         | PASS   | `tests/test_feedback_api.py`, `test_feedback_service.py`, `test_feedback_repository.py`                           |
| Origin allowlist / hostile embed                       | PASS   | live: hostile `Origin` → 403 `WIDGET_ORIGIN_NOT_ALLOWED`; `tests/test_widget_origin.py`                           |
| Invalid widget ID handling                             | PASS   | live: `GET /api/widget/v1/config/does-not-exist` → 404 `WIDGET_NOT_FOUND`; `tests/test_widget_api.py`             |
| CORS (widget any-origin, dashboard scoped)             | PASS   | `tests/test_widget_api.py` (CORS block)                                                                           |
| Rate limiting (IP / widget / visitor / per-key)        | PASS   | `tests/test_rate_limit.py`, `test_widget_security.py`, `test_api_key_auth.py`                                     |
| Spam filter                                            | PASS   | `tests/test_spam_filter.py`                                                                                       |
| Crawler + SSRF + URL validation                        | PASS   | `tests/test_crawler.py`, `test_crawl_service.py`, `test_ssrf_guard.py`, `test_url_validator.py`, `test_robots.py` |
| Workers / knowledge pipeline                           | PASS   | `tests/test_crawl_worker.py`, `test_knowledge_processor.py`, `test_knowledge_worker.py`                           |
| Health + readiness probes                              | PASS   | `tests/test_health.py`; live `/api/health/ready` → `{"status":"ready"}`                                           |
| Dashboard auth flow                                    | PASS   | `pnpm test` 168 passed (incl. `auth-context.test.tsx`, `resend-verification-form.test.tsx`)                       |
| Dashboard API keys page (create/list/revoke UI)        | PASS   | `api-keys-page.test.tsx` (7 tests)                                                                                |
| Dashboard analytics page                               | PASS   | `analytics-page.test.tsx`                                                                                         |
| Dashboard conversations page                           | PASS   | `conversations-page.test.tsx`                                                                                     |
| Dashboard admin page (owner-gated)                     | PASS   | `admin-page.test.tsx`, `admin-guard.test.tsx`                                                                     |
| Dashboard production build                             | PASS   | `pnpm build` — all routes emitted (incl. `/admin`, `/analytics`, `/api-keys`, `/conversations`, `/widget`)        |
| Widget SDK tests                                       | PASS   | `pnpm test` → 170 passed                                                                                          |
| Widget production build                                | PASS   | `tsc --noEmit` + vite build + copy-stable + check-assets all clean                                                |
| Widget bundle self-contained                           | PASS   | check-assets: no loopback hosts, no `@import`/`@font-face`, no external refs                                      |
| Widget live embed → chat (customer flow)               | PASS   | E2E browser: launcher mounts, window opens, message sent, SSE answer rendered                                     |
| Widget markdown + XSS safety                           | PASS   | `markdown/render.test.ts` (bold/headings/code/links, raw-HTML escaping)                                           |
| Widget visitor/session persistence                     | PASS   | `core/visitor.test.ts` (anonymous cookie stable across reloads)                                                   |
| Widget feedback UI                                     | PASS   | `ui/feedback.test.ts` (thumbs, category chips, `aria-pressed`)                                                    |
| Widget mobile/responsive                               | PASS   | `ui/styles.ts` `@media (max-width: 480px)`, `min(380px, 100vw-32px)`, `max-height: calc(100vh-84px)`              |
| Widget accessibility                                   | PASS   | `ui/accessibility.test.ts`, `ui/window.ts` (live regions, alert banner, reduced motion)                           |

---

## 4. Failed Tests / Issues

| #   | Issue                                                                                                                                                                                                                                                                                                                                         | Severity           | File location                     | Recommended fix                                                                                                                                                                           |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ | --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **E2E `test_widget_blocked_origin`** failed with `200 != 403`. Root cause: `page.set_extra_http_headers({"Origin": ...})` cannot override the browser-computed `Origin` on cross-origin fetches — the hostile header never reached the API. Product behavior was verified correct by direct API calls (`Origin: https://evil.example` → 403). | Low (test harness) | `tests/e2e/test_widget_e2e.py`    | **Fixed during audit.** Rewrote the test to assert the live origin policy over httpx against the provisioned widget (hostile 403, allowlisted 200, headerless 200). Re-run: 2/2 E2E pass. |
| 2   | **Intermittent** `test_update_widget_config_validation` failed once in a full-suite run; passed in isolation and in two subsequent full runs. No deterministic reproducer; unrelated to the audited API-key/auth changes (widget-config area).                                                                                                | Low / observation  | `tests/test_widget_config_api.py` | Monitor. If it recurs, add per-test isolation for the empty-patch case (`({}, ...)` → 422) rather than relying on full-suite ordering.                                                    |
| 3   | **1 skipped test** — `tests/e2e/test_widget_e2e.py` self-skips without `E2E_BASE_URL` (by design). Requires a live stack (`scripts/e2e-widget.sh`).                                                                                                                                                                                           | Info               | `tests/e2e/conftest.py`           | Not a defect. CI runs the suite without the live stack; E2E is an opt-in deployment verification.                                                                                         |

No product bugs, security defects, or failing production paths were found.

---

## 5. Missing Features

Only genuinely absent items (not in scope of the completed phases, or deliberately out):

- **Native mobile apps / PWA** — the chat surface is web-only (widget + dashboard). No iOS/Android wrapper.
- **SSO / OAuth / SAML** — email/password authentication only.
- **Team member management UI** — member roles exist in the data model and admin surfaces, but the tenant-facing UI for inviting/managing teammates is not exposed.
- **Self-serve billing / plan management** — plan field exists on tenants (admin can change it); no customer-facing payment flow.
- **Multi-model choice in tenant UI** — AI providers are configured at the platform level; tenants cannot pick a model in the dashboard.
- **Analytics export** — analytics are view-only; no CSV/PDF export.
- **Localization (i18n)** — English-only UI.

None of these block production deployment; they are roadmap items.

---

## 6. Production Readiness Score

| Category                        | Score                               |
| ------------------------------- | ----------------------------------- |
| Backend correctness & security  | 9.5 / 10                            |
| Dashboard completeness & UX     | 9 / 10                              |
| Widget SDK quality & resilience | 9 / 10                              |
| Test coverage & verification    | 9.5 / 10                            |
| Build/deploy hygiene            | 9 / 10                              |
| **Overall**                     | **9.3 / 10 — READY FOR PRODUCTION** |

Deployment notes before release:

- Build the widget image with `--build-arg VITE_WIDGET_API_BASE_URL=https://<public-api>` and set `WIDGET_API_BASE_URL` / `WIDGET_SCRIPT_URL` (content-hashed bundle) / `PUBLIC_BASE_URL` in the API env.
- Production config validation hard-fails on loopback hosts for the widget API base and script URL (enforced in `Settings.model_validator`).
- The E2E suite should be run once against the deployed stack (`scripts/e2e-widget.sh`) as a release gate.

---

## Appendix A — Audit run evidence

- `uv run pytest` → `631 passed, 1 skipped, 1 warning in 221.34s`
- `uv run ruff check .` → `All checks passed!`
- `uv run mypy backend` → `Success: no issues found in 135 source files`
- `pnpm test` (dashboard) → `25 files / 168 tests passed`
- `pnpm lint` (dashboard) → clean
- `pnpm build` (dashboard) → all routes emitted (Static/Dynamic)
- `pnpm test` (widget) → `24 files / 170 tests passed`
- `pnpm build` (widget) → IIFE `webchat-widget.iife.min.CbwRxBt0.js` 80.07 kB (gzip 26.52 kB), ESM 104.12 kB (gzip 30.51 kB), UMD 80.26 kB (gzip 26.59 kB); check-assets clean
- Live E2E → `2 passed in 24.52s` (full customer flow + hostile origin)
- Live readiness → `GET /api/health/ready` → `{"status":"ready"}`

## Appendix B — Repository hygiene

- Historical verification/audit docs (`docs/Phase-*.md`, `reports/audit/*.md`) were
  restored after review; dead links in `apps/widget/README.md` and
  `docs/07-Architecture-Decisions.md` remain valid.
- Cache artifacts (`.coverage`, `__pycache__`, `.pytest_cache`, `.ruff_cache`,
  `.mypy_cache`, `*.tsbuildinfo`, `dist/` of build artifacts) are gitignored.
- Secrets (`.env`) are gitignored and were not part of any change.
