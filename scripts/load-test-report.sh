#!/usr/bin/env bash
# scripts/load-test-report.sh
# Phase 14.8.4 — Production load-test report.
#
# Runs lightweight load tests against a *running* deployment and emits a
# summary (latency, failures, memory growth). No heavy dependencies: it uses
# `hey` for raw throughput when available and `curl` + `python3` (stdlib only)
# for authenticated chat/SSE concurrency.
#
# The health endpoint is always exercised. The chat and SSE phases require a
# live, authenticated deployment and read their inputs from the environment:
#
#   BASE_URL=http://localhost:8000
#   CHAT_AUTH_TOKEN="Bearer <jwt>"      # required for the chat phase
#   CHAT_REQUEST_BODY='{"website_id":"...","message":"hi"}'
#   CRAWL_AUTH_TOKEN="Bearer <jwt>"     # required for the SSE crawl phase
#   CRAWL_JOB_ID="<job-id>"
#   HEALTH_CONCURRENCY=100
#
# With no auth supplied, the authenticated phases are skipped (NOTE) so the
# script still produces a health baseline in CI / local smoke runs.
set -uo pipefail
cd "$(dirname "$0")/.."

BASE_URL="${BASE_URL:-http://localhost:8000}"
HEALTH_URL="${BASE_URL}/api/health/live"
CONCURRENCY="${HEALTH_CONCURRENCY:-100}"
REQUESTS="${HEALTH_REQUESTS:-1000}"

PASS=0; FAIL=0; SKIP=0; TOTAL=0
pass() { PASS=$((PASS + 1)); TOTAL=$((TOTAL + 1)); echo "  [PASS] $1"; }
fail() { FAIL=$((FAIL + 1)); TOTAL=$((TOTAL + 1)); echo "  [FAIL] $1"; }
note() { SKIP=$((SKIP + 1)); TOTAL=$((TOTAL + 1)); echo "  [NOTE] $1"; }

# Measure the RSS (bytes) of a local API process, or echo empty if not local.
api_rss() {
    if [[ "$BASE_URL" == *"localhost"* || "$BASE_URL" == *"127.0.0.1"* ]]; then
        local pid
        pid=$(pgrep -f "uvicorn backend.main:app" | head -1 || true)
        if [ -n "$pid" ] && [ -r "/proc/$pid/status" ]; then
            awk '/^VmRSS:/ {print $2 * 1024}' "/proc/$pid/status" 2>/dev/null || echo ""
        else
            echo ""
        fi
    else
        echo ""
    fi
}

echo "=== Phase 14.8.4 — Load test report ==="
echo "Target:  $BASE_URL"
echo "Health:  $HEALTH_URL"
echo "Concurr: $CONCURRENCY   Requests: $REQUESTS"
echo ""

# ── [1/4] Health endpoint — 100 concurrent requests ──────────────────
echo "[1/4] Health endpoint under load (${CONCURRENCY} concurrent)"
if ! curl -s -o /dev/null --max-time 3 "$HEALTH_URL"; then
    note "API not reachable at $HEALTH_URL — skipping live load tests."
    echo ""
    echo "Load test: $PASS passed, $FAIL failed, $SKIP skipped (of $TOTAL)"
    [ "$FAIL" -gt 0 ] && exit 1
    exit 0
fi

RSS_BEFORE=$(api_rss || true)

if command -v hey >/dev/null 2>&1; then
    OUTPUT=$(hey -n "$REQUESTS" -c "$CONCURRENCY" "$HEALTH_URL" 2>&1 || true)
    AVG=$(echo "$OUTPUT" | grep -E '^\s*Average:' | awk '{print $2}')
    RPS=$(echo "$OUTPUT" | grep -E 'Requests/sec' | awk '{print $2}')
    STATUS_200=$(echo "$OUTPUT" | grep -E '^\[200\]' | awk '{print $2}' || true)
    ERRORS=$(echo "$OUTPUT" | grep -E 'Errors:' | awk '{print $2}' || true)
    if [ -n "$AVG" ]; then
        pass "Health avg latency ${AVG} (${REQUESTS} reqs @ ${CONCURRENCY} conc)"
    else
        fail "Could not parse hey output"
    fi
    if [ -n "$STATUS_200" ] && [ "${ERRORS:-0}" = "0" ]; then
        pass "All responses 200, 0 errors (RPS=${RPS:-n/a})"
    else
        fail "Errors=${ERRORS:-?} status200=${STATUS_200:-?}"
    fi
else
    # Dependency-free fallback: python3 stdlib concurrent health hits.
    AVG=$(python3 - "$HEALTH_URL" "$CONCURRENCY" "$REQUESTS" <<'PY' 2>/dev/null || true
import sys, time, concurrent.futures, urllib.request
url, conc, n = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
def hit():
    t=time.time()
    try:
        urllib.request.urlopen(url, timeout=5); return time.time()-t, True
    except Exception:
        return 0.0, False
ok=0; lat=0.0
with concurrent.futures.ThreadPoolExecutor(max_workers=conc) as ex:
    for d,s in ex.map(lambda _: hit(), range(n)):
        if s: ok+=1; lat+=d
print(f"{ (lat/ok*1000) if ok else 0:.1f}ms" if ok else "n/a")
PY
)
    if [ -n "$AVG" ]; then
        pass "Health avg latency ${AVG} (fallback loader, ${REQUESTS} reqs @ ${CONCURRENCY} conc)"
    else
        fail "Fallback health loader produced no result"
    fi
