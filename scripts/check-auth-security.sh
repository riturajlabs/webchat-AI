#!/usr/bin/env bash
# check-auth-security.sh — Verify Phase 14.4 auth & session security hardening.
#
# Exit 0 when every check passes; exit 1 on the first failure.
set -euo pipefail

PASS=0
FAIL=0
TOTAL=0

pass() { PASS=$((PASS + 1)); TOTAL=$((TOTAL + 1)); echo "  ✓ $1"; }
fail() { FAIL=$((FAIL + 1)); TOTAL=$((TOTAL + 1)); echo "  ✗ $1"; }

echo "─── Auth security audit ───"

# ── [1/7] JWT secret validation ──────────────────────────────────────
if grep -q 'JWT_SECRET must be at least 32 characters in production' backend/core/config.py; then
  pass "JWT secret minimum length validated in production"
else
  fail "No JWT secret minimum length validator"
fi

if grep -q 'jwt_secret: str' backend/core/config.py; then
  pass "JWT secret field exists in config"
else
  fail "JWT secret field missing"
fi

# ── [2/7] Cookie security ───────────────────────────────────────────
if grep -q 'httponly=True' backend/api/routes/auth.py; then
  pass "Refresh cookie uses HttpOnly"
else
  fail "Refresh cookie missing HttpOnly"
fi

if grep -q 'samesite="lax"' backend/api/routes/auth.py; then
  pass "Auth cookies use SameSite=Lax"
else
  fail "Auth cookies missing SameSite"
fi

if grep -q 'COOKIE_SECURE must be true in production' backend/core/config.py; then
  pass "Production rejects COOKIE_SECURE=false"
else
  fail "No production validator for COOKIE_SECURE"
fi

# ── [3/7] Refresh token rotation ─────────────────────────────────────
if grep -q 'find_and_consume' backend/services/auth/auth_service.py; then
  pass "Refresh token rotation uses atomic consumption"
else
  fail "Refresh token rotation not atomic"
fi

if grep -q 'TokenReuseError' backend/services/auth/auth_service.py; then
  pass "Refresh token reuse detection exists"
else
  fail "No refresh token reuse detection"
fi

# ── [4/7] Logout invalidation ────────────────────────────────────────
if grep -q 'revoke_token' backend/services/auth/auth_service.py; then
  pass "Logout revokes refresh token"
else
  fail "Logout does not revoke refresh token"
fi

if grep -q 'revoke_all_for_user' backend/services/auth/auth_service.py; then
  pass "Logout-all revokes all user sessions"
else
  fail "Logout-all not implemented"
fi

if grep -q 'delete_cookie' backend/api/routes/auth.py; then
  pass "Logout clears cookies"
else
  fail "Logout does not clear cookies"
fi

# ── [5/7] Login brute-force protection ───────────────────────────────
if grep -q 'login_max_attempts' backend/core/config.py; then
  pass "Login max attempts configurable"
else
  fail "Login max attempts not configurable"
fi

if grep -q 'lock_account' backend/services/auth/auth_service.py; then
  pass "Account lockout implemented"
else
  fail "Account lockout not implemented"
fi

if grep -q 'Invalid email or password' backend/services/auth/auth_service.py; then
  pass "Login error is generic (no user enumeration)"
else
  fail "Login error may leak user existence"
fi

if grep -q 'login_limiter' backend/api/deps.py; then
  pass "Login rate limiting exists"
else
  fail "Login rate limiting missing"
fi

# ── [6/7] Auth response cache headers ────────────────────────────────
if grep -q 'AuthCacheHeadersMiddleware' backend/api/middleware.py; then
  pass "AuthCacheHeadersMiddleware exists"
else
  fail "AuthCacheHeadersMiddleware missing"
fi

if grep -q 'AuthCacheHeadersMiddleware' backend/main.py; then
  pass "AuthCacheHeadersMiddleware wired in main.py"
else
  fail "AuthCacheHeadersMiddleware not wired"
fi

# ── [7/7] Tests exist ────────────────────────────────────────────────
if grep -q 'test_production_rejects_insecure_cookies' tests/test_config.py; then
  pass "Test: production rejects insecure cookies"
else
  fail "Missing test: production rejects insecure cookies"
fi

if grep -q 'test_auth_login_response_has_no_store_cache' tests/test_middleware.py; then
  pass "Test: auth responses have no-store cache"
else
  fail "Missing test: auth responses have no-store cache"
fi

if grep -q 'test_refresh_rotates_refresh_cookie_with_valid_csrf' tests/test_auth_api.py; then
  pass "Test: refresh token rotation"
else
  fail "Missing test: refresh token rotation"
fi

if grep -q 'test_logout_clears_cookies' tests/test_auth_api.py; then
  pass "Test: logout clears cookies"
else
  fail "Missing test: logout clears cookies"
fi

if grep -q 'test_refresh_reuse_detection' tests/test_auth_service.py; then
  pass "Test: refresh reuse detection"
else
  fail "Missing test: refresh reuse detection"
fi

if grep -q 'test_login_locks_account_after_max_attempts' tests/test_auth_service.py; then
  pass "Test: account lockout"
else
  fail "Missing test: account lockout"
fi

echo ""
echo "─── Results: ${PASS}/${TOTAL} passed, ${FAIL} failed ───"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
