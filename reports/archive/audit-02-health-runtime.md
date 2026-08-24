# Audit 02 — Health & Runtime Verification

Target: WebChat AI Phase 1–8, commit `cee0ec4`.
Date: 2026-08-10

## 1. Health endpoints

`backend/api/routes/health.py`:

- `GET /health` — liveness: returns `200` when the API process is alive, with a
  `checks` object reporting `database` and `redis` ping results.
- `GET /health/ready` — readiness: returns `{"status": "ready"}` only when both
  Mongo and Redis are reachable; otherwise `{"status": "degraded"}` (HTTP 200).

Ping implementations: `MongoDB.ping()` (motor) and `redis.ping_redis()`.

These two probes are correctly separated for orchestration (liveness vs
readiness), matching the 12-factor pattern in `docs/07`.

### 1.1 Recommendation

`/health/ready` returns HTTP 200 even when degraded. For load-balancer / k8s
readiness this should return HTTP 503 when degraded so a probe fails closed.

## 2. Runtime verification — method

Live runtime gates were NOT executed: no Docker services were running and the
local `.env` secret values are placeholders (Mailpit/Resend, Gemini API key).
Verification was performed statically by inspecting the compose topology,
entrypoints, and health wiring.

## 3. Docker topology (`docker/compose.dev.yml`, 7 services)

| Service     | Notes                                                             |
| ----------- | ----------------------------------------------------------------- |
| `mongo`     | MongoDB for primary persistence + Atlas vector search (local run) |
| `redis`     | Queue broker + cache + rate limiting backend                      |
| `mailpit`   | SMTP dev mail catcher for verification/password-reset emails      |
| `api`       | FastAPI app (`docker/Dockerfile.api`)                             |
| `worker`    | arq worker for crawl + knowledge jobs (`Dockerfile.worker`)       |
| `dashboard` | Next.js dashboard (`Dockerfile.dashboard`)                        |
| `widget`    | Static widget bundle (`Dockerfile.widget`)                        |

Health dependencies are accurate: the API is worthless without Mongo (vector
search, users, websites) and Redis (sessions, limits, queues) — both probed by
`/health`.

## 4. CI configuration

`.github/workflows/ci.yml` — three jobs:

1. **Backend** — `uv sync --frozen`, `ruff check`, `mypy backend`, `pytest --cov`.
2. **Frontend** — pnpm 11.13.1, Node 22, `lint` / `typecheck` / `build` / `test`.
3. **Docker** — builds all four images (api, worker, dashboard, widget).

All commands in CI were executed locally and reproduced the results in audit-01
and audit-03. Concurrency is bounded via `concurrency: group=ci-${{ github.ref }}`.

## 5. Deployment scripts present

`scripts/setup.sh`, `scripts/docker-up.sh`, `scripts/check-backend.sh`,
`scripts/dev-api.sh`, `scripts/dev-worker.sh`.

## 6. Process health observations

- Working tree is clean at audit time; git history is 8 commits with phase
  tags `v0.6-rag-complete`, `v0.7-dashboard-complete`, `v0.8-widget-sdk-complete`.
- FastAPI entrypoint `backend/main.py` registers routers for auth, websites,
  crawl jobs, chat, widget config, and health; includes CORS (allowed origins
  from settings) and error handlers.

## 7. Open items

1. Return HTTP 503 from `/health/ready` when degraded (fail-closed probes).
2. Run `docker-up.sh` and verify `/health` + `/health/ready` live (Mongo + Redis
   required) once real secrets are supplied.
3. Confirm the widget bundle is served by `nginx`/static host with the exact
   `WIDGET_SCRIPT_URL` used by the dashboard snippet.
