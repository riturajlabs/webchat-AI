#!/usr/bin/env bash
# WebChat AI - one-command production deployment with automatic rollback.
#
# Flow: git pull --ff-only -> load .env.production -> compose build (fresh tag)
#       -> compose up -d -> wait for healthchecks -> deployment-check.sh
# On any failure after `up`, it rolls back to the previously running image tag.
#
# Example:
#   cd /opt/webchat-ai && scripts/deploy-production.sh
#
# Optional env:
#   APP_DIR       deployment directory (default: this repo root)
#   BRANCH        git branch            (default: main)
#   COMPOSE_FILE  compose file          (default: docker-compose.prod.yml)
#   TAG           explicit image tag    (default: git short SHA)
#   HEALTH_TIMEOUT  seconds to wait for healthchecks (default: 300)
set -euo pipefail

cd "$(dirname "$0")/.."       # this script lives in <repo>/scripts

APP_DIR="$(pwd)"
BRANCH="${BRANCH:-main}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
TAG="${TAG:-}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-300}"

log()  { printf '\n==> %s\n' "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# --- 1. preflight -----------------------------------------------------------
[[ -d .git ]] || die "not a git repository: ${APP_DIR}"
command -v docker >/dev/null 2>&1 || die "docker not installed (run scripts/server-init.sh)"
docker compose version >/dev/null 2>&1 || die "docker compose plugin missing (run scripts/server-init.sh)"
[[ -f .env.production ]] || die ".env.production missing - copy .env.production.example and fill it in"

# --- 2. load secrets, capture the running stack -----------------------------
set -a; source .env.production; set +a

OLD_TAG=""
FIRST_CID="$(docker compose -f "$COMPOSE_FILE" ps -q 2>/dev/null | head -n1 || true)"
if [[ -n "${FIRST_CID}" ]]; then
  OLD_TAG="$(docker inspect -f '{{index .Config.Image}}' "${FIRST_CID}" 2>/dev/null | sed -E 's/.*:([^:]+)$/\1/')"
fi
log "Current image tag: ${OLD_TAG:-<none - first deployment>}"

# --- 3. pull the new code ---------------------------------------------------
log "Pulling branch '${BRANCH}'"
git fetch origin
git checkout "${BRANCH}"
git pull --ff-only origin "${BRANCH}"

NEW_TAG="${TAG:-$(git rev-parse --short HEAD)}"
log "Deploying tag: ${NEW_TAG}"
export TAG="${NEW_TAG}"

# --- 4. build ---------------------------------------------------------------
log "Building images (${COMPOSE_FILE})"
docker compose -f "${COMPOSE_FILE}" build

# --- 5. up -d (point of no return: failures trigger rollback) ---------------
rollback() {
  printf '\nDEPLOY FAILED - rolling back.\n' >&2
  if [[ -n "${OLD_TAG:-}" ]]; then
    export TAG="${OLD_TAG}"
    docker compose -f "${COMPOSE_FILE}" up -d || printf '  rollback up failed\n' >&2
    if wait_for_healthy && scripts/deployment-check.sh; then
      printf 'Rollback OK - running image tag %s\n' "${OLD_TAG}"
    else
      printf 'ROLLBACK UNHEALTHY - manual intervention required (see docs/ORACLE_FREE_VM_DEPLOYMENT.md)\n' >&2
    fi
  else
    printf 'No previous image tag - nothing to roll back to (first deployment).\n' >&2
  fi
  exit 1
}

wait_for_healthy() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT)) out svc state health ok
  while (( SECONDS < deadline )); do
    out="$(docker compose -f "${COMPOSE_FILE}" ps --format '{{.Service}} {{.State}} {{.Health}}')"
    ok=1
    while read -r svc state health; do
      [[ "${state}" == "running" ]] || ok=0
      if [[ -n "${health}" && "${health}" != "healthy" ]]; then ok=0; fi
    done <<<"${out}"
    [[ "${ok}" == "1" ]] && return 0
    sleep 5
  done
  return 1
}

log "Starting containers (${COMPOSE_FILE})"
set -Eeuo pipefail
trap rollback ERR
docker compose -f "${COMPOSE_FILE}" up -d

log "Waiting for all services to become healthy (${HEALTH_TIMEOUT}s)"
wait_for_healthy

# --- 6. end-to-end verification ---------------------------------------------
log "Running deployment checks"
scripts/deployment-check.sh
trap - ERR

log "Deploy successful (tag ${NEW_TAG})."
log "Next steps: inspect logs, then remove stale images: docker image prune -f"
