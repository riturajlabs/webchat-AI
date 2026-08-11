#!/usr/bin/env bash
# WebChat AI - run the isolated performance-benchmark API (Phase 12.1).
#
# Starts uvicorn on :8001 against the NATIVE MongoDB (localhost:27017) and a
# dedicated load-test Redis (localhost:6380, see scripts/perf/redis.sh), using
# the deterministic `mock` AI providers so benchmarks never hit a paid API.
#
# The Docker dev stack (api:8000/dashboard:3000/widget:8080) is left untouched.
set -euo pipefail
cd "$(dirname "$0")/../.."

export MONGODB_URI="${MONGODB_URI:-mongodb://localhost:27017}"
export MONGODB_DB="${MONGODB_DB:-webchat_ai}"
export REDIS_URL="${REDIS_URL:-redis://localhost:6380}"
export RATE_LIMIT_ENABLED=false
export WIDGET_RATE_LIMIT_ENABLED=false
export ENVIRONMENT=performance
export DEBUG=false
export PERF_TIMING_LOG_ENABLED=true
export MONGODB_SLOW_QUERY_THRESHOLD_MS=50
export GENERATION_PROVIDER_ORDER='["mock"]'
export EMBEDDING_PROVIDER_ORDER='["mock"]'

exec uv run uvicorn backend.main:app --host 127.0.0.1 --port "${PERF_PORT:-8001}" "$@"
