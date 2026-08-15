# WebChat AI — Production Deployment Guide

This is the canonical deployment guide for WebChat AI (Phase 16). It covers the
single-origin production stack — an nginx reverse proxy in front of the API,
Next.js dashboard, and widget SDK host — plus the security hardening applied to
the backend.

Deep-dive companion docs: `docs/PRODUCTION_AUDIT_REPORT.md`,
`docs/DEPLOYMENT_READINESS_REPORT.md`, and the legacy
`docs/PRODUCTION_DEPLOYMENT.md` (superseded by this guide).

> Read this end-to-end once before starting. MongoDB Atlas Vector Search index
> creation, Resend domain verification, and DNS are manual one-time steps the
> stack does not automate.

---

## 1. Architecture

```
                          ┌───────────────────────────────────┐
        Browser ─────────▶│  nginx  :80 / :443 (ENABLE_TLS)   │  single origin
                          │  security headers · gzip · rate   │  https://app.example.com
                          │  limit · host allowlist pass-     │
                          │  through (Host → API)             │
                          └───────┬──────────┬────────┬───────┘
                                  │          │        │
                           /api/* │  /widget/*│  /*    │ /dashboard/*
                                  ▼          ▼        ▼
                          ┌────────────┐ ┌────────┐ ┌────────────┐
                          │  api:8000  │ │widget:80│ │dashboard: │
                          │  (uvicorn, │ │ (nginx  │ │ 3000 (Next│
                          │  ≥1)       │ │  static)│ │ standalone)│
                          └─────┬──────┘ └────────┘ └────────────┘
                                │
                          ┌─────▼─────┐         ┌──────────────┐
                          │ worker ≥1 │         │ Mongo Atlas  │
                          │ (ARQ)     │         │ + Vector idx │
                          └───────────┘         └──────────────┘
                              │ Redis (TLS) · Resend (email)
```

- **nginx** — the only published port. Routes `/api/*` → API, `/widget/*` →
  widget SDK host, everything else → dashboard (with a `/dashboard` alias).
  Adds edge rate limits, gzip, security headers, and `server_tokens off`.
  Optional TLS vhost (`ENABLE_TLS=1`) with certs mounted at `/etc/nginx/tls`.
- **API** — FastAPI on 8000. Terminates nothing; trusts `X-Forwarded-For`
  (`TRUST_PROXY=true`) and enforces an `ALLOWED_HOSTS` allowlist.
- **Worker** — ARQ background process (crawl, embeddings, email).
- **Dashboard / Widget** — builds bake the API origin at **build time**
  (`NEXT_PUBLIC_API_URL`, `VITE_WIDGET_API_BASE_URL`).
- **MongoDB / Redis / Resend** — external, managed.

### Single-origin URLs

Because nginx serves everything from one hostname, every URL points at the
same origin (this is the recommended layout):

| Variable              | Value                                                       |
| --------------------- | ----------------------------------------------------------- |
| `NEXT_PUBLIC_API_URL` | `https://app.example.com`                                   |
| `WIDGET_API_BASE_URL` | `https://app.example.com`                                   |
| `WIDGET_SCRIPT_URL`   | `https://app.example.com/widget/webchat-widget.iife.min.js` |
| `PUBLIC_BASE_URL`     | `https://app.example.com`                                   |
| `CORS_ORIGINS`        | `["https://app.example.com"]`                               |
| `ALLOWED_HOSTS`       | `app.example.com`                                           |

---

## 2. Prerequisites

- Docker with Buildx; `docker compose` v2.
- MongoDB Atlas (M7+/M10, **Vector Search** enabled).
- Managed TLS Redis (Upstash / Redis Cloud).
- Resend account with a verified sending domain.
- The external services provisioned (sections 3–5).

---

## 3. External services

The details are identical to the legacy guide (`docs/PRODUCTION_DEPLOYMENT.md`
§3–§5). Summary:

