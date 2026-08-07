#!/usr/bin/env bash
# WebChat AI - run the FastAPI dev server with hot reload.
set -euo pipefail
cd "$(dirname "$0")/.."

uv run uvicorn backend.main:app --reload --host 0.0.0.0 --port "${BACKEND_PORT:-8000}"
