# WebChat AI — Production Audit Report

**Date:** 2026-08-16
**Repository:** `/home/riturajlabs/Projects/webchat-AI` (branch `main`, HEAD `d16a18c`)
**Method:** Manual, file-by-file audit. Every claim below was verified against current source/config/tests. Prior `docs/` reports and commit messages were treated as unverified claims, not evidence. No code was modified.

---

## 1. Executive Summary

WebChat AI is a well-structured, genuinely production-oriented multi-tenant RAG SaaS. The codebase is consistently layered (routes → services → repositories), multi-tenancy is enforced at the repository layer via `tenant_id` in every query, authentication/authorization is carefully implemented (Argon2id, short-lived access JWTs, opaque rotated refresh tokens with reuse detection, live role re-resolution), rate limiting and SSRF guards are real, and the test suites are unusually thorough and hermetic.

**Test execution (run fresh during this audit):**

| Suite                   | Result                                                                      |
| ----------------------- | --------------------------------------------------------------------------- |
| Backend (pytest)        | 909 collected, **all passed**, exit 0, 87% line coverage (70 files at 100%) |
| Dashboard (vitest)      | 38 files / **258 passed**                                                   |
| Widget SDK (vitest)     | 26 files / **221 passed**                                                   |
| mypy --strict (backend) | Clean (158 source files)                                                    |
| ruff check (backend)    | Clean; `ruff format` not enforced (55 files would reformat)                 |
| tsc --noEmit            | Clean (dashboard + widget)                                                  |

**No P0 (critical) findings.** The most important real issues are operational/process risks, not code defects — most notably that real production secrets sit in plaintext in `.env.production` (untracked and gitignored, so not in the repo, but unrotated and unprotected), plus a handful of P1/P2 edge cases detailed below.

---

## 2. Architecture Overview

- **Backend:** FastAPI (Python 3.13), MongoDB via Motor (async), Redis, ARQ worker. 14 routers wired in `backend/main.py`.
- **Dashboard:** Next.js 15.5 (App Router, Turbopack, React 19), TanStack Query, recharts, Tailwind v4, vitest.
- **Widget:** Framework-independent Vite SDK (IIFE/ESM/UMD bundles), shadow-DOM UI, DOMPurify markdown, SSE streaming.
- **Themes:** `packages/@webchat/themes`.
- **Deploy:** `docker/compose.yml` (Mongo 7 + Redis 7 + Mailpit + API + Worker + Dashboard + Widget) with dedicated Dockerfiles; nginx static host for the widget bundles with immutable caching for content-hashed files.

---

## 3. Feature Inventory (verified against code)

### Backend routes (`backend/api/routes/`)

| Router             | Surface                                                                       | Notes                                                                                                                         |
| ------------------ | ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `auth.py`          | register, login, logout, refresh, verify-email, resend, forgot/reset password | Argon2id; 15-min access JWT; opaque rotated refresh w/ reuse detection; email-verify & reset tokens; per-endpoint rate limits |
| `websites.py`      | CRUD + crawl trigger                                                          | Owner/admin gating; `Origin`-validated add-flow                                                                               |
| `knowledge.py`     | documents list, status, retry, delete                                         | Pipeline state machine (pending → processing → ready/failed)                                                                  |
| `chat.py`          | authenticated chat (SSE)                                                      | `RagService.stream_answer`; usage recording                                                                                   |
| `conversations.py` | list, detail, delete                                                          | `tenant_id`-scoped                                                                                                            |
| `feedback.py`      | submit + list                                                                 | tenant + widget scoped                                                                                                        |
| `api_keys.py`      | create/list/revoke                                                            | `wc_` keys, hashed at rest, 300/min budget                                                                                    |
| `analytics.py`     | aggregate usage/time-series                                                   | tenant-scoped                                                                                                                 |
| `billing.py`       | usage, plans, checkout, subscription                                          | Stripe/Razorpay/mock providers; webhook = only unauthenticated billing surface (HMAC-verified, idempotent)                    |
| `crawl_jobs.py`    | history/status                                                                | 30-day retention                                                                                                              |
| `admin.py`         | tenant/users analytics, system panel, SaaS metrics                            | `super_admin` only (`ADMIN_ROLES = {super_admin}`)                                                                            |
| `widget.py`        | session, validate-chat, stream, config, feedback                              | Public by design; origin-guarded + IP-limited                                                                                 |
| `webhooks.py`      | Stripe/Razorpay webhooks                                                      | HMAC verified, idempotent on `payment_id`                                                                                     |
| `health.py`        | `/health/live`, `/health`, `/health/ready`                                    | liveness avoids I/O by design                                                                                                 |

### Dashboard pages (`apps/dashboard/src/app/(dashboard)/`)

`analytics`, `api-keys`, `billing`, `conversations`, `docs`, `knowledge`, `profile`, `settings`, `usage`, `websites`, `widget` (+ `widget-test`), `admin` (revenue/system/tenants/users); auth group: `login`, `signup`, `forgot-password`, `reset-password`, `verify-email`.

