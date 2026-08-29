#!/usr/bin/env bash
# check-api-security.sh — Verify Phase 14.3 API production hardening.
#
# Exit 0 when every check passes; exit 1 on the first failure.
set -euo pipefail

PASS=0
FAIL=0
TOTAL=0

pass() { PASS=$((PASS + 1)); TOTAL=$((TOTAL + 1)); echo "  ✓ $1"; }
fail() { FAIL=$((FAIL + 1)); TOTAL=$((TOTAL + 1)); echo "  ✗ $1"; }

echo "─── API security audit ───"

# ── [1/6] DEBUG must be false in production ──────────────────────────
if grep -qE '^\s*debug:\s*bool\s*=\s*False' backend/core/config.py; then
  pass "DEBUG defaults to False"
else
  fail "DEBUG does not default to False"
fi

if grep -q 'DEBUG must be false in production' backend/core/config.py; then
  pass "Production validator rejects DEBUG=true"
else
  fail "No production validator for DEBUG"
fi

# ── [2/6] ENABLE_DOCS defaults & production validator ────────────────
if grep -qE '^\s*enable_docs:\s*bool\s*=\s*True' backend/core/config.py; then
  pass "ENABLE_DOCS defaults to True"
else
  fail "ENABLE_DOCS field missing or wrong default"
fi

if grep -q 'ENABLE_DOCS must be false in production' backend/core/config.py; then
  pass "Production validator rejects ENABLE_DOCS=true"
else
  fail "No production validator for ENABLE_DOCS"
fi

# ── [3/6] Docs gated on both debug AND enable_docs ──────────────────
if grep -q 'settings.debug and settings.enable_docs' backend/main.py; then
  pass "Docs gated on debug AND enable_docs"
else
  fail "Docs not gated on both debug AND enable_docs"
fi

# ── [4/6] RequestBodyLimitMiddleware present ─────────────────────────
if grep -q 'class RequestBodyLimitMiddleware' backend/api/middleware.py; then
  pass "RequestBodyLimitMiddleware class exists"
else
  fail "RequestBodyLimitMiddleware class missing"
fi

if grep -q 'RequestBodyLimitMiddleware' backend/main.py; then
  pass "RequestBodyLimitMiddleware wired in main.py"
else
  fail "RequestBodyLimitMiddleware not wired in main.py"
fi

# ── [5/6] REQUEST_BODY_MAX_BYTES default & validator ────────────────
if grep -qE 'request_body_max_bytes:\s*int\s*=\s*10\s*\*\s*1024\s*\*\s*1024' backend/core/config.py; then
  pass "request_body_max_bytes defaults to 10 MB"
else
  fail "request_body_max_bytes missing or wrong default"
fi

if grep -q 'REQUEST_BODY_MAX_BYTES must be at least' backend/core/config.py; then
  pass "Body size validator rejects < 1 KB"
else
  fail "No body size minimum validator"
fi

# ── [6/6] Tests exist ────────────────────────────────────────────────
if grep -q 'test_production_rejects_debug_enabled' tests/test_config.py; then
  pass "Test: production rejects DEBUG=true"
else
  fail "Missing test: production rejects DEBUG=true"
fi

if grep -q 'test_production_rejects_enable_docs_enabled' tests/test_config.py; then
  pass "Test: production rejects ENABLE_DOCS=true"
else
  fail "Missing test: production rejects ENABLE_DOCS=true"
fi

if grep -q 'test_request_exceeding_limit_rejected' tests/test_middleware.py; then
  pass "Test: oversized body rejected"
else
  fail "Missing test: oversized body rejected"
fi

echo ""
echo "─── Results: ${PASS}/${TOTAL} passed, ${FAIL} failed ───"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
