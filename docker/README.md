# WebChat AI — Docker

Container definitions for the platform, plus the development and deployment
compose stacks.

| File                        | Purpose                                                                                                           |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `Dockerfile.api`            | FastAPI service (`ghcr.io/astral-sh/uv:python3.13-bookworm-slim`, EXPOSE 8000, healthcheck on `/api/health/live`) |
| `Dockerfile.worker`         | ARQ worker with Playwright + Chromium installed (`PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`)                       |
| `Dockerfile.dashboard`      | Next.js dashboard (`output: 'standalone'`)                                                                        |
| `Dockerfile.widget`         | Widget bundles served by nginx (`webchat-widget.iife.min.js`)                                                     |
| `compose.yml`               | Single env-driven compose file: dev services + the four app services                                              |
| `compose.prod.yml`          | Production overlay: immutable `image:` refs, `init: true`, read-only root FS (api/worker), bounded json-file logs |
| `nginx.widget.conf`         | Widget nginx: immutable long-cache serving of the hashed bundle                                                   |
| `prometheus/prometheus.yml` | Prometheus scrape config (target `api:8000`, `/metrics`)                                                          |
| `prometheus/alerts.yml`     | Alert rules (validated against `backend/core/metrics.py` by tests)                                                |

## Local development

The stack runs MongoDB 7, Redis, Mailpit (email testing), and the four app
services on a `webchat` bridge network:

```bash
cp .env.development .env            # bundled dev env pointing at docker services
docker compose --env-file .env.development -f docker/compose.yml up --build
# or: scripts/docker-up.sh
```

- API `:8000`, dashboard `:3000`, widget `:8080` (nginx), Mailpit web UI + API
- The app services build from their `backend/`, `apps/dashboard/`,
  `apps/widget/` build contexts (see `build.context` in `compose.yml`).

## Production

The **current production** system runs on **Vercel** (Dashboard, Widget) and
**Railway** (API, Worker) with managed MongoDB/Redis — it does **not** use the
Docker images below for deployment.

The Docker images remain a **CI validation / security gate** (built and scanned
with Trivy in `ci.yml` / `cd.yml`) and an **optional self-hosting** path via
Docker Compose + `scripts/deploy.sh`. Production uses immutable, SHA-tagged
GHCR images only when self-hosting; see
[`docs/deployment/README.md`](../docs/deployment/README.md) for the full
architecture, environment contracts, and the Docker Compose self-hosting runbook.

The four production images:

| Image                  | Runs                                               | Probe                                      |
| ---------------------- | -------------------------------------------------- | ------------------------------------------ |
| `webchat-ai-api`       | uvicorn (`${PORT:-8000}`, `${UVICORN_WORKERS:-1}`) | `/api/health/live` + `/api/health/ready`   |
| `webchat-ai-worker`    | ARQ (`python -m backend.workers`)                  | Redis `PING` broker check                  |
| `webchat-ai-dashboard` | `next start` on `:3000`                            | `wget :3000`                               |
| `webchat-ai-widget`    | nginx on `:8080`                                   | `wget --spider webchat-widget.iife.min.js` |

The worker image carries Playwright + Chromium so the HTTP-first crawler can
fall back to JS rendering (see [`backend/README.md`](../backend/README.md)).

## Security posture

- api/worker run read-only root FS, `no-new-privileges`, `cap_drop: ALL`
- `init: true` for signal handling
- Trivy HIGH/CRITICAL scan gate in CI/CD before publish
- Secrets are injected via environment (never baked into images); see
  `scripts/check-secrets.sh`
