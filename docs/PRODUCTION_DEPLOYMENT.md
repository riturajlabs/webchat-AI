# WebChat AI v1.0.0 — Production Deployment Guide

> **Superseded:** this guide describes the original multi-origin layout. The
> canonical Phase 16 deployment (single-origin nginx reverse proxy) is
> documented in `docs/DEPLOYMENT.md`. This file is kept for historical detail
> (MongoDB/Redis/Resend setup, E2E wiring).

This guide covers deploying WebChat AI to production with the provided
`docker-compose.prod.yml` stack, external MongoDB Atlas, managed Redis, and the
Resend email provider. It complements `docs/PRODUCTION_AUDIT_REPORT.md` and
`docs/DEPLOYMENT_READINESS_REPORT.md`.

> Read this end-to-end once before starting. There are manual one-time steps
> (MongoDB Atlas Vector Search index, Resend domain verification, DNS/proxy
> routing) that the stack does not automate.

---

## 1. Architecture Overview

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
└──────────────┘ └──────────────┘             ▼
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

- **API** — FastAPI on port 8000. Terminates nothing; expects a TLS proxy.
- **Worker** — ARQ background process (crawl, embeddings, email). No HTTP port.
- **Dashboard** — Next.js standalone server on port 3000. The API URL is baked
  in at **build time** (`NEXT_PUBLIC_API_URL`).
- **Widget** — nginx serving the SDK bundles on port 80, with immutable caching
  for content-hashed files.
- **MongoDB / Redis / Resend** — external, managed services.

---

## 2. Required Environment Variables

### 2.1 Runtime — API and Worker (identical set)

`docker-compose.prod.yml` fails fast (`:?`) when a required variable is
missing. Provide all of these via your secret manager / CI environment:

| Variable                        | Required | Notes                                                                   |
| ------------------------------- | -------- | ----------------------------------------------------------------------- |
| `JWT_SECRET`                    | **yes**  | ≥ 32 bytes. `openssl rand -hex 32`                                      |
| `MONGODB_URI`                   | **yes**  | Atlas `mongodb+srv://user:pass@cluster.mongodb.net/?...`                |
| `MONGODB_DB`                    | no       | default `webchat_ai`                                                    |
| `REDIS_URL`                     | **yes**  | TLS RESP URL, e.g. `rediss://user:pass@host:6379`                       |
| `REDIS_PREFIX`                  | no       | default `webchat_ai`; set per environment                               |
| `CORS_ORIGINS`                  | **yes**  | JSON array of dashboard origins, e.g. `["https://app.example.com"]`     |
| `PUBLIC_BASE_URL`               | **yes**  | production dashboard origin (used in email links)                       |
| `WIDGET_SCRIPT_URL`             | **yes**  | HTTPS URL of the **content-hashed** widget bundle                       |
| `WIDGET_API_BASE_URL`           | **yes**  | HTTPS API origin baked into embed snippets (`data-api-base-url`)        |
| `RESEND_API_KEY`                | **yes**  | Resend API key                                                          |
| `EMAIL_FROM`                    | **yes**  | verified sender, e.g. `WebChat AI <no-reply@example.com>`               |
| `GEMINI_API_KEY`                | one of   | at least one generation provider key required                           |
| `GROQ_API_KEY`                  | one of   | fallback generation provider                                            |
| `OPENROUTER_API_KEY`            | one of   | fallback generation provider                                            |
| `EMBEDDING_PROVIDER_ORDER`      | no       | default `["gemini"]`                                                    |
| `EMBEDDING_DIMENSIONS`          | **yes*** | must match the Atlas vector index (`3072` for gemini-embedding-001)     |
| `TRUST_PROXY`                   | no       | default `true` behind a proxy; `false` when the API is directly exposed |
| `COOKIE_SECURE`                 | no       | default `true` (HTTPS)                                                  |
| `API_KEY_RATE_LIMIT_PER_MINUTE` | no       | default `300`                                                           |

`*` `EMBEDDING_DIMENSIONS` must equal the `numDimensions` of the Atlas Vector
Search index. Changing it after ingestion corrupts retrieval.

### 2.2 Build-time (passed as `--build-arg`)

