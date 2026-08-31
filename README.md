# WebChat AI

Multi-tenant AI SaaS platform that lets anyone deploy a website-specific AI chat assistant in minutes. Zero-code integration via a single script tag, powered by RAG (retrieval-augmented generation) on Google Gemini.

## Repository layout

```
apps/dashboard     Next.js 15 dashboard (tenant + admin)
apps/widget        Framework-independent embeddable widget SDK
backend/           FastAPI backend (api, services, repositories, workers, ai)
docs/              Design documents 00-07 (07 = Architecture Decision Record)
docker/            Dockerfiles + compose for local development
scripts/           Dev/ops helper scripts
tests/             Test suites (backend pytest, frontend vitest/e2e)
```

## Prerequisites

- Node.js >= 20, pnpm >= 9
- Python 3.13 (via `uv`)
- Docker + Docker Compose

## Quick start

1. Copy environment variables (a ready-made development file ships with the
   repo; copy it for local development):

   ```bash
   cp .env.development .env
   ```

2. Start the full development stack (MongoDB, Redis, Mailpit, API, Worker,
   Dashboard, Widget):

   ```bash
   docker compose --env-file .env.development -f docker/compose.yml up --build
   ```

   (or `scripts/docker-up.sh`). The `--env-file` flag loads the selected
   environment file and compose passes it straight into the containers.

3. Install frontend dependencies and run the dashboard:

   ```bash
   pnpm install
   pnpm dev:dashboard
   ```

4. Backend (local, without Docker) — see `scripts/setup.sh` and `scripts/dev-api.sh`.

> MongoDB Atlas and managed Redis are used for production (Phase 13/14). Local
> development uses the Docker `mongo`/`redis` services or a native local
> instance; the service URIs come from the selected env file.
>
> **Environment configuration**: see `.env.example` for the full variable
> reference. Two env files ship with the repo:
>
> - `.env.development` — local docker services (`ENVIRONMENT=development`,
>   `MONGODB_URI=mongodb://mongo:27017`, `REDIS_URL=redis://redis:6379`,
>   `MAILPIT_API_URL=http://mailpit:8025`, `DEBUG=true`, `COOKIE_SECURE=false`,
>   `PAYMENT_PROVIDER=mock`).
> - `.env.production` — `ENVIRONMENT=production` for **local production
>   testing**: external managed services (Atlas MongoDB, managed Redis, Resend,
>   real AI keys) but localhost app URLs, gated by `LOCAL_PRODUCTION_TEST=true`.
>   `backend/core/config.py` fails fast at boot on weak production values
>   (loopback CORS/hosts, short JWT secret, missing AI keys, mock payments)
>   unless the explicit local-production-test flag is set. Before deploying to
>   Railway, only URL/domain and provider-credential values change (see
>   `.env.example` "RAILWAY DEPLOYMENT").

## Production Environment Setup

**Never commit secrets to the repository.** All production credentials must be
managed through your deployment platform.

### Development (local)

```bash
cp .env.example .env          # or use .env.development directly
# Fill in local values, then:
docker compose --env-file .env.development -f docker/compose.yml up --build
```

### Production (deployed)

Secrets are set as **environment variables** on your deployment platform — no
`.env` file is shipped. Examples:

| Platform    | How to set secrets                                                                 |
| ----------- | ---------------------------------------------------------------------------------- |
| **Railway** | Project → Variables tab (supports multi-line JSON, secret masking)                 |
| **AWS**     | Secrets Manager / SSM Parameter Store → inject via task definition or ECS          |
| **Docker**  | `docker run -e MONGODB_URI=...` or Docker Compose `secrets` / `.env` (not tracked) |

> Kubernetes is explicitly NOT a deployment target. Production uses the Docker
> Compose stack with immutable GHCR images (see `docs/deployment/README.md` and
> `.github/workflows/cd.yml`).

### Required secrets for production

At minimum you must provide:

- `MONGODB_URI` — MongoDB Atlas connection string (`mongodb+srv://...`)
- `REDIS_URL` — Managed Redis URL (`rediss://...`)
- `JWT_SECRET` — Generate with `openssl rand -hex 32` (>= 32 bytes)
- `GEMINI_API_KEY` — Required for embeddings + generation
- `RESEND_API_KEY` — Required for email delivery
- `STRIPE_SECRET_KEY` / `RAZORPAY_KEY_ID` — Required if payments enabled

Run `./scripts/check-secrets.sh` before every commit to verify no secrets are
accidentally tracked.

## Development scripts

| Script                     | Purpose                                                                         |
| -------------------------- | ------------------------------------------------------------------------------- |
| `scripts/setup.sh`         | One-time setup (`.env`, pnpm install, uv sync)                                  |
| `scripts/dev-api.sh`       | FastAPI dev server (hot reload, `:8000`)                                        |
| `scripts/dev-worker.sh`    | ARQ background worker (`python -m backend.workers`)                             |
| `scripts/docker-up.sh`     | Start full Docker stack (Mongo, Redis, Mailpit, API, Worker, Dashboard, Widget) |
| `scripts/check-backend.sh` | ruff + mypy + pytest                                                            |

## Verification

```bash
pnpm lint && pnpm typecheck && pnpm build && pnpm test   # frontend
./scripts/check-backend.sh                                # backend
curl http://localhost:8000/api/health                     # expect database:true, redis:true
```

## Documentation

| Doc                                 | Purpose                                        |
| ----------------------------------- | ---------------------------------------------- |
| `00-AI-Development-Rules.md`        | Mandatory rules for AI coding agents           |
| `docs/01-PRD.md`                    | Product requirements                           |
| `docs/02-TRD.md`                    | Technical requirements                         |
| `docs/03-App-Flow.md`               | Application flows                              |
| `docs/04-UI-UX-Brief.md`            | UI/UX design brief                             |
| `docs/05-Backend-Schema.md`         | Database schema                                |
| `docs/06-Implementation-Plan.md`    | Phased implementation plan                     |
| `docs/07-Architecture-Decisions.md` | Architecture decision record (source of truth) |

## License

Proprietary. All rights reserved.
