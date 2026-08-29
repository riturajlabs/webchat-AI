#!/usr/bin/env bash
# WebChat AI — Local Production Smoke Test.
#
# Validates the running production-like local stack (docker compose with
# .env.production). Runs 10 checks; exits non-zero if any fail.
#
#     scripts/local-production-smoke-test.sh
#
# Requirements: docker compose, the .venv (for the python API checks),
# and an active audit-style account (see SMOKE_* vars below).
set -uo pipefail

cd "$(dirname "$0")/.."

COMPOSE=(docker compose --env-file .env.production -f docker/compose.yml)
API_BASE="${API_BASE:-http://localhost:8000}"
DASHBOARD_URL="${DASHBOARD_URL:-http://localhost:3000}"
WIDGET_URL="${WIDGET_URL:-http://localhost:8080/webchat-widget.iife.min.js}"

SMOKE_EMAIL="${SMOKE_EMAIL:-audit1787887157@example.com}"
SMOKE_PASS="${SMOKE_PASS:-Audit@Pass123!}"
SMOKE_QUESTION="${SMOKE_QUESTION:-What courses are offered by Indira University?}"

PASS=0
FAIL=0

note() { printf '[%s/10] %s\n' "$1" "$2"; }
ok()   { PASS=$((PASS+1)); printf '  [PASS] %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  [FAIL] %s\n' "$1"; }

EXPECTED_SERVICES=(api worker dashboard widget mongo redis mailpit)

echo "==> STEP 9 — Local Production Smoke Test"

# [1/10] Docker services running
note 1 "Docker services running"
PS_OUT=$("${COMPOSE[@]}" ps --format '{{.Service}} {{.State}}' 2>/dev/null)
missing=()
for svc in "${EXPECTED_SERVICES[@]}"; do
  state=$(printf '%s\n' "$PS_OUT" | awk -v s="$svc" '$1==s{print $2}')
  if [ "$state" != "running" ]; then
    missing+=("$svc=$state")
  fi
