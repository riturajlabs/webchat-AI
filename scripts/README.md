# WebChat AI — Scripts

Dev, ops, and verification helpers. Scripts are grouped by intent; some **modify
data or trigger production operations** — read before running.

## Development / local run

| Script          | Purpose                                                                                           |
| --------------- | ------------------------------------------------------------------------------------------------- |
| `setup.sh`      | One-time setup: copy `.env.example` → `.env`, `pnpm install`, `uv sync`                           |
| `dev-api.sh`    | FastAPI dev server with hot reload (`uvicorn backend.main:app --reload`, `${BACKEND_PORT:-8000}`) |
| `dev-worker.sh` | ARQ background worker (`python -m backend.workers`)                                               |
| `docker-up.sh`  | Full local Docker stack (Mongo, Redis, Mailpit, API, Worker, Dashboard, Widget)                   |

## Verification & release gates

| Script                           | Purpose                                                                           |
| -------------------------------- | --------------------------------------------------------------------------------- |
| `check-backend.sh`               | The backend gate: `ruff check .` + `mypy backend` + `pytest`                      |
| `check-secrets.sh`               | Lightweight secret scanner (grep + git + bash builtins) — run before every commit |
| `local-production-smoke-test.sh` | 10 smoke checks against a locally-running production stack                        |
| `check-production-docker.sh`     | Production Docker hardening audit (8 checks)                                      |
| `check-docker-security.sh`       | Dockerfile/compose hardening compliance                                           |
| `check-ai-security.sh`           | AI/RAG security & reliability audit                                               |
| `check-api-security.sh`          | API production hardening audit                                                    |
| `check-auth-security.sh`         | Auth/session security hardening audit                                             |
| `check-database-security.sh`     | MongoDB auth/port/credential/posture checks                                       |
| `check-input-validation.sh`      | Input validation & injection-prevention audit                                     |
| `check-observability.sh`         | Production observability & monitoring audit                                       |
| `load-test-report.sh`            | Load-test report (phase 14.8.4)                                                   |

## RAG evaluation & debugging

| Script                                  | Purpose                                           |
| --------------------------------------- | ------------------------------------------------- |
| `evaluate_rag.py`                       | Run RAG evaluation over a corpus                  |
| `staging_golden_eval.py`                | Golden-dataset evaluation (`golden_dataset.json`) |
| `inspect_rag.py`                        | Inspect RAG pipeline state for a site/question    |
| `debug_vector_search.py`                | Inspect `$vectorSearch` behavior                  |
| `corpus_reingest_dry_run.py`            | Dry-run re-ingestion report (no writes)           |
| `reingest_website_corpus.py`            | Full corpus re-ingestion (**modifies data**)      |
| `backfill-embedding-identity.py`        | Backfill corpus embedding identity                |
| `reindex-website-embedding-identity.py` | Re-index a website's embedding identity           |
| `migrate-allowed-domains.py`            | One-off allowed-domain migration                  |

## Widget / E2E

| Script                    | Purpose                                               |
| ------------------------- | ----------------------------------------------------- |
| `e2e-widget.sh`           | Full widget E2E — no-mock flow against the live stack |
| `verify_widget_chat.py`   | Verify widget chat flow against a running API         |
| `seed-widget.py`          | Seed a widget (and website) for manual testing        |
| `e2e_phase2_ingestion.py` | Ingestion E2E harness                                 |

## Deployment

| Script      | Purpose                                                                                                                                                                                       |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `deploy.sh` | Production compose deployment: `deploy` / `migrate` / `rollback` / `status` with a fail-fast preflight. Used by CD (`cd.yml`) — see [docs/deployment/README.md](../docs/deployment/README.md) |

## Perf helpers (`scripts/perf/`)

Performance/benchmark tooling: `benchmark.py`, `ab_evaluation.py`,
`benchmark_live.py`, `health_read_bench.py`, `load-test.js`, `redis.sh`,
`run-api.sh`, `seed.py`.

## Conventions

- Shell scripts are `set -euo pipefail` and `cd` to the repo root first.
- Python helpers are run with the repo's `uv` environment
  (`uv run python scripts/...py`).
- Anything that writes to the database is labeled "modifies data" above — use
  the dry-run variant first where one exists.