| Variable                   | Where     | Notes                                                |
| -------------------------- | --------- | ---------------------------------------------------- |
| `NEXT_PUBLIC_API_URL`      | dashboard | public HTTPS API origin reachable from the browser   |
| `VITE_WIDGET_API_BASE_URL` | widget    | wired to `WIDGET_API_BASE_URL` in `compose.prod.yml` |

`compose.prod.yml` passes `NEXT_PUBLIC_API_URL` and `WIDGET_API_BASE_URL` as
build args automatically.

### 2.3 Image tagging

```
REGISTRY=ghcr.io/<org>    # default ghcr.io/your-org
ORG=<org>
TAG=v1.0.0               # default v1.0.0
```

---

## 3. MongoDB Atlas Setup

1. **Create a cluster** — any tier with Atlas Vector Search enabled (M7+ / M10
   recommended for production).
2. **Create a database user** — Database Access → Add New Database User. Use a
   strong password and network access restrictions (e.g. your egress IPs, or a
   VPC peering endpoint). Scope the user to the `webchat_ai` database.
3. **Build the connection string:**
   ```
   mongodb+srv://<user>:<password>@<cluster>.mongodb.net/?retryWrites=true&w=majority
   ```
   Set it as `MONGODB_URI`.
4. **Create the Vector Search index (one-time, mandatory).** Open your cluster →
   **Search → Create Search Index** with the JSON editor:
   ```json
   {
     "name": "default",
     "type": "vectorSearch",
     "definition": {
       "fields": [
         { "type": "vector", "path": "embedding", "numDimensions": 3072, "similarity": "cosine" }
       ]
     }
   }
   ```
   The name **must** be `default` (hardcoded in
   `backend/repositories/vector/mongodb.py`). `numDimensions` **must** equal
   `EMBEDDING_DIMENSIONS`. After creating the index, wait for it to reach
   **Active** before enabling chat.
5. **Indexes are created automatically** — the API's `init_indexes()` runs at
   startup and creates all unique/partial/TTL indexes idempotently. Only the
   Vector Search index is manual.
6. **Enable backups** (Atlas Cloud Backup) and set a snapshot schedule.

> The local/MongoDB-Community brute-force fallback is for development only. In
> production on Atlas, `similarity_search` always uses the vector index.

---

## 4. Redis Setup

WebChat AI uses Redis for **rate limiting**, the **widget config cache**, and
the **ARQ job queue**. Use a managed TLS-enabled Redis (Upstash / Redis Cloud).

1. Create the database with TLS (`rediss://`).
2. Set `REDIS_URL`:
   ```
   rediss://<user>:<password>@<host>:<port>
   ```
   Upstash URLs already include credentials; Redis Cloud uses
   `rediss://default:<password>@<host>:<port>`.
3. Enable **persistence** (AOF/RDB) so queued ARQ jobs survive restarts; set a
   modest `maxmemory` policy compatible with the queue data.
4. The worker healthcheck pings Redis; a unreachable broker reports the worker
   as unhealthy.

---

## 5. Resend Email Setup

1. Create a Resend account and **verify your sending domain** (DNS: SPF/DKIM/
   MX records under the domain).
2. Create an API key (scoped to the sending domain) → `RESEND_API_KEY`.
3. Set `EMAIL_FROM` to a **verified sender**:
   ```
   EMAIL_FROM=WebChat AI <no-reply@example.com>
   ```
4. Email templates ship with the app (Jinja2). Mailpit is **development only** —
   the app selects Resend automatically when `ENVIRONMENT=production`.

---

## 6. Deploying the Stack

### 6.1 Prerequisites

- Docker with Buildx; `docker compose` v2.
- The external services from §3–§5 provisioned.
- A `.env`-style source for secrets **injected into the shell/CI**, never
  committed. Example pattern:
  ```bash
  export JWT_SECRET=$(openssl rand -hex 32)
  export MONGODB_URI="mongodb+srv://..."
  export REDIS_URL="rediss://..."
  export CORS_ORIGINS='["https://app.example.com"]'
  export PUBLIC_BASE_URL="https://app.example.com"
  export WIDGET_SCRIPT_URL="https://cdn.example.com/webchat-widget.iife.min.ABCDEF12.js"
  export WIDGET_API_BASE_URL="https://api.example.com"
  export NEXT_PUBLIC_API_URL="https://api.example.com"
  export RESEND_API_KEY="re_..."
  export EMAIL_FROM="WebChat AI <no-reply@example.com>"
  export GEMINI_API_KEY="AIza..."
  export TAG=v1.0.0
  ```

