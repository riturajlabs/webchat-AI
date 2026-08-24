# WebChat AI v1.0.0 — Deployment Readiness Report

**Audit date:** 2026-08-14
**Target release:** v1.0.0
**Method:** static audit of Dockerfiles, compose, environment configuration, production URL/CORS wiring, and database setup. No code was modified.

---

## 1. Executive Summary

The application stack is **functionally complete and deployable**, but it is
currently only provisioned for **local development**. There is **no production
compose file or IaC manifest**, the dashboard image **cannot receive the
production API URL at build time**, and MongoDB Atlas vector-search requires a
**manually created index** that is not automated. These are the three blockers
that must be closed before a production release.

| Check                                       | Status               | Blocking?         |
| ------------------------------------------- | -------------------- | ----------------- |
| Docker images (api/dashboard/widget/worker) | READY (with caveats) | 1 fix needed      |
| Production environment configuration        | PARTIAL              | Yes               |
| Production URLs & CORS                      | PARTIAL              | Yes (URL wiring)  |
| Database requirements (Mongo/Redis/indexes) | PARTIAL              | Yes (Atlas index) |
| Deployment pipeline / orchestration         | MISSING              | Yes               |

---

## 2. Ready Items

- **All four Dockerfiles are multi-stage and production-shaped:**
  - `docker/Dockerfile.api` — uv-synced, frozen lockfile, no dev deps, cached
    dependency layer, uvicorn entrypoint, `EXPOSE 8000`.
  - `docker/Dockerfile.dashboard` — Node 22 + pinned pnpm 11.13.1, standalone
    Next.js output (`.next/standalone`), `NODE_ENV=production`, non-privileged
    port 3000.
  - `docker/Dockerfile.widget` — builds the SDK with a configurable
    `VITE_WIDGET_API_BASE_URL` build arg, ships nginx serving content-hashed
    bundles with immutable caching.
  - `docker/Dockerfile.worker` — installs Playwright Chromium for the crawler
    (`--with-deps`), ARQ entrypoint `python -m backend.workers`.
- **Reproducible dependency installs** — `uv sync --frozen`, `pnpm install --frozen-lockfile`,
  pinned tool versions.
- **Build-time validation gates** — widget build runs `check-assets.mjs`
  (rejects loopback hosts in baked-in URLs, verifies bundle self-containment);
  the API's `Settings._validate_production_security()` fails fast on weak
  production secrets and loopback widget URLs.
- **Comprehensive `.env.example`** (199 lines) documenting every runtime and
  build-time variable, with generated-secret guidance
  (`openssl rand -hex 32`).
- **Fail-safe prod config validator** (`backend/core/config.py:201`) — rejects
  JWT_SECRET < 32 bytes, no generation provider key, empty embedding order,
  loopback `WIDGET_SCRIPT_URL` / `WIDGET_API_BASE_URL`.
- **Idempotent index creation** — `MongoDB.init_indexes()` runs at API startup
  (`backend/main.py:41`) and creates all unique/partial/TTL indexes.
- **Health/readiness probes** — `/api/health` (liveness) and
  `/api/health/ready` (fail-closed 503 when Mongo or Redis is unreachable).
- **Public widget CORS** — `WidgetCORSHeadersMiddleware` serves `ACAO: *` on
  `/api/widget/*` while dashboard CORS stays origin-scoped.
- **No secrets committed** — `.dockerignore` excludes `.env*`, `git ls-files`
  shows no `.env`/keys; current `.env` is gitignored.
- **Email provider selection** — Mailpit in development, Resend in production
  (`backend/services/mail/__init__.py`); `RESEND_API_KEY` is required and
  raises at startup in non-development.

---

## 3. Missing Configuration (Blockers)

### B1 — No production compose / IaC manifest

Only `docker/compose.dev.yml` exists. It hardcodes development values:

- `ENVIRONMENT: development`, `DEBUG: "true"`
- `JWT_SECRET: dev-only-jwt-secret-change-me`
- `COOKIE_SECURE: "false"`
- `CORS_ORIGINS: ["http://localhost:3000"]`
- `PUBLIC_BASE_URL: http://localhost:3000`
- Mailpit in place of Resend

