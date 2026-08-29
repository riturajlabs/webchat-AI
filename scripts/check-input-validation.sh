#!/usr/bin/env bash
# scripts/check-input-validation.sh
# Phase 14.5 — Input Validation & Injection Prevention audit.
# Returns 0 when all checks pass, 1 on any failure.
set -euo pipefail
cd "$(dirname "$0")/.."

PASS=0; FAIL=0; TOTAL=0
pass() { PASS=$((PASS + 1)); TOTAL=$((TOTAL + 1)); echo "  ✓ $1"; }
fail() { FAIL=$((FAIL + 1)); TOTAL=$((TOTAL + 1)); echo "  ✗ $1"; }

echo "─── Input validation & injection prevention audit ───"

# --- 1. MongoDB $regex must use re.escape() ---
# For each file containing $regex, verify it also uses re.escape (even via variable).
REGEX_FILES=$(grep -rl '\$regex' backend/repositories/ --include='*.py' 2>/dev/null | grep -v '__pycache__' || true)
UNSAFE_REGEX_FILE=""
for f in $REGEX_FILES; do
    HAS_REGEX=$(grep -c '\$regex' "$f" 2>/dev/null || true)
    HAS_ESCAPE=$(grep -c 're\.escape' "$f" 2>/dev/null || true)
    if [ "$HAS_REGEX" -gt 0 ] && [ "$HAS_ESCAPE" -eq 0 ]; then
        UNSAFE_REGEX_FILE="$f"
    fi
done
if [ -z "$UNSAFE_REGEX_FILE" ] && [ -n "$REGEX_FILES" ]; then
    pass "All MongoDB \$regex usages apply re.escape()"
elif [ -z "$REGEX_FILES" ]; then
    pass "No MongoDB \$regex usage found (or not applicable)"
else
    fail "MongoDB \$regex without re.escape() in $UNSAFE_REGEX_FILE"
fi

# --- 2. Billing CheckoutRequest has URL validation ---
if grep -q 'field_validator.*success_url\|field_validator.*cancel_url\|_validate_checkout_url' backend/schemas/billing.py 2>/dev/null; then
    pass "CheckoutRequest has URL field_validator"
else
    fail "CheckoutRequest missing URL field_validator"
fi

# --- 3. UsageMetricOut uses MetricName Literal ---
if grep -q 'metric: MetricName' backend/schemas/billing.py 2>/dev/null; then
    pass "UsageMetricOut.metric uses MetricName Literal"
else
    fail "UsageMetricOut.metric not using MetricName Literal"
fi

# --- 4. Checkout URL rejects non-http schemes ---
if grep -q 'ALLOWED_REDIRECT_SCHEMES\|_ALLOWED_REDIRECT_SCHEMES' backend/schemas/billing.py 2>/dev/null; then
    pass "Checkout URL scheme whitelist defined"
else
    fail "Checkout URL scheme whitelist missing"
fi

# --- 5. Shared sanitization module exists ---
if [ -f backend/utils/sanitization.py ]; then
    pass "Shared sanitization module exists"
else
    fail "Shared sanitization module missing"
fi

# --- 6. safe_regex() is available ---
if grep -q 'def safe_regex' backend/utils/sanitization.py 2>/dev/null; then
    pass "safe_regex() utility available"
else
    fail "safe_regex() utility missing"
fi

# --- 7. sanitize_text() is available ---
if grep -q 'def sanitize_text' backend/utils/sanitization.py 2>/dev/null; then
    pass "sanitize_text() utility available"
else
    fail "sanitize_text() utility missing"
fi

# --- 8. No $where operator in queries ---
if grep -rq '"\$where"' backend/ 2>/dev/null; then
    fail "MongoDB \$where operator found (JS injection risk)"
else
    pass "No MongoDB \$where operator usage"
fi

# --- 9. No f-string query construction ---
# Check for f-strings used inside MongoDB query filters (find/update/find_one calls)
if grep -rn "f'" backend/repositories/ --include='*.py' 2>/dev/null | grep -E '(find|update|delete)_one|\.find\(' | grep -v '__pycache__' > /dev/null 2>&1; then
    fail "f-string query construction detected in repositories"
