# WebChat AI - Architecture Decision Record (ADR)

**Version:** 1.0  
**Project Name:** WebChat AI  
**Document Type:** Architecture Decision Record  
**Status:** Approved (Source of Truth)  
**Author:** Ritu Raj  
**Last Updated:** August 2026

---

# 0. Purpose & Scope

This document is the **binding source of truth** for all architecture and technical decisions before development begins.

It resolves every gap, conflict, and open question identified during the pre-development review of documents `00` through `06`.

**Supersedes / modifies:**

- `02-TRD.md` §3 (Celery replaced by ARQ), §5 (queue architecture), §11 (token strategy detail)
- `05-Backend-Schema.md` (widget fields, onboarding, usage, feedback, TTL, schema versioning, new collections)
- `00-AI-Development-Rules.md` §5 and `06-Implementation-Plan.md` §3 (folder structure unified)
- `06-Implementation-Plan.md` (phase list amended; admin panel, usage/feedback added)

Where any earlier document conflicts with this ADR, **this ADR wins.**

---

# 1. ADR-001: Email Provider

## Decision

**Provider:** Resend (transactional email API).
**Local development:** Mailpit (Docker) — no external dependency, captured emails in a local UI.
**Python integration:** official `resend` SDK wrapped behind a `MailService` interface (injectable and mockable in tests).

## Responsibilities

| Feature            | Implementation                                                                        |
| ------------------ | ------------------------------------------------------------------------------------- |
| Email Verification | Sent at signup; contains a signed verification link                                   |
| Password Reset     | Sent on "forgot password"; contains a signed reset link                               |
| Transactional      | Welcome, notify crawl failure, notify index ready, account suspended, security alerts |

## Email Templates

- Templates live in `backend/templates/emails/` (Jinja2 + inline CSS).
- Rendering: server-side template → plain text + HTML parts.
- Email sending runs **asynchronously** through an ARQ task (`send_email`) — never blocks an API request.

## Token Design for Email Links (no extra collections)

| Use                | Token                                                                     | Lifetime | Invalidation                                                              |
| ------------------ | ------------------------------------------------------------------------- | -------- | ------------------------------------------------------------------------- |
| Email verification | Signed JWT (`purpose=email_verify`, `sub=user_id`, `jti`)                 | 24 h     | Idempotent; sets `email_verified=true`                                    |
| Password reset     | Signed JWT (`purpose=password_reset`, `sub=user_id`, `pwd_token_version`) | 30 min   | `pwd_token_version` incremented on every reset → all prior tokens invalid |

- Store only the token **version** on the user (integer, default `0`), not the tokens.
- `RESEND_API_KEY` in env; dev fallback logs the email to console / Mailpit.

## Environment Variables

```
RESEND_API_KEY=
EMAIL_FROM=WebChat AI <no-reply@webchatai.example>
EMAIL_BASE_URL=https://app.webchatai.example
```

---

# 2. ADR-002: Queue System

## Decision

**Queue:** ARQ + Redis (replaces Celery from the original TRD).

## Rationale

- The entire backend is **async-first** (FastAPI + Motor). ARQ is natively asyncio and runs cleanly against `redis.asyncio`.
- Playwright (crawler) has an async API; keeping the worker async avoids the Celery ↔ async-Motor friction flagged as a HIGH risk in review.
- ARQ provides retries, timeouts, job results, and health checks with minimal dependencies.

## Configuration

| Concern                           | Value                                                                      |
| --------------------------------- | -------------------------------------------------------------------------- |
| Broker / cache / rate-limit store | Redis 7+ (single instance; Docker `redis:7` in dev; managed Redis in prod) |
| Worker entrypoint                 | `python -m backend.workers` (separate Docker image/process from the API)   |
| Retry policy                      | Max 3 attempts, exponential backoff (`2^n × 30s`), timeouts per job        |
| Job timeouts                      | Crawl 10 min · Embed 5 min · Email 30 s · Re-index 30 min                  |

## Task Registry (`backend/workers/tasks.py`)