There is **no production compose, Helm chart, Terraform, Render/fly config, or
CI deploy workflow** (`.github/workflows/` has only `ci.yml`, which is test-only).

**Required action:** author a production compose file (or chosen IaC) that sets
`ENVIRONMENT=production`, `DEBUG=false`, real secrets via secret manager, the
production dashboard origin in `CORS_ORIGINS`, `COOKIE_SECURE=true`,
`TRUST_PROXY=true` (behind an LB), real `PUBLIC_BASE_URL`, and Resend settings.

### B2 — Dashboard image cannot receive the API URL at build time

The dashboard reads `NEXT_PUBLIC_API_URL` at build time
(`apps/dashboard/src/lib/api.ts`). `docker/Dockerfile.dashboard`:

- does **not** declare `ARG NEXT_PUBLIC_API_URL` / `ENV NEXT_PUBLIC_API_URL`, and
- is built in compose **without any `args:`** for the dashboard service.

Every dashboard image built today therefore bakes the fallback
`http://localhost:8000`. In production the dashboard would call the API on the
client's own machine.

**Required action:** add `ARG NEXT_PUBLIC_API_URL` (and re-export via `ENV`)
before the `pnpm build` step in `Dockerfile.dashboard`, and pass
`args: { NEXT_PUBLIC_API_URL: ... }` in the production compose build.

### B3 — MongoDB Atlas Vector Search index must be created manually

`MongoDB.init_indexes()` does **not** create the Atlas search index. Vector
retrieval requires a search index named `default` on
`knowledge_chunks.embedding` (`backend/repositories/vector/mongodb.py:74-86`).
Until it exists, `similarity_search` fails with a fail-fast error (the brute-force
fallback only triggers on Atlas-missing markers, not a missing index on Atlas).

**Required action (one-time Atlas setup):**

```json
{
  "name": "default",
  "type": "vectorSearch",
  "definition": {
    "fields": [
      { "type": "vector", "path": "embedding", "numDimensions": 1024, "similarity": "cosine" },
      { "type": "filter", "path": "tenant_id" },
      { "type": "filter", "path": "website_id" },
      { "type": "filter", "path": "embedding_provider" },
      { "type": "filter", "path": "embedding_model" },
      { "type": "filter", "path": "embedding_dimensions" },
      { "type": "filter", "path": "embedding_version" }
    ]
  }
}
```

`numDimensions` must match `EMBEDDING_DIMENSIONS` (1024 in the current production configuration).
Add this step to the release runbook.

---

## 4. Production Risks