1. **MongoDB Atlas** — create a database user scoped to `webchat_ai`; build
   `MONGODB_URI`. Create the **Vector Search index** (name `default`,
   `type: vectorSearch`, `path: embedding`, `numDimensions` = `EMBEDDING_DIMENSIONS`,
   similarity `cosine`). Wait for it to reach **Active** before enabling chat.
   Application indexes (`init_indexes()`) are created automatically at startup.
2. **Redis** — TLS database (`rediss://`); `REDIS_URL`. Enable persistence.
3. **Resend** — verify the sending domain (SPF/DKIM/MX); create a domain-scoped
   API key → `RESEND_API_KEY`; set `EMAIL_FROM` to a verified sender.

---

## 4. Environment

Fill in `.env.production.example` (copy to `.env.production` or your secret
manager / CI variables). `docker compose` fails fast (`:?`) on any missing
required variable, and the API **fails fast at boot** on weak production config
(`backend/core/config.py`): short `JWT_SECRET`, missing AI/gateway keys,
loopback/`http`/wildcard `CORS_ORIGINS`, loopback-only `ALLOWED_HOSTS`,
wildcard `ALLOWED_HOSTS`, or `RATE_LIMIT_ENABLED=false`.

Key variables:

| Variable                 | Notes                                                                |
| ------------------------ | -------------------------------------------------------------------- |
| `JWT_SECRET`             | `openssl rand -hex 32`                                               |
| `ALLOWED_HOSTS`          | comma-separated or JSON; must include your public hostname(s)        |
| `CORS_ORIGINS`           | JSON array, HTTPS, non-loopback                                      |
| `WIDGET_SCRIPT_URL`      | **content-hashed** bundle, e.g. `webchat-widget.iife.min.<hash>.js`  |
| `TRUST_PROXY`            | `true` behind nginx (default)                                        |
| `COOKIE_SECURE`          | `true` (default)                                                     |
| `ENABLE_TLS`             | `1` to serve HTTPS from nginx; `0` when a fronting LB/CDN terminates |
| `TLS_CERT_DIR`           | dir with `fullchain.pem` + `privkey.pem` (when `ENABLE_TLS=1`)       |
| `TAG` / `REGISTRY`/`ORG` | image tags, e.g. `TAG=v1.0.0`                                        |

> **Build-time network access:** the dashboard build downloads the Geist fonts
> (`next/font/google`). The build host/CI must reach `fonts.googleapis.com` and
> `fonts.gstatic.com`.

---

## 5. Build and deploy

```bash
# 1. Load secrets into the shell (never commit them)
set -a; source .env.production; set +a   # or export ... in CI

# 2. Build images (api, worker, dashboard, widget, nginx)
docker compose -f docker-compose.prod.yml build

# 3. Start the stack
docker compose -f docker-compose.prod.yml up -d

# 4. Verify
docker compose -f docker-compose.prod.yml ps
curl -fsS http://127.0.0.1/api/health/ready
```

`depends_on` gating: dashboard and nginx wait for a **healthy** API; nginx also
waits for the widget. The API readiness probe (`/api/health/ready`) returns 200
only when MongoDB **and** Redis are reachable, else 503 (fail-closed).

### TLS

- **Fronting LB/CDN (recommended):** keep `ENABLE_TLS=0`; nginx serves plain
  HTTP on the compose network. Set `TRUST_PROXY=true`.
- **nginx-terminated TLS:** set `ENABLE_TLS=1`, mount
  `TLS_CERT_DIR` containing `fullchain.pem` + `privkey.pem` read-only at
  `/etc/nginx/tls`. nginx adds `Strict-Transport-Security` on the HTTPS vhost;
  the API also sends HSTS when `COOKIE_SECURE=true`.

### DNS / routing

Point your A/AAAA (and CAA) records at the host: `app.example.com` → nginx.

---

## 6. Health checks

