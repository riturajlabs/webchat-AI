#!/usr/bin/env bash
# scripts/check-docker-security.sh — Docker security posture check
# Inspects Dockerfiles and compose.yml for hardening compliance.
# No external dependencies; uses grep, sed, and bash builtins.
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RESET='\033[0m'

PASS=0
FAIL=0
WARN=0

pass() { echo -e "${GREEN}  PASS${RESET}  $1"; PASS=$((PASS + 1)); }
fail() { echo -e "${RED}  FAIL${RESET}  $1"; FAIL=$((FAIL + 1)); }
warn() { echo -e "${YELLOW}  WARN${RESET}  $1"; WARN=$((WARN + 1)); }

COMPOSE="docker/compose.yml"

echo "========================================"
echo " Docker Security Check — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "========================================"
echo ""

# ── 1. Dockerfiles run as non-root ──────────────────────────────────────────
echo "[1/6] Dockerfiles: non-root USER directive"

for df in docker/Dockerfile.api docker/Dockerfile.worker docker/Dockerfile.dashboard docker/Dockerfile.widget; do
    if [ ! -f "$df" ]; then
        warn "Dockerfile not found: $df"
        continue
    fi
    # Check for a USER directive that is not root
    USER_LINE=$(grep -E '^USER\s+' "$df" 2>/dev/null | tail -1 || true)
    if [ -z "$USER_LINE" ]; then
        fail "$df — no USER directive (runs as root)"
    elif echo "$USER_LINE" | grep -qE 'USER\s+(root|0)\s*$'; then
        fail "$df — USER is explicitly root"
    else
        USER_NAME=$(echo "$USER_LINE" | awk '{print $2}')
        pass "$df — USER $USER_NAME"
    fi
done
echo ""

# ── 2. MongoDB not publicly exposed ─────────────────────────────────────────
echo "[2/6] MongoDB: no host port mapping"

if [ ! -f "$COMPOSE" ]; then
    fail "compose file not found: $COMPOSE"
else
    # Find the mongo service block and check for ports
    MONGO_BLOCK=$(sed -n '/^  mongo:/,/^  [a-z]/p' "$COMPOSE" | head -n -1)
    if echo "$MONGO_BLOCK" | grep -qE '^\s+ports:'; then
        fail "MongoDB has a host port mapping — remove 'ports:' from mongo service"
    else
        pass "MongoDB has no host port mapping"
    fi
fi
echo ""

# ── 3. Redis not publicly exposed ───────────────────────────────────────────
echo "[3/6] Redis: no host port mapping"

if [ -f "$COMPOSE" ]; then
    REDIS_BLOCK=$(sed -n '/^  redis:/,/^  [a-z]/p' "$COMPOSE" | head -n -1)
    if echo "$REDIS_BLOCK" | grep -qE '^\s+ports:'; then
        fail "Redis has a host port mapping — remove 'ports:' from redis service"
    else
        pass "Redis has no host port mapping"
    fi
fi
echo ""

# ── 4. No privileged containers ─────────────────────────────────────────────
echo "[4/6] No privileged containers"

if [ -f "$COMPOSE" ]; then
    PRIV_LINE=$(grep -n 'privileged:\s*true' "$COMPOSE" 2>/dev/null || true)
    if [ -n "$PRIV_LINE" ]; then
        fail "Privileged mode found:"
        echo "$PRIV_LINE" | while IFS= read -r line; do echo "         $line"; done
    else
        pass "No containers use privileged: true"
    fi
fi
echo ""

# ── 5. security_opt: no-new-privileges on all services ──────────────────────
echo "[5/6] security_opt: no-new-privileges on services"

if [ -f "$COMPOSE" ]; then
    # Extract only service names from the services: section.
    # Match lines indented with exactly 4 spaces under "services:" that end
    # with ":" and are NOT under "volumes:" or "networks:" sections.
    IN_SERVICES=0
    SERVICES=""
    while IFS= read -r line; do
        # Detect section headers (top-level keys)
        if echo "$line" | grep -qE '^services:'; then
            IN_SERVICES=1
            continue
        fi
        if echo "$line" | grep -qE '^(networks|volumes|x-):'; then
            IN_SERVICES=0
            continue
        fi
        if [ "$IN_SERVICES" -eq 1 ]; then
            # Service names are indented with exactly 4 spaces and end with ":"
            SVC_NAME=$(echo "$line" | sed -n 's/^  \([a-z][a-z0-9_-]*\):$/\1/p')
            if [ -n "$SVC_NAME" ]; then
                SERVICES="$SERVICES $SVC_NAME"
            fi
        fi
    done < "$COMPOSE"

    for svc in $SERVICES; do
        SVC_BLOCK=$(sed -n "/^  ${svc}:/,/^  [a-z]/p" "$COMPOSE")
        if echo "$SVC_BLOCK" | grep -q 'no-new-privileges:true'; then
            pass "$svc — no-new-privileges"
        else
            warn "$svc — missing no-new-privileges (recommended)"
        fi
    done
fi
echo ""

# ── 6. cap_drop: ALL on all services ─────────────────────────────────────────
echo "[6/6] cap_drop: ALL on all services"

if [ -f "$COMPOSE" ]; then
    # Reuse SERVICES from section 5 (already extracted)
    for svc in $SERVICES; do
        SVC_BLOCK=$(sed -n "/^  ${svc}:/,/^  [a-z]/p" "$COMPOSE")
        if echo "$SVC_BLOCK" | grep -qE 'cap_drop:.*ALL|- ALL'; then
            pass "$svc — cap_drop ALL"
        else
            fail "$svc — missing cap_drop: ALL"
        fi
    done
fi
echo ""

# ── Summary ──────────────────────────────────────────────────────────────────
echo "========================================"
echo " Summary"
echo "  Passed: $PASS"
echo "  Failed: $FAIL"
echo "  Warnings: $WARN"
echo "========================================"

if [ "$FAIL" -gt 0 ]; then
    echo -e "${RED}RESULT: FAIL — $FAIL critical issue(s) found${RESET}"
    exit 1
elif [ "$WARN" -gt 0 ]; then
    echo -e "${YELLOW}RESULT: PASS with $WARN warning(s)${RESET}"
    exit 0
else
    echo -e "${GREEN}RESULT: PASS — all checks passed${RESET}"
    exit 0
fi