| Task                                | Queue / Purpose                                               |
| ----------------------------------- | ------------------------------------------------------------- |
| `crawl_website(crawl_job_id)`       | Playwright crawl → extract → clean → chunk → embed → store    |
| `reindex_website(website_id, mode)` | Incremental re-index (detects changed pages via content hash) |
| `send_email(payload)`               | All transactional email                                       |
| `finalize_crawl(crawl_job_id)`      | Post-job status, analytics, notification                      |

## Deviations from original docs

- `02-TRD.md` §3 listed Celery — **superseded** by ARQ (recorded in §0).
- Upstash Redis (TRD §3 hosting) is acceptable **only if** the chosen managed Redis supports the RESP/TLS protocol that `redis.asyncio` requires. Verify before Phase 1; otherwise use Redis Cloud / a small dedicated Redis.

---

# 3. ADR-003: Authentication Token Strategy

## Decision

**Stateless access tokens + stateful rotating refresh tokens + double-submit CSRF.**

| Token                | Type                                                                                                   | Storage                                           | Lifetime                              |
| -------------------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------- | ------------------------------------- |
| Access token         | JWT (HS256) — claims: `sub`, `tenant_id`, `role`, `token_type=access`, `jti`                           | **Frontend memory only** (React state)            | 15 min                                |
| Refresh token        | Opaque, 256-bit random, **SHA-256 hashed** in DB                                                       | `refresh_tokens` collection + **httpOnly cookie** | 30 days (rolling)                     |
| Widget session token | JWT — claims: `widget_id`, `tenant_id`, `website_id`, `visitor_id`, `token_type=widget_session`, `jti` | Client-side (widget), short-lived                 | 15 min (renewed via session endpoint) |

## Why in-memory access tokens

- Avoids `localStorage`/`sessionStorage` XSS exposure (a top OWASP concern).
- Access token is lost on full page reload → frontend silently refreshes using the httpOnly cookie and retries the original request once.

## Cookie Strategy

```
refresh_token  HttpOnly; Secure; SameSite=Lax; Path=/api/auth; Max-Age=30d
csrf_token     NOT HttpOnly (readable by JS); Secure; SameSite=Lax; Path=/; rotated at login
```

- Refresh cookie is scoped to `Path=/api/auth` so it is never sent to non-auth endpoints.
- `SameSite=Lax` blocks cross-site cookie sends on most requests (CSRF mitigation layer 1).

## Refresh Token Rotation & Reuse Detection

- Every `/api/auth/refresh` issues a **new** refresh token, marks the presented one `revoked`, and stores `replaced_by`.
- If a **revoked/replaced** token is ever presented again → **revoke all refresh tokens for that user**, flag the account, write an `audit_log` entry (`REFRESH_REUSE_DETECTED`).
- Refresh tokens are stored **hashed** (SHA-256) in `refresh_tokens` — a DB leak does not expose usable tokens.

## CSRF Protection (dashboard API only)

- **Double-submit cookie pattern:** server sets a non-httpOnly `csrf_token` cookie; the frontend echoes it in the `X-CSRF-Token` header on every mutating (non-GET) request; the backend rejects if cookie ≠ header.
- Applies only to cookie-authenticated dashboard routes. The public widget API uses session tokens (no cookies) and is exempt.

## Session Lifecycle

| Event            | Behavior                                                                        |
| ---------------- | ------------------------------------------------------------------------------- |
| Login / Signup   | Issue access token (in memory) + refresh token (cookie + DB)                    |
| 401 on API       | Frontend calls `/api/auth/refresh` silently, retries once                       |
| Refresh fails    | Redirect to `/login`, clear cookies                                             |
| Logout           | Revoke all user refresh tokens, clear cookies, clear in-memory token, audit log |
| Suspended tenant | Login and refresh rejected; widget config endpoint returns disabled             |

## Passwords

- Argon2id via `argon2-cffi` with sensible parameters (memory 19 MiB, time 2, parallelism 1).
- Password policy enforced with Pydantic validation (min 8 chars, complexity, max 72 bytes).

