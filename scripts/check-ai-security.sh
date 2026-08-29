#!/usr/bin/env bash
# scripts/check-ai-security.sh
# Phase 14.6 — AI/RAG Security & Reliability audit.
# Returns 0 when all checks pass, 1 on any failure.
set -euo pipefail
cd "$(dirname "$0")/.."

PASS=0; FAIL=0; TOTAL=0
pass() { PASS=$((PASS + 1)); TOTAL=$((TOTAL + 1)); echo "  ✓ $1"; }
fail() { FAIL=$((FAIL + 1)); TOTAL=$((TOTAL + 1)); echo "  ✗ $1"; }

echo "─── AI/RAG security audit ───"

# ===== PROMPT SECURITY =====

# 1. prompt_security.py exists
if [ -f backend/utils/prompt_security.py ]; then
    pass "prompt_security.py exists"
else
    fail "prompt_security.py missing"
fi

# 2. Injection detection exists
if grep -q 'def detect_injection\|def scan_user_input' backend/utils/prompt_security.py backend/core/prompt_guard.py 2>/dev/null; then
    pass "Injection detection functions exist"
else
    fail "Injection detection functions missing"
fi

# 3. History sanitization exists
if grep -q 'def sanitize_history_turn' backend/utils/prompt_security.py 2>/dev/null; then
    pass "History sanitization exists"
else
    fail "History sanitization missing"
fi

# 4. History sanitization integrated into render_history
if grep -q 'sanitize_history_turn' backend/prompts/rag.py 2>/dev/null; then
    pass "History sanitization integrated into RAG pipeline"
else
    fail "History sanitization not integrated into RAG pipeline"
fi

# 5. Context breakout detection exists
if grep -q 'def detect_context_breakout' backend/utils/prompt_security.py 2>/dev/null; then
    pass "Context breakout detection exists"
else
    fail "Context breakout detection missing"
fi

# 6. Enhanced scan integrated into sanitize_question
if grep -q 'scan_user_input' backend/prompts/rag.py 2>/dev/null; then
    pass "Enhanced input scan integrated into sanitize_question"
else
    fail "Enhanced input scan not integrated"
fi

# ===== RAG ISOLATION =====

# 7. Retrieval cache key includes tenant_id
if grep -q 'tenant_id.*website_id.*search_query\|tenant_id.*:.*website_id' backend/services/chat/rag_service.py 2>/dev/null; then
    pass "Retrieval cache key includes tenant_id"
else
    fail "Retrieval cache key missing tenant_id"
fi

# 8. Vector search always includes tenant_id
if grep -q 'similarity_search' backend/services/chat/rag_service.py 2>/dev/null && grep -q 'tenant_id' backend/repositories/vector/mongodb.py 2>/dev/null; then
    pass "Vector search enforces tenant_id"
else
    fail "Vector search missing tenant_id enforcement"
fi

# 9. Confidence threshold exists
if grep -q 'chat_context_min_score\|rag_confidence_threshold\|enable_rag_confidence_check' backend/core/config.py 2>/dev/null; then
    pass "Confidence threshold configuration exists"
else
    fail "Confidence threshold configuration missing"
fi

# 10. Confidence check enforced in rag_service
if grep -q 'assess_confidence\|confidence_low' backend/services/chat/rag_service.py 2>/dev/null; then
    pass "Confidence check enforced in RAG service"
else
    fail "Confidence check not enforced in RAG service"
fi

# ===== LLM RELIABILITY =====

# 11. Retry configuration exists
if grep -q 'llm_max_retries' backend/core/config.py 2>/dev/null; then
    pass "LLM retry configuration exists"
else
    fail "LLM retry configuration missing"
fi

# 12. Retry logic in gemini client
if grep -q 'for attempt in range.*max_retries\|gemini_retry' backend/ai/gemini.py 2>/dev/null; then
    pass "Retry logic implemented in Gemini client"
else
    fail "Retry logic missing in Gemini client"
fi

# 13. Timeout configuration exists
if grep -q 'generation_timeout_seconds\|generation_first_token_timeout_seconds' backend/core/config.py 2>/dev/null; then
    pass "LLM timeout configuration exists"
else
    fail "LLM timeout configuration missing"
fi

# 14. Max output tokens configured
if grep -q 'chat_max_output_tokens' backend/core/config.py 2>/dev/null; then
    pass "Max output tokens configured"
else
    fail "Max output tokens not configured"
fi

# 15. Context character budget exists
if grep -q 'chat_context_max_chars' backend/core/config.py 2>/dev/null; then
    pass "Context character budget exists"
else
    fail "Context character budget missing"
fi

# 16. Error sanitization (no stack traces to client)
if grep -q '_safe_message\|An unexpected error occurred' backend/services/chat/rag_service.py 2>/dev/null; then
    pass "Error messages sanitized (no stack traces)"
else
    fail "Error message sanitization missing"
fi

# ===== STREAMING =====

# 17. Disconnect handling exists
if grep -q 'is_disconnected\|GeneratorExit\|aclose' backend/api/sse.py 2>/dev/null; then
    pass "Streaming disconnect handling exists"
else
    fail "Streaming disconnect handling missing"
fi

# 18. Async task cleanup
if grep -q 'history_task.cancel\|\.cancel()' backend/services/chat/rag_service.py 2>/dev/null; then
    pass "Async task cleanup exists"
else
    fail "Async task cleanup missing"
fi

# ===== ABUSE PROTECTION =====

# 19. Injection tracker exists
if grep -q 'class InjectionTracker' backend/utils/prompt_security.py 2>/dev/null; then
    pass "Injection tracker exists"
else
    fail "Injection tracker missing"
fi

# 20. Chat rate limiting exists
if grep -q 'chat_limiter\|widget_chat_limiter\|widget_visitor_limiter' backend/api/deps.py 2>/dev/null; then
    pass "Chat rate limiting exists"
else
    fail "Chat rate limiting missing"
fi

# 21. Question length validation
if grep -q 'chat_question_max_chars\|MAX_QUESTION_LENGTH' backend/core/config.py backend/schemas/chat.py 2>/dev/null; then
    pass "Question length validation exists"
else
    fail "Question length validation missing"
fi

# 22. Tests exist for AI security
RETRY_TESTS=0
PROMPT_SECURITY_TESTS=0
[ -f tests/test_ai_retry.py ] && RETRY_TESTS=$(grep -c 'def test_' tests/test_ai_retry.py 2>/dev/null || echo 0)
[ -f tests/test_prompt_security.py ] && PROMPT_SECURITY_TESTS=$(grep -c 'def test_' tests/test_prompt_security.py 2>/dev/null || echo 0)
if [ "$RETRY_TESTS" -ge 3 ] && [ "$PROMPT_SECURITY_TESTS" -ge 8 ]; then
    pass "AI retry tests ($RETRY_TESTS) + prompt security tests ($PROMPT_SECURITY_TESTS)"
else
    fail "Missing tests: retry=$RETRY_TESTS, prompt_security=$PROMPT_SECURITY_TESTS"
fi

echo ""
echo "─── Results: $PASS/$TOTAL passed, $FAIL failed ───"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