> **Build-time network access:** the dashboard build (via `next/font/google`)
> downloads the Geist fonts at image build time. The build host/CI runner must
> reach `fonts.googleapis.com` and `fonts.gstatic.com`; an air-gapped build
> environment will fail at the `pnpm --filter @webchat/dashboard build` step.

### 6.2 Build and start

```bash
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
```

### 6.3 Deployment order

The compose `depends_on` handles intra-stack ordering (dashboard waits for a
healthy API). Cross-service order for a green deployment:

1. MongoDB Atlas reachable + Vector Search index **Active**.
2. Redis reachable.
3. Resend domain verified + `RESEND_API_KEY` valid.
4. Start **api** and **worker** first. Verify readiness:
   ```bash
   curl -s http://localhost:8000/api/health/ready
   # {"status":"ready"}
   ```
   The API also hard-fails startup on weak `JWT_SECRET`, missing provider keys,
   or loopback widget URLs.
5. Start **dashboard**. Verify it loads and authenticates against the API.
6. Start **widget**. Verify the bundle is served:
   ```bash
   curl -sI https://cdn.example.com/webchat-widget.iife.min.js
   ```

### 6.4 Point DNS / proxy

Terminate TLS at your load balancer / proxy and route:

- `app.example.com` → dashboard container (3000)
- `api.example.com` → api container (8000)
- `cdn.example.com` (or a subpath on the API host) → widget container (80)

Set `TRUST_PROXY=true` so `X-Forwarded-For` is used for rate limiting. Keep
`COOKIE_SECURE=true` (default) so auth cookies are HTTPS-only.

---

## 7. Health Checks

| Service       | Endpoint / command                                          | Healthy when                                                        |
| ------------- | ----------------------------------------------------------- | ------------------------------------------------------------------- |
| API liveness  | `GET /api/health`                                           | 200; reports `database` + `redis` booleans                          |
| API readiness | `GET /api/health/ready`                                     | **200** `{"status":"ready"}` when Mongo+Redis up; **503** otherwise |
| Dashboard     | `wget -qO- http://127.0.0.1:3000`                           | 200                                                                 |
| Widget        | `wget --spider http://127.0.0.1/webchat-widget.iife.min.js` | 200                                                                 |
| Worker        | `python -c "... Redis.from_url(...).ping()"`                | Redis ping succeeds (process up + broker reachable)                 |

Use the API readiness probe as the load-balancer health target and the
dashboard/widget/worker probes for their respective orchestrator health checks.

---

## 8. Post-Deploy Verification Checklist

- [ ] `GET /api/health/ready` → 200
- [ ] Register a user; the verification email arrives via Resend; clicking the
      link verifies the account
- [ ] Create a website; the embed snippet references `WIDGET_SCRIPT_URL` and
      includes `data-api-base-url="https://api.example.com"`
- [ ] Crawl a page; `knowledge_chunks` are populated and
      `$vectorSearch` returns results (Atlas index Active)
- [ ] Embed the widget on an allowlisted domain; chat streams an answer via SSE
- [ ] Embed on a hostile domain → `403 WIDGET_ORIGIN_NOT_ALLOWED`
- [ ] Dashboard analytics/conversations/admin pages reach the API
- [ ] Worker logs show crawl + embedding jobs completing

Run the no-mock E2E suite against the deployed stack as a release gate:

```bash
E2E_BASE_URL=https://api.example.com \
E2E_MAILPIT_URL=... E2E_WIDGET_SCRIPT_URL=https://cdn.example.com/webchat-widget.iife.min.js \
  .venv/bin/pytest tests/e2e -v
```

(E2E uses Mailpit for mail capture; in production swap that to a capture
mailbox or Resend webhook inspection.)

---

## 9. Operating Notes

- **Scaling:** run multiple API replicas behind the LB; keep ≥1 worker (raise
  `max_jobs` / concurrency via ARQ settings if the crawl queue backs up).
- **Logs:** JSON structured logs; `PERF_TIMING_LOG_ENABLED` stays off in
  production.
- **Secrets rotation:** rotate `JWT_SECRET` only with a planned maintenance
  window (refresh tokens are hash-revoked on rotation).
- **Backups:** Atlas snapshots + Redis persistence are the recovery path; test
  a restore before release.