---

# 4. ADR-004: Widget Security

## Decision

**Public, secret-free widget + server-issued scoped session tokens.** The widget is embedded on customer websites, so it can never contain a secret.

## Endpoints (public namespace `/api/widget/v1`)

| Endpoint                                | Auth                                    | Purpose                                                                      |
| --------------------------------------- | --------------------------------------- | ---------------------------------------------------------------------------- |
| `GET /api/widget/v1/config/{widget_id}` | None (public config)                    | Theme, welcome message, suggested questions, branding. Cached in Redis 5 min |
| `POST /api/widget/v1/sessions`          | Rate-limited only                       | Body `{widget_id, visitor_id}` → returns `{session_token, expires_at}`       |
| `POST /api/widget/v1/chat` (SSE stream) | `Authorization: Bearer <session_token>` | Chat; tenant-scoped retrieval + Gemini streaming                             |

## "Signed requests" (resolving TRD §10 ambiguity)

- The TRD/PRD mention _"Signed Widget Requests."_ Since a client-embedded script cannot hold a secret, "signing" is implemented as **server-issued session tokens** bound to `widget_id + tenant_id + website_id + visitor_id`.
- The widget first obtains a session token from `/sessions`, then presents it as a Bearer token. Backend validates the token signature, expiry, and that the bound `widget_id` is enabled and its website is `ready`.
- **`widget_secret` (HMAC-SHA256)** is generated per widget for future **server-to-server** integrations only (Slack/WhatsApp/webhooks). It is stored hashed, returned **once** at creation, and is **never** shipped in the client JS.

## Tenant Validation Flow (every widget request)

```
Request → widget_id → load widget (Redis-cached) → tenant_id, website_id, enabled, website.status
   → issue/validate scoped session token
   → every downstream DB/vector query filters by tenant_id + website_id
   → no cross-tenant access possible
```

## Abuse & Rate Protection

| Guard                  | Policy                                                                                                             |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Per-widget rate limit  | 60 messages / min (Redis sliding window)                                                                           |
| Per-visitor rate limit | 20 messages / min                                                                                                  |
| Session validity       | Max 24 h, sliding                                                                                                  |
| Message limits         | Max length 2,000 chars; max 50 messages per visitor session                                                        |
| Content                | Basic spam filtering; sanitize all HTML on render (widget escapes by default)                                      |
| CORS                   | Public widget endpoints: `Access-Control-Allow-Origin: *` (tokens are required); dashboard API: strict same-origin |

## Public vs Protected API Split

| Surface                                | Auth                             |
| -------------------------------------- | -------------------------------- |
| Dashboard API `/api/*` (except widget) | JWT + tenant + RBAC              |
| Public widget API `/api/widget/v1/*`   | widget_id + scoped session token |
| Admin API `/api/admin/*`               | JWT + `role=admin`               |

---

# 5. ADR-005: Database Schema Updates

These deltas update `05-Backend-Schema.md`. Collections not listed are unchanged except for `schema_version` and TTL notes.

## 5.1 Global Rules

- **`schema_version: int`** added to `websites`, `widgets`, `knowledge_chunks` to support future migrations. Default `1`.
- Every query still **must** include `tenant_id` (unchanged, non-negotiable).
- **TTL indexes** introduced via dedicated `expires_at` fields (see §5.7).

## 5.2 `users` — added fields

```json
{
  "_id": "UUID",
  "tenant_id": "UUID",
  "name": "John Doe",
  "email": "john@example.com",
  "password_hash": "argon2_hash",
  "role": "owner", // owner | admin
  "status": "active", // active | suspended | pending_email
  "email_verified": false,
  "onboarding_completed": false, // NEW
  "onboarding_step": "welcome", // NEW: welcome | connect_website | index_website | embed_widget | done
  "pwd_token_version": 0, // NEW: invalidates old reset tokens
  "last_login": "ISODate",
  "created_at": "ISODate",
  "updated_at": "ISODate",
  "schema_version": 1
}
```

