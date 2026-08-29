#!/usr/bin/env bash
# scripts/check-observability.sh
# Phase 14.7 — Production Observability & Monitoring audit.
# Returns 0 when all checks pass, 1 on any failure.
set -euo pipefail
cd "$(dirname "$0")/.."

PASS=0; FAIL=0; TOTAL=0
pass() { PASS=$((PASS + 1)); TOTAL=$((TOTAL + 1)); echo "  ✓ $1"; }
fail() { FAIL=$((FAIL + 1)); TOTAL=$((TOTAL + 1)); echo "  ✗ $1"; }

echo "─── Observability audit ───"

# ===== STRUCTURED LOGGING =====

# 1. Logging module exists
if [ -f backend/core/logging.py ]; then
    pass "logging module exists"
else
    fail "logging module missing"
fi

# 2. JSON formatter exists
if grep -q 'class JsonFormatter' backend/core/logging.py 2>/dev/null; then
    pass "JsonFormatter exists"
else
    fail "JsonFormatter missing"
fi

# 3. Sensitive data filter exists
if grep -q 'class SensitiveDataFilter' backend/core/logging.py 2>/dev/null; then
    pass "SensitiveDataFilter exists"
else
    fail "SensitiveDataFilter missing"
fi

# 4. Sensitive filter wired in main.py
if grep -q 'attach_sensitive_data_filter' backend/main.py 2>/dev/null; then
    pass "sensitive filter wired in main.py"
else
    fail "sensitive filter not wired"
fi

# 5. LOG_LEVEL config exists
if grep -q 'log_level' backend/core/config.py 2>/dev/null; then
    pass "LOG_LEVEL config exists"
else
    fail "LOG_LEVEL config missing"
fi

# ===== REQUEST ID TRACING =====

# 6. Request ID middleware exists
if grep -q 'class RequestIDMiddleware' backend/api/middleware.py 2>/dev/null; then
    pass "RequestIDMiddleware exists"
else
    fail "RequestIDMiddleware missing"
fi

# 7. request_id_var context variable exists
if grep -q 'request_id_var' backend/core/logging.py 2>/dev/null; then
    pass "request_id_var context variable exists"
else
    fail "request_id_var missing"
fi

# ===== METRICS =====

# 8. Metrics module exists
if [ -f backend/core/metrics.py ]; then
    pass "metrics module exists"
else
    fail "metrics module missing"
fi

# 9. Prometheus render function exists
if grep -q 'def render_prometheus' backend/core/metrics.py 2>/dev/null; then
    pass "render_prometheus exists"
else
    fail "render_prometheus missing"
fi

# 10. HTTP metrics exist
if grep -q 'http_requests_total' backend/core/metrics.py 2>/dev/null; then
    pass "HTTP metrics exist"
else
    fail "HTTP metrics missing"
fi

# 11. Chat metrics exist
if grep -q 'chat_requests_total' backend/core/metrics.py 2>/dev/null; then
    pass "chat metrics exist"
else
    fail "chat metrics missing"
fi

# 12. LLM metrics exist
if grep -q 'llm_requests_total' backend/core/metrics.py 2>/dev/null; then
    pass "LLM metrics exist"
else
    fail "LLM metrics missing"
fi

# 13. RAG metrics exist
if grep -q 'rag_retrieval_total' backend/core/metrics.py 2>/dev/null && grep -q 'rag_latency_seconds' backend/core/metrics.py 2>/dev/null; then
    pass "RAG metrics exist"
else
    fail "RAG metrics missing"
fi

# 14. Crawl metrics exist
if grep -q 'crawl_started_total' backend/core/metrics.py 2>/dev/null; then
    pass "crawl metrics exist"
else
    fail "crawl metrics missing"
fi

# ===== AI PERFORMANCE TRACKING =====

# 15. Chat latency tracked in rag_service
if grep -q 'record_chat_latency' backend/services/chat/rag_service.py 2>/dev/null; then
    pass "chat latency tracked in RAG service"
else
    fail "chat latency not tracked"
fi

# 16. LLM latency tracked in rag_service
if grep -q 'record_llm_latency' backend/services/chat/rag_service.py 2>/dev/null; then
    pass "LLM latency tracked in RAG service"
else
    fail "LLM latency not tracked"
fi

# 17. RAG latency tracked in rag_service
if grep -q 'record_rag_latency' backend/services/chat/rag_service.py 2>/dev/null; then
    pass "RAG latency tracked in RAG service"
else
    fail "RAG latency not tracked"
fi

# 18. Chat failure tracking in rag_service
if grep -q 'record_chat_failure' backend/services/chat/rag_service.py 2>/dev/null; then
    pass "chat failure tracking in RAG service"
else
    fail "chat failure tracking missing"
fi

# ===== WORKER OBSERVABILITY =====

# 19. Crawl metrics wired in worker
if grep -q 'record_crawl_started' backend/workers/jobs/crawl.py 2>/dev/null && grep -q 'record_crawl_completed' backend/workers/jobs/crawl.py 2>/dev/null && grep -q 'record_crawl_failed' backend/workers/jobs/crawl.py 2>/dev/null; then
    pass "crawl lifecycle metrics wired"
else
    fail "crawl lifecycle metrics not fully wired"
fi

# 20. Worker timing exists
if [ -f backend/workers/timing.py ]; then
    pass "worker timing module exists"
else
    fail "worker timing module missing"
fi

# ===== ERROR TRACKING =====

# 21. capture_exception exists
if grep -q 'def capture_exception' backend/core/errors.py 2>/dev/null; then
    pass "capture_exception exists"
else
    fail "capture_exception missing"
fi

# ===== HEALTH ENDPOINTS =====

# 22. Health endpoints exist
if grep -q 'health/live' backend/api/routes/health.py 2>/dev/null && grep -q 'health/ready' backend/api/routes/health.py 2>/dev/null; then
    pass "health endpoints exist"
else
    fail "health endpoints missing"
fi

echo ""
echo "─── Results: $PASS/$TOTAL passed, $FAIL failed ───"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
