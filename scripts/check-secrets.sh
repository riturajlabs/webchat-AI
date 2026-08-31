#!/usr/bin/env bash
# scripts/check-secrets.sh — lightweight secret scanner for CI / pre-commit
# No external dependencies; uses grep, git, and bash builtins.
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RESET='\033[0m'

PASS=0
FAIL=0

pass() { echo -e "${GREEN}  PASS${RESET}  $1"; PASS=$((PASS + 1)); }
fail() { echo -e "${RED}  FAIL${RESET}  $1"; FAIL=$((FAIL + 1)); }
warn() { echo -e "${YELLOW}  WARN${RESET}  $1"; }

echo "========================================"
echo " Secret Scan — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "========================================"
echo ""

# ── 1. Check tracked env files ──────────────────────────────────────────────
echo "[1/4] Tracked .env files"
TRACKED_ENVS=$(git ls-files --cached 2>/dev/null | grep -E '\.env' || true)
# Allow committed templates only: .env.example and .env.<name>.example.
# Real env files (.env, .env.development, .env.production) must never be tracked.
BAD_ENVS=$(echo "$TRACKED_ENVS" | grep -vE '\.env([.-][a-zA-Z0-9_-]+)*\.example$' || true)

if [ -z "$BAD_ENVS" ]; then
    pass "No tracked .env files (only .env.example)"
else
    fail "Secret env files tracked in git:"
    echo "$BAD_ENVS" | while IFS= read -r f; do echo "         $f"; done
fi
echo ""

# ── 2. Check staged / working-tree .env files ───────────────────────────────
echo "[2/4] Untracked .env files in working tree"
UNTRACKED_ENVS=$(find . -maxdepth 3 -name '.env*' -not -name '.env.example' -not -path './.git/*' -not -path './node_modules/*' -not -path './.venv/*' 2>/dev/null || true)

if [ -z "$UNTRACKED_ENVS" ]; then
    pass "No .env files found outside .env.example"
else
    echo "$UNTRACKED_ENVS" | while IFS= read -r f; do
        if [ -f "$f" ]; then
            warn "File exists locally (ensure it is gitignored): $f"
        fi
    done
    # This is a warning, not a failure — local .env files are expected
fi
echo ""

# ── 3. Scan tracked files for leaked secrets ────────────────────────────────
echo "[3/4] Scanning tracked files for secret patterns"

# Build list of tracked text files (exclude binaries, node_modules, etc.)
TRACKED_FILES=$(git ls-files --cached 2>/dev/null \
    -- ':!*.pyc' ':!*.pyo' ':!*.so' ':!*.dylib' ':!*.wasm' \
    ':!node_modules/' ':!.venv/' ':!*.min.js' ':!*.min.css' \
    ':!pnpm-lock.yaml' ':!package-lock.json' ':!*.lockb' \
    ':!*.svg' ':!*.png' ':!*.jpg' ':!*.gif' \
    | head -5000)

SECRET_FOUND=0

# Pattern: MongoDB URI with credentials (mongodb+srv://user:pass@)
if echo "$TRACKED_FILES" | xargs grep -rn -E 'mongodb(\+srv)?://[^/]*:[^/]*@' 2>/dev/null | grep -vE '\.env([.-][a-zA-Z0-9_-]+)*\.example' | grep -v 'check-secrets.sh' | grep -v '\.md:' | head -5 > /dev/null 2>&1; then
    fail "MongoDB URI with embedded credentials found"
    echo "$TRACKED_FILES" | xargs grep -rn -E 'mongodb(\+srv)?://[^/]*:[^/]*@' 2>/dev/null | grep -vE '\.env([.-][a-zA-Z0-9_-]+)*\.example' | grep -v 'check-secrets.sh' | grep -v '\.md:' | head -5 | while IFS= read -r line; do echo "         $line"; done
    SECRET_FOUND=1
fi

# Pattern: Redis URL with password (redis://:pass@)
if echo "$TRACKED_FILES" | xargs grep -rn -E 'redis(s)?://:[^@]+@' 2>/dev/null | grep -vE '\.env([.-][a-zA-Z0-9_-]+)*\.example' | grep -v 'check-secrets.sh' | grep -v '\.md:' | head -5 > /dev/null 2>&1; then
    fail "Redis URL with embedded password found"
    echo "$TRACKED_FILES" | xargs grep -rn -E 'redis(s)?://:[^@]+@' 2>/dev/null | grep -vE '\.env([.-][a-zA-Z0-9_-]+)*\.example' | grep -v 'check-secrets.sh' | grep -v '\.md:' | head -5 | while IFS= read -r line; do echo "         $line"; done
    SECRET_FOUND=1