| Service   | Probe                                                       | Healthy when                     |
| --------- | ----------------------------------------------------------- | -------------------------------- |
| nginx     | `GET /healthz` (nginx itself)                               | 200 `ok`                         |
| API live  | `GET /api/health/live`                                      | 200 `alive` (no dependency I/O)  |
| API ready | `GET /api/health/ready`                                     | **200** Mongo+Redis up, else 503 |
| API       | `GET /api/health`                                           | 200 + `database`/`redis` flags   |
| Dashboard | `wget -qO- http://127.0.0.1:3000`                           | 200                              |
| Widget    | `wget --spider http://127.0.0.1/webchat-widget.iife.min.js` | 200                              |
| Worker    | Redis `ping()` from the worker                              | broker reachable                 |

Health payloads include `version` + `environment` for release verification.

---

## 7. Security hardening (Phase 16)

- **Host allowlist** — `TrustedHostMiddleware` (from `ALLOWED_HOSTS`) rejects
  unknown `Host` headers with 400 before any handler runs; loopback is
  auto-allowed for container health checks.
- **CORS validation** — production refuses empty, wildcard, loopback, or
  non-HTTPS `CORS_ORIGINS`.
- **Edge rate limiting (nginx)** — 30 r/s on `/api/`, 5 r/m on auth/webhook
  endpoints, 120 r/m on widget assets; app-level per-key/per-widget limiters
  still apply downstream and `RATE_LIMIT_ENABLED=false` is a boot error in
  production.
- **Security headers (nginx)** — `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `server_tokens off`,
  optional HSTS. The API additionally sends its own headers (incl. a strict
  `default-src 'none'` CSP).
- **Structured logging** — JSON logs with `request_id` correlation in
  production (`backend/core/logging.py`).
- **Secret validation** — fail-fast boot checks for `JWT_SECRET`, AI keys,
  gateway keys, widget URLs.

---

## 8. Post-deploy checklist

- [ ] `GET /api/health/ready` → 200 via nginx
- [ ] `/api/health/live` reports the expected `version`
- [ ] Register a user; the verification email arrives via Resend
- [ ] Create a website; the embed snippet points at `WIDGET_SCRIPT_URL` and
      carries `data-api-base-url="https://app.example.com"`
- [ ] Crawl a page; `knowledge_chunks` are populated and `$vectorSearch`
      returns results
- [ ] Widget chat streams a streamed answer (SSE) from an allowlisted domain
- [ ] Hostile origin → `403 WIDGET_ORIGIN_NOT_ALLOWED`
- [ ] `curl -H "Host: evil.test" https://app.example.com/api/health/live` → 400
- [ ] Dashboard analytics / conversations / admin pages reach the API
- [ ] Worker logs show crawl + embedding jobs completing

Release-gate E2E (requires mail capture; see legacy guide §8 for wiring):

```bash
E2E_BASE_URL=https://api.example.com \
E2E_WIDGET_SCRIPT_URL=https://app.example.com/widget/webchat-widget.iife.min.js \
  .venv/bin/pytest tests/e2e -v
```

---

## 9. Operations

- **Deployment workflows** — for the zero-cost Oracle Free VM path, the runbook
  covers **first deployment**, **update deployment** and **emergency rollback**
  in `docs/ORACLE_FREE_VM_DEPLOYMENT.md`, driven by `scripts/server-init.sh`
  (server bootstrap) and `scripts/deploy-production.sh` (one-command deploy with
  automatic rollback).
- **Scaling** — multiple API replicas behind nginx (add `scale: N`); keep ≥1
  worker.
- **Secrets rotation** — rotate `JWT_SECRET` in a maintenance window (refresh
  tokens are hash-revoked on rotation). Use a secret manager; never `.env` in
  the image.
- **Backups** — Atlas snapshots + Redis persistence; test a restore.
- **Logs** — `docker compose logs -f api worker nginx`; JSON in production.
