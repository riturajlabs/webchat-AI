#!/usr/bin/env bash
# WebChat AI - deployment verification (zero-cost production, Phase 17).
#
# Verifies a deployed WebChat AI stack without modifying anything:
#   1. production-required environment variables are present
#   2. docker compose config validates and all services are healthy
#   3. API health endpoints respond (ready fail-closed + liveness)
#   4. dashboard responds on the root and /dashboard/ alias
#   5. widget SDK bundle is served
#
# Usage:
#   set -a; source .env.production; set +a          # load secrets
#   scripts/deployment-check.sh                     # against docker-compose.prod.yml
#   COMPOSE_FILE=docker/compose.dev.yml BASE_URL=http://localhost:8000 \
#     WIDGET_PATH=/webchat-widget.iife.min.js scripts/deployment-check.sh
#
# Options:
#   COMPOSE_FILE   compose file to inspect   (default: docker-compose.prod.yml)
#   BASE_URL       public entry origin       (default: http://127.0.0.1)
#   WIDGET_PATH    widget bundle URL path    (default: /widget/webchat-widget.iife.min.js)
#
# Exit code: 0 when every check passes, 1 otherwise.
set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BASE_URL="${BASE_URL:-http://127.0.0.1}"
WIDGET_PATH="${WIDGET_PATH:-/widget/webchat-widget.iife.min.js}"
DASHBOARD_ROOT_PATH="${DASHBOARD_ROOT_PATH:-/}"
DASHBOARD_ALIAS_PATH="${DASHBOARD_ALIAS_PATH:-/dashboard/}"

# Production-required variables (mirrors the compose `:?` gate and config.py
# boot validators). Not exhaustive - see .env.production.example.
REQUIRED_ENV_VARS=(
  ENVIRONMENT JWT_SECRET ALLOWED_HOSTS CORS_ORIGINS PUBLIC_BASE_URL
  WIDGET_SCRIPT_URL WIDGET_API_BASE_URL NEXT_PUBLIC_API_URL
  MONGODB_URI MONGODB_DB REDIS_URL RESEND_API_KEY EMAIL_FROM
  PAYMENT_PROVIDER
)
# At least one generation/embedding AI key is required.
AI_KEYS=(GEMINI_API_KEY GROQ_API_KEY OPENROUTER_API_KEY)

pass_count=0
fail_count=0

_pass() {
  pass_count=$((pass_count + 1))
  printf '  [PASS] %s\n' "$1"
}

_fail() {
  fail_count=$((fail_count + 1))
  printf '  [FAIL] %s\n' "$1" >&2
}

_title() {
  printf '\n==> %s\n' "$1"
}

_check_env() {
  _title "Environment variables"
  local missing=0 name

  if [[ "${ENVIRONMENT:-}" != "production" ]]; then
    _fail "ENVIRONMENT must be 'production' (got '${ENVIRONMENT:-<unset>}')"
    missing=1
  fi
  for name in "${REQUIRED_ENV_VARS[@]}"; do
    if [[ -n "${!name:-}" ]]; then
      _pass "$name is set"
    else
      _fail "$name is missing (set -a; source .env.production; set +a)"
      missing=1
    fi
  done

  local ai_keys=0
  for name in "${AI_KEYS[@]}"; do
    [[ -n "${!name:-}" ]] && ai_keys=$((ai_keys + 1))
  done
  if ((ai_keys >= 1)); then
    _pass "at least one AI provider key is set"
  else
    _fail "no AI provider key set (GEMINI_API_KEY / GROQ_API_KEY / OPENROUTER_API_KEY)"
    missing=1
  fi
  [[ "$missing" -eq 0 ]]
}

