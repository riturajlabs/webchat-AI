# WebChat AI — Railway Deployment Guide

Deploy the WebChat AI monorepo to **Railway** using the existing Docker
architecture. This is the Railway-specific companion to `docs/DEPLOYMENT.md` and
`docs/ORACLE_FREE_VM_DEPLOYMENT.md`; the generic production stack is unchanged.

No application code changes are required. This document only describes how the
existing Docker services map onto Railway and which environment variables to
set.

---

## 1. Overview

WebChat AI is a multi-tenant RAG SaaS with five deployable containers, built
from the repo root:

| Container   | Role                                              |
| ----------- | ------------------------------------------------- |
| `gateway`   | nginx reverse proxy — the **only** public entry   |
| `api`       | FastAPI REST API + readiness checks               |
| `worker`    | ARQ background worker (crawler, embeddings, mail) |
| `dashboard` | Next.js 15 standalone SPA (client-side app)       |
| `widget`    | static host for the widget SDK bundles            |

External services: **MongoDB Atlas** (database), **Redis** (queue/cache/rate
limits), **Resend** (email), **Gemini** (+ optional Groq/OpenRouter) for AI,
and **Stripe**/**Razorpay** for payments.

## 2. Railway service topology

```
                      Railway public domain (HTTPS, Railway-terminated)
                                        │
                        ┌───────────────▼────────────────┐
                        │  gateway  (nginx, PUBLIC)      │  ENABLE_TLS=0
                        │  listens on $PORT              │
                        └──┬──────────┬───────────┬──────┘
                     /api/ │          │ /widget/  │ /
              ┌────────────▼──┐  ┌────▼────────┐  │
              │ api (private) │  │ widget      │  │
              │  :8000        │  │ (static)    │  │
              └──────┬────────┘  └─────────────┘  │
                     │      ┌──────────────┐      │
                     │      │ worker       │      │  (no HTTP endpoint)
                     │      │ (private)    │      │
                     │      └──────────────┘      │
              ┌──────▼────────────────────────────▼─┐
              │ dashboard (private) Next.js :3000   │
              └─────────────────────────────────────┘

   External (unchanged): MongoDB Atlas ── Redis (Upstash or Railway) ── Resend
                         ── Gemini/Groq/OpenRouter ── Stripe/Razorpay
```

## 3. Public vs private services

- **Public:** only `gateway`. Railway assigns it a public domain (e.g.
  `webchat-ai-production-XXXX.up.railway.app`) and terminates HTTPS.
- **Private:** `api`, `dashboard`, `widget`, `worker`. They get no public
  domain and are reachable from `gateway` over **Railway private networking**
  using the per-service private URLs.
- The browser talks **only** to `gateway`. The dashboard JS calls the API
  through the same origin (`/api/*`), and the widget SDK calls it via the
  public origin too. Never expose `api` or `dashboard` publicly — see
  §13 (single-origin requirement).

## 4. Service configuration table

| SERVICE   | SOURCE    | DOCKERFILE                    | START COMMAND                                         | PUBLIC? | PORT                                   | HEALTHCHECK                            | DEPENDENCIES                                          |
| --------- | --------- | ----------------------------- | ----------------------------------------------------- | ------- | -------------------------------------- | -------------------------------------- | ----------------------------------------------------- |
| gateway   | repo root | `docker/Dockerfile.nginx`     | image CMD (`nginx`)                                   | **yes** | Railway `$PORT` (default 80)           | HTTP `GET /healthz`                    | api, dashboard, widget (reachable)                    |
| api       | repo root | `docker/Dockerfile.api`       | `uvicorn backend.main:app --host 0.0.0.0 --port 8000` | no      | 8000                                   | HTTP `GET /api/health/ready` (200/503) | MongoDB Atlas, Redis                                  |
| worker    | repo root | `docker/Dockerfile.worker`    | `python -m backend.workers`                           | no      | none                                   | **none** (process health only)         | MongoDB Atlas, Redis                                  |
| dashboard | repo root | `docker/Dockerfile.dashboard` | `node apps/dashboard/server.js`                       | no      | 3000 (`PORT`/`HOSTNAME` env respected) | HTTP `GET /`                           | api (for readiness), build-time `NEXT_PUBLIC_API_URL` |
| widget    | repo root | `docker/Dockerfile.widget`    | nginx static server                                   | no      | 80                                     | HTTP `GET /webchat-widget.iife.min.js` | build-time `VITE_WIDGET_API_BASE_URL`                 |

Notes:

- Railway injects `PORT` into every service container. The gateway renders its
  vhost to listen on `$PORT` (fallback 80). The dashboard's Next.js standalone
  server already honors `PORT`/`HOSTNAME` at runtime.
- Railway healthchecks are HTTP probes (except when disabled). `worker` has no
  HTTP endpoint — see §11.
- Compose-level healthchecks (`docker-compose.prod.yml`) are ignored by
  Railway and remain for local/CI use only.

## 5. Gateway configuration

The nginx vhosts are rendered at container startup from templates by
`/docker-entrypoint.d/20-render-config.sh`. Only these variables are
substituted (a fixed allowlist — nginx runtime variables like `$host` are
untouched).

| Variable                   | Meaning                                      | Compose default  | Railway value                        |
| -------------------------- | -------------------------------------------- | ---------------- | ------------------------------------ |
| `PORT`                     | HTTP vhost listen port                       | `80`             | injected by Railway (e.g. `8080`)    |
| `NGINX_API_UPSTREAM`       | api `host:port`                              | `api:8000`       | private URL of the api service       |
| `NGINX_WIDGET_UPSTREAM`    | widget `host:port`                           | `widget:80`      | private URL of the widget service    |
| `NGINX_DASHBOARD_UPSTREAM` | dashboard `host:port`                        | `dashboard:3000` | private URL of the dashboard service |
| `NGINX_HTTPS_PORT`         | TLS vhost listen port (`ENABLE_TLS=1` only)  | `443`            | unused (see §6)                      |
| `ENABLE_TLS`               | `1` = nginx terminates TLS; `0` = plain HTTP | `0`              | **`0`**                              |

On Railway, set the three `NGINX_*_UPSTREAM` values to the **private** URLs
Railway assigns to each service (under Project → Service → Networking →
Private Networking, e.g. `api.production.<project>.up.railway.app`). Do not
prefix a scheme — the config renders `proxy_pass http://<upstream>;`.

Compose behavior is unchanged: with no overrides the same image resolves to
`api:8000` / `widget:80` / `dashboard:3000`, so `docker-compose.prod.yml` and
the CI smoke stack keep working without Railway-specific values.

## 6. Railway TLS model

Railway terminates HTTPS at its edge and forwards plain HTTP to the gateway
container. Therefore the gateway must **not** terminate TLS itself:

- `ENABLE_TLS=0` → the HTTP vhost only; no certificate files are read.
- Do not mount `TLS_CERT_DIR` on Railway, and leave `COOKIE_SECURE=true`
  (browsers see HTTPS because Railway terminates it; the API trusts
  `X-Forwarded-Proto: https` via `TRUST_PROXY=true`).

The `ENABLE_TLS=1` path (nginx-terminated TLS with certs at
`/etc/nginx/tls`) is preserved for self-managed deployments and is unaffected.

## 7. Environment variables

### Build-time (set on the service's Build settings in Railway)

| Variable                   | Service   | Purpose                                                       |
| -------------------------- | --------- | ------------------------------------------------------------- |
| `NEXT_PUBLIC_API_URL`      | dashboard | inlined into the client bundle; **must** be the public origin |
| `VITE_WIDGET_API_BASE_URL` | widget    | inlined into the SDK bundle; public API origin                |

### Runtime — non-secret

| Variable                                                                                 | Service(s)                            |
| ---------------------------------------------------------------------------------------- | ------------------------------------- |
| `ENVIRONMENT=production`                                                                 | api, worker                           |
| `DEBUG=false`                                                                            | api, worker                           |
| `PORT`, `NGINX_*_UPSTREAM`, `NGINX_HTTPS_PORT`, `ENABLE_TLS=0`                           | gateway                               |
| `ALLOWED_HOSTS`                                                                          | api (public + private hostnames)      |
| `CORS_ORIGINS`                                                                           | api (JSON array of the public origin) |
| `PUBLIC_BASE_URL`                                                                        | api (public origin)                   |
| `WIDGET_API_BASE_URL`, `WIDGET_SCRIPT_URL`                                               | api (public origin / bundle URL)      |
| `TRUST_PROXY=true`                                                                       | api, worker                           |
| `RATE_LIMIT_ENABLED=true`                                                                | api, worker                           |
| `COOKIE_SECURE=true`                                                                     | api, worker                           |
| `MONGODB_DB`, Redis prefix/tuning, widget limits, RAG/crawl tuning, `SUPER_ADMIN_EMAILS` | api, worker                           |

### Runtime — secrets (use Railway Variables / secret references; placeholders only)

| Variable                                                             | Notes                                       |
| -------------------------------------------------------------------- | ------------------------------------------- |
| `JWT_SECRET`                                                         | `openssl rand -hex 32`; ≥32 bytes required  |
| `MONGODB_URI`                                                        | existing Atlas connection string            |
| `REDIS_URL`                                                          | Upstash `rediss://...` or Railway Redis URL |
| `RESEND_API_KEY`, `EMAIL_FROM`                                       | verified sender                             |
| `GEMINI_API_KEY` (+ `GROQ_API_KEY`, `OPENROUTER_API_KEY` as desired) | ≥1 generation key                           |
| `PAYMENT_PROVIDER=stripe` (or razorpay) + its keys/webhook secrets   | real gateway required                       |

Never store real credential values in this document or in git.

## 8. Required public-origin variables

Once Railway generates the **gateway public URL**, every public-origin variable
must use it (no `localhost`, no loopback):

```
PUBLIC_BASE_URL=https://webchat-ai-production-XXXX.up.railway.app
CORS_ORIGINS=["https://webchat-ai-production-XXXX.up.railway.app"]
ALLOWED_HOSTS=webchat-ai-production-XXXX.up.railway.app
WIDGET_API_BASE_URL=https://webchat-ai-production-XXXX.up.railway.app
WIDGET_SCRIPT_URL=https://webchat-ai-production-XXXX.up.railway.app/widget/webchat-widget.iife.min.<hash>.js
```

**BUILD-TIME** (set before the service builds; changing them later requires a
redeploy):

```
NEXT_PUBLIC_API_URL=https://webchat-ai-production-XXXX.up.railway.app
VITE_WIDGET_API_BASE_URL=https://webchat-ai-production-XXXX.up.railway.app
```

`NEXT_PUBLIC_API_URL` is inlined into the dashboard client bundle at build time
(`apps/dashboard/src/lib/api.ts`); `VITE_WIDGET_API_BASE_URL` is inlined into
the widget bundles (`apps/widget/src/config/types.ts`). The backend additionally
enforces that `CORS_ORIGINS`, `ALLOWED_HOSTS`, `WIDGET_SCRIPT_URL` and
`WIDGET_API_BASE_URL` are non-loopback HTTPS origins in production — a boot
error otherwise.

## 9. Redis

Two supported choices — pick one and put its connection URL in `REDIS_URL`:

1. **Upstash (external):** `REDIS_URL=rediss://<user>:<pass>@<region>.upstash.io:<port>`.
   REST + TLS, no extra Railway resource. Ensure `rediss://` (TLS) is used.
2. **Railway Redis plugin:** add the Redis plugin to the project and copy the
   generated `REDIS_URL` from its Variables tab into api, worker and gateway
   dependencies. Same variable name; the plugin value already uses the correct
   internal URL.

`REDIS_URL` must be a RESP URL reachable from the api and worker services
(`redis://` or `rediss://`). The backend uses it for the ARQ broker, rate
limiting and the widget config cache. If a cache-only value is ever needed,
set `REDIS_PREFIX` to namespace keys.

## 10. MongoDB Atlas

The existing Atlas cluster stays the source of truth. Set `MONGODB_URI`
(existing connection string) and `MONGODB_DB` on **api** and **worker**. Do not
provision a database on Railway.

- Indexes are created idempotently by the API at startup (`init_indexes()`).
- On the free tier (no `$vectorSearch`), the repository falls back to exact
  brute-force retrieval automatically — no code change.
- Atlas must allow connections from Railway egress (IP allowlist / network
  access) — use MongoDB Atlas "Access from anywhere" only if you accept the
  trade-off, or use Atlas PrivateLink/network peering for production hardening.

## 11. Worker

- Runs the ARQ worker (`python -m backend.workers`): crawl jobs, document
  processing/embeddings, transactional email, with retries and Redis-backed
  persistence.
- Requires Playwright/Chromium — already installed in the worker image
  (`playwright install --with-deps chromium`).
- **No HTTP endpoint, no healthcheck.** Do not configure an HTTP healthcheck
  path in Railway for the worker.
- Railway should treat the worker as a **process-health service**: if the
  process exits, Railway restarts it (default restart policy). Configure the
  service with "Start command" left as the image default and no public domain.
- The existing compose healthcheck (Redis ping) remains for
  local/CI only and is not part of the image.

## 12. Deployment order

Create the project and add services in this order:

1. **Railway project** — create, connect the GitHub repo.
2. **Redis** — add the Redis plugin (or use existing Upstash and skip this).
3. **api** — add service from `docker/Dockerfile.api` (root context), private.
4. **worker** — add service from `docker/Dockerfile.worker`, private, no port.
5. **dashboard** — add service from `docker/Dockerfile.dashboard`, private;
   set build-time `NEXT_PUBLIC_API_URL`.
6. **widget** — add service from `docker/Dockerfile.widget`, private; set
   build-time `VITE_WIDGET_API_BASE_URL`.
7. **gateway** — add service from `docker/Dockerfile.nginx`, **public**; set
   `PORT` handling (Railway injects it), the three `NGINX_*_UPSTREAM` private
   URLs and `ENABLE_TLS=0`.
8. **Environment variables** — set the runtime vars from §7/§8 on each service
   (secrets via Railway Variables).
9. **Deploy** — trigger builds.
10. **Health checks** — confirm `GET https://<gateway>/healthz` returns `ok`
    and `GET https://<gateway>/api/health/ready` returns `"status":"ready"`.
11. **End-to-end testing** — register, create a website, crawl, chat (widget),
    billing checkout webhook, super-admin overview.

## 13. Single-origin requirement

The dashboard **must** stay behind the same public origin as the API. Reasons:

- Auth refresh cookies are `HttpOnly; Secure; SameSite=Lax; Path=/api/auth`
  (`backend/api/routes/auth.py`). `SameSite=Lax` cookies are not sent on
  cross-origin `fetch`, so splitting dashboard and API onto separate public
  domains breaks token refresh.
- CSRF uses a double-submit pattern: the browser reads the non-HttpOnly
  `csrf_token` cookie via `document.cookie` and echoes it in `X-CSRF-Token`
  (`backend/api/deps.py`). A cookie set on a different origin is not readable
  by the dashboard script, so the flow fails.
- The dashboard client already calls `/api/*` relative to its own origin, so
  proxying everything through `gateway` requires no frontend change.

**Do not** give the api or dashboard their own public Railway domains. Route
all browser traffic through the gateway origin.

## 14. Troubleshooting

| Symptom                    | Likely cause                                                                            | Fix                                                                            |
| -------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| gateway `502 Bad Gateway`  | upstream env not set / wrong private URL                                                | verify `NGINX_*_UPSTREAM` on the gateway service; check gateway logs           |
| API not reachable          | `ALLOWED_HOSTS` missing the gateway domain; api not started                             | add the public hostname to `ALLOWED_HOSTS`; check api logs                     |
| dashboard blank page       | `NEXT_PUBLIC_API_URL` wrong at build time; JS error                                     | rebuild dashboard with the public origin; browser devtools network tab         |
| widget not loading         | `WIDGET_SCRIPT_URL`/`VITE_WIDGET_API_BASE_URL` not the public origin; bundle not cached | rebuild widget; check `GET /widget/webchat-widget.iife.min.<hash>.js`          |
| CORS errors                | `CORS_ORIGINS` missing the gateway origin or loopback value                             | set `CORS_ORIGINS=["https://<gateway>"]`; restart api                          |
| cookie/CSRF errors         | dashboard/API split onto separate public domains                                        | return to single-origin via the gateway (see §13)                              |
| worker crash               | Playwright sandbox/memory or Redis broker                                               | ensure `CRAWL_NO_SANDBOX=true`, enough memory; worker restarts on process exit |
| Redis connection failure   | wrong `REDIS_URL`/TLS                                                                   | use `rediss://` for Upstash or the Railway Redis URL; check reachability       |
| MongoDB connection failure | Atlas allowlist / bad `MONGODB_URI`                                                     | allow Railway egress; verify the connection string                             |
| api fails to boot          | production validators reject a value                                                    | read the api logs — CORS/hosts/keys/JWT must be non-loopback and complete      |

## 15. Rollback

Railway keeps previous deployments per service.

- **Redeploy a previous version:** open the service → Deployments → select the
  previous successful deployment → **Redeploy**. Railway rebuilds that exact
  commit with its recorded settings.
- **Rollback with env changes:** the nginx upstreams and public-origin
  variables are runtime env — reverting them requires a redeploy of the
  gateway and, for the build-time URLs, a rebuild of dashboard/widget.
- **Data safety:** MongoDB and Redis hold all state, so rolling back a service
  never loses data; `init_indexes()` and ARQ jobs are idempotent/persistent.
- After any rollback, re-run the §12 health checks before traffic is
  considered healthy.
