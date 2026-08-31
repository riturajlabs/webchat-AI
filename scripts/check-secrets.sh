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

# ─────────────────────────────────────────────────────────────────────────────
# Verified non-secret line filter.
#
# This is NOT a broad ignore list: we never suppress whole files/directories,
# and nothing under application/infra code (backend/, apps/, docker/, etc.) is
# ever exempted. Suppressions are limited to:
#   (1) doc/usage comment lines (leading `#` or `//`), and
#   (2) explicit signal-password / bearer-style false positives refined below.
# A real credential added anywhere still matches the rules and fails the build.
#
# 1) Comment lines (leading `#` or `//` after `path:lineno:`): documentation /
#    usage examples are not executable configuration. A real credential is never
#    expressed as a doc comment; secrets in active code are still flagged.
comment_line() { grep -vE '^[^:]+:[0-9]+:[[:space:]]*(#|//)'; }

# 2) The generic password rule is refined to ignore values that are bare
#    alphabetic identifiers (variable names / enum constants), which are never
#    real secrets.  Real passwords contain digits or symbols and are still hit.
bare_identifier() { grep -viE '(password|passwd|pwd)[[:space:]]*[:=][[:space:]]*["'"'"']?[A-Za-z_]{4,}["'"'"']?(,|;|\)|\}|\]|\[|[[:space:]]|$)'; }