_check_compose() {
  _title "Docker services ($COMPOSE_FILE)"
  if ! command -v docker >/dev/null 2>&1; then
    _fail "docker is not installed"
    return 1
  fi

  if docker compose -f "$COMPOSE_FILE" config -q >/dev/null 2>&1; then
    _pass "compose config validates"
  else
    _fail "compose config failed (missing variables? run the env checks first)"
    return 1
  fi

  local services
  services="$(docker compose -f "$COMPOSE_FILE" config --services 2>/dev/null)"
  if [[ -z "$services" ]]; then
    _fail "no services found in $COMPOSE_FILE"
    return 1
  fi

  local expected=("api" "worker" "dashboard" "widget" "nginx")
  local svc state health ok=1
  for svc in "${expected[@]}"; do
    if ! grep -qx "$svc" <<<"$services"; then
      # The dev stack has no nginx; do not fail on optional services.
      [[ "$svc" == "nginx" ]] && continue
      _fail "service '$svc' not defined in $COMPOSE_FILE"
      ok=0
      continue
    fi
    # Format: <service> <state> <health> (health is empty when no healthcheck).
    state="$(docker compose -f "$COMPOSE_FILE" ps --format '{{.Service}} {{.State}} {{.Health}}' "$svc" | awk '{print $2}')"
    health="$(docker compose -f "$COMPOSE_FILE" ps --format '{{.Service}} {{.State}} {{.Health}}' "$svc" | awk '{print $3}')"
    if [[ "$state" == "running" && ( -z "$health" || "$health" == "healthy" ) ]]; then
      _pass "service '$svc' is running${health:+/}${health:+$health}"
    elif [[ "$state" == "running" ]]; then
      _fail "service '$svc' is running but $health"
      ok=0
    else
      _fail "service '$svc' state: ${state:-stopped}"
      ok=0
    fi
  done
  [[ "$ok" -eq 1 ]]
}

_http_ok() {
  local url="$1"
  curl -fsS -o /dev/null --max-time 15 "$url" 2>/dev/null
}

_check_api() {
  _title "API health (via $BASE_URL)"
  local ready live

  ready="$(curl -fsS --max-time 20 "$BASE_URL/api/health/ready" 2>/dev/null || true)"
  if grep -q '"status":"ready"' <<<"$ready"; then
    _pass "/api/health/ready reports ready (Mongo + Redis reachable)"
  else
    _fail "/api/health/ready did not report ready (body: ${ready:-no response})"
  fi

  live="$(curl -fsS --max-time 15 "$BASE_URL/api/health/live" 2>/dev/null || true)"
  if grep -q '"status":"alive"' <<<"$live"; then
    _pass "/api/health/live reports alive"
  else
    _fail "/api/health/live did not report alive"
  fi
}

_check_dashboard() {
  _title "Dashboard (via $BASE_URL)"
  if _http_ok "$BASE_URL$DASHBOARD_ROOT_PATH"; then
    _pass "root responds 200"
  else
    _fail "root did not respond 200"
  fi
  if _http_ok "$BASE_URL$DASHBOARD_ALIAS_PATH"; then
    _pass "$DASHBOARD_ALIAS_PATH responds 200"
  else
    _fail "$DASHBOARD_ALIAS_PATH did not respond 200"
  fi
}

_check_widget() {
  _title "Widget bundle (via $BASE_URL)"
  if _http_ok "$BASE_URL$WIDGET_PATH"; then
    _pass "$WIDGET_PATH responds 200"
  else
    _fail "$WIDGET_PATH did not respond 200"
  fi
}

main() {
  local ok=0
  _check_env && ok=$((ok + 1)) || true
  _check_compose && ok=$((ok + 1)) || true
  _check_api && ok=$((ok + 1)) || true
  _check_dashboard && ok=$((ok + 1)) || true
  _check_widget && ok=$((ok + 1)) || true

  printf '\n==> Summary: %d passed, %d failed\n' "$pass_count" "$fail_count"
  if ((fail_count == 0)); then
    printf 'Deployment looks healthy.\n'
    return 0
  fi
  printf 'Deployment needs attention - see the failures above.\n' >&2
  return 1
}

main "$@"
