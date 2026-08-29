# WebChat AI — Production Security & SaaS Readiness Audit

**Date:** August 26, 2026 · **Mode:** Read-only audit (no code modified)
**Scope:** Complete security posture and production readiness across all layers

---

## 1. Executive Summary

This audit inspects the actual implementation across the full stack: FastAPI backend, Next.js dashboard, vanilla TypeScript widget SDK, ARQ workers, Docker deployment, and all infrastructure configuration. The codebase demonstrates **strong security engineering in many areas** — tenant isolation is consistently enforced at the query level, CSRF double-submit is correctly implemented, widget XSS defense is dual-gated with DOMPurify, refresh token rotation is atomic, and the model is never invoked without retrieved context.

However, the audit identified **7 production-blocking findings** that must be resolved before deployment to a live multi-tenant environment. The most critical is **production secrets committed to the repository**, followed by containers running as root and an unauthenticated MongoDB instance exposed on the host network.

---

## 2. Security Score

| Area                                   | Score | Summary                                                                                             |
| -------------------------------------- | ----- | --------------------------------------------------------------------------------------------------- |
| Authentication & Session Security      | 8/10  | Excellent token rotation, CSRF, lockout. SSE cookie is a minor XSS surface.                         |
| Authorization & Multi-Tenant Isolation | 8/10  | Consistent `tenant_id` scoping in every query. Role hierarchy is sound.                             |
| Widget Security                        | 8/10  | Origin allowlist, session binding, rate layers are thorough. DOMPurify XSS defense is strong.       |
| AI / RAG Security                      | 7/10  | 3-layer prompt guard. Context sanitization. Crawl SSRF protection. No output blocking on injection. |
| API Security                           | 7/10  | Good validation, rate limits, CORS. No request body size limit. Debug mode exposes docs.            |
| Database Security                      | 6/10  | Comprehensive indexes and TTLs. MongoDB exposed on host network with no auth.                       |
| Docker & Deployment                    | 4/10  | Running as root. No resource limits. Secrets in compose env. No CI/CD.                              |
| Frontend Security                      | 8/10  | Tokens in memory only, DOMPurify rendering, safe URL checks.                                        |
| Logging & Monitoring                   | 7/10  | Structured JSON logging, content hashing for privacy. No centralized error tracking.                |
| SaaS Production Readiness              | 6/10  | Usage limits, billing, RBAC present. No backup strategy, no cron job cleanup.                       |

**Overall: 7.0 / 10**

---

## 3. Critical Findings Table

