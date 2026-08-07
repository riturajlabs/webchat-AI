#!/usr/bin/env bash
# WebChat AI - run the ARQ background worker.
set -euo pipefail
cd "$(dirname "$0")/.."

uv run python -m backend.workers