### Widget SDK (`apps/widget/src`)

`core/` (mount, embed, conversation), `stream/` (client, chat SSE), `config/` (fetch+cache), `markdown/` (DOMPurify render), `theme/` (custom-property injection), `ui/` (launcher, suggested), `feedback/`. Entry `index.ts` exposes `init`/`mount`/`defineWidgetElement`; `autoUpgrade()` reads `data-widget-id` on the embed script.

---

## 4. Chat Flow Trace (end-to-end, verified)

1. **Dashboard path:** `chat` page → `POST /api/chat` (or SSE stream) → `RagService.stream_answer` (`backend/services/chat/rag_service.py`) → topic → tenant-scoped `$vectorSearch` (Top-5) → context assembly → provider chain (gemini → groq → openrouter) → SSE frames (`sources`, `sources:done`, `content`, `done`) → usage + conversation persisted best-effort. Hallucination guard: fixed `UNKNOWN_ANSWER` when retrieval returns nothing — LLM is never called without context.
2. **Widget path:** embed script → `autoUpgrade` → `mount` → `POST /api/widget/session` (15-min JWT, 24 h sliding validity) → `validate-chat` (50-msg cap `ws:msgs:*`, spam filter) → SSE stream (same pipeline) → per-visitor/per-widget/IP limits.
3. **Disconnect handling:** `api/sse.py` `stream_with_disconnect` cancels the generator on client disconnect; `stream_answer_with_usage` checks `messages_sent` before streaming and emits `LIMIT_REACHED` SSE error event.

---

## 5. Security Findings

### 5.1 Secrets handling — **P1**

`.env.production` contains **real, live credentials** in plaintext: MongoDB Atlas password, Upstash Redis password, Resend key, Gemini/OpenRouter/Groq/Jina/Cohere keys, Razorpay test keys, JWT secret.

- **Verified safe today:** `.gitignore` covers `.env` / `.env.*` (except `.env.example`); `git ls-files` confirms only `.env.example` is tracked; a grep of every tracked file for the secret values found zero full-key matches (the only hit, `docs/Phase-5-Verification-Report.md:89`, mentions only the key _prefix_ `AQ.Ab8RN6…` in a "no secrets in tree" note).
- **Risk:** unrotated keys + plaintext-at-rest + accidental-commit/sharing exposure. Production should move secrets to a vault/secret manager (or at minimum rotate the current values) and add a git guard/hook (e.g. pre-commit secret scanner).

### 5.2 AuthN/AuthZ (verified in `core/security.py`, `services/auth/auth_service.py`, `core/rbac.py`)

- Argon2id (19 MiB, t=2, p=1) — no plaintext passwords anywhere.
- Access JWT: 15 min, HS256, claims `sub/tenant_id/role/token_type/jti`.
- Refresh token: 256-bit opaque, stored only as SHA-256; rotation on every refresh; reuse of a rotated token revokes all sessions + emails the user.
- Every request re-validates `claims["tenant_id"] == user.tenant_id` **and** live-resolves the current role (role changes apply immediately; stale-token role escalation not possible).
- RBAC fail-closed: unknown roles rank 0; `ADMIN_ROLES = {super_admin}` only.
- Cookies: `refresh_token` httpOnly/Secure/SameSite=Lax/`Path=/api/auth`; `csrf_token` non-httpOnly `Path=/`; double-submit CSRF enforced on mutating auth routes.
- **P2:** JWT dev fallback `dev-only-jwt-secret-change-me` is <32 bytes — pytest emits `InsecureKeyLengthWarning` (RFC 7518 §3.2). Config doesn't enforce a minimum key length; production should reject <32-byte HMAC keys. `localhost` also doesn't trigger HSTS (by design), but a production deployment without `COOKIE_SECURE=true` silently loses both Secure cookies and HSTS — worth a startup validation.

### 5.3 Web/API hardening

- Security headers on every response (`middleware.py:23-29`): `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy`, `CSP default-src 'none'`; HSTS (2 y) only when `cookie_secure`.
- Rate limiting: Redis sliding-window per endpoint (login 20/15min, register 10/hr, billing 240/hr/IP, checkout 30/hr/IP, API keys 300/min, widget IP 120/hr, per-widget 60, per-visitor 20, session-issue 30).
- SSRF guard for crawler (`services/ingestion/ssrf_guard.py`, 76% tested) blocks localhost/private ranges; crawl limits (depth 3, 50 pages, 5 MB HTML / 200 KB content caps).
- Widget public endpoints: origin allow-list + IP limiter + per-widget limits; suspended tenant returns `enabled:false` rather than an error (deliberate).
- `ALLOWED_HOSTS` + reverse-proxy trust configured; config.py validates in production.

### 5.4 Payment security

- Only unauthenticated billing surface is the webhook handler; HMAC signature verified via provider-specific parsers; idempotent on `payment_id`.
- **P2:** `_payment_out` (`routes/billing.py:89`) renders `amount_cents` from the **current** plan price (`plan.price_cents`, line 96), not the persisted `subscription.amount_cents` — subscription history will disagree with what customers were actually charged if prices change. Cosmetic for the API response, but a billing-audit correctness issue.

