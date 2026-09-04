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

| Concern                           | Value                                                                                                                                    |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Broker / cache / rate-limit store | Redis 7+ (single instance; Docker `redis:7` in dev; managed Redis in prod)                                                               |
| Worker entrypoint                 | `python -m backend.workers` (separate Docker image/process from the API)                                                                 |
| Retry policy                      | Max 3 attempts (`max_tries = 3`); ARQ default retry behaviour (no custom backoff configured — `retry_backoff` 1 s, `retry_jitter` 0.5 s) |
| Job timeouts                      | Unified ARQ `job_timeout = 600` (10 min) for all jobs (`backend/workers/app.py`)                                                         |

## Task Registry (`backend/workers/tasks.py`)

| Task                                    | Queue / Purpose                                                |
| --------------------------------------- | -------------------------------------------------------------- |
| `ping()`                                | Worker health-check                                            |
| `send_email(payload)`                   | All transactional email (Phase 2)                              |
| `crawl_website(crawl_job_id)`           | Playwright crawl → extract → clean → store documents (Phase 4) |
| `process_document(document_id)`         | Embed one document: chunk → embed → store (Phase 5)            |
| `process_website_documents(website_id)` | Fan a website's documents out as per-document jobs (Phase 5)   |

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

### Phase ordering clarification (post-ADR-008)

ADR-008 lists _Phase 7 → Widget SDK, Phase 8 → Dashboard_. However, the Dashboard was **implemented in Phase 7**, ahead of the Widget SDK, because the APIs the dashboard consumes were already available: authentication (Phase 2), website management (Phase 3), crawl jobs (Phase 4), knowledge (Phase 5), RAG chat + usage (Phase 6), and health endpoints (Phase 1).

- The **Widget SDK is moved to Phase 8** (public config/sessions/chat endpoints, scoped session tokens, rate limits, <100 KB embed script — per ADR-004).
- `docs/06-Implementation-Plan.md` is the **active implementation roadmap** and governs phase ordering. Its _Phase 7 — Dashboard_ and _Phase 8 — Widget SDK_ sections reflect the implemented order.
- Phase completion is tracked by the per-phase verification reports in `docs/`.

Where the two documents differ, `docs/06` ordering wins for scheduling; ADR-008 remains authoritative for the scope of each phase and for the decision register.

---

# 9. ADR-009: AI Provider Abstraction & Fallback

## Decision

Introduce a thin provider abstraction for the two AI capabilities the platform consumes — **LLM answer generation** and **text embedding** — so no application code is coupled to a single vendor. Application code keeps depending on the existing Protocols (`GenerationClient` in `backend/ai/gemini.py`, `EmbeddingClient` in `backend/services/knowledge/embedding.py`); the concrete provider now resolves through a registry + fallback chain.

## Provider interfaces

Both capabilities keep the exact Protocol surfaces already used by the RAG service and the knowledge worker (Liskov Substitution: any provider is a drop-in for the Protocol):

- `GenerationClient` — `stream_generate(system, messages)` streaming answer deltas; `usage` for token capture (ADR-005 §5.8).
- `EmbeddingClient` — `embed(texts)` → one vector per text; `usage` for usage rollups; `dimensions` for the compatibility check.

## Registry (`backend/ai/registry.py`)

- Providers register by name with a factory and, optionally, a `required_key` (settings field whose presence gates availability).
- `GENERATION_PROVIDER_ORDER` / `EMBEDDING_PROVIDER_ORDER` (JSON arrays in `.env`) resolve into ordered client chains:
  - a provider whose required key is missing is **skipped with a warning** (one unconfigured provider cannot break the chain);
  - an **unknown name fails fast** with `ProviderConfigurationError` (500) rather than silently serving a degraded chain.
- Embedding chains **warn when providers report differing vector dimensions** (e.g. Gemini 3072 vs Ollama 768), because switching embedding providers on a mixed corpus corrupts `$vectorSearch`.

## Fallback semantics (`backend/ai/router.py`)

