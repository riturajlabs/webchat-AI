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

1. Copy environment variables:

   ```bash
   cp .env.example .env
   ```

2. Start the full development stack (MongoDB, Redis, Mailpit, API, Worker,
   Dashboard, Widget):

   ```bash
   docker compose --env-file .env -f docker/compose.dev.yml up --build
   ```

   (or `scripts/docker-up.sh`). The `--env-file .env` flag loads your local
   secrets (AI keys, JWT secret) into the api/worker containers.

3. Install frontend dependencies and run the dashboard:

   ```bash
   pnpm install
   pnpm dev:dashboard
   ```

4. Backend (local, without Docker) — see `scripts/setup.sh` and `scripts/dev-api.sh`.

> MongoDB Atlas and managed Redis are used for production (Phase 13/14). Local
> development uses the Docker `mongo`/`redis` services or a native local
> instance; the service URIs come from `.env`.
>
> **Environment configuration**: see `.env.example` for the full variable
> reference. `docker/compose.dev.yml` is fully `.env`-driven - it passes every
> variable straight through to the api/worker containers via `${VAR:-default}`
> and only supplies local-dev fallbacks (`ENVIRONMENT=development`,
> `MONGODB_URI=mongodb://mongo:27017`, `REDIS_URL=redis://redis:6379`,
> `MAILPIT_API_URL=http://mailpit:8025`) when `.env` does not set them. All
> secrets come from `.env`. For production, set `ENVIRONMENT=production` in
> `.env` with external managed services; `backend/core/config.py` fails fast at
> boot on weak production values (loopback CORS/hosts, short JWT secret, missing
> AI keys, mock payments).

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