Indexes: `email` (unique), `tenant_id`, `status`.

## 5.3 `widgets` — extended fields (resolves UI/UX ↔ schema drift)

```json
{
  "_id": "UUID",
  "tenant_id": "UUID",
  "website_id": "UUID",
  "widget_id": "UUID", // public identifier
  "theme": "light", // light | dark | auto
  "position": "bottom-right", // bottom-left | bottom-right
  "primary_color": "#2563eb",
  "accent_color": "#4f46e5", // NEW
  "font_size": "md", // NEW: sm | md | lg
  "logo_url": null, // NEW
  "avatar_url": null, // NEW
  "welcome_message": "Hi! How can I help you?",
  "placeholder": "Type your question...", // NEW
  "suggested_questions": [], // NEW: string[], max 5, each ≤ 120 chars
  "branding": true, // show "Powered by WebChat AI"
  "dark_mode": false, // NEW (widget-level default)
  "auto_open": false, // NEW
  "enabled": true,
  "widget_secret_hash": null, // NEW: HMAC secret, hashed, shown once
  "schema_version": 1,
  "created_at": "ISODate",
  "updated_at": "ISODate"
}
```

Indexes: `widget_id` (unique), `tenant_id`, `website_id` (unique per tenant).

## 5.4 NEW collection: `refresh_tokens`

```json
{
  "_id": "UUID",
  "tenant_id": "UUID",
  "user_id": "UUID",
  "token_hash": "sha256_of_opaque_token", // unique
  "expires_at": "ISODate",
  "created_at": "ISODate",
  "last_rotated_at": "ISODate",
  "revoked_at": null,
  "replaced_by": "UUID",
  "schema_version": 1
}
```

Indexes: `token_hash` (unique), `tenant_id`, `user_id`, `expires_at` (TTL, 40 days).

## 5.5 NEW collection: `usage_records`

Daily tenant usage rollup — enables Phase 9 analytics and future billing.

```json
{
  "_id": "UUID",
  "tenant_id": "UUID",
  "website_id": "UUID",
  "date": "2026-08-07", // "YYYY-MM-DD"
  "counters": {
    "chats": 0,
    "messages": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "embeddings_created": 0,
    "vector_queries": 0,
    "crawl_pages": 0
  },
  "created_at": "ISODate",
  "updated_at": "ISODate"
}
```

Indexes: unique `(tenant_id, website_id, date)`, `tenant_id`, `date`. TTL 3 years on `updated_at`.

## 5.6 NEW collection: `feedback`

Moved out of the _future_ list into v1 (PRD: "visitor submit feedback"; UI: "user satisfaction").

```json
{
  "_id": "UUID",
  "tenant_id": "UUID",
  "website_id": "UUID",
  "session_id": "UUID",
  "message_id": "UUID",
  "rating": 4, // 1-5
  "category": "helpful", // helpful | wrong | incomplete | offensive | other
  "comment": "",
  "created_at": "ISODate"
}
```

Indexes: `tenant_id`, `created_at`, `rating`. TTL 2 years on `created_at`.

## 5.7 TTL Index Summary (data retention)

| Collection                      | Retention                   | TTL field    |
| ------------------------------- | --------------------------- | ------------ |
| `audit_logs`                    | 1 year                      | `created_at` |
| `chat_sessions`                 | 90 days (configurable)      | `expires_at` |
| `messages`                      | 90 days (configurable)      | `created_at` |
| `crawl_jobs`                    | 30 days                     | `created_at` |
| `refresh_tokens`                | 40 days                     | `expires_at` |
| `usage_records`                 | 3 years                     | `updated_at` |
| `feedback`                      | 2 years                     | `created_at` |
| `knowledge_chunks` / `websites` | Until deleted (soft delete) | —            |

## 5.8 Token usage capture

- Gemini response `usage_metadata` (input/output tokens) is captured per message in the RAG service and written into `usage_records.counters`.
- Storage: raw per-message tokens on `messages` (`input_tokens`, `output_tokens`) for audit; rollups in `usage_records`.

