#!/usr/bin/env bash
# WebChat AI widget E2E - full no-mock flow against the live stack.
#
#  1. Builds the widget bundle (must match HEAD).
#  2. Brings up mongo, redis, mailpit, api, worker, widget via compose
#     (GEMINI_API_KEY passes through from .env; see docker/compose.dev.yml).
#  3. Waits for the API readiness probe.
#  4. Runs tests/e2e with the live environment wired up.
#
# Requirements: docker compose, a GEMINI_API_KEY in .env, and the venv with
# playwright (backend dependency).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Building widget bundle"
pnpm --filter @webchat/widget build

echo "==> Starting stack (mongo, redis, mailpit, api, worker, widget)"
# RATE_LIMIT_ENABLED=false: the E2E exercises the full functional flow; auth/
# widget rate limits have their own unit tests and would otherwise make the
# no-mock E2E flaky across repeated runs (register is 10 req/hour/IP).
RATE_LIMIT_ENABLED="${RATE_LIMIT_ENABLED:-false}" \
  docker compose -f docker/compose.dev.yml --env-file .env up -d --build widget api worker

echo "==> Waiting for API readiness"
ready=""
for _ in $(seq 1 90); do
  if curl -sf -o /dev/null http://localhost:8000/api/health/ready; then
    ready="yes"
    break
  fi
  sleep 2
done
if [ -z "$ready" ]; then
  echo "API never became ready - check docker compose ps" >&2
  exit 1
fi

echo "==> Running widget E2E"
E2E_BASE_URL="${E2E_BASE_URL:-http://localhost:8000}" \
E2E_MAILPIT_URL="${E2E_MAILPIT_URL:-http://localhost:8025}" \
E2E_WIDGET_SCRIPT_URL="${E2E_WIDGET_SCRIPT_URL:-http://localhost:8080/webchat-widget.iife.min.js}" \
  .venv/bin/pytest tests/e2e -v "$@"
