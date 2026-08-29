#!/usr/bin/env bash
# scripts/check-production-docker.sh
# Phase 14.8.1 — Production Docker hardening audit (8 checks).
# Returns 0 when all checks pass, 1 on any failure.
#
# [1/8] Dockerfiles use non-root USER
# [2/8] No environment secrets copied
# [3/8] Resource limits configured
# [4/8] security_opt configured
# [5/8] cap_drop configured
# [6/8] Healthchecks configured
# [7/8] No privileged containers
# [8/8] Docker compose validation
set -euo pipefail
cd "$(dirname "$0")/.."

PASS=0; FAIL=0; TOTAL=0
pass() { PASS=$((PASS + 1)); TOTAL=$((TOTAL + 1)); echo "  [PASS] $1"; }
fail() { FAIL=$((FAIL + 1)); TOTAL=$((TOTAL + 1)); echo "  [FAIL] $1"; }
note() { echo "  [NOTE] $1"; }

COMPOSE="docker/compose.yml"
PROD_SERVICES="mongo redis mailpit api worker dashboard widget"

echo "=== Phase 14.8.1 — Production Docker audit (8 checks) ==="

# Extract a single service block (from "  name:" until the next sibling at the
# same 2-space indent) from the compose file.
svc_block() {
  awk -v svc="$1" '
    $0 ~ "^  " svc ":" { capture=1; print; next }
    capture && $0 ~ "^  [a-zA-Z]" { capture=0 }
    capture { print }
  ' "$COMPOSE"
}

# ── [1/8] All Dockerfiles run as non-root user ──────────────────────
echo ""
echo "[1/8] Dockerfiles use non-root USER"
non_root=0; non_root_expected=0
for f in docker/Dockerfile.*; do
    non_root_expected=$((non_root_expected + 1))
    # A USER directive that is not root / uid 0.
    if grep -qE '^USER\s+(root|0)\s*$' "$f"; then
        fail "$f runs as root USER"
    elif grep -qE '^USER\s+' "$f"; then
        non_root=$((non_root + 1))
    else
        fail "$f missing non-root USER directive"
    fi
done
if [ "$non_root" -eq "$non_root_expected" ] && [ "$non_root_expected" -gt 0 ]; then
    pass "All $non_root_expected Dockerfiles run as non-root"
fi

# ── [2/8] No environment secrets copied into images ─────────────────
echo ""
echo "[2/8] No environment secrets copied"
secrets_ok=true
if [ ! -f .dockerignore ]; then
    fail ".dockerignore file missing"
    secrets_ok=false
else
    for pattern in ".env" ".env.*" "*.env"; do
        if ! grep -qF "$pattern" .dockerignore; then
            fail ".dockerignore missing pattern: $pattern"
            secrets_ok=false
        fi
    done
fi
# No Dockerfile may COPY a .env / key / secret / credential file into the image.
for f in docker/Dockerfile.*; do
    if grep -qEi 'COPY\s+.*(\.env|\.pem|\.key|secret|credential)' "$f" 2>/dev/null; then
        fail "$f copies secrets into image"
        secrets_ok=false
    fi
done
if $secrets_ok; then
    pass "No .env/secret files copied into images (.dockerignore + Dockerfile scan)"
fi

# ── [3/8] Resource limits (memory + cpu) on all services ───────────
echo ""
echo "[3/8] Resource limits configured"
limits_missing=0
for svc in $PROD_SERVICES; do
    section=$(svc_block "$svc")
    has_mem=$(printf '%s' "$section" | grep -cE '^\s+memory:' || true)
    has_cpu=$(printf '%s' "$section" | grep -cE '^\s+cpus:' || true)
    if [ "$has_mem" -eq 0 ] || [ "$has_cpu" -eq 0 ]; then
        fail "$svc missing memory/cpu resource limits"
        limits_missing=$((limits_missing + 1))
    fi
done
if [ "$limits_missing" -eq 0 ]; then
    pass "All services have memory + CPU resource limits"
fi

# ── [4/8] security_opt: no-new-privileges on all services ──────────
echo ""
echo "[4/8] security_opt configured"
sec_missing=0
for svc in $PROD_SERVICES; do
    section=$(svc_block "$svc")
    if printf '%s' "$section" | grep -q 'no-new-privileges'; then
        :
    else
        fail "$svc missing security_opt: no-new-privileges"
        sec_missing=$((sec_missing + 1))
    fi
done
if [ "$sec_missing" -eq 0 ]; then
    pass "All services have security_opt: no-new-privileges"
fi

# ── [5/8] cap_drop: ALL on all services ────────────────────────────
echo ""
echo "[5/8] cap_drop configured"
cap_missing=0
for svc in $PROD_SERVICES; do
    section=$(svc_block "$svc")
    if printf '%s' "$section" | grep -qE 'cap_drop'; then
        :
    else
        fail "$svc missing cap_drop"
        cap_missing=$((cap_missing + 1))
    fi
done
if [ "$cap_missing" -eq 0 ]; then
    pass "All services have cap_drop configured"
fi

# ── [6/8] Healthchecks on all production services ──────────────────
echo ""
echo "[6/8] Healthchecks configured"
hc_missing=0
for svc in $PROD_SERVICES; do
    section=$(svc_block "$svc")
    if printf '%s' "$section" | grep -q 'healthcheck'; then
        :
    else
        fail "$svc missing healthcheck"
        hc_missing=$((hc_missing + 1))
    fi
done
if [ "$hc_missing" -eq 0 ]; then
    pass "All production services have healthchecks"
fi

# ── [7/8] No privileged containers ─────────────────────────────────
echo ""
echo "[7/8] No privileged containers"
privileged=$(grep -cE 'privileged:\s*true' "$COMPOSE" 2>/dev/null || true)
if [ "$privileged" -eq 0 ]; then
    pass "No privileged containers"
else
    fail "Found $privileged privileged container(s)"
fi

# ── [8/8] Docker compose validation ────────────────────────────────
echo ""
echo "[8/8] Docker compose validation"
if command -v docker >/dev/null 2>&1; then
    if docker compose -f "$COMPOSE" config --quiet >/dev/null 2>&1; then
        pass "docker compose config validates"
    else
        fail "docker compose config failed (run: docker compose -f $COMPOSE config)"
        docker compose -f "$COMPOSE" config >/dev/null || true
    fi
else
    note "docker not available in this environment — skipping live compose validation"
    note "verify manually: docker compose -f $COMPOSE config --quiet"
    TOTAL=$((TOTAL + 1))  # count as checked-but-skipped
fi

echo ""
echo "Production Docker audit: $PASS passed, $FAIL failed (of $TOTAL checks)"
if [ "$FAIL" -gt 0 ]; then
    echo "RESULT: FAIL"
    exit 1
fi
echo "RESULT: PASS"
exit 0
