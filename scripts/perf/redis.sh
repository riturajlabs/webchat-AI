#!/usr/bin/env bash
# WebChat AI - dedicated load-test Redis on :6380 (Phase 12.1).
#
# The redis-server on :6379 belongs to Ollama and is auth-protected; the
# performance runs use this isolated instance so they never touch it.
set -euo pipefail

DATA_DIR="${REDIS_DIR:-/tmp/redis6380}"
PORT="${REDIS_PORT:-6380}"
mkdir -p "${DATA_DIR}"

if redis-cli -p "${PORT}" PING >/dev/null 2>&1; then
    echo "redis already running on :${PORT}"
    exit 0
fi

redis-server --port "${PORT}" --save '' --appendonly no --daemonize yes \
    --dir "${DATA_DIR}" --logfile "${DATA_DIR}/redis.log" --pidfile "${DATA_DIR}/redis.pid"
echo "redis started on :${PORT}"