fi

# Pattern: Generic API key assignments (KEY=sk-..., KEY=sk_live_, etc.)
if echo "$TRACKED_FILES" | xargs grep -rn -E '(API_KEY|SECRET|TOKEN|PASSWORD)\s*=\s*(sk[_-]|whsec_|ghp_|gho_|xoxb-|xoxp-|AKIA|AIza)' 2>/dev/null | grep -vE '\.env([.-][a-zA-Z0-9_-]+)*\.example' | grep -v 'check-secrets.sh' | grep -v '\.md:' | grep -v 'YOUR_API_KEY' | head -5 > /dev/null 2>&1; then
    fail "Possible API key or secret value found in tracked file"
    echo "$TRACKED_FILES" | xargs grep -rn -E '(API_KEY|SECRET|TOKEN|PASSWORD)\s*=\s*(sk[_-]|whsec_|ghp_|gho_|xoxb-|xoxp-|AKIA|AIza)' 2>/dev/null | grep -vE '\.env([.-][a-zA-Z0-9_-]+)*\.example' | grep -v 'check-secrets.sh' | grep -v '\.md:' | grep -v 'YOUR_API_KEY' | head -5 | while IFS= read -r line; do echo "         $line"; done
    SECRET_FOUND=1
fi

# Pattern: Private key blocks
if echo "$TRACKED_FILES" | xargs grep -rn -l 'BEGIN.*PRIVATE KEY' 2>/dev/null | grep -vE '\.env([.-][a-zA-Z0-9_-]+)*\.example' | grep -v 'check-secrets.sh' | head -5 > /dev/null 2>&1; then
    fail "Private key file tracked in git"
    echo "$TRACKED_FILES" | xargs grep -rn -l 'BEGIN.*PRIVATE KEY' 2>/dev/null | grep -vE '\.env([.-][a-zA-Z0-9_-]+)*\.example' | grep -v 'check-secrets.sh' | head -5 | while IFS= read -r line; do echo "         $line"; done
    SECRET_FOUND=1
fi

# Pattern: Bearer tokens with real-looking values
if echo "$TRACKED_FILES" | xargs grep -rn -E 'Bearer\s+[A-Za-z0-9_\-]{20,}' 2>/dev/null | grep -vE '\.env([.-][a-zA-Z0-9_-]+)*\.example' | grep -v 'check-secrets.sh' | grep -v '\.md:' | head -5 > /dev/null 2>&1; then
    fail "Possible Bearer token found in tracked file"
    echo "$TRACKED_FILES" | xargs grep -rn -E 'Bearer\s+[A-Za-z0-9_\-]{20,}' 2>/dev/null | grep -vE '\.env([.-][a-zA-Z0-9_-]+)*\.example' | grep -v 'check-secrets.sh' | grep -v '\.md:' | head -5 | while IFS= read -r line; do echo "         $line"; done
    SECRET_FOUND=1
fi

# Pattern: Generic password in config with real-looking value
if echo "$TRACKED_FILES" | xargs grep -rn -iE '(password|passwd|pwd)\s*[:=]\s*["\x27]?[A-Za-z0-9_\-]{8,}' 2>/dev/null | grep -vE '\.env([.-][a-zA-Z0-9_-]+)*\.example' | grep -v 'check-secrets.sh' | grep -v '\.md:' | grep -v 'CHANGE_ME' | grep -v 'YOUR_' | head -5 > /dev/null 2>&1; then
    fail "Possible hardcoded password found"
    echo "$TRACKED_FILES" | xargs grep -rn -iE '(password|passwd|pwd)\s*[:=]\s*["\x27]?[A-Za-z0-9_\-]{8,}' 2>/dev/null | grep -vE '\.env([.-][a-zA-Z0-9_-]+)*\.example' | grep -v 'check-secrets.sh' | grep -v '\.md:' | grep -v 'CHANGE_ME' | grep -v 'YOUR_' | head -5 | while IFS= read -r line; do echo "         $line"; done
    SECRET_FOUND=1
fi

if [ "$SECRET_FOUND" -eq 0 ]; then
    pass "No obvious secrets found in tracked files"
fi
echo ""

# ── 4. Summary ──────────────────────────────────────────────────────────────
echo "[4/4] Summary"
echo "  Passed: $PASS"
echo "  Failed: $FAIL"
echo ""

if [ "$FAIL" -gt 0 ]; then
    echo -e "${RED}RESULT: FAIL — secrets detected. Do not commit.${RESET}"
    exit 1
else
    echo -e "${GREEN}RESULT: PASS — no secrets in tracked files${RESET}"
    exit 0
fi
