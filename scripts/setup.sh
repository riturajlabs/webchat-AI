#!/usr/bin/env bash
# WebChat AI - one-time development setup.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Copying .env.example -> .env (if missing)"
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "    Created .env. Edit it to add your secrets."
fi

echo "==> Installing frontend dependencies (pnpm)"
pnpm install

echo "==> Installing backend dependencies (uv, Python 3.13)"
uv sync

echo "==> Done. Start infra with:"
echo "    docker compose --env-file .env.development -f docker/compose.yml up --build"
echo "    Then run: scripts/dev-api.sh"