---

# 6. ADR-006: Admin Panel Scope

## Scope

A super-admin surface to operate the platform. Introduced as an explicit phase (was specified in the PRD/TRD but missing from the implementation plan).

## Features

| Area               | Capabilities                                                                               |
| ------------------ | ------------------------------------------------------------------------------------------ |
| Tenant Management  | List, search, view detail, suspend / activate, change plan                                 |
| Platform Analytics | Total users, tenants, conversations, messages, token usage, error rate, MRR-ready counters |
| Crawl Monitoring   | Global crawl job queue view, retry / cancel stuck jobs                                     |
| Audit Logs         | View, filter (action, tenant, user, date range)                                            |
| Account Actions    | Suspend user, reset user password, force logout (revoke refresh tokens)                    |
| Settings           | Platform feature flags (future), admin API keys                                            |

## Required APIs (`/api/admin/*`, guarded by `role=admin`)

| Method | Path                                                          | Purpose                                                  |
| ------ | ------------------------------------------------------------- | -------------------------------------------------------- |
| GET    | `/api/admin/tenants`                                          | List tenants (paginated, search)                         |
| GET    | `/api/admin/tenants/{tenant_id}`                              | Tenant detail (websites, usage, status)                  |
| PATCH  | `/api/admin/tenants/{tenant_id}`                              | Suspend / activate / plan change                         |
| POST   | `/api/admin/tenants/{tenant_id}/users/{user_id}/suspend`      | Suspend user                                             |
| POST   | `/api/admin/tenants/{tenant_id}/users/{user_id}/force-logout` | Revoke all refresh tokens                                |
| GET    | `/api/admin/stats`                                            | Platform KPIs (rollup from `usage_records`, `analytics`) |
| GET    | `/api/admin/crawl-jobs`                                       | Global crawl queue monitor                               |
| POST   | `/api/admin/crawl-jobs/{job_id}/retry`                        | Retry failed job                                         |
| GET    | `/api/admin/audit-logs`                                       | Audit log viewer (filters + pagination)                  |

## Required collections

- **No new collections.** Reuses `tenants`, `users`, `websites`, `crawl_jobs`, `audit_logs`, `analytics`, `usage_records`.
- `users.role = "admin"` designates super admins.
- **Suspension semantics:** `tenants.status=suspended` → login/refresh rejected, widget config endpoint returns disabled; `users.status=suspended` → that user locked out.

## Admin UI

- Dashboard app gains an `/admin/*` section (visible only to `role=admin`).
- Stricter rate limits and a dedicated audit trail for admin actions.

---

# 7. ADR-007: Final Canonical Folder Structure

Resolves the conflict between `00-AI-Development-Rules.md` §5 (missing `schemas/`, `scripts/`) and `06-Implementation-Plan.md` §3. **No random folders** are added beyond this tree.