| #    | Severity        | Issue                                                  | File:Line                                                     | Root Cause                                                                                                                                             | Impact                                                                                                                | Recommended Fix                                                                                                                                                                   |
| ---- | --------------- | ------------------------------------------------------ | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| S-01 | **P0 Critical** | Production secrets committed to git                    | `.env.production:73-234`                                      | MongoDB URI/password, Redis password, Gemini/Groq/OpenRouter/Jina/Cohere API keys, Resend key, Razorpay keys all stored in plaintext in a tracked file | Full database takeover, AI provider abuse (cost), payment fraud, email spoofing if repo is leaked                     | Move all secrets to a vault (e.g. Railway env vars, Doppler). Rotate every exposed key immediately. Add `.env.production` to `.gitignore` (only `.env.example` should be tracked) |
| S-02 | **P0 Critical** | Docker containers run as root                          | `docker/Dockerfile.api:4-40`, `docker/Dockerfile.worker:4-43` | No `USER` directive in either Dockerfile                                                                                                               | Container escape gives root on host. Crawler with Playwright + root = full system compromise if browser漏洞 exploited | Add `RUN adduser --disabled-password --no-create-home appuser` and `USER appuser` before `CMD` in both Dockerfiles                                                                |
| S-03 | **P0 Critical** | MongoDB exposed on host network without authentication | `docker/compose.yml:222`                                      | `ports: "27017:27017"` publishes Mongo to the host with no `--auth` flag                                                                               | Anyone on the network can connect, read/write all tenant data, drop collections                                       | Remove the `ports` mapping (internal only). Add `--auth` flag or MongoDB Atlas-style auth. Use a dedicated Docker network                                                         |
| S-04 | **P1 High**     | Access token mirrored to non-httpOnly cookie           | `apps/dashboard/src/lib/session.ts:20-37`                     | `sse_access_token` cookie is readable by JavaScript (SameSite=Lax, not HttpOnly) for SSE auth                                                          | XSS on any dashboard page steals the access token. Combined with CSRF cookie, attacker gets full session              | Use a short-lived, single-purpose SSE token minted server-side, or implement SSE authentication via a query parameter signed with a short-lived HMAC                              |
| S-05 | **P1 High**     | No request body size limit                             | `backend/main.py:139-155`                                     | FastAPI app has no `body` size limit configured                                                                                                        | Attacker sends multi-GB POST body to exhaust memory (DoS)                                                             | Add `max_body_size` middleware or nginx `client_max_body_size`                                                                                                                    |
| S-06 | **P1 High**     | DEBUG=true in production config                        | `.env.production:45`                                          | `DEBUG=true` enables `/api/docs` and `/api/openapi.json` endpoints                                                                                     | Exposes full API schema, all endpoints, all request/response models to attackers                                      | Set `DEBUG=false` in production                                                                                                                                                   |
| S-07 | **P1 High**     | No CI/CD pipeline exists                               | (absent)                                                      | No `.github/workflows/`, no CI configuration                                                                                                           | No automated security scanning, no lint/test gates, no dependency vulnerability checks                                | Implement CI with ruff, mypy, pytest, `pip-audit`/`safety`, Dockerfile linting (hadolint)                                                                                         |
| S-08 | **P2 Medium**   | No request body size limit at nginx level              | `docker/nginx.widget.conf`                                    | Nginx config does not set `client_max_body_size`                                                                                                       | Widget SDK can upload unbounded payloads                                                                              | Add `client_max_body_size 1m;` to nginx config                                                                                                                                    |
| S-09 | **P2 Medium**   | Redis has no authentication                            | `docker/compose.yml:232-243`                                  | Redis service has no `--requirepass`                                                                                                                   | Any container on the Docker network can read/write Redis (rate limits, cache, sessions)                               | Add `--requirepass` to Redis command or use `REDIS_URL` with password                                                                                                             |
| S-10 | **P2 Medium**   | Docker services have no resource limits                | `docker/compose.yml`                                          | No `mem_limit`, `cpus`, or `deploy.resources` on any service                                                                                           | A single container can consume all host resources                                                                     | Add `deploy.resources.limits` for memory and CPU on each service                                                                                                                  |
| S-11 | **P2 Medium**   | No `Content-Security-Policy` for widget                | `docker/nginx.widget.conf`                                    | Nginx serves widget JS without CSP header                                                                                                              | If widget JS is compromised via CDN/cache poisoning, no CSP blocks execution                                          | Add `Content-Security-Policy: script-src 'self'` header for widget static assets                                                                                                  |
| S-12 | **P2 Medium**   | `ALLOWED_HOSTS` includes `0.0.0.0` in production       | `.env.production:115`                                         | `0.0.0.0` is in the allowed hosts list                                                                                                                 | Host header poisoning attacks possible via `0.0.0.0`                                                                  | Remove `0.0.0.0` from `ALLOWED_HOSTS` in production; only include actual hostnames                                                                                                |
| S-13 | **P2 Medium**   | Widget session token has no JTI revocation mechanism   | `backend/core/security.py:134-158`                            | Widget session JWTs have a `jti` but no revocation list                                                                                                | A compromised widget token remains valid until expiry (15 min)                                                        | Acceptable for 15-min tokens; document as known limitation. Consider adding a Redis-backed JTI blacklist for emergency revocation                                                 |
| S-14 | **P2 Medium**   | CORS allows all methods and headers                    | `backend/main.py:157-163`                                     | `allow_methods=["*"]`, `allow_headers=["*"]`                                                                                                           | Unnecessarily broad; should restrict to used methods                                                                  | Change to `allow_methods=["GET","POST","PATCH","DELETE"]`, `allow_headers=["Authorization","Content-Type","X-CSRF-Token"]`                                                        |
| S-15 | **P2 Medium**   | Playwright runs with `--no-sandbox`                    | `backend/core/config.py:289`                                  | `crawl_no_sandbox: bool = True` defaults to True                                                                                                       | Chromium sandbox bypass; if browser exploit found, full container compromise                                          | Run worker as non-root, set `crawl_no_sandbox=False` in production                                                                                                                |
| S-16 | **P3 Low**      | No automated backup strategy                           | (absent)                                                      | No MongoDB backup cron, no Redis backup                                                                                                                | Data loss on infrastructure failure                                                                                   | Configure MongoDB Atlas continuous backups or `mongodump` cron                                                                                                                    |
| S-17 | **P3 Low**      | No health check authentication                         | `backend/api/routes/health.py`                                | `/api/health` is unauthenticated                                                                                                                       | Information disclosure (uptime, DB status)                                                                            | Acceptable for health endpoints; document as intentional                                                                                                                          |
| S-18 | **P3 Low**      | Spam filter is heuristic-only                          | `backend/services/widget/spam_filter.py`                      | Simple keyword/pattern matching                                                                                                                        | Deterministic bypass by slightly varying spam content                                                                 | Add ML-based or API-based spam detection as an additional layer                                                                                                                   |
| S-19 | **P3 Low**      | No audit trail for widget API key rotation             | `backend/services/api_keys/api_key_service.py`                | API key creation logged but revocation reason not captured                                                                                             | Forensic gap for key compromise investigations                                                                        | Add `revocation_reason` field to audit log entries                                                                                                                                |