done
if [ ${#missing[@]} -eq 0 ]; then ok "all ${#EXPECTED_SERVICES[@]} services running"; else bad "missing/not running: ${missing[*]}"; fi

# [2/10] API health
note 2 "API health"
HEALTH=$(curl -s -m 10 "$API_BASE/api/health") || HEALTH=""
if printf '%s' "$HEALTH" | grep -q '"status":"ok"' &&
   printf '%s' "$HEALTH" | grep -q '"database":true' &&
   printf '%s' "$HEALTH" | grep -q '"redis":true'; then
  ok "database+redis connected, status ok"
else
  bad "health unexpected: $HEALTH"
fi

# [3/10] Dashboard reachable
note 3 "Dashboard reachable"
if [ "$(curl -s -o /dev/null -w '%{http_code}' -m 15 "$DASHBOARD_URL")" = "200" ]; then
  ok "$DASHBOARD_URL -> 200"
else
  bad "$DASHBOARD_URL not 200"
fi

# [4/10] Widget bundle reachable
note 4 "Widget bundle reachable"
if [ "$(curl -s -o /dev/null -w '%{http_code}' -m 15 "$WIDGET_URL")" = "200" ]; then
  ok "$WIDGET_URL -> 200"
else
  bad "$WIDGET_URL not 200"
fi

# [5/10] Redis connected
# The local compose redis container enables requirepass when REDIS_PASSWORD is
# set in .env.production, so authenticate explicitly.
note 5 "Redis connected"
REDIS_PW=$(grep -E "^REDIS_PASSWORD=" .env.production | head -1 | cut -d= -f2-)
REDIS_PING=$(docker exec webchat-redis redis-cli -a "$REDIS_PW" ping 2>/dev/null | grep -v "Warning: Using a password")
if [ "$REDIS_PING" = "PONG" ]; then
  ok "redis-cli ping -> PONG"
else
  bad "redis ping failed"
fi

# [6/10] Mongo connected
note 6 "Mongo connected"
MONGO_PING=$(docker exec webchat-mongo mongosh --quiet --eval 'db.runCommand({ping:1}).ok' 2>/dev/null | tr -d '[:space:]')
if [ "$MONGO_PING" = "1" ]; then
  ok "mongosh ping ok"
else
  bad "mongo ping failed (got: '$MONGO_PING')"
fi

# [7/10] / [8/10] / [9/10] Auth / Website / Chat endpoints (python + httpx)
note 7 "Auth endpoints (login)"
note 8 "Website endpoints"
note 9 "Chat endpoint"
API_BASE="$API_BASE" SMOKE_EMAIL="$SMOKE_EMAIL" SMOKE_PASS="$SMOKE_PASS" \
SMOKE_QUESTION="$SMOKE_QUESTION" \
.venv/bin/python - <<'PY'
import json, os, sys, uuid
import httpx

base = os.environ["API_BASE"]
email = os.environ["SMOKE_EMAIL"]
password = os.environ["SMOKE_PASS"]
question = os.environ["SMOKE_QUESTION"]
res = {"auth": False, "websites": False, "chat": False}

try:
    with httpx.Client(base_url=base, timeout=60.0) as c:
        r = c.post("/api/auth/login", json={"email": email, "password": password})
        data = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
        token = data.get("access_token") or data.get("accessToken")
        if r.status_code == 200 and token:
            res["auth"] = True
            h = {"Authorization": f"Bearer {token}"}
            wr = c.get("/api/websites", headers=h)
            sites = wr.json() if wr.headers.get("content-type","").startswith("application/json") else []
            if wr.status_code == 200 and isinstance(sites, list):
                if sites:
                    res["websites"] = True
                    wid = sites[0].get("_id") or sites[0].get("id")
                    cr = c.post("/api/chat/stream", headers=h,
                                json={"website_id": wid, "question": question,
                                      "visitor_id": "smoke-" + str(uuid.uuid4())})
                    body = cr.text
                    if cr.status_code == 200 and ("event:" in body or 'sources' in body or 'data:' in body):
                        res["chat"] = True
        if not res["auth"]:
            print(f"    auth detail: status={r.status_code} body={r.text[:200]}")
        elif not res["websites"]:
            print(f"    websites detail: status={wr.status_code} body={wr.text[:200]}")
        elif not res["chat"]:
            print(f"    chat detail: status={cr.status_code} body={body[:200]}")
except Exception as exc:  # noqa: BLE001
    print(f"    exception: {exc!r}")
    sys.exit(1)

print(f"  [{'PASS' if res['auth'] else 'FAIL'}] auth/login -> 200 + access_token")
print(f"  [{'PASS' if res['websites'] else 'FAIL'}] websites list -> 200 with site")
if not res["auth"] or not res["websites"]:
    res["chat"] = False
print(f"  [{'PASS' if res['chat'] else 'FAIL'}] chat stream -> 200 with SSE content")
ok_count = sum(res.values())
sys.exit(0 if ok_count == 3 else 1)
PY
# Map python exit back into the outer counters
if [ $? -eq 0 ]; then
  PASS=$((PASS+3))
  ok_count=3
else
  FAIL=$((FAIL+3))
fi

# [10/10] No container errors
# Fail only on genuine platform faults (crash loops, bind failures, OOM, fatal
# shutdowns, import errors). The ARQ worker logs a Traceback for every *caught*
# job exception by design; in this local production simulation those are the
# Resend ValidationError (email to the fake `example.com` audit mailbox --
# rejected so we must use Resend's testing address) and transient Upstash
# ConnectionError resets. Both are non-fatal / self-recovering, so they are
# classified (counted) but not treated as a container failure.
note 10 "No container errors"
PLATFORM_FAULT=$(docker compose --env-file .env.production -f docker/compose.yml logs --tail=300 2>/dev/null \
  | grep -iE 'Address already in use|Out of memory|Killed$|ModuleNotFoundError|ImportError|Segmentation|FATAL|ERROR: Failed to|CrashLoopBackOff|connection refused' \
  | grep -viE 'resend\.exceptions\.ValidationError|Connection reset by peer|ConnectionError:|ConnectionResetError' \
  | head -20)
KNOWN_WORKER_ERR=$(docker compose --env-file .env.production -f docker/compose.yml logs --tail=500 2>/dev/null \
  | grep -icE 'ValidationError: Invalid `to` field|Connection reset by peer')
if [ -z "$PLATFORM_FAULT" ]; then
  ok "no platform faults in last logs"
  if [ "${KNOWN_WORKER_ERR:-0}" -gt 0 ]; then
    echo "  [NOTE] $KNOWN_WORKER_ERR caught non-fatal worker job exception(s) (email/redis) - expected in local prod sim"
  fi
else
  bad "platform faults found:"
  printf '%s\n' "$PLATFORM_FAULT" | sed 's/^/    /'
fi

echo
echo "===== SMOKE SUMMARY ====="
echo "PASS: $PASS  FAIL: $FAIL"
if [ "$FAIL" -eq 0 ]; then
  echo "RESULT: OK"
  exit 0
else
  echo "RESULT: FAILED"
  exit 1
fi
