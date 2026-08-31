#!/usr/bin/env bash
# scripts/deploy.sh — Docker Compose production deployment (migration + rollout + rollback).
#
# Deploys the four application services (api worker dashboard widget) built from
# immutable GHCR images tagged by CI. Local dev services (mongo/redis/mailpit)
# are never started here — the stack targets managed MongoDB/Redis.
#
# Usage:
#   scripts/deploy.sh deploy  --env-file .env.production --tag <git-sha> [--registry ghcr.io] [--namespace your-org]
#   scripts/deploy.sh migrate --env-file .env.production --tag <git-sha> [--registry ghcr.io] [--namespace your-org]
#   scripts/deploy.sh rollback --env-file .env.production --tag <previous-sha> [--registry ghcr.io] [--namespace your-org]
#   scripts/deploy.sh status  --env-file .env.production
#
# deploy = validate -> pull images -> run migrations -> compose up -> wait for
#          health; on failure it exits non-zero and prints the rollback command.
# migrate = run the one-shot migration only (idempotent; safe to re-run).
# rollback = redeploy a previously-known-good image tag (immutable tags make
#          this a single-tag restart, no rebuild).
# status = show running services + image tags + health readiness.
#
# Environment interpolation mirrors docker/compose.yml: ${VAR-default} will also
# be picked up by the compose file, so export IMAGE_TAG/IMAGE_REGISTRY/IMAGE_NAMESPACE
# before `docker compose ... up` if NOT passing them as flags here.
set -euo pipefail
cd "$(dirname "$0")/.."

DEFAULT_ENV_FILE=".env.production"
COMPOSE_BASE="docker/compose.yml"
COMPOSE_PROD="docker/compose.prod.yml"
PROJECT="webchat-ai"
API_IMAGE="webchat-ai-api"
WORKER_IMAGE="webchat-ai-worker"
DASHBOARD_IMAGE="webchat-ai-dashboard"
WIDGET_IMAGE="webchat-ai-widget"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RESET='\033[0m'
ok()  { echo -e "${GREEN}[ok]${RESET}   $1"; }
warn(){ echo -e "${YELLOW}[warn]${RESET} $1"; }
bad() { echo -e "${RED}[FAIL]${RESET}  $1"; }

usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; }

# Read a value from an env file (no shell eval; values with '#' are fine).
env_val() {
  local key="$1" file="$2" line
  while IFS= read -r line; do
    line="${line%%#*}"
    line="$(printf '%s' "$line" | tr -d '\r')"
    case "$line" in
      "$key="*) printf '%s' "${line#"$key"=}" | sed 's/^"//; s/"$//'; return 0 ;;
    esac
  done < "$file"
  return 1
}

preflight() {
  local ENV_FILE="$1"
  [ -f "$ENV_FILE" ] || { bad "env file not found: $ENV_FILE"; exit 1; }

  local ENVIRONMENT LOCAL_TEST MONGO_URI REDIS_URL JWT
  ENVIRONMENT=$(env_val ENVIRONMENT "$ENV_FILE" || echo development)
  LOCAL_TEST=$(env_val LOCAL_PRODUCTION_TEST "$ENV_FILE" || echo "")
  MONGO_URI=$(env_val MONGODB_URI "$ENV_FILE" || echo "")
  REDIS_URL=$(env_val REDIS_URL "$ENV_FILE" || echo "")
  JWT=$(env_val JWT_SECRET "$ENV_FILE" || echo "")

  if [ "$ENVIRONMENT" != "production" ]; then
    bad ".env requires ENVIRONMENT=production (found '$ENVIRONMENT')"; exit 1
  fi
  if [ "$LOCAL_TEST" = "true" ]; then
    bad "LOCAL_PRODUCTION_TEST=true found — this is a local-production-testing flag and must NEVER be set on a real deployment."; exit 1
  fi
  if { [ -z "$MONGO_URI" ] || [[ "$MONGO_URI" =~ (change_me|changeme|change-me) ]]; }; then
    bad "MONGODB_URI is missing or a placeholder in $ENV_FILE"; exit 1
  fi
  if { [ -z "$REDIS_URL" ] || [[ "$REDIS_URL" =~ (change_me|changeme|change-me) ]]; }; then
    bad "REDIS_URL is missing or a placeholder in $ENV_FILE"; exit 1
  fi
  if { [ -z "$JWT" ] || [[ "$JWT" =~ (change_me|changeme|dev-only-jwt-secret|your-secret) ]]; }; then
    bad "JWT_SECRET is missing or a known placeholder in $ENV_FILE"; exit 1
  fi
  ok "preflight: production env file passes deploy-time validation"
}

parse_args() {
  ACTION="${1:-}"; shift || true
  ENV_FILE="$DEFAULT_ENV_FILE"; IMAGE_TAG=""; REGISTRY="ghcr.io"; NAMESPACE=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --env-file) ENV_FILE="$2"; shift 2 ;;
      --tag)      IMAGE_TAG="$2"; shift 2 ;;
      --registry) REGISTRY="$2"; shift 2 ;;
      --namespace) NAMESPACE="$2"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) bad "unknown argument: $1"; usage; exit 1 ;;
    esac
  done
  if [ -z "$NAMESPACE" ]; then
    # Fall back to git remote owner (user/repo) so images resolve to the same
    # GHCR path CI publishes to; override with --namespace.
    NAMESPACE=$(git config --get remote.origin.url 2>/dev/null | sed -E 's#.*[:/]([^/]+/[^/.]+)(\.git)?$#\1#' || echo "")
  fi
}

compose_cmd() {
  docker compose --env-file "$ENV_FILE" --project-name "$PROJECT" -f "$COMPOSE_BASE" -f "$COMPOSE_PROD" "$@"
}