else
    pass "No f-string query construction in repositories"
fi

# --- 10. Pydantic schemas validate email fields ---
# Auth schemas must have email validation; other schemas with user input should too.
if grep -q '_validated_email\|validate_email' backend/schemas/auth.py 2>/dev/null; then
    pass "Auth schemas have email validation"
else
    fail "Auth schemas missing email validation"
fi

# --- 11. Password policy enforcement ---
if grep -q 'validate_password_policy\|_password_policy' backend/schemas/auth.py 2>/dev/null; then
    pass "Password policy enforced in auth schemas"
else
    fail "Password policy missing in auth schemas"
fi

# --- 12. Chat question length validation ---
if grep -q 'MAX_QUESTION_LENGTH\|min_length=1.*max_length' backend/schemas/chat.py 2>/dev/null; then
    pass "Chat question length validated"
else
    fail "Chat question length not validated"
fi

# --- 13. Widget config CSS length validation ---
if grep -q '_CSS_LENGTH\|_validate_css_length' backend/schemas/widget.py 2>/dev/null; then
    pass "Widget CSS length validation present"
else
    fail "Widget CSS length validation missing"
fi

# --- 14. Widget config color validation ---
if grep -q '_HTML_HEX_COLOR\|_validate_color' backend/schemas/widget.py 2>/dev/null; then
    pass "Widget color validation present"
else
    fail "Widget color validation missing"
fi

# --- 15. SSRF URL validation ---
if [ -f backend/utils/url_validator.py ]; then
    pass "SSRF URL validation module exists"
else
    fail "SSRF URL validation module missing"
fi

# --- 16. URL validator blocks private IPs ---
if grep -q '_PRIVATE_NETWORKS\|_is_blocked_ip' backend/utils/url_validator.py 2>/dev/null; then
    pass "URL validator blocks private/internal IPs"
else
    fail "URL validator does not block private IPs"
fi

# --- 17. URL validator enforces scheme whitelist ---
if grep -q 'ALLOWED_SCHEMES' backend/utils/url_validator.py 2>/dev/null; then
    pass "URL validator enforces scheme whitelist"
else
    fail "URL validator missing scheme whitelist"
fi

# --- 18. Admin search fields have max_length ---
if grep -q 'max_length.*100\|MAX_ADMIN_SEARCH_LENGTH' backend/schemas/admin.py 2>/dev/null; then
    pass "Admin search fields have max_length"
else
    fail "Admin search fields missing max_length"
fi

# --- 19. Request body size limit ---
if grep -q 'RequestBodyLimitMiddleware\|request_body_max_bytes' backend/api/middleware.py 2>/dev/null; then
    pass "Request body size limit enforced"
else
    fail "Request body size limit missing"
fi

# --- 20. Tests exist ---
SANITIZATION_TESTS=0
BILLING_SCHEMA_TESTS=0
[ -f tests/test_sanitization.py ] && SANITIZATION_TESTS=$(grep -c 'def test_' tests/test_sanitization.py 2>/dev/null || echo 0)
[ -f tests/test_billing_schemas.py ] && BILLING_SCHEMA_TESTS=$(grep -c 'def test_' tests/test_billing_schemas.py 2>/dev/null || echo 0)
if [ "$SANITIZATION_TESTS" -ge 4 ] && [ "$BILLING_SCHEMA_TESTS" -ge 4 ]; then
    pass "Sanitization tests ($SANITIZATION_TESTS) + billing schema tests ($BILLING_SCHEMA_TESTS)"
else
    fail "Missing tests: sanitization=$SANITIZATION_TESTS, billing=$BILLING_SCHEMA_TESTS"
fi

# --- 21. chat_message_repository uses re.escape() ---
if grep -q 're\.escape' backend/repositories/chat_message_repository.py 2>/dev/null; then
    pass "chat_message_repository uses re.escape() for search"
else
    fail "chat_message_repository missing re.escape()"
fi

# --- 22. Origin validation module ---
if [ -f backend/utils/origin.py ]; then
    pass "Origin/hostname normalization module exists"
else
    fail "Origin/hostname normalization module missing"
fi

echo ""
echo "─── Results: $PASS/$TOTAL passed, $FAIL failed ───"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
