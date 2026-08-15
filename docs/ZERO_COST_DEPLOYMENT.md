# WebChat AI — Zero-Cost Production Deployment

Deployment strategy for running the full WebChat AI SaaS on **$0/month** cloud
services while keeping the current Phase 16 architecture (nginx reverse proxy →
FastAPI + ARQ worker + Next.js dashboard + static widget SDK, with MongoDB
Atlas, Redis, Resend). No application-logic changes are required.

Scope: `docs/DEPLOYMENT.md` is the canonical operational guide; this document
adds the **free-tier strategy**, the **Docker production audit**, and the
**rollback plan**.

---

## 1. Current architecture

```
                          ┌───────────────────────────────────┐
        Browser ─────────▶│  nginx  :80 / :443 (ENABLE_TLS)   │  single origin
                          │  /api/*  → api:8000               │  https://app.example.com
                          │  /widget/* → widget:80 (SDK)      │
                          │  /* and /dashboard/* → dashboard  │
                          └───────┬──────────┬────────┬───────┘
                                  │          │        │
                                  ▼          ▼        ▼
                          ┌────────────┐ ┌────────┐ ┌────────────┐
                          │  api:8000  │ │widget:80│ │dashboard:3000│
                          │  (uvicorn) │ │ (nginx  │ │ (Next.js   │
                          │            │ │  static)│ │  standalone)│
                          └─────┬──────┘ └────────┘ └────────────┘
                                │
                          ┌─────▼─────┐         ┌──────────────┐
                          │ worker ≥1 │         │ Mongo Atlas  │
                          │ (ARQ,     │         │ + app indexes│
                          │ Playwright│         └──────────────┘
                          └───────────┘
                              Redis (queue/rate/cache) · Resend (email)
```

- **API** — FastAPI on 8000; `TrustedHostMiddleware` (`ALLOWED_HOSTS`),
  production boot validation, JSON logs, `/api/health/live` + `/api/health/ready`
  (fail-closed on Mongo/Redis).
- **Worker** — ARQ: crawl (Playwright Chromium), embeddings, email.
- **Dashboard** — Next.js `output: 'standalone'`; API origin baked at build
  time (`NEXT_PUBLIC_API_URL`).
- **Widget** — content-hashed static bundles (+ stable `webchat-widget.iife.min.js`),
  built with `VITE_WIDGET_API_BASE_URL` baked in.
- **External** — MongoDB Atlas, Redis, Resend.

---

## 2. Free hosting strategy

| Component                                  | Free option                                                     | Notes                                                                                                                                                                                                                                                                  |
| ------------------------------------------ | --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| API + Worker + Dashboard + nginx + (Redis) | **Oracle Cloud Free Tier ARM VM** (4 OCPU / 24 GB, always free) | Runs `docker-compose.prod.yml` unchanged; single always-on host (Render/Fly free instances sleep).                                                                                                                                                                     |
| MongoDB                                    | **Atlas M0** (already configured)                               | M0 has **no Vector Search index**; the backend auto-degrades to exact brute-force cosine search (`backend/repositories/vector/mongodb.py:_brute_force_search`, auto-detected Atlas-only errors). Retrieval stays exact — O(chunks) per query. Fine for modest corpora. |
| Redis                                      | **Upstash free** (256 MB) **or** Redis container on the VM      | External `REDIS_URL` (TLS `rediss://`) supported; no code change. Self-hosted option: small compose override adding `redis:7-alpine`.                                                                                                                                  |
| Email                                      | **Resend free** (3k emails/month)                               | Selected automatically when `ENVIRONMENT=production`.                                                                                                                                                                                                                  |
| Widget CDN                                 | **Cloudflare Pages** (free, unlimited bandwidth)                | Static deploy of `apps/widget/dist`; hashed bundles immutable, stable copy `no-store`. `WIDGET_SCRIPT_URL` → Pages URL **or** nginx `/widget/`.                                                                                                                        |
| DNS / edge / TLS                           | **Cloudflare free**                                             | Proxy (orange cloud) + HSTS; set `ENABLE_TLS=0` when Cloudflare terminates TLS.                                                                                                                                                                                        |
| CI/CD                                      | **GitHub Actions free**                                         | Existing `ci.yml` (tests, lint, build, prod smoke).                                                                                                                                                                                                                    |
| Domain                                     | ~$10/yr or free `*.pages.dev` subdomain                         | The only potentially-paid item.                                                                                                                                                                                                                                        |

