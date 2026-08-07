#!/usr/bin/env bash
# WebChat AI - run backend checks (lint, typecheck, tests).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> ruff"
uv run ruff check .

echo "==> mypy"
uv run mypy backend

echo "==> pytest"
uv run pytest
