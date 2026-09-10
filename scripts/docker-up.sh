#!/usr/bin/env bash
# WebChat AI - start the full local docker stack (MongoDB, Redis, Mailpit,
# API, Worker, Dashboard, Widget) using the development environment file.
# For a SAFE production-STYLE local run (local docker services only, zero
# production access) use the sandbox - never the real .env.production:
#   docker compose --env-file .env.production.sandbox -f docker/compose.yml up --build
# !!! .env.production targets REAL production infrastructure (Atlas / Upstash /
#     payments / AI) and must never be used for local runs.
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose --env-file .env.development -f docker/compose.yml up --build "$@"