| #   | Risk                                                                                                                                            | Severity | Mitigation                                                                                                                            |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| R1  | Containers run as **root** (no `USER` in any Dockerfile); `CRAWL_NO_SANDBOX=true` default is tied to a root runtime.                            | Medium   | Add non-root `USER` to api/dashboard/widget images; keep `--no-sandbox` off in production worker (Playwright Chromium needs sandbox). |
| R2  | `COOKIE_SECURE` is documented but **not validated** to be `true` in production. A misconfiguration leaks refresh tokens over HTTP.              | Medium   | Extend the prod validator to require `COOKIE_SECURE=true` when `ENVIRONMENT=production`.                                              |
| R3  | `TRUST_PROXY` defaults to `false`. Behind any reverse proxy / load balancer, client IP (used for rate limiting and audit) will be the proxy IP. | Medium   | Set `TRUST_PROXY=true` in production compose; it is already gated to trusted-proxy deployments.                                       |
| R4  | The dev `compose.dev.yml` exposes **Mailpit on 1025/8025** and hardcodes a known dev JWT secret — never deploy this file as-is.                 | High     | Use a dedicated production compose; rotate secrets.                                                                                   |
| R5  | **Worker has no healthcheck** and no liveness probe; a wedged worker silently stops processing crawls/embeddings/email.                         | Medium   | Add a worker healthcheck (e.g. ARQ's result / Redis ping) to the production compose and monitor queue lag.                            |
| R6  | `NEXT_PUBLIC_API_URL` and `VITE_WIDGET_API_BASE_URL` are **build-time baked**; a stale image can point at an old origin.                        | Low      | Build with correct args per environment; use `data-api-base-url` (`WIDGET_API_BASE_URL`) as the runtime override for the widget.      |
| R7  | `CORS_ORIGINS` defaults to localhost origins; if unset in production the dashboard cannot call the API.                                         | Medium   | Always set `CORS_ORIGINS` to the production dashboard origin(s).                                                                      |
| R8  | `cost_per_million_*` values are estimates used in the dashboard only; billing reconciles externally.                                            | Low      | Document that analytics costs are estimates.                                                                                          |
| R9  | No **TLS termination** in any image; every service expects a terminating proxy/LB.                                                              | Info     | Terminate TLS at the LB/proxy; the app sets `COOKIE_SECURE` accordingly.                                                              |
| R10 | No **backup/restore** runbook for Mongo data volumes or Atlas snapshots.                                                                        | Medium   | Enable Atlas continuous backups / take snapshots before release.                                                                      |

---

## 5. Required Environment Variables

### Runtime (API + worker), production

| Variable                   | Required                 | Notes                                                                            |
| -------------------------- | ------------------------ | -------------------------------------------------------------------------------- |
| `ENVIRONMENT`              | yes                      | `production` (triggers fail-fast validator)                                      |
| `DEBUG`                    | yes                      | `false` (also disables `/api/docs`)                                              |
| `JWT_SECRET`               | yes                      | ≥ 32 bytes; `openssl rand -hex 32`                                               |
| `MONGODB_URI`              | yes                      | Atlas `mongodb+srv://...`                                                        |
| `MONGODB_DB`               | yes                      | e.g. `webchat_ai`                                                                |
| `REDIS_URL`                | yes                      | Upstash/Redis Cloud RESP w/ TLS (`rediss://`)                                    |
| `REDIS_PREFIX`             | recommended              | per-env key isolation                                                            |
| `CORS_ORIGINS`             | yes                      | JSON array of production dashboard origins                                       |
| `PUBLIC_BASE_URL`          | yes                      | production dashboard origin (email links)                                        |
| `COOKIE_SECURE`            | yes                      | `true`                                                                           |
| `TRUST_PROXY`              | yes                      | `true` behind a trusted LB                                                       |
| `RESEND_API_KEY`           | yes                      | email delivery (Mailpit is dev-only)                                             |
| `EMAIL_FROM`               | yes                      | verified sender domain                                                           |
| `GEMINI_API_KEY`           | yes (or Groq/OpenRouter) | at least one generation provider                                                 |
| `EMBEDDING_PROVIDER_ORDER` | yes                      | e.g. `["gemini"]`                                                                |
| `EMBEDDING_DIMENSIONS`     | yes                      | must match the Atlas vector index (1024 in the current production configuration) |
| `WIDGET_SCRIPT_URL`        | yes                      | HTTPS URL of the **content-hashed** widget bundle on the CDN/host                |
| `WIDGET_API_BASE_URL`      | recommended              | HTTPS API origin; baked into embed snippets as `data-api-base-url`               |
| `RATE_LIMIT_ENABLED`       | recommended              | `true`                                                                           |
| `PERF_TIMING_LOG_ENABLED`  | no                       | keep off in production                                                           |

### Build-time (must be passed at image build)

| Variable                   | Image     | Notes                                                                   |
| -------------------------- | --------- | ----------------------------------------------------------------------- |
| `NEXT_PUBLIC_API_URL`      | dashboard | **B1 blocker** — ARG not yet wired in the Dockerfile                    |
| `VITE_WIDGET_API_BASE_URL` | widget    | already supported via build arg (default: same-origin `/api/widget/v1`) |

### Not currently defined / worth adding to `.env.example`

- `MONGO_ATLAS_VECTOR_INDEX_NAME` — not used by code; the index name `default`
  is hardcoded in `mongodb.py`. Add a settings field so the Atlas index name is
  configurable without a code change.
- `WORKER_MAX_JOBS` / `ARQ_MAX_JOBS` — currently hardcoded (`max_jobs = 10`).
- `ENVIRONMENT` values are free-form strings; document the canonical values
  (`development` / `production`).

---

## 6. Recommended Deployment Architecture

```
                      ┌────────────────────────────┐
   Customer browser   │   HTTPS (LB / reverse proxy)│
   (embed page)       └────────────┬───────────────┘
                                  │
        ┌─────────────┬───────────┴───────────┐
        ▼             ▼                       ▼
┌──────────────┐ ┌──────────────┐   ┌─────────────────────┐
│ Widget CDN / │ │  Dashboard   │   │  API (uvicorn, x N)  │
│ static host  │ │ (Next.js     │   │  /api/health/ready   │
│ nginx        │ │  standalone) │   └─────────┬───────────┘
│ :443         │ │ :3000        │             │
└──────────────┘ └──────────────┘             │
                                              ▼
                                  ┌──────────────────────┐
                                  │  Worker (ARQ, ≥1)     │
                                  │  crawler·embeddings·  │
                                  │  email                │
                                  └─────────┬────────────┘
                                            │
        ┌───────────────────────────────────┴────────────────────┐
        ▼                            ▼                           ▼
┌───────────────┐           ┌───────────────┐            ┌───────────────┐
│ MongoDB Atlas │           │  Redis        │            │  Resend       │
│ + Vector      │           │  (Upstash)    │            │  (email)      │
│ Search index  │           │  rate/cache/  │            │               │
│ (manual step) │           │  ARQ queue    │            │               │
└───────────────┘           └───────────────┘            └───────────────┘
```

**Runbook order:**

1. Provision MongoDB Atlas (M7+ tier with Vector Search) and create the
   `default` vector index on `knowledge_chunks.embedding` (**B3**).
2. Provision Redis (TLS) and Resend (verified domain).
3. Create a production `.env` / secret-manager entries from §5.
4. Fix **B1** (production compose) and **B2** (dashboard build arg), then build
   images passing `NEXT_PUBLIC_API_URL` and `VITE_WIDGET_API_BASE_URL`.
5. Deploy API + worker first; verify `/api/health/ready` is `200`.
6. Deploy dashboard; verify the admin/websites/analytics pages hit the API.
7. Host the widget bundle and set `WIDGET_SCRIPT_URL` to the content-hashed file.
8. Smoke-test the embed on an allowlisted domain; confirm a hostile origin is
   rejected (`403 WIDGET_ORIGIN_NOT_ALLOWED`).
9. Run the live E2E suite (`scripts/e2e-widget.sh`) against the deployed stack
   as a release gate.

---

## 7. Summary of Blocking Actions

| Blocker | Item                                            | Owner action                                                    |
| ------- | ----------------------------------------------- | --------------------------------------------------------------- |
| B1      | Production compose / IaC missing                | Author production deployment config with prod-safe env          |
| B2      | Dashboard `NEXT_PUBLIC_API_URL` not a build arg | Add `ARG/ENV` to `Dockerfile.dashboard` + pass in compose       |
| B3      | Atlas Vector Search index manual step           | Create `default` index on `knowledge_chunks.embedding` (1024-d) |

Plus: add non-root users (R1), validate `COOKIE_SECURE=true` in prod (R2), set
`TRUST_PROXY=true` (R3), and add a worker healthcheck (R5).

---

## Appendix — Files Reviewed

- `docker/Dockerfile.api`, `docker/Dockerfile.dashboard`, `docker/Dockerfile.widget`, `docker/Dockerfile.worker`
- `docker/compose.dev.yml`, `docker/nginx.widget.conf`, `.dockerignore`
- `.env.example`, `.env` (presence/secret-length check only — values not logged)
- `backend/core/config.py` (settings + prod validator), `backend/main.py`
- `backend/core/database.py` (`init_indexes`), `backend/core/redis.py`
- `backend/repositories/vector/mongodb.py` (`$vectorSearch`, index name `default`)
- `backend/services/mail/__init__.py` (provider selection), `backend/api/routes/health.py`
- `backend/api/middleware.py` (CORS), `apps/dashboard/src/lib/api.ts`, `apps/widget/src/config/types.ts`
- `.github/workflows/ci.yml` (no deploy workflow)
