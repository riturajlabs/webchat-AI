#!/usr/bin/env bash
# scripts/check-database-security.sh — Database security posture checks
# Validates MongoDB auth, port exposure, credential leaks, settings validation,
# and backup documentation for the WebChat AI stack.
set -uo pipefail

COMPOSE_FILE="docker/compose.yml"
ENV_FILE=".env.production"
ANY_FAIL=0

# ── Argument parsing ─────────────────────────────────────────────────────────
while [ $# -gt 0 ]; do
    case "$1" in
        --env-file)
            ENV_FILE="$2"; shift 2 ;;
        --compose-file)
            COMPOSE_FILE="$2"; shift 2 ;;
        *)
            echo "Unknown argument: $1"; exit 2 ;;
    esac
done

# ── Helpers ──────────────────────────────────────────────────────────────────
# Read a key from an env file (VAR=value). Strips surrounding quotes.
# Outputs empty string if key is absent or empty.
env_val() {
    local key="$1" file="$2"
    if [ ! -f "$file" ]; then
        echo ""
        return
    fi
    # Match VAR=val or VAR="val" — skip comment lines, stop at first match.
    local line
    line=$(grep -E "^${key}=" "$file" 2>/dev/null | head -1 || true)
    if [ -z "$line" ]; then
        echo ""
        return
    fi
    # Strip KEY= and outer quotes
    local val="${line#*=}"
    val="${val#\"}"
    val="${val%\"}"
    val="${val#\'}"
    val="${val%\'}"
    echo "$val"
}

# ── Check 1/5: MongoDB authentication enabled ───────────────────────────────
echo "[1/5] MongoDB authentication enabled"

if [ ! -f "$ENV_FILE" ]; then
    echo "      [SKIP] env file not found: $ENV_FILE"
else
    ENVIRONMENT=$(env_val ENVIRONMENT "$ENV_FILE")
    LOCAL_TEST=$(env_val LOCAL_PRODUCTION_TEST "$ENV_FILE")
    MONGO_URI=$(env_val MONGODB_URI "$ENV_FILE")
    MONGO_USER=$(env_val MONGO_USERNAME "$ENV_FILE")
    MONGO_PASS=$(env_val MONGO_PASSWORD "$ENV_FILE")

    # Only enforce when production AND not local-production-test
    if [ "$ENVIRONMENT" = "production" ] && [ "$LOCAL_TEST" != "true" ]; then
        URI_HAS_CREDS=0
        case "$MONGO_URI" in
            *@*) URI_HAS_CREDS=1 ;;
        esac
        if [ "$URI_HAS_CREDS" -eq 1 ] || { [ -n "$MONGO_USER" ] && [ -n "$MONGO_PASS" ]; }; then
            echo "      [PASS] MongoDB auth configured (production)"
        else
            echo "      [FAIL] MongoDB auth required in production — MONGODB_URI must embed credentials or MONGO_USERNAME+MONGO_PASSWORD must be set"
            ANY_FAIL=1
        fi
    else
        echo "      [PASS] non-production / local-test mode — auth optional"
    fi
fi
echo ""

# ── Check 2/5: MongoDB port not exposed to host ─────────────────────────────
echo "[2/5] MongoDB port not exposed to host"

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "      [SKIP] compose file not found: $COMPOSE_FILE"
elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    # Use docker compose config for authoritative parsed output
    MONGO_SERVICES=$(docker compose -f "$COMPOSE_FILE" config --services 2>/dev/null || true)
    case "$MONGO_SERVICES" in
        *mongo*)
            # Extract the mongo service block and look for ports
            MONGO_BLOCK=$(docker compose -f "$COMPOSE_FILE" config 2>/dev/null | sed -n '/^services:/,/^volumes:/p' | sed -n '/^  mongo:/,/^  [a-z]/p' || true)
            if echo "$MONGO_BLOCK" | grep -qE '^\s+ports:'; then
                echo "      [FAIL] mongo service has a host port mapping"
                ANY_FAIL=1
            else
                echo "      [PASS] mongo has no host port mapping (docker compose config)"
            fi
            ;;
        *)
            echo "      [SKIP] mongo service not found in compose config"
            ;;
    esac
else
    # Fallback: grep the raw YAML for mongo service section
    MONGO_BLOCK=$(sed -n '/^  mongo:/,/^  [a-z]/p' "$COMPOSE_FILE" | head -n -1 || true)
    if [ -z "$MONGO_BLOCK" ]; then
        echo "      [SKIP] could not parse mongo service from $COMPOSE_FILE"
    elif echo "$MONGO_BLOCK" | grep -qE '^\s+ports:'; then
        echo "      [FAIL] mongo service has a host port mapping (grep fallback)"
        ANY_FAIL=1
    else
        echo "      [PASS] mongo has no host port mapping (grep fallback)"
    fi