- **Generation is pre-stream only:** providers are tried in order, but once a provider starts emitting deltas the stream is committed. A mid-stream failure is re-raised (surfaces as an SSE `error`) rather than restarting the answer, so the client never sees a truncated answer followed by a fresh complete one.
- **Embedding is atomic** (no streaming), so a failed provider is fully retried on the next one.
- An **empty chain raises at call time** (`GenerationUnavailableError` / `EmbeddingUnavailableError`), preserving the no-key behaviour the direct Gemini client had.
- `active_provider` reports which provider served the last request (observability); token usage always reflects the _serving_ provider.

## Providers

| Capability | Provider   | Client                                                              | Default model                       | API key              |
| ---------- | ---------- | ------------------------------------------------------------------- | ----------------------------------- | -------------------- |
| Generation | Gemini     | `GoogleGeminiClient` (`backend/ai/gemini.py`)                       | `gemini-2.5-flash`                  | `GEMINI_API_KEY`     |
| Generation | Groq       | `GroqGenerationClient` (`backend/ai/providers/groq.py`)             | `openai/gpt-oss-20b`                | `GROQ_API_KEY`       |
| Generation | OpenRouter | `OpenRouterGenerationClient` (`backend/ai/providers/openrouter.py`) | `meta-llama/llama-3.3-70b-instruct` | `OPENROUTER_API_KEY` |
| Embedding  | Gemini     | `GoogleEmbeddingClient` (`backend/services/knowledge/embedding.py`) | `gemini-embedding-001`              | `GEMINI_API_KEY`     |
| Embedding  | Ollama     | `OllamaEmbeddingClient` (`backend/ai/providers/ollama.py`)          | `nomic-embed-text` (768-dim)        | none (self-hosted)   |

Groq and OpenRouter share an OpenAI-compatible `chat/completions` streaming implementation (`backend/ai/providers/openai_compat.py`): one connection pool per process, a single `build_chat_payload` (with `stream_options.include_usage` for token capture), robust SSE parsing, and HTTP status mapping (401/402/403/429 → unavailable so the chain moves on; other statuses → `GenerationError`). Raw SDK/`httpx` errors never escape the AI layer (00-AI-Development-Rules §18).

## Configuration

Default chains are Gemini-only; production fails fast unless at least one generation key and a non-empty embedding order are configured. New env vars (all in `.env.example`):

- `GENERATION_PROVIDER_ORDER` / `EMBEDDING_PROVIDER_ORDER`
- `GROQ_API_KEY` / `GROQ_MODEL`
- `OPENROUTER_API_KEY` / `OPENROUTER_MODEL`
- `AI_PROVIDER_TIMEOUT_SECONDS`
- `EMBEDDING_DIMENSIONS`
- `OLLAMA_BASE_URL` / `OLLAMA_MODEL` / `OLLAMA_EMBEDDING_DIMENSIONS`

## Why not a single "generic LLM SDK"

- **No new runtime dependency.** Groq/OpenRouter are called over `httpx` (already a dependency) instead of adding `openai`; Gemini keeps the `google-genai` SDK.
- **Keeps existing Protocols stable.** The RAG service and knowledge worker required zero signature changes; wiring simply switches `GoogleGeminiClient()` / `GoogleEmbeddingClient()` for `build_generation_fallback()` / `build_embedding_fallback()`.
- **Fail-fast configuration** catches typos in the order lists instead of silently degrading.

---

# 10. Decision Register

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
| ADR-009 | AI provider abstraction: registry + ordered fallback (Gemini→Groq→OpenRouter gen; Gemini/Ollama embed)          | Approved |

---

# 11. Documentation Reconciliation

| Doc                          | Reconciliation action                                                                                                            |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `00-AI-Development-Rules.md` | §5 folder structure superseded by ADR-007                                                                                        |
| `02-TRD.md`                  | §3 Celery superseded by ADR-002; §10 token/signing detail per ADR-003/004                                                        |
| `05-Backend-Schema.md`       | Collections updated per ADR-005 (widgets/users deltas, new `refresh_tokens`, `usage_records`, `feedback`, TTL, `schema_version`) |
| `06-Implementation-Plan.md`  | Phases amended per ADR-008; folder structure per ADR-007                                                                         |
| `04-UI-UX-Brief.md`          | No conflicts remain once widget fields (ADR-005) are in schema                                                                   |