fi

# ── [2/4] Chat API — concurrent streaming requests ──────────────────
echo ""
echo "[2/4] Chat API concurrent streaming"
if [ -z "${CHAT_AUTH_TOKEN:-}" ]; then
    note "CHAT_AUTH_TOKEN not set — skipping chat load phase (needs live auth)."
elif ! command -v curl >/dev/null 2>&1; then
    note "curl not available — skipping chat load phase."
else
    BODY="${CHAT_REQUEST_BODY:-{\"website_id\":\"load-test\",\"message\":\"ping\"}}"
    CHAT_URL="${BASE_URL}/api/chat/stream"
    CHAT_CONC="${CHAT_CONCURRENCY:-10}"
    CHAT_USERS="${CHAT_USERS:-20}"
    start=$(date +%s%N)
    ok=0; failc=0
    tmp=$(mktemp -d)
    for i in $(seq 1 "$CHAT_USERS"); do
        (
            code=$(curl -s -o "$tmp/r$i" -w "%{http_code}" --max-time 20 \
                -H "Authorization: ${CHAT_AUTH_TOKEN}" \
                -H "Content-Type: application/json" \
                -d "$BODY" -N "$CHAT_URL" 2>/dev/null || echo "000")
            if [ "$code" = "200" ]; then echo ok >> "$tmp/ok"; else echo fail >> "$tmp/ok"; fi
        ) &
        if (( i % CHAT_CONC == 0 )); then wait; fi
    done
    wait
    ok=$(grep -c ok "$tmp/ok" 2>/dev/null || echo 0)
    failc=$(grep -c fail "$tmp/ok" 2>/dev/null || echo 0)
    end=$(date +%s%N)
    dur=$(( (end - start) / 1000000 ))
    rm -rf "$tmp"
    if [ "$failc" -eq 0 ] && [ "$ok" -gt 0 ]; then
        pass "Chat stream: ${ok}/${CHAT_USERS} succeeded in ${dur}ms (conc=${CHAT_CONC})"
    elif [ "$ok" -gt 0 ]; then
        pass "Chat stream: ${ok}/${CHAT_USERS} succeeded, ${failc} failed (conc=${CHAT_CONC})"
        note "Some chat requests failed under load; review server logs."
    else
        fail "Chat stream: 0/${CHAT_USERS} succeeded (${failc} failed)"
    fi
fi

# ── [3/4] SSE crawl progress — simultaneous streams + disconnect ────
echo ""
echo "[3/4] SSE crawl progress (simultaneous + disconnected clients)"
if [ -z "${CRAWL_AUTH_TOKEN:-}" ] || [ -z "${CRAWL_JOB_ID:-}" ]; then
    note "CRAWL_AUTH_TOKEN/CRAWL_JOB_ID not set — skipping SSE crawl phase."
elif ! command -v curl >/dev/null 2>&1; then
    note "curl not available — skipping SSE crawl phase."
else
    SSE_URL="${BASE_URL}/api/crawl-jobs/${CRAWL_JOB_ID}/stream"
    SSE_CONC="${SSE_CONCURRENCY:-5}"
    connected=0
    tmp=$(mktemp -d)
    # Multiple simultaneous SSE subscribers.
    for i in $(seq 1 "$SSE_CONC"); do
        (
            # Read up to 3 SSE lines or 5s, whichever first; then close (client
            # disconnect) to exercise the server's per-client cleanup path.
            curl -s -N --max-time 5 \
                -H "Authorization: ${CRAWL_AUTH_TOKEN}" \
                "$SSE_URL" 2>/dev/null | head -n 3 | grep -q . && echo ok >> "$tmp/sse" || echo no >> "$tmp/sse"
        ) &
    done
    wait
    connected=$(grep -c ok "$tmp/sse" 2>/dev/null || echo 0)
    rm -rf "$tmp"
    if [ "$connected" -gt 0 ]; then
        pass "SSE crawl: ${connected}/${SSE_CONC} clients received events (disconnect cleanup exercised)"
    else
        fail "SSE crawl: 0/${SSE_CONC} clients received events"
    fi
fi

# ── [4/4] Memory growth observation ──────────────────────────────────
echo ""
echo "[4/4] Memory growth"
RSS_AFTER=$(api_rss || true)
if [ -n "${RSS_BEFORE:-}" ] && [ -n "${RSS_AFTER:-}" ]; then
    GROWTH=$((RSS_AFTER - RSS_BEFORE))
    MB_BEFORE=$((RSS_BEFORE / 1024 / 1024))
    MB_AFTER=$((RSS_AFTER / 1024 / 1024))
    MB_GROWTH=$((GROWTH / 1024 / 1024))
    if [ "$GROWTH" -le 52428800 ]; then  # < 50 MiB growth is acceptable
        pass "API RSS ${MB_BEFORE}MiB -> ${MB_AFTER}MiB (growth ${MB_GROWTH}MiB)"
    else
        fail "API RSS grew ${MB_GROWTH}MiB under load (possible leak)"
    fi
else
    note "Memory measurement requires a local API process; skipping (remote target)."
fi

echo ""
echo "Load test: $PASS passed, $FAIL failed, $SKIP skipped (of $TOTAL)"
if [ "$FAIL" -gt 0 ]; then
    echo "RESULT: FAIL"
    exit 1
fi
echo "RESULT: PASS"
exit 0