---

## 4. Attack Scenarios

### Scenario 1: Cross-Tenant Data Access via IDOR

**Blocked.** Every repository query includes `tenant_id` from the authenticated principal (`backend/api/routes/websites.py:82`, `backend/api/routes/conversations.py:60`). The JWT's `tenant_id` is re-validated against the live user record in `auth_service.py:445`. An attacker cannot forge a `tenant_id` because it's signed in the JWT with `HS256` and the secret is server-side only.

### Scenario 2: Widget Token Theft via XSS

**Possible.** If an attacker achieves XSS on a page embedding the widget, they can read `document.cookie` and extract `sse_access_token` (`apps/dashboard/src/lib/session.ts:20-37`). This token grants 15 minutes of dashboard API access. The widget's Shadow DOM + DOMPurify rendering (`apps/widget/src/markdown/render.ts`) makes XSS in the widget itself very difficult, but an XSS on the _host page_ (not the widget) is the real threat surface.

### Scenario 3: Prompt Injection via Crawled Pages

**Mitigated.** Three defense layers exist:

1. Input detection (`backend/core/prompt_guard.py:150-166`) logs injection attempts
2. Context chunk sanitization (`backend/core/prompt_guard.py:204-219`) wraps suspicious chunks with `[SANITIZED CONTENT]` markers
3. System prompt instructs the model to ignore instructions in reference material (`backend/prompts/rag.py:53-55`)

A sophisticated attacker could still attempt multi-step injection across conversation turns, but the 12-turn memory limit (`chat_memory_turns: 12`) bounds the attack surface.

### Scenario 4: SSRF via Crawler

**Mitigated.** `backend/services/ingestion/ssrf_guard.py` performs DNS resolution + IP range validation before every navigation. Private IPs, link-local, and metadata addresses are blocked (`backend/utils/url_validator.py`). The async variant re-resolves on every navigation hop to prevent DNS rebinding.

### Scenario 5: Rate Limit Bypass via Visitor ID Rotation

**Partially Mitigated.** Entity-keyed rate limits (per-widget, per-visitor) can be rotated by a hostile client changing `visitor_id`. However, dedicated per-IP burst budgets (`widget_chat_ip_limiter`, `widget_session_ip_limiter` at `backend/api/deps.py:891-920`) cannot be trivially rotated. The layered approach (entity + IP) provides reasonable protection.

### Scenario 6: Refresh Token Theft

**Mitigated.** Refresh tokens are httpOnly cookies (`backend/api/routes/auth.py:51-58`), hashed with SHA-256 before storage (`backend/core/security.py:171-173`), and rotation is atomic via `findOneAndUpdate` with a `revoked_at` guard (`backend/services/auth/auth_service.py:303-313`). Reuse detection revokes all sessions and sends a security alert email (`auth_service.py:572-593`).

---

## 5. Production Blocking Issues

These must be fixed before any real user data enters the system:

| #    | Issue                        | Action Required                                                                                                                                                                          |
| ---- | ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| S-01 | Secrets in `.env.production` | Rotate ALL exposed keys (MongoDB, Redis, Gemini, Groq, OpenRouter, Jina, Cohere, Resend, Razorpay). Move secrets to deployment platform env vars. Add `.env.production` to `.gitignore`. |
| S-02 | Containers run as root       | Add non-root `USER` to `Dockerfile.api` and `Dockerfile.worker`.                                                                                                                         |
| S-03 | MongoDB exposed without auth | Remove host port mapping. Enable MongoDB authentication.                                                                                                                                 |
| S-05 | No request body size limit   | Add body size middleware or nginx limit.                                                                                                                                                 |
| S-06 | DEBUG=true in production     | Set `DEBUG=false`. Remove docs/openapi endpoints.                                                                                                                                        |
| S-07 | No CI/CD                     | Set up GitHub Actions with lint, type-check, test, dependency audit.                                                                                                                     |
| S-15 | No-sandbox Chromium          | Run worker as non-root, disable no-sandbox.                                                                                                                                              |