This ADR must be kept in sync with `05` and `06` as the codebase evolves.

---

# 12. Phase 4 Completion Notes (August 2026)

Phase 4 (Data Ingestion Engine) is implemented and verified end-to-end. Notes below describe how the phase was built against the decisions in this record; they do not change any ADR.

- **Execution model:** the crawler runs inside the ARQ worker (ADR-002) using a shared Playwright/Chromium browser process, serialized by a process-wide semaphore (`CRAWL_MAX_CONCURRENT=2`) for memory safety.
- **SSRF mitigation (TRD §10):** a per-request validator re-resolves DNS for every navigation and redirect (DNS-rebinding defense) and blocks private/loopback/link-local/CGNAT/metadata ranges plus internal hostnames; seeds blocked this way fail the job permanently instead of retrying.
- **Incremental ingestion:** `documents` are idempotently upserted on the unique `(tenant_id, website_id, url)` key with a SHA-256 content checksum, so Phase 5 can re-embed only changed content.
- **Retention (ADR-005):** `crawl_jobs` carry a 30-day TTL; crawl audit entries a 1-year TTL.
- **Deferred to Phase 5:** semantic chunking, embedding generation, vector storage, duplicate detection across embeddings.

---

# 13. Phase 5 Completion Notes (August 2026)

Phase 5 (Knowledge Processing) is implemented and verified end-to-end. Notes below describe how the phase was built against the decisions in this record; they do not change any ADR.

- **Chunking (TRD §6):** `backend/services/knowledge/chunker.py` is a dependency-free approximate tokenizer (word + punctuation runs); defaults `KNOWLEDGE_CHUNK_SIZE_TOKENS=700` / `KNOWLEDGE_CHUNK_OVERLAP_TOKENS=100` follow the TRD. Windows prefer sentence/paragraph boundaries; the window always advances by at least one token, guaranteeing termination even when a boundary cut sits close to the window start.
- **Embedding (ADR-008 Phase 5):** `GoogleEmbeddingClient` (`backend/services/knowledge/embedding.py`) calls `text-embedding-004` via the Google GenAI async SDK (`client.aio.models.embed_content`, verified against SDK 2.17). Batches of `EMBEDDING_BATCH_SIZE=32` retry with exponential backoff + full jitter up to `EMBEDDING_MAX_RETRIES=5`, bounded by `EMBEDDING_REQUEST_TIMEOUT_SECONDS`. `EmbeddingUnavailableError` fails fast (no retries) when `GEMINI_API_KEY` is missing; all other errors normalize to `EmbeddingError` after retry exhaustion. Usage (calls/characters/estimated_tokens/failures) is captured per batch and reported through an optional hook.
- **Layering:** the processor depends only on the `VectorRepository` and `EmbeddingClient` Protocols (00-AI-Development-Rules §13); the ARQ worker binds MongoDB-backed repositories and injects the embedding client via `ctx["embedding_client"]` at startup (ADR-002 container pattern, mirroring the crawl job).
- **Worker/queue config (ADR-002):** `process_document` and `process_website_documents` are registered alongside `ping`, `send_email`, and `crawl_website`. The worker applies a unified `job_timeout = 600` (10 min) to all jobs, `max_tries = 3`, and ARQ default retry behaviour (no custom backoff). ADR-002's Configuration and Task Registry tables were corrected to match this implementation after the Phase 5 audit (`docs/Phase-5-Verification-Report.md`).
- **Vector storage:** `knowledge_chunks` (docs/05 §7) with a unique `(tenant_id, website_id, document_id, chunk_index)` index for idempotent writes; Atlas `$vectorSearch` with `filter` on tenant+website, `numCandidates=max(top_k*10, 50)`, and `score` via `$meta: vectorSearchScore`. Missing Atlas index surfaces an actionable error. `KnowledgeChunk.to_out()` never exposes the embedding vector.
- **Incremental re-indexing:** `documents.knowledge_checksum` is compared to the Phase 4 content checksum; unchanged documents with existing chunks skip embedding entirely, changed documents delete + rebuild their chunks. Empty pages record a clean `ready`/`0` state.
- **Status surface:** `WebsiteOut` and the dashboard website card expose `knowledge_status` / `knowledge_documents` / `knowledge_chunks` / `last_knowledge_at`; failures audit `KNOWLEDGE_FAILED`.
- **Deferred to Phase 6:** retrieval (question embedding + vector search), prompt building, Gemini generation, conversation memory, and cross-embedding duplicate detection.