fi
echo ""

# ── Check 3/5: Credentials not committed to git ─────────────────────────────
echo "[3/5] Credentials not committed to git"

LEAK_FOUND=0

# 3a. .env files must not be tracked
for tracked_env in $(git ls-files 2>/dev/null | grep -E '\.env\.(production|development)$' || true); do
    echo "      [FAIL] tracked env file: $tracked_env"
    LEAK_FOUND=1
done

# 3b. Scan tracked files for literal password assignments (non-empty, real values).
# Exclude: .env.example, .env.*.example, compose.yml variable references ${VAR-default}.
# Only flag lines like VAR=realvalue (not VAR=${VAR-default} or VAR=).
if [ "$LEAK_FOUND" -eq 0 ]; then
    # Search tracked files for password-like patterns
    LEAK_HITS=$(git grep -n -E '(MONGO_PASSWORD|REDIS_PASSWORD)=' -- ':!.env.example' ':!.env.*.example' ':!docker/compose.yml' 2>/dev/null | grep -v '=${' | grep -v '=$' | grep -v '^\(.*\.env\.\(production\|development\):.*#.*\)' || true)
    # Filter out comment-only lines and variable-interpolation lines
    LEAK_HITS=$(echo "$LEAK_HITS" | grep -v '^\s*#' | grep -v '=.*\${' | grep -v '=$(' || true)
    if [ -n "$LEAK_HITS" ]; then
        echo "      [FAIL] password value found in tracked files:"
        echo "$LEAK_HITS" | while IFS= read -r hit; do echo "             $hit"; done
        LEAK_FOUND=1
    fi
fi

if [ "$LEAK_FOUND" -eq 1 ]; then
    ANY_FAIL=1
else
    echo "      [PASS] no credential leaks in tracked files"
fi
echo ""

# ── Check 4/5: Connection string validation ─────────────────────────────────
echo "[4/5] Connection string validation"

if [ ! -f "$ENV_FILE" ]; then
    echo "      [SKIP] env file not found: $ENV_FILE"
elif [ ! -x .venv/bin/python ]; then
    echo "      [SKIP] python venv not available at .venv/bin/python"
else
    SETTINGS_OUTPUT=$(./.venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from backend.core.config import Settings
Settings(_env_file='${ENV_FILE}')
print('ok')
" 2>&1) || SETTINGS_EXIT=$?
    SETTINGS_EXIT=${SETTINGS_EXIT:-0}
    if [ "$SETTINGS_EXIT" -eq 0 ] && echo "$SETTINGS_OUTPUT" | grep -q '^ok$'; then
        echo "      [PASS] Settings validation passed for $ENV_FILE"
    else
        echo "      [FAIL] Settings validation failed for $ENV_FILE"
        echo "$SETTINGS_OUTPUT" | tail -5 | sed 's/^/             /'
        ANY_FAIL=1
    fi
fi
echo ""

# ── Check 5/5: Backup documentation exists ──────────────────────────────────
echo "[5/5] Backup documentation exists"

BACKUP_DOC="docs/DATABASE_BACKUP_RESTORE.md"
if [ ! -f "$BACKUP_DOC" ]; then
    echo "      [FAIL] $BACKUP_DOC not found"
    ANY_FAIL=1
else
    DOC_CONTENT=$(tr '[:upper:]' '[:lower:]' < "$BACKUP_DOC")
    HAS_MONGODUMP=0
    HAS_MONGORESTORE=0
    case "$DOC_CONTENT" in
        *mongodump*)  HAS_MONGODUMP=1 ;;
    esac
    case "$DOC_CONTENT" in
        *mongorestore*) HAS_MONGORESTORE=1 ;;
    esac
    if [ "$HAS_MONGODUMP" -eq 1 ] && [ "$HAS_MONGORESTORE" -eq 1 ]; then
        echo "      [PASS] $BACKUP_DOC exists and references mongodump/mongorestore"
    else
        echo "      [FAIL] $BACKUP_DOC missing required content (mongodump or mongorestore)"
        ANY_FAIL=1
    fi
fi
echo ""

# ── Summary ──────────────────────────────────────────────────────────────────
echo "========================================"
if [ "$ANY_FAIL" -eq 0 ]; then
    echo "DATABASE SECURITY: PASS"
else
    echo "DATABASE SECURITY: FAIL"
fi
echo "========================================"

exit "$ANY_FAIL"