```text
webchat-ai/
├── apps/
│   ├── dashboard/                          # Next.js 15 dashboard (admin + tenant)
│   │   └── src/
│   │       ├── app/                        # App Router pages
│   │       ├── components/
│   │       │   ├── ui/                     # shadcn/ui primitives
│   │       │   └── layout/                 # sidebar, navbar, providers
│   │       ├── features/                   # feature modules
│   │       │   ├── auth/
│   │       │   ├── websites/
│   │       │   ├── knowledge/
│   │       │   ├── conversations/
│   │       │   ├── analytics/
│   │       │   ├── widget-config/
│   │       │   ├── api-keys/
│   │       │   ├── settings/
│   │       │   └── admin/
│   │       ├── lib/                        # api client, auth, query client
│   │       ├── hooks/
│   │       └── types/
│   └── widget/                             # framework-independent SDK
│       ├── src/
│       │   ├── core/                       # session mgmt, api client
│       │   ├── ui/                         # launcher, chat window, messages
│       │   ├── stream/                     # SSE client
│       │   ├── markdown/                   # markdown renderer
│       │   ├── theme/                      # theme + tokens
│       │   └── config/                     # public widget config types
│       └── vite.config.ts                  # IIFE + ESM builds (<100KB)
├── backend/
│   ├── api/
│   │   ├── deps.py                         # auth/tenant dependencies
│   │   ├── middleware.py                   # security headers, request-id
│   │   └── routes/
│   │       ├── auth.py
│   │       ├── users.py
│   │       ├── websites.py
│   │       ├── widgets.py
│   │       ├── chat.py                     # dashboard conversation views
│   │       ├── widget.py                   # public widget endpoints (v1)
│   │       ├── analytics.py
│   │       ├── api_keys.py
│   │       ├── feedback.py
│   │       └── admin/                      # tenants, stats, audit, crawl-jobs
│   ├── core/                               # config, database, redis, security, errors
│   ├── models/                             # Motor document models
│   ├── schemas/                            # Pydantic v2 (request/response)
│   ├── services/                           # business logic (auth, website, ingestion, chat, analytics, usage, email)
│   ├── repositories/                       # DB access + storage abstractions
│   │   └── vector/                         # base + mongo | qdrant | pinecone | weaviate
│   ├── workers/                            # ARQ worker + tasks
│   │   ├── app.py
│   │   ├── tasks.py
│   │   └── jobs/                           # crawl, embed, email, reindex
│   ├── ai/                                 # embeddings, llm, rag, chunker, prompts loader
│   ├── prompts/                            # versioned prompt files (Git-tracked)
│   ├── templates/
│   │   └── emails/                         # Jinja2 email templates
│   ├── utils/                              # ssrf guard, sanitizer, url, crypto
│   └── main.py
├── docs/                                   # 00-07 design docs (this ADR = 07)
├── docker/                                 # compose files + Dockerfiles (api, worker, widget)
├── scripts/                                # dev/ops helper scripts
├── tests/                                  # backend (pytest) + frontend/e2e (vitest/playwright)
├── package.json
├── pnpm-workspace.yaml                     # monorepo tooling
├── .env.example
├── .gitignore
└── README.md
```

**Layering invariants (unchanged from Rule §6):** routes → validate → services (business logic) → repositories (DB/vector). No business logic in routes. `VectorRepository` is an interface — application code never depends on MongoDB Vector Search directly (Rule §13).

---

# 8. ADR-008: Updated Implementation Phases

Amended from `06-Implementation-Plan.md`. One phase must be fully complete (tested + documented) before the next begins.

| Phase | Name                        | Key changes from original plan                                                                                       |
| ----- | --------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| 1     | Project Foundation          | Add `pnpm` workspaces, `ruff`+`mypy`, ARQ worker skeleton, Mailpit for local email, health endpoints                 |
| 2     | Authentication              | ADR-001 (Resend email) + ADR-003 (token strategy, refresh rotation, CSRF)                                            |
| 3     | Website Management          | URL validation with SSRF-safe pre-check; widget creation with `widget_secret`                                        |
| 4     | Ingestion Engine            | ARQ (not Celery); Playwright crawler; robots.txt + caps + SSRF guard; retry policy                                   |
| 5     | Knowledge Processing        | Chunking, embeddings, vector storage, `schema_version`, page content-hash incremental re-index                       |
| 6     | RAG Pipeline                | Tenant-filtered retrieval (Top-5), versioned prompts, Gemini SSE streaming, token usage capture, hallucination guard |
| 7     | Widget SDK                  | Public endpoints (config/sessions/chat), scoped session tokens, rate limits, <100KB build, embed script              |
| 8     | Dashboard                   | All tenant pages incl. onboarding wizard, conversations, API keys, knowledge base; loading/empty/error states        |
| 9     | Analytics, Usage & Feedback | `usage_records` rollups, token usage, charts, feedback endpoint + UI (ADR-005)                                       |
| 10    | Admin Panel                 | ADR-006 scope (new phase)                                                                                            |
| 11    | Security Hardening          | Full audit: headers, CSP, HSTS, prompt-injection guard, abuse limits (audit, not first pass)                         |
| 12    | Performance Optimization    | Redis caching, lazy loading, index tuning; hit 500 ms API / 3 s first-token / 100 KB widget                          |
| 13    | Testing                     | Complete unit/integration/E2E/security suites; ≥90% critical path                                                    |
| 14    | Deployment                  | Vercel (dashboard) + Render (api+worker) + Atlas + Redis + Resend                                                    |
| 15    | Monitoring                  | Logs, health, queue/AI/DB metrics; OTel + Sentry ready                                                               |
| 16    | Documentation               | Install, deploy, API, env, troubleshooting, contributing; sync docs 00–07                                            |