---

# 14. Phase 6 Completion Notes (August 2026)

Phase 6 (RAG Pipeline) is implemented and verified (`docs/Phase-6-Verification-Report.md`). Notes below describe how the phase was built against the decisions in this record; they do not change any ADR.

- **Answer pipeline (ADR-008 Phase 6):** `backend/services/chat/rag_service.py::stream_answer` implements the full retrieve-before-generate flow: validate website ownership → sanitize the question → persist the user turn → embed the question (reuses the Phase 5 `GoogleEmbeddingClient`) → tenant-filtered Top-5 `$vectorSearch` → deduplicate context + load conversation memory → build the versioned prompt → stream Gemini 2.5 Flash → persist the answer with sources/tokens/latency → touch the session → atomic `$inc` rollup into `usage_records` (ADR-005 §5.5/§5.8).
- **Hallucination guard:** the model is never called without retrieved context. Empty knowledge base or zero search hits return the fixed TRD §8 fallback (`UNKNOWN_ANSWER_FALLBACK`, `docs/02-TRD.md §8`); internal errors surface only as generic SSE `error` events.
- **Conversation memory (docs/05 §9-10):** `chat_sessions` (unique `session_id`, `expires_at` TTL) + `messages` (tenant/session/created_at index + `created_at` TTL). `list_recent` returns the latest `CHAT_MEMORY_TURNS` turns in chronological order (sort DESC, limit, reverse).
- **Versioned prompts:** `backend/prompts/rag.py` catalog keyed by `RAG_PROMPT_VERSION` (config/env); `sanitize_question` strips control characters and caps length; reference material is delimited and labelled untrusted (prompt-injection defense, TRD §8).
- **Token usage capture (ADR-005 §5.8):** per-message `input_tokens`/`output_tokens` on `messages`; daily atomic rollups (`chats`, `messages`, `input_tokens`, `output_tokens`, `vector_queries`) in `usage_records`. `embeddings_created`/`crawl_pages` counters remain reserved for the Phase 5/9 worker rollups.
- **TTL alignment (ADR-005 §5.7):** `chat_sessions` uses the Mongo deadline pattern (`expires_at` with `expireAfterSeconds=0`, matching `CHAT_RETENTION_DAYS`); `messages` and `usage_records` TTLs are derived from `CHAT_RETENTION_DAYS` / `USAGE_RETENTION_DAYS` config.
- **Deferred to Phase 7:** dashboard chat UI/conversations surface; widget SDK chat (public endpoints + scoped session tokens, ADR-004) is Phase 8. Cross-embedding duplicate detection remains open for the analytics phase.

---

# 15. Phase 9 Completion Notes (August 2026)

Phase 9 (AI Provider Abstraction & Fallback, ADR-009) is implemented. Notes below describe how it was built against this record; they do not change any ADR.

- **Stable Protocols:** `GenerationClient` and `EmbeddingClient` were unchanged at the call site. The embedding Protocol gained only `usage` and `dimensions` read-only properties (already present on the concrete clients) so the fallback router can report the serving provider's usage and the registry can detect dimension mismatches.
- **Wiring:** the RAG dependency (`backend/api/deps.py::get_rag_service`) and the ARQ worker (`backend/workers/app.py` startup) now build the chains via `build_generation_fallback()` / `build_embedding_fallback()` instead of hardcoding `GoogleGeminiClient` / `GoogleEmbeddingClient`. Building a chain never touches the network — provider clients are created lazily.
- **No API surface change:** routes, SSE event shapes, and worker task signatures are untouched; fallback is purely internal. A Gemini-only environment behaves exactly as before Phase 9.
- **Deferred:** analytics rollups for `embeddings_created`/`crawl_pages`, UI improvements, and adding further providers to the chains.

---

# End of Architecture Decision Record