---

## 6. Performance Audit

- **Indexes/retention:** TTL indexes (refresh 40 d, messages 90 d, sessions 90 d, usage 3 y, feedback 2 y, crawl jobs 30 d, audit 1 y); tenant-scoped composite indexes.
- **Vector search:** `$vectorSearch` with tenant filter, `limit 5`, `CHAT_TOP_K=5`; embeddings+search results cached (bounded); answers never cached.
- **Streaming:** SSE first-token timeout + generation timeout (60 s), disconnect cancels generator.
- **Pools:** Mongo min/max pool 10/100, slow-query threshold configurable; Redis pool; worker `max_jobs=10`, `job_timeout=600`, `max_tries=3`.
- **Widget:** config cached in Redis 300 s (fail-open on cache error).
- **Note:** mixed-dimension chunks are silently filtered by the vector store (not fatal — verified); a log line would aid debugging. Embedding fallback chain (gemini → jina → cohere) built once per worker.

---

## 7. Test Quality Audit

| Metric           | Value                                                                                                                                            |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| Backend tests    | 909, all passing, hermetic (MongoDB stubbed via `tests/conftest.py`; real queries fail loudly)                                                   |
| Backend coverage | 87% lines; **gaps**: `workers/*` (0–68%), `ingestion/browser.py` (26%), payment providers (47–63%), `mail/providers.py` (45%), `timing.py` (51%) |
| Dashboard        | 38 files / 258 tests (session, auth, admin guards, widget embed/domain, components)                                                              |
| Widget SDK       | 26 files / 221 tests (mount integration, stream/chat SSE, markdown sanitization, embed, profile, accessibility via axe)                          |
| Static           | mypy strict clean; ruff check clean; tsc clean both apps                                                                                         |

**Gaps worth closing:** worker module coverage is near-zero (`backend/workers/*`), and the crawler's Playwright browser layer (26%) and payment-provider network paths (47–63%) are the thin spots. `ruff format` is not enforced in CI-equivalent checks (55 files would be reformatted) — enforce it or drop the config to avoid drift.

---

## 8. Deployment Readiness

- `docker/compose.yml` is well-built: `${VAR-default}` interpolation preserves intentionally-empty production values (e.g. `MAILPIT_API_URL=`), healthchecks on every service, `depends_on: service_healthy` chains, env passthrough for build-time-only vars documented (`NEXT_PUBLIC_API_URL`, `VITE_WIDGET_API_BASE_URL`).
- Worker image installs headless Chromium with `--with-deps` for the crawler.
- Widget nginx config: 1-year immutable caching for content-hashed bundles, `must-revalidate` for stable names — correct.
- Widget production bundle must be built with `VITE_WIDGET_API_BASE_URL` set (empty is a local/dev gate; `check-assets.mjs` rejects loopback hosts).

---

## 9. Findings Register

| #   | Sev | Finding                                                                                               | Location                                                                           |
| --- | --- | ----------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| 1   | P1  | Real production secrets in plaintext `.env.production` (untracked today, but unrotated and shareable) | `.env.production`                                                                  |
| 2   | P1  | JWT HMAC key length not validated; dev fallback <32 bytes (RFC 7518 warning in test output)           | `backend/core/config.py`, `docker/compose.yml:49`                                  |
| 3   | P2  | Billing history renders current plan price, not persisted charged amount                              | `backend/api/routes/billing.py:89-96`                                              |
| 4   | P2  | Worker shutdown closes browser only; Mongo/Redis/ARQ connections not closed                           | `backend/workers/app.py:32-35`                                                     |
| 5   | P2  | `autoUpgrade` mounts only the first `<webchat-widget>`; multi-embed silently unsupported              | `apps/widget/src/core/embed.ts:28`                                                 |
| 6   | P2  | Widget `mount()` on an already-mounted host is unguarded (duplicate UI appended)                      | `apps/widget/src/core/mount.ts`                                                    |
| 7   | P2  | Dashboard `request()` has no timeout/AbortController; hung fetch never settles                        | `apps/dashboard/src/lib/api.ts:108`                                                |
| 8   | P3  | Mixed-dimension vector chunks filtered silently (log would aid debugging)                             | `backend/repositories/vector/`                                                     |
| 9   | P3  | Worker, browser, and payment-provider code paths thinly tested (0–63%)                                | `backend/workers/*`, `services/ingestion/browser.py`, `services/billing/payments/` |
| 10  | P3  | `ruff format` not enforced (55 files drift)                                                           | `pyproject.toml`                                                                   |

---

## 10. Bottom Line

Production-ready with discipline: layered architecture, tenant isolation enforced at the repository layer, strong authn/authz, real abuse protections, hermetic and extensive tests, and sane deployment config. The blocking work is **process/ops**: rotate and externalize the secrets in `.env.production` (they are not in the repo today, but are live and plaintext), enforce JWT secret strength, and address the P2 items above before relying on billing history, multi-embed pages, or long-lived worker/API processes.