**Ordering note:** Analytics/usage was moved after the dashboard so its backends exist first; Admin Panel is now a first-class phase; security hardening remains an audit on top of security implemented from Phase 2 onward.

---

# 9. Decision Register

| ADR     | Decision                                                                                                        | Status   |
| ------- | --------------------------------------------------------------------------------------------------------------- | -------- |
| ADR-001 | Email: Resend + Mailpit (dev) behind `MailService`; signed JWT links                                            | Approved |
| ADR-002 | Queue: ARQ + Redis (replaces Celery)                                                                            | Approved |
| ADR-003 | Auth: in-memory JWT access + hashed opaque rotating refresh cookie + double-submit CSRF                         | Approved |
| ADR-004 | Widget: secret-free SDK + server-issued scoped session tokens + per-widget/visitor rate limits                  | Approved |
| ADR-005 | Schema: widget fields, onboarding, `usage_records`, `feedback`, `refresh_tokens`, `schema_version`, TTL indexes | Approved |
| ADR-006 | Admin panel: tenants, stats, audit, crawl monitor via `/api/admin/*`; no new collections                        | Approved |
| ADR-007 | Canonical folder structure (resolves `00` vs `06` conflict)                                                     | Approved |
| ADR-008 | 16-phase plan incl. admin + usage/feedback; security from Phase 2                                               | Approved |

---

# 10. Documentation Reconciliation

| Doc                          | Reconciliation action                                                                                                            |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `00-AI-Development-Rules.md` | §5 folder structure superseded by ADR-007                                                                                        |
| `02-TRD.md`                  | §3 Celery superseded by ADR-002; §10 token/signing detail per ADR-003/004                                                        |
| `05-Backend-Schema.md`       | Collections updated per ADR-005 (widgets/users deltas, new `refresh_tokens`, `usage_records`, `feedback`, TTL, `schema_version`) |
| `06-Implementation-Plan.md`  | Phases amended per ADR-008; folder structure per ADR-007                                                                         |
| `04-UI-UX-Brief.md`          | No conflicts remain once widget fields (ADR-005) are in schema                                                                   |

This ADR must be kept in sync with `05` and `06` as the codebase evolves.

---

# 11. Phase 4 Completion Notes (August 2026)

Phase 4 (Data Ingestion Engine) is implemented and verified end-to-end. Notes below describe how the phase was built against the decisions in this record; they do not change any ADR.

- **Execution model:** the crawler runs inside the ARQ worker (ADR-002) using a shared Playwright/Chromium browser process, serialized by a process-wide semaphore (`CRAWL_MAX_CONCURRENT=2`) for memory safety.
- **SSRF mitigation (TRD §10):** a per-request validator re-resolves DNS for every navigation and redirect (DNS-rebinding defense) and blocks private/loopback/link-local/CGNAT/metadata ranges plus internal hostnames; seeds blocked this way fail the job permanently instead of retrying.
- **Incremental ingestion:** `documents` are idempotently upserted on the unique `(tenant_id, website_id, url)` key with a SHA-256 content checksum, so Phase 5 can re-embed only changed content.
- **Retention (ADR-005):** `crawl_jobs` carry a 30-day TTL; crawl audit entries a 1-year TTL.
- **Deferred to Phase 5:** semantic chunking, embedding generation, vector storage, duplicate detection across embeddings.

---

# End of Architecture Decision Record