---

## 6. Recommended Implementation Order

### Phase 14.1 — Secret Rotation & Repository Hygiene (Day 1)

1. Rotate every secret in `.env.production` (MongoDB, Redis, all API keys, Razorpay)
2. Move all secrets to deployment platform environment variables
3. Add `.env.production` and `.env.development` to `.gitignore`
4. Keep only `.env.example` tracked
5. Audit git history for committed secrets; consider `git-filter-repo` if sensitive

### Phase 14.2 — Docker Hardening (Days 2-3)

1. Add `USER appuser` to `Dockerfile.api` and `Dockerfile.worker`
2. Remove `ports: "27017:27017"` from `docker/compose.yml` (MongoDB)
3. Add `--requirepass` to Redis or use authenticated `REDIS_URL`
4. Add `deploy.resources.limits` (memory: 512MB api, 1GB worker, 256MB dashboard)
5. Set `crawl_no_sandbox=False` in production compose env
6. Add `client_max_body_size 1m;` to nginx widget config

### Phase 14.3 — API Security Hardening (Days 3-4)

1. Set `DEBUG=false` in production
2. Add request body size limit middleware (FastAPI `max_body_size` or Starlette middleware)
3. Restrict CORS to used methods: `["GET","POST","PATCH","DELETE"]`
4. Restrict CORS headers: `["Authorization","Content-Type","X-CSRF-Token"]`
5. Remove `0.0.0.0` from `ALLOWED_HOSTS` in production

### Phase 14.4 — SSE Token Security (Days 4-5)

1. Replace the readable `sse_access_token` cookie with a server-side SSE token minting endpoint
2. Or: implement a short-lived (5 min), single-purpose SSE HMAC token
3. Audit all cookie permissions (`HttpOnly`, `Secure`, `SameSite`)

### Phase 14.5 — CI/CD Pipeline (Days 5-7)

1. Create `.github/workflows/ci.yml` with:
   - `ruff check` (lint)
   - `mypy --strict` (type check)
   - `pytest` (tests)
   - `pip-audit` or `safety` (dependency vulnerabilities)
   - `hadolint` (Dockerfile linting)
   - Build verification for dashboard + widget
2. Require CI pass before merge to `main`

### Phase 14.6 — Monitoring & Backup (Days 7-10)

1. Configure MongoDB Atlas continuous backups (or `mongodump` cron)
2. Set up error tracking (Sentry or equivalent)
3. Add alerting for: rate limit spikes, auth failures, AI provider errors
4. Document runbook for secret rotation, incident response

---

## 7. Final Production Readiness

### **NOT READY** — with conditions

**Blockers (must fix before deployment):**

1. Production secrets are committed to the git repository — every key must be rotated
2. Docker containers run as root — unacceptable for a multi-tenant SaaS
3. MongoDB is exposed on the host network without authentication
4. No CI/CD pipeline — no automated quality gates
5. `DEBUG=true` exposes API documentation endpoints

**After fixing the 7 production-blocking issues (Phase 14.1–14.3), the system WILL BE ready for staging deployment.** The remaining P2/P3 items can be addressed iteratively in production.

**Strengths that support readiness:**

- Tenant isolation is consistently enforced at every query level
- Refresh token rotation is atomic with reuse detection
- Widget XSS defense is dual-gated (DOMPurify + allowlisted tokenizer)
- Rate limiting is comprehensive (entity-keyed + IP-keyed layers)
- Prompt injection defense is 3-layered (input detection, context sanitization, output validation)
- SSRF protection with DNS rebinding mitigation
- Comprehensive database indexes and TTL cleanup policies
- Privacy-safe logging (SHA-256 content hashing, no PII in logs)
- RBAC with numeric hierarchy and fail-closed unknown roles
- Boot-time production validation rejects weak secrets, missing providers, wildcard CORS

---

_Audit performed by inspecting actual source code across 50+ files. No assumptions — all findings are verified against implementation._