**Requirement coverage (free-tier compatibility):**

- MongoDB Atlas M0 — ✅ brute-force fallback (no code change, verified by
  `tests/test_vector_mongodb.py`).
- Redis external URL — ✅ `REDIS_URL` env (any RESP provider).
- Worker with Playwright — ✅ `Dockerfile.worker` installs Chromium.
- Next.js standalone — ✅ `apps/dashboard/next.config.mjs` (`output: 'standalone'`).
- Widget static CDN — ✅ `Dockerfile.widget` emits `dist/` (hashed + stable).

---

## 3. Environment variables

Fill `.env.production.example` → `.env.production` (never commit). Required set:

| Variable                          | Purpose                                                    |
| --------------------------------- | ---------------------------------------------------------- |
| `ENVIRONMENT`                     | `production`                                               |
| `JWT_SECRET`                      | ≥32 bytes (`openssl rand -hex 32`)                         |
| `ALLOWED_HOSTS`                   | public hostname(s); loopback auto-allowed for healthchecks |
| `CORS_ORIGINS`                    | JSON array, HTTPS, non-loopback (boot-validated)           |
| `PUBLIC_BASE_URL`                 | dashboard origin (email links)                             |
| `WIDGET_SCRIPT_URL`               | HTTPS URL of the content-hashed widget bundle              |
| `WIDGET_API_BASE_URL`             | API origin the SDK talks to                                |
| `NEXT_PUBLIC_API_URL`             | dashboard build-time API origin                            |
| `MONGODB_URI` / `MONGODB_DB`      | Atlas M0                                                   |
| `REDIS_URL`                       | TLS RESP URL (Upstash) or container URL                    |
| `RESEND_API_KEY` / `EMAIL_FROM`   | verified sender                                            |
| `PAYMENT_PROVIDER` + gateway keys | `stripe`/`razorpay` (mock is a boot error)                 |
| `GEMINI_API_KEY` (≥1 AI key)      | generation + embeddings                                    |
| `SUPER_ADMIN_EMAILS`              | JSON array; empty disables the admin API                   |
| `COOKIE_SECURE` / `TRUST_PROXY`   | `true` behind TLS proxy                                    |
| `ENABLE_TLS`                      | `0` behind Cloudflare, `1` for nginx-terminated TLS        |

Load before compose:

```bash
set -a; source .env.production; set +a
```

---

## 4. Production vs development differences

| Aspect                  | Development                           | Production                                             |
| ----------------------- | ------------------------------------- | ------------------------------------------------------ |
| `ENVIRONMENT` / `DEBUG` | `development` / `true`                | `production` / `false`                                 |
| Email                   | Mailpit                               | Resend                                                 |
| Cookies                 | `COOKIE_SECURE=false`                 | `COOKIE_SECURE=true`                                   |
| API docs/OpenAPI        | `/api/docs`                           | disabled                                               |
| Logging                 | human-readable                        | JSON + `request_id`                                    |
| Payments                | `mock`                                | real gateway required                                  |
| Hosts / CORS            | loopback + testserver                 | `ALLOWED_HOSTS`/`CORS_ORIGINS` allowlists enforced     |
| Rate limiting           | app-level                             | app-level + nginx edge zones                           |
| Retrieval               | local Mongo → brute-force             | M0 → brute-force fallback (no `$vectorSearch`)         |
| Compose                 | `docker/compose.dev.yml` (host ports) | `docker-compose.prod.yml` (nginx front, `expose` only) |

---

## 5. Deployment order

1. Provision external services: Atlas M0 (exists), Redis (Upstash free or VM),
   Resend domain verified, Cloudflare zone + DNS.