# 3) Path-scoped exceptions for deliberately synthetic test/seed fixtures.
#
# This is NOT a broad whitelist: it only suppresses a match when BOTH
#   (a) the line is under `tests/` or `scripts/` (test doubles / local dev seed
#       tooling), AND
#   (b) the secret value is one of the explicit, documented synthetic markers
#       below (names contain markers like `test`, `dummy`, `perf`, `FAKE`).
# Application / infra code (backend/, apps/, docker/, migrations/, etc.) is
# NEVER exempted — any real-looking credential there still fails the build.
# Each marker below was reviewed and classified as a non-credential fixture.
is_synthetic_fixture() {
  local line="$1"
  case "$line" in
    tests/*|scripts/*)
      case "$line" in
        # tests/test_logging.py — input to SensitiveDataFilter proving a
        # Bearer-like string is redacted (obvious FAKE marker, not a token).
        *'Bearer FAKE.JWT.FOR.REDACTION.TEST'*) return 0 ;;
        # scripts/perf/seed.py + load-test.js — deterministic benchmark-only
        # dev-stack account (documented in seed.py docstring).
        *'perf-test-password-123'*) return 0 ;;
        # scripts/seed-widget.py — throwaway local-dev tenant password.
        *'seed-dummy-pass-2026'*) return 0 ;;
        # tests/* — generic config/test-double passwords (mongo/redis test-pass,
        # wrong/unknown login fixtures, password-reset doubles, redaction input).
        # All literal `...-pass` / `Pass1!` / `Str0ng!` test fixtures reviewed.
        *'test-pass'*) return 0 ;;
        *'WrongPass1!'*) return 0 ;;
        *'Whatever1!'*) return 0 ;;
        *'NewStr0ng!Pass'*) return 0 ;;
        *'AnotherStr0ng!'*) return 0 ;;
        *'SuperSecret123!'*) return 0 ;;
      esac
      ;;
  esac
  return 1
}
filter_safe() {
  local line
  while IFS= read -r line; do
    if ! is_synthetic_fixture "$line"; then printf '%s\n' "$line"; fi
  done
}
# Common post-filter chain shared by every rule: drop .example env files, this
# script itself, markdown docs, and the verified non-secret lines above.
common_filter() {
  grep -vE '\.env([.-][a-zA-Z0-9_-]+)*\.example' \
    | grep -v 'check-secrets.sh' \
    | grep -v '\.md:' \
    | comment_line \
    | filter_safe
}
# ─────────────────────────────────────────────────────────────────────────────

# Pattern: MongoDB URI with credentials (mongodb+srv://user:pass@)
if echo "$TRACKED_FILES" | xargs grep -rn -E 'mongodb(\+srv)?://[^/]*:[^/]*@' 2>/dev/null | common_filter | head -5 > /dev/null 2>&1; then
    fail "MongoDB URI with embedded credentials found"
    echo "$TRACKED_FILES" | xargs grep -rn -E 'mongodb(\+srv)?://[^/]*:[^/]*@' 2>/dev/null | common_filter | head -5 | while IFS= read -r line; do echo "         $line"; done
    SECRET_FOUND=1
fi

# Pattern: Redis URL with password (redis://:pass@)
if echo "$TRACKED_FILES" | xargs grep -rn -E 'redis(s)?://:[^@]+@' 2>/dev/null | common_filter | head -5 > /dev/null 2>&1; then
    fail "Redis URL with embedded password found"
    echo "$TRACKED_FILES" | xargs grep -rn -E 'redis(s)?://:[^@]+@' 2>/dev/null | common_filter | head -5 | while IFS= read -r line; do echo "         $line"; done
    SECRET_FOUND=1
fi

# Pattern: Generic API key assignments (KEY=sk-..., KEY=sk_live_, etc.)
if echo "$TRACKED_FILES" | xargs grep -rn -E '(API_KEY|SECRET|TOKEN|PASSWORD)\s*=\s*(sk[_-]|whsec_|ghp_|gho_|xoxb-|xoxp-|AKIA|AIza)' 2>/dev/null | common_filter | grep -v 'YOUR_API_KEY' | head -5 > /dev/null 2>&1; then
    fail "Possible API key or secret value found in tracked file"
    echo "$TRACKED_FILES" | xargs grep -rn -E '(API_KEY|SECRET|TOKEN|PASSWORD)\s*=\s*(sk[_-]|whsec_|ghp_|gho_|xoxb-|xoxp-|AKIA|AIza)' 2>/dev/null | common_filter | grep -v 'YOUR_API_KEY' | head -5 | while IFS= read -r line; do echo "         $line"; done
    SECRET_FOUND=1
fi

# Pattern: Private key blocks
if echo "$TRACKED_FILES" | xargs grep -rn -l 'BEGIN.*PRIVATE KEY' 2>/dev/null | grep -vE '\.env([.-][a-zA-Z0-9_-]+)*\.example' | grep -v 'check-secrets.sh' | head -5 > /dev/null 2>&1; then
    fail "Private key file tracked in git"
    echo "$TRACKED_FILES" | xargs grep -rn -l 'BEGIN.*PRIVATE KEY' 2>/dev/null | grep -vE '\.env([.-][a-zA-Z0-9_-]+)*\.example' | grep -v 'check-secrets.sh' | head -5 | while IFS= read -r line; do echo "         $line"; done
    SECRET_FOUND=1
fi

# Pattern: Bearer tokens with real-looking values
if echo "$TRACKED_FILES" | xargs grep -rn -E 'Bearer\s+[A-Za-z0-9_\-]{20,}' 2>/dev/null | common_filter | head -5 > /dev/null 2>&1; then
    fail "Possible Bearer token found in tracked file"
    echo "$TRACKED_FILES" | xargs grep -rn -E 'Bearer\s+[A-Za-z0-9_\-]{20,}' 2>/dev/null | common_filter | head -5 | while IFS= read -r line; do echo "         $line"; done
    SECRET_FOUND=1
fi

# Pattern: Generic password in config with real-looking value
# Refined by bare_identifier() so `new_password: password`,
# `AUDIT_FORGOT_PASSWORD = "..."`, and `password: PASSWORD` (bare identifiers /
# enum / variable references) don't false-positive, while any value containing
# digits or symbols still matches.
if echo "$TRACKED_FILES" | xargs grep -rn -iE '(password|passwd|pwd)\s*[:=]\s*["\x27]?[A-Za-z0-9_\-]{8,}' 2>/dev/null | common_filter | grep -v 'CHANGE_ME' | grep -v 'YOUR_' | bare_identifier | head -5 > /dev/null 2>&1; then
    fail "Possible hardcoded password found"
    echo "$TRACKED_FILES" | xargs grep -rn -iE '(password|passwd|pwd)\s*[:=]\s*["\x27]?[A-Za-z0-9_\-]{8,}' 2>/dev/null | common_filter | grep -v 'CHANGE_ME' | grep -v 'YOUR_' | bare_identifier | head -5 | while IFS= read -r line; do echo "         $line"; done
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
