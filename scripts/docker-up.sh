#!/usr/bin/env bash
# WebChat AI - start the full local docker stack (MongoDB, Redis, Mailpit,
# API, Worker, Dashboard, Widget).
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose --env-file .env -f docker/compose.dev.yml up --build "$@"