2. Create `.env.production` from `.env.production.example` (real secrets).
3. Create the Oracle ARM VM; install Docker + compose plugin; firewall 22/80/443.
4. `git clone`; `set -a; source .env.production; set +a`.
5. `docker compose -f docker-compose.prod.yml build` (builds already use
   `network: host` for the documented Docker MTU issue).
6. `docker compose -f docker-compose.prod.yml up -d` — `depends_on` boots
   api → dashboard/widget → nginx; verify `docker compose ps` all healthy.
7. Verify with `scripts/deployment-check.sh`.
8. Deploy widget `dist` to Cloudflare Pages; set cache rules; point
   `WIDGET_SCRIPT_URL` at the hashed bundle.
9. Point DNS at the VM, enable Cloudflare proxy + HSTS.
10. Security spot-checks (section 6) + post-deploy checklist in
    `docs/DEPLOYMENT.md`.

---

## 6. Security checklist

- [ ] `JWT_SECRET` ≥32 bytes, in `.env.production`/secret manager only
- [ ] `ALLOWED_HOSTS` exact public hostnames (verify `evil.test` Host → 400)
- [ ] `CORS_ORIGINS` HTTPS, non-loopback, no wildcard
- [ ] `COOKIE_SECURE=true`; HSTS via Cloudflare or `ENABLE_TLS=1`
- [ ] `TRUST_PROXY=true` only behind Cloudflare/nginx
- [ ] Rate limiting on (edge + app); `RATE_LIMIT_ENABLED=true`
- [ ] VM firewall: 22 (SSH keys only) / 80 / 443; Mongo/Redis never public
- [ ] Atlas: database-scoped user, IP allowlist, snapshots
- [ ] Redis: TLS `rediss://`, credentials; self-hosted → `requirepass` + internal net
- [ ] Resend: domain-scoped API key
- [ ] Widget origin allowlist enforced (`403 WIDGET_ORIGIN_NOT_ALLOWED` on hostile origins)
- [ ] Structured logs contain no secrets

---

## 7. Rollback strategy

- **Application** — images are tagged (`TAG=v1.0.0`). Roll back by re-running
  compose with the previous tag: `export TAG=<previous>` then
  `docker compose -f docker-compose.prod.yml up -d`. Healthchecks gate the swap.
- **Database** — migrations are additive and `init_indexes()` is idempotent; a
  previous app version runs safely against the current schema. For data-level
  rollback, restore an Atlas snapshot.
- **Redis** — ARQ jobs survive restarts (persistence). On rollback, drain the
  queue (`redis-cli` against the configured `REDIS_URL`) rather than force-drop;
  rate-limit counters reset harmlessly.
- **Widget CDN** — hashed bundles are immutable, so a previous release is still
  served at its old hash. Roll back by repointing `WIDGET_SCRIPT_URL` to the
  prior hashed bundle (keep ≥2 releases on Pages).
- **Secrets** — keep the same `JWT_SECRET` across rollbacks: rotation revokes
  refresh tokens (hash-revoked) and would sign every user out.
- **DNS** — Cloudflare makes DNS instant; a catastrophic failure rolls back by
  repointing to a previous host while the old VM/image set is kept warm.

---

## 8. Docker production files audit

See the accompanying report in the delivery notes. Summary:

| File                      | Production ready                                                                                        | Needs modification                                 |
| ------------------------- | ------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| `docker-compose.prod.yml` | ✅ nginx service, healthchecks, `depends_on`, fail-fast `:?` vars, payment vars, `network: host` builds | optional self-hosted Redis override (not required) |
| `Dockerfile.api`          | ✅ slim uv image, cached deps                                                                           | hardening only: run as non-root                    |
| `Dockerfile.worker`       | ✅ Playwright Chromium                                                                                  | hardening only: non-root; cap memory at runtime    |
| `Dockerfile.dashboard`    | ✅ standalone output, pinned pnpm                                                                       | hardening only: non-root                           |
| `Dockerfile.widget`       | ✅ static dist (hashed + stable), immutable cache config                                                | hardening only: non-root                           |
| `docker/nginx/*`          | ✅ single-origin routing, rate limits, security headers, optional TLS                                   | none                                               |

No application-logic changes are required for a zero-cost deploy.
