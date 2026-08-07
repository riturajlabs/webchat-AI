#!/usr/bin/env bash
# WebChat AI - start the full local docker stack (MongoDB, Redis, Mailpit, API, Worker).
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose -f docker/compose.dev.yml up --build "$@"
