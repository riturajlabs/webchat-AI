#!/usr/bin/env bash
# WebChat AI - start the full local docker stack (MongoDB, Redis, Mailpit,
# API, Worker, Dashboard, Widget) using the development environment file.
# For a local production-mode run use:
#   docker compose --env-file .env.production -f docker/compose.yml up --build
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose --env-file .env.development -f docker/compose.yml up --build "$@"