# Ensure the compose network exists BEFORE the migration one-shot runs.
# Compose derives the network name as `<project>_<key>` (webchat-ai_webchat from
# docker/compose.yml's `networks: webchat`) and only creates it lazily on the
# first `up`, so a fresh host has no network until then. Create it up front,
# mirroring the compose network's bridge MTU option, so the migration container
# and the rollout share one deterministic network. Idempotent.
ensure_network() {
  local net="${PROJECT}_webchat" mtu
  mtu=$(env_val DOCKER_BRIDGE_MTU "$ENV_FILE" || true)
  mtu="${mtu:-1500}"
  if docker network inspect "$net" >/dev/null 2>&1; then
    ok "network '$net' already exists"
  else
    # Mirror the labels compose stamps on its own network so the pre-created
    # network is recognized as compose-owned (no "not created by compose"
    # warning during the first rollout) and matches --network webchat.
    docker network create --driver bridge \
      --label "com.docker.compose.project=${PROJECT}" \
      --label "com.docker.compose.network=webchat" \
      --opt "com.docker.network.driver.mtu=${mtu}" \
      "$net"
    ok "created network '$net' (bridge mtu=${mtu})"
  fi
}

migrate() {
  preflight "$ENV_FILE"
  [ -n "$IMAGE_TAG" ] || { bad "--tag is required"; exit 1; }
  ensure_network
  local image="${REGISTRY:-ghcr.io}/${NAMESPACE:-your-org}/${API_IMAGE}:${IMAGE_TAG}"
  echo "==> Running schema migrations ($image)"
  docker pull "$image" >/dev/null 2>&1 || warn "image not found locally/remotely ($image); using local build"

  # Attach to the compose network the app runs on (webchat-ai_webchat). It was
  # ensured to exist above; fall back to the running api container's first
  # network if the stack was started with a different topology.
  local network
  network=$(docker inspect --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "${PROJECT}-api" 2>/dev/null | awk '{print $1}')
  [ -n "$network" ] || network="${PROJECT}_webchat"

  docker run --rm --name "${PROJECT}-migrate-${IMAGE_TAG##*.}" \
    --network "$network" \
    --env-file "$ENV_FILE" \
    "$image" python -m backend.migrations
  ok "migrations applied (exit 0)"
}

deploy() {
  preflight "$ENV_FILE"
  [ -n "$IMAGE_TAG" ] || { bad "--tag is required"; exit 1; }

  # 1. Ensure the compose network exists BEFORE pulling/migrating so the
  #    migration one-shot has a network to attach to on a fresh host.
  ensure_network

  # 2. Ensure immutable images are available.
  for svc in "$API_IMAGE" "$WORKER_IMAGE" "$DASHBOARD_IMAGE" "$WIDGET_IMAGE"; do
    local image="${REGISTRY:-ghcr.io}/${NAMESPACE:-your-org}/${svc}:${IMAGE_TAG}"
    ok "pulling $image"
    docker pull "$image" >/dev/null 2>&1 || warn "pull failed for $image — will use a local build if present"
  done

  # 3. Apply schema migrations BEFORE the rollout so the new API/worker never
  #    races against a not-yet-migrated schema.
  migrate

  # 4. Roll out the four application services.
  ok "rolling out api worker dashboard widget (tag=$IMAGE_TAG)"
  IMAGE_TAG="$IMAGE_TAG" IMAGE_REGISTRY="${REGISTRY:-ghcr.io}" IMAGE_NAMESPACE="${NAMESPACE:-your-org}" \
    compose_cmd up -d api worker dashboard widget

  wait_healthy
  status
  ok "deployment complete (tag=$IMAGE_TAG)"
}

wait_healthy() {
  echo "==> Waiting for API readiness (up to 180s)..."
  local i=0
  until curl -fsS "http://127.0.0.1:8000/api/health/ready" >/dev/null 2>&1; do
    i=$((i + 1))
    if [ "$i" -ge 180 ]; then
      bad "API did not become ready within 180s"
      docker compose --project-name "$PROJECT" -f "$COMPOSE_BASE" -f "$COMPOSE_PROD" ps
      echo ""
      bad "ROLLBACK: run:  $0 rollback --env-file $ENV_FILE --tag <previously-known-good-sha>"
      exit 1
    fi
    sleep 1
  done
  ok "API is ready (/api/health/ready)"
}

rollback() {
  preflight "$ENV_FILE"
  [ -n "$IMAGE_TAG" ] || { bad "--tag is required"; exit 1; }
  ok "rolling back to immutable tag $IMAGE_TAG"
  IMAGE_TAG="$IMAGE_TAG" IMAGE_REGISTRY="${REGISTRY:-ghcr.io}" IMAGE_NAMESPACE="${NAMESPACE:-your-org}" \
    compose_cmd up -d --force-recreate api worker dashboard widget
  wait_healthy
  ok "rollback complete (tag=$IMAGE_TAG)"
}

status() {
  compose_cmd ps
  echo ""
  ok "image tags in use:"
  for svc in "$API_IMAGE" "$WORKER_IMAGE" "$DASHBOARD_IMAGE" "$WIDGET_IMAGE"; do
    docker inspect "webchat-${svc##webchat-ai-}" 2>/dev/null --format "  {{.Name}} -> {{.Image}}" || true
  done
}

main() {
  if [ "$#" -eq 0 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then usage; exit 0; fi
  parse_args "$@"
  case "$ACTION" in
    deploy)   deploy ;;
    migrate)  migrate ;;
    rollback) rollback ;;
    status)   status ;;
    *) bad "unknown action: $ACTION"; usage; exit 1 ;;
  esac
}

main "$@"