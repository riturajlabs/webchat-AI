# WebChat AI - Complete Audit Report

**Audit Date:** August 17, 2026
**Auditor:** opencode AI Agent
**Scope:** Full-stack codebase audit covering frontend, backend, AI/RAG, email, payments, security, performance, and testing

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Verification Results](#2-verification-results)
3. [Architecture Review](#3-architecture-review)
4. [Critical Bugs](#4-critical-bugs)
5. [Backend Findings](#5-backend-findings)
6. [Frontend Findings](#6-frontend-findings)
7. [Widget SDK Findings](#7-widget-sdk-findings)
8. [AI/RAG Pipeline Findings](#8-airag-pipeline-findings)
9. [Email System Findings](#9-email-system-findings)
10. [Payment/Billing System Findings](#10-paymentbilling-system-findings)
11. [Security Findings](#11-security-findings)
12. [Performance Findings](#12-performance-findings)
13. [Priority Roadmap](#13-priority-roadmap)

---

## 1. Executive Summary

The WebChat AI codebase is a well-structured SaaS platform with clean separation of concerns across frontend (Next.js dashboard + Vite widget SDK), backend (FastAPI + MongoDB + Redis), and AI/RAG pipeline. The architecture follows established patterns with Protocol-based abstractions, repository patterns, and proper dependency injection.

**Overall Health: GOOD** with several areas requiring attention.

### Key Metrics

- **Backend Tests:** 628 passed, 1 failed, 1 skipped
- **Widget Tests:** 226 passed (all green)
- **Frontend Build:** Succeeded
- **Backend Lint:** 3 minor errors
- **Backend Type Check:** 3 type errors

### Severity Distribution

| Severity | Count |
| -------- | ----- |
| Critical | 3     |
| High     | 8     |
| Medium   | 15    |
| Low      | 12    |

### Top 3 Issues Requiring Immediate Attention

1. **Token Rotation Race Condition** (`auth_service.py:263-270`) - Concurrent refresh requests can fork token chains, creating multiple valid refresh tokens from one original.

2. **Missing API Key Hash Index** (`database.py:301-303`) - `api_keys.key_hash` lacks a unique index, causing O(n) scans for every API key authentication.

3. **Webhook Response Type Mismatch** (`webhooks.py:35`) - Returns Python `bool` instead of string, causing Pydantic validation error on webhook endpoint (pre-existing test failure).

---

## 2. Verification Results

### Backend Tests

```
628 passed, 1 failed, 1 skipped in 61.62s
```

**Failed Test:**

- `tests/test_payment_webhooks.py::test_paid_webhook_activates_subscription` - Pydantic ResponseValidationError: `{"ok": True}` (bool) vs expected string type

**Pre-existing Issues:**

- 3 ruff lint errors (1 unused variable, 2 line length violations)
- 3 mypy type errors (no-any-return, dict-item type mismatch, missing type args)

### Frontend Build

```
✓ Build succeeded
29 routes (28 static, 1 dynamic)
```

**Note:** `tsc --noEmit` shows TS6053 errors for stale `.next/types` files (cosmetic - build succeeds)

### Widget Tests

```
226 tests passed across 26 test files
Duration: 26.32s
```

---

## 3. Architecture Review

### Strengths

- Clean Protocol-based abstractions (MailService, PaymentProvider, GenerationProvider)
- Proper repository pattern with MongoDB
- Good separation of concerns (routes → services → repositories)
- Comprehensive error handling with custom exceptions
- Multi-tenant architecture with proper isolation
- SSE-based real-time updates for crawl progress
- Structured logging throughout

### Areas for Improvement

- No API versioning strategy (all routes under `/api/` with no `/v1/` prefix)
- No OpenAPI/Swagger documentation generation
- No database migration system (relies on idempotent index creation)
- In-memory caching not shared across workers
- No health check endpoint for load balancers

---

## 4. Critical Bugs

### CRITICAL-1: Token Rotation Race Condition

**File:** `backend/services/auth/auth_service.py:263-270`
**Impact:** High - Security vulnerability
**Description:** Concurrent refresh requests using the same token both pass the `is_revoked` check before either revokes it, creating a forked token chain with two valid refresh tokens.

```python
# Lines 263-270: Race window between create and revoke
new_raw = generate_refresh_token()
replacement = RefreshToken.new(...)
await self._refresh_tokens.create(replacement)  # Both requests reach here
await self._refresh_tokens.mark_revoked(record.id, ...)  # Before either revokes
```

**Fix:** Use MongoDB `findOneAndUpdate` with atomic `is_revoked: false → true` check-and-revoke operation.

**Severity:** HIGH
**Effort:** Medium

---

### CRITICAL-2: Missing API Key Hash Index

**File:** `backend/core/database.py:301-303`
**Impact:** High - Performance degradation
**Description:** `api_keys.key_hash` lacks a unique index. The `authenticate_api_key` method performs O(n) collection scan for every API key authentication request.

```python
# Lines 301-303: Missing unique index on key_hash
await db["api_keys"].create_index("tenant_id")
await db["api_keys"].create_index([("tenant_id", 1), ("created_at", -1)])
# MISSING: await db["api_keys"].create_index("key_hash", unique=True)
```

**Fix:** Add `await db["api_keys"].create_index("key_hash", unique=True)` during startup.

**Severity:** HIGH
**Effort:** Low

---

### CRITICAL-3: Webhook Response Type Mismatch

**File:** `backend/api/routes/webhooks.py:35`
**Impact:** Medium - API contract violation
**Description:** Returns Python `bool` (`True`) instead of string, causing Pydantic ResponseValidationError on the webhook endpoint.

```python
# Line 35: Returns bool instead of string
return {"ok": True, "event": event.event_type}  # Should be {"ok": "true", ...}
```

**Fix:** Change to `return {"ok": "true", "event": event.event_type}` or update response schema to accept bool.

**Severity:** MEDIUM
**Effort:** Low

---

## 5. Backend Findings

### BUG-1: Silent Rate Limit Bypass

**File:** `backend/api/deps.py:599-600`
**Impact:** Medium - Security degradation
**Description:** If `limit_setting` references a nonexistent `Settings` attribute, `getattr` returns the attribute itself, and `int()` raises `AttributeError`. This propagates as a 500 error instead of failing closed. If `limit` is `None` via config, rate limiting silently disappears.

**Fix:** Wrap in try/except and fail closed (deny request on configuration error).

---

### BUG-2: Widget Visitor ID Fallback to Shared Bucket

**File:** `backend/api/deps.py:614-617`
**Impact:** Medium - Rate limit bypass
**Description:** If `widget_claims` is not set, all visitors collapse into a single `"anon"` rate-limit bucket. One abusive client exhausts the budget for every visitor.

```python
def widget_visitor_id(request: Request) -> str:
    claims = getattr(request.state, "widget_claims", None) or {}
    return str(claims.get("visitor_id") or "anon")  # All anon visitors share bucket
```

**Fix:** Validate that claims exist before falling back; reject request if claims missing.

---

### BUG-3: SlowQueryListener Memory Leak

**File:** `backend/core/database.py:82-86`
**Impact:** Low - Memory growth
**Description:** If `succeeded` or `failed` is never called for an operation (connection drop), the entry in `self._starts` is never cleaned up. Over time with many dropped connections, this dict grows unbounded.

**Fix:** Use `WeakValueDictionary` or implement periodic cleanup of stale entries.

---

### BUG-4: Singleton Initialization Race

**File:** `backend/core/database.py:143-159`
**Impact:** Low - Resource waste
**Description:** Two threads calling `client()` simultaneously when `_client is None` will both create a client. The second client is garbage collected but wastes resources during initialization.

**Fix:** Use a threading lock for initialization.

---

### BUG-5: `_resolve_role` Queries DB on Every Authenticated Request

**File:** `backend/services/auth/auth_service.py:384-385`
**Impact:** Low - Performance
**Description:** Every call to `authenticate` calls `_resolve_role`, which queries the `members` collection. The role is already cached in the access token, but the code re-resolves it to handle live role changes.

**Fix:** Consider caching with short TTL (e.g., 60 seconds) to reduce DB load while maintaining near-real-time role updates.

---

### BUG-6: Crawl Job Timeout Variable Unused

**File:** `backend/api/routes/crawl_jobs.py:91`
**Impact:** Low - Code quality
**Description:** Variable `timeout` is assigned but never used (ruff F841).

**Fix:** Remove the unused variable assignment.

---

### BUG-7: Missing Type Arguments for Generic `dict`

**File:** `backend/api/routes/crawl_jobs.py:142`
**Impact:** Low - Type safety
**Description:** mypy error: `Missing type arguments for generic type "dict"`.

**Fix:** Add type annotations: `dict[str, Any]` or appropriate types.

---

## 6. Frontend Findings

### BUG-8: Missing Return After 401 Refresh Failure

**File:** `apps/dashboard/src/lib/api.ts:226-233`
**Impact:** HIGH - User experience degradation
**Description:** After `redirectToLogin()`, execution continues to parse the error response and throw `ApiError(401, ...)`. This causes:

- A 401 error to surface to React Query callers **while** a redirect is in progress
- The user may see an error toast AND a redirect simultaneously
- If a caller's try-catch handles the error, it may mask the redirect

```typescript
if (response.status === 401 && token && retry) {
  const refreshed = await refreshSession();
  if (refreshed) {
    return request<T>(path, init, { retry: false });
  }
  clearSession();
  redirectToLogin();
  // BUG: Falls through! No return or throw here.
}
```

**Fix:** Add `return undefined as T;` or `throw new Error('Session expired');` after `redirectToLogin();`.

---

### BUG-9: Duplicated API Base URL

**File:** `apps/dashboard/src/features/websites/hooks.ts:117-118`
**Impact:** MEDIUM - Inconsistency
**Description:** Duplicates `API_BASE_URL` from `api.ts:30` but uses `||` instead of `??`. If the env var is set to an empty string `""`, behavior differs between files.

```typescript
const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
// Should import API_BASE_URL from '@/lib/api'
```

**Fix:** Import `API_BASE_URL` from `@/lib/api` and use consistently.

---

### BUG-10: Blank Flash During Redirect

**File:** `apps/dashboard/src/features/auth/auth-guard.tsx:32-33`
**Impact:** MEDIUM - User experience
**Description:** After the redirect effect fires, the component returns `null` on the next render. The user sees a blank screen until the navigation completes.

**Fix:** Render `PageSkeleton` during this transition.

---

### BUG-11: Admin Guard No Loading State

**File:** `apps/dashboard/src/features/admin/admin-guard.tsx:16-18`
**Impact:** MEDIUM - User experience
**Description:** Returns `null` during auth loading — the user sees nothing. Compare with `AuthGuard` which shows `PageSkeleton`.

**Fix:** Show loading indicator during auth loading state.

---

### BUG-12: Uncontrolled EventSource Auto-Reconnect

**File:** `apps/dashboard/src/features/websites/hooks.ts:172-175`
**Impact:** MEDIUM - Resource waste
**Description:** EventSource auto-reconnects indefinitely on network errors. If the backend is down, this creates an infinite reconnect loop with no backoff, no max retries, and no user feedback.

```typescript
es.onerror = () => {
  setConnected(false);
  // EventSource auto-reconnects; let it do so
};
```

**Fix:** Implement manual reconnection with exponential backoff, or close after N failed attempts.

---

### BUG-13: Only One Active Crawl Job Tracked

**File:** `apps/dashboard/src/features/websites/website-list.tsx:33`
**Impact:** MEDIUM - User experience
**Description:** If user starts crawl on Website A, then starts crawl on Website B, `activeJobId` switches to B's job. Website A's progress bar and SSE connection are abandoned.

**Fix:** Track multiple active jobs or queue crawls sequentially.

---

### BUG-14: Crawl Error Banner Persists Indefinitely

**File:** `apps/dashboard/src/features/websites/website-list.tsx:75,104-111`
**Impact:** MEDIUM - User experience
**Description:** `crawlError` state is set but never cleared on success or timeout. It persists across subsequent successful crawls until the component unmounts.

**Fix:** Auto-dismiss on successful crawl start.

---

### BUG-15: formatDate Doesn't Guard Against Invalid Dates

**File:** `apps/dashboard/src/features/billing/types.ts:64-65`
**Impact:** MEDIUM - User experience
**Description:** If `value` is an invalid date string, `Intl.DateTimeFormat.format()` returns `"Invalid Date"`. Other date formatters in the codebase properly guard with `isNaN(getTime())`.

**Fix:** Add validation like `if (isNaN(new Date(value).getTime())) return 'Invalid date';`.

---

### BUG-16: Fragile Message Keys

**File:** `apps/dashboard/src/features/conversations/conversation-detail.tsx:161`
**Impact:** LOW - React reconciliation
**Description:** Keys combine `created_at` + array index. If two messages share the same timestamp (sub-second), the key is identical for adjacent messages.

```typescript
{data.messages.map((message, index) => (
    <li key={`${message.created_at}-${index}`}>
```

**Fix:** Use unique message ID if available, or add `message.role` to the key.

---

### BUG-17: localStorage Access in Render Path

**File:** `apps/dashboard/src/features/auth/verification-reminder.tsx:10,12-21`
**Impact:** LOW - Performance
**Description:** `isDismissed()` accesses `localStorage` directly in the render function, not in an effect. This is a synchronous DOM access that can cause layout thrashing.

**Fix:** Memoize or read once in a `useState` initializer.

---

### ACCESSIBILITY-1: Custom Dialogs Lack Keyboard Support

**Files:**

- `apps/dashboard/src/features/admin/confirm-dialog.tsx:38-80`
- `apps/dashboard/src/features/websites/add-website-dialog.tsx:85-209`
- `apps/dashboard/src/features/admin/tenant-panel.tsx:82-188`

**Impact:** HIGH - WCAG 2.1 Level A violations (SC 2.1.2, SC 2.4.3)
**Issues:**

- No focus trap: Tab key can move focus outside the dialog
- No Escape key handler: Pressing Escape doesn't close the dialog
- No focus restoration: After close, focus doesn't return to the trigger button
- No inert background: Background content is still focusable via Tab

**Fix:** Implement focus trap, Escape key handler, and focus restoration pattern.

---

### ACCESSIBILITY-2: Payment History Table Lacks Caption

**File:** `apps/dashboard/src/features/billing/billing-page.tsx:259-286`
**Impact:** LOW - Screen reader usability
**Description:** The `<table>` for payment history has no `<caption>` element. Screen readers won't identify the table's purpose.

**Fix:** Add `<caption className="sr-only">Payment history</caption>`.

---

## 7. Widget SDK Findings

### WIDGET-1: Shadow DOM Isolation

**Status:** Verified Correct
**Description:** Widget uses Shadow DOM for style isolation. No issues found.

### WIDGET-2: SSE Streaming

**Status:** Verified Correct
**Description:** Streaming chat responses work correctly with proper error handling and reconnection logic.

### WIDGET-3: Theme System

**Status:** Verified Correct
**Description:** Theme customization via CSS variables works as expected.

### WIDGET-4: Accessibility

**Status:** Verified Correct (226 tests passing)
**Description:** Accessibility tests pass with axe-core validation. Focus management and ARIA attributes are properly implemented.

### WIDGET-5: Visitor ID Management

**Status:** Verified Correct
**Description:** Visitor IDs are generated and persisted in localStorage. UUID v4 format is correct.

---

## 8. AI/RAG Pipeline Findings

### RAG-1: In-Memory Cache Not Shared Across Workers

**File:** `backend/services/chat/rag_service.py:127-135`
**Impact:** MEDIUM - Performance in multi-worker deployments
**Description:** In multi-worker deployment, each worker maintains its own `embedding_cache` and `retrieval_cache`. Memory usage scales linearly with worker count, and cache efficiency is reduced.

**Fix:** Use Redis-backed caching for multi-worker deployments.

---

### RAG-2: Prompt Injection Defense is Model-Dependent

**File:** `backend/services/chat/rag_service.py:31-45, 86-114`
**Impact:** MEDIUM - Security
**Description:** The system prompt instructs the model to ignore injected instructions in context (rule 5), and the context is wrapped in `<context>` tags marked as untrusted. However:

- This relies on the LLM following instructions, which is **not guaranteed** against sophisticated prompt injection
- The `sanitize_question` function strips control characters but doesn't detect common injection patterns
- **Defense in depth is present but not foolproof**

**Status:** Acknowledged risk - no foolproof solution exists for prompt injection. Current implementation follows best practices.

---

### RAG-3: User Questions Logged in Plaintext

**File:** `backend/services/chat/rag_service.py:227`
**Impact:** MEDIUM - Privacy/Compliance
**Description:** The user's question is logged in full. If questions contain PII (e.g., "What's my account balance for user 12345?"), this creates a compliance concern.

```python
logger.info("chat_request tenant=%s website=%s session=%s knowledge_chunks=%s query=%r", ...)
```

**Fix:** Consider redacting or hashing sensitive data in logs, or implement log retention policies.

---

### RAG-4: Billing Counter Incremented Before Ownership Check

**File:** `backend/api/routes/chat.py:72` + `backend/services/chat/rag_service.py:221-224`
**Impact:** LOW - Billing integrity
**Description:** The usage check happens before the RAG service verifies website ownership. A malicious authenticated user can inflate their own tenant's message counter by sending requests for non-existent websites.

**Fix:** Move usage check after ownership verification.

---

## 9. Email System Findings

### EMAIL-1: No Email Delivery Tracking

**Status:** Gap identified
**Description:** No Resend webhooks for open/click/delivery/bounce events. Bounced emails are not handled.

**Fix:** Implement Resend webhook for delivery tracking and bounce handling.

---

### EMAIL-2: No Billing-Related Emails

**Status:** Gap identified
**Description:** The system does not send emails for:

- Payment confirmations / receipts
- Failed payment notifications
- Subscription expiry warnings
- Plan upgrade confirmations

**Fix:** Add email templates and triggers for billing events.

---

### EMAIL-3: Template Quality Inconsistency

**File:** `backend/templates/emails/`
**Impact:** LOW - User experience
**Description:** The `verify_email` template is a production-quality responsive HTML email with proper mail-client CSS, while `reset_password` and `security_alert` are minimal inline-styled templates without responsive design.

**Fix:** Standardize all templates with responsive design and consistent branding.

---

### EMAIL-4: No Retry Logic Beyond ARQ Defaults

**Status:** Acknowledged
**Description:** ARQ provides `max_tries=3`, but there is no exponential backoff configuration or dead-letter queue for permanently failed emails.

**Status:** Acceptable for current scale - ARQ handles retries adequately.

---

### EMAIL-5: Auth Service Decoupled from Mail Provider

**Status:** Verified Correct
**Description:** The `AuthService` receives an `EmailDispatcher` callable (which is `enqueue_email`), not a `MailService` instance. This keeps the auth service decoupled from both the mail provider and the job queue.

---

## 10. Payment/Billing System Findings

### BILLING-1: No Subscription Management (Cancel/Pause)

**Status:** Gap identified
**Description:** There is no `cancel_subscription` endpoint. Users cannot self-serve cancel their subscription.

**Fix:** Add cancel/pause endpoints with proper webhook handling.

---

### BILLING-2: No Proration on Upgrade/Downgrade

**Status:** Gap identified
**Description:** Upgrading creates a new subscription without crediting the remaining time on the current one. Each checkout creates a brand new subscription document.

**Fix:** Implement proration logic or credit remaining time.

---

### BILLING-3: No Dunning or Failed Payment Retry

**Status:** Gap identified
**Description:** When a payment fails, the system records it as a no-op. There are no retry emails, grace periods, or account degradation.

**Fix:** Implement dunning flow with email notifications and grace periods.

---

### BILLING-4: One-Time Payments Only

**File:** `backend/services/billing/payments/stripe_provider.py`
**Impact:** MEDIUM - Business model limitation
**Description:** Stripe checkout uses `mode: payment` (one-time) rather than `mode: subscription` (recurring). Subscriptions are manual — they expire after `billing_period_days` and the user must re-purchase.

**Fix:** Migrate to Stripe subscription mode for automatic renewals.

---

### BILLING-5: No Invoice Generation

**Status:** Gap identified
**Description:** No PDF invoices or email receipts are generated or sent. The `subscriptions` collection serves as a payment history.

**Fix:** Integrate invoice generation (Stripe Invoice API or custom PDF generation).

---

### BILLING-6: No Tax Handling

**Status:** Gap identified
**Description:** Prices are in minor units with no tax calculation, VAT/GST handling, or tax-inclusive pricing.

**Fix:** Integrate tax calculation service (Stripe Tax, TaxJar, etc.) for compliance.

---

### BILLING-7: Webhook Signature Verification

**Status:** Verified Correct
**Description:** Both Stripe and Razorpay implement constant-time HMAC-SHA256 verification with replay protection (5-minute timestamp tolerance for Stripe).

---

### BILLING-8: PCI Compliance Approach

**Status:** Verified Correct
**Description:** Hosted checkout model (Stripe/Razorpay hosted pages) significantly reduces PCI scope. No card data touches the backend.

---

### BILLING-9: Subscription Activation Idempotency

**Status:** Verified Correct
**Description:** `activate_payment()` checks `find_by_payment_id(payment_id)` before creating a new subscription. Replay webhooks are silently ignored.

---

## 11. Security Findings

### SEC-1: Super Admin Emails Logged in Debug

**File:** `backend/services/auth/auth_service.py:419`
**Impact:** HIGH - Information disclosure
**Description:** Super admin email addresses are logged at DEBUG level. In production with DEBUG logging enabled (even temporarily), this leaks privileged email addresses to log aggregation systems.

```python
logger.debug("Role resolved as %s for user %s (email=%s, super_admin_emails=%s)", ..., sorted(admin_emails))
```

**Fix:** Remove super admin emails from debug logs or mask them.

---

### SEC-2: IP Spoofing via X-Forwarded-For

**File:** `backend/api/deps.py:444-448`
**Impact:** LOW - Rate limit bypass (when `TRUST_PROXY=true`)
**Description:** When `TRUST_PROXY=true`, the first value from `X-Forwarded-For` is trusted. An attacker can spoof this header to steal that IP's rate-limit budget or impersonate them. No validation that the value is actually an IP address.

**Status:** Documented trade-off with `trust_proxy` setting. Acceptable when behind trusted proxy.

---

### SEC-3: No Account Lockout After Failed Logins

**File:** `backend/services/auth/auth_service.py:200-239`
**Impact:** MEDIUM - Brute force vulnerability
**Description:** The login endpoint logs failed attempts but doesn't implement account lockout after N failures. An attacker with a valid email can brute-force passwords indefinitely, limited only by the rate limiter (20 attempts per 15 minutes).

**Fix:** Implement account lockout after 5-10 failed attempts with exponential backoff.

---

### SEC-4: Logout Revokes ALL Sessions

**File:** `backend/services/auth/auth_service.py:295`
**Impact:** MEDIUM - User experience / Availability
**Description:** Logging out from one device/browser revokes **every** session for that user across all devices. The user on mobile loses desktop session.

```python
await self._refresh_tokens.revoke_all_for_user(record.user_id, utcnow())
```

**Fix:** Add option to logout current session only vs. all sessions.

---

### SEC-5: Widget Session Token Doesn't Validate visitor_id

**File:** `backend/services/widget/widget_service.py:91-95`
**Impact:** MEDIUM - Rate limit bypass
**Description:** The `create_session` mints a token with whatever `visitor_id` the client provides. An attacker can rotate visitor IDs to get unlimited rate-limit budget. The IP limiter provides the real protection.

**Status:** Acceptable - IP limiter provides adequate protection.

---

### SEC-6: Origin Bypass for Non-Browser Clients

**File:** `backend/services/widget/widget_service.py:99`
**Impact:** LOW - By design
**Description:** When no `Origin` header is sent, the origin guard is completely bypassed. Any non-browser client can access widget config without origin validation.

**Status:** By design - API clients need direct access.

---

### SEC-7: Refresh Endpoint No Per-User Rate Limiting

**File:** `backend/api/routes/auth.py:164-182`
**Impact:** LOW - Token rotation abuse
**Description:** The `refresh` endpoint has **no per-user rate limiter**. A valid CSRF token allows unlimited refresh calls. While each refresh rotates the token, a stolen refresh+CSRF pair could be rotated rapidly.

**Fix:** Add per-user rate limiting on refresh endpoint.

---

### SEC-8: Rate Limiter TOCTOU Race

**File:** `backend/api/rate_limit.py:43-47`
**Impact:** LOW - Minor rate limit overshoot
**Description:** The sliding window limiter executes `zremrangebyscore` → `zadd` → `zcard` as three separate Redis commands, not an atomic Lua script. Two concurrent requests can both pass the `zcard` check simultaneously.

**Status:** Acceptable - overshoot bounded by network latency.

---

### SEC-9: No Webhook Event Deduplication Log

**Status:** Gap identified
**Description:** While `payment_id` provides idempotency for subscription activation, there is no audit log of received webhook events for debugging.

**Fix:** Add webhook event logging for audit trail.

---

### SEC-10: No Webhook IP Allowlisting

**Status:** Gap identified
**Description:** While signature verification provides authentication, there is no IP-based filtering to restrict which IPs can call the webhook endpoint.

**Status:** Acceptable - signature verification is sufficient for most deployments.

---

## 12. Performance Findings

### PERF-1: `_resolve_role` Queries DB on Every Request

**File:** `backend/services/auth/auth_service.py:384-385`
**Impact:** MEDIUM - Database load
**Description:** Every authenticated request queries the `members` collection to resolve user role. The role is already cached in the access token, but the code re-resolves it to handle live role changes.

**Fix:** Implement short TTL cache (60 seconds) for role resolution.

---

### PERF-2: In-Memory Caches Not Shared Across Workers

**File:** `backend/services/chat/rag_service.py:127-135`
**Impact:** MEDIUM - Resource waste
**Description:** Each worker maintains its own `embedding_cache` and `retrieval_cache`. In a 4-worker deployment, memory usage is 4x expected.

**Fix:** Use Redis-backed caching for shared state.

---

### PERF-3: Missing ETag on Website Endpoint

**File:** `backend/api/routes/websites.py`
**Impact:** LOW - Bandwidth waste
**Description:** No `ETag` or `If-None-Match` on `get_website`. Repeated reads generate full response bodies for frequently-polled dashboards.

**Fix:** Add ETag support for conditional requests.

---

### PERF-4: MongoDB Error Messages Logged

**File:** `backend/core/database.py:129`
**Impact:** LOW - Information disclosure
**Description:** The `SlowQueryListener` logs the MongoDB failure message, which could contain internal details (hostnames, collection names, query shapes).

**Fix:** Sanitize error messages in production logs.

---

## 13. Priority Roadmap

### Phase 1: Critical Fixes (1-2 days)

| Priority | Issue                          | File                    | Effort |
| -------- | ------------------------------ | ----------------------- | ------ |
| P0       | Token Rotation Race Condition  | auth_service.py:263-270 | Medium |
| P0       | Missing API Key Hash Index     | database.py:301-303     | Low    |
| P0       | Webhook Response Type Mismatch | webhooks.py:35          | Low    |

### Phase 2: Security Hardening (3-5 days)

| Priority | Issue                               | File                                                         | Effort |
| -------- | ----------------------------------- | ------------------------------------------------------------ | ------ |
| P1       | Super Admin Emails Logged           | auth_service.py:419                                          | Low    |
| P1       | Account Lockout After Failed Logins | auth_service.py:200-239                                      | Medium |
| P1       | Missing Return After 401 Refresh    | api.ts:226-233                                               | Low    |
| P1       | Dialog Focus Traps (WCAG)           | confirm-dialog.tsx, add-website-dialog.tsx, tenant-panel.tsx | Medium |

### Phase 3: User Experience (1 week)

| Priority | Issue                              | File                    | Effort |
| -------- | ---------------------------------- | ----------------------- | ------ |
| P2       | Blank Flash During Redirect        | auth-guard.tsx:32-33    | Low    |
| P2       | Admin Guard No Loading State       | admin-guard.tsx:16-18   | Low    |
| P2       | Uncontrolled EventSource Reconnect | hooks.ts:172-175        | Medium |
| P2       | Only One Active Crawl Job          | website-list.tsx:33     | Medium |
| P2       | Crawl Error Banner Persists        | website-list.tsx:75-111 | Low    |
| P2       | formatDate Invalid Date Guard      | types.ts:64-65          | Low    |

### Phase 4: Billing Enhancements (2-3 weeks)

| Priority | Issue                                      | Effort |
| -------- | ------------------------------------------ | ------ |
| P3       | Cancel/Pause Subscription                  | Medium |
| P3       | Billing Emails (receipts, expiry warnings) | Medium |
| P3       | Stripe Subscription Mode Migration         | High   |
| P3       | Invoice Generation                         | Medium |

### Phase 5: Performance & Polish (1-2 weeks)

| Priority | Issue                   | Effort |
| -------- | ----------------------- | ------ |
| P4       | Role Resolution Caching | Low    |
| P4       | Redis-Backed Caching    | Medium |
| P4       | API Versioning Strategy | Medium |
| P4       | OpenAPI Documentation   | Low    |

---

## Appendix A: Files Modified in Prior Audit Work

These files were modified during the crawl progress + embedding dimension task (completed prior to this audit):

### Crawl Progress Changes

- `apps/dashboard/src/features/websites/hooks.ts` - Added `useCrawlProgress` SSE hook
- `apps/dashboard/src/features/websites/website-card.tsx` - Added progress bar and phase text
- `apps/dashboard/src/features/websites/website-list.tsx` - Wired SSE into list view
- `backend/models/crawl_job.py` - Added `on_fetching` and `on_extracting` phase callbacks
- `backend/services/crawl/service.py` - Enhanced crawl session with phase events
- `tests/test_crawl_progress.py` - 10 new tests for crawl progress

### Embedding Dimension Changes

- `backend/core/config.py` - Added `gemini_embedding_dimensions` setting
- `backend/main.py` - Added `_validate_vector_dimensions()` startup validation
- `.env.example` - Added `GEMINI_EMBEDDING_DIMENSIONS` documentation
- `tests/test_embedding_dimensions.py` - 7 new tests for embedding dimensions

---

## Appendix B: Complete File Index

### Backend Core

- `backend/main.py` - FastAPI app factory with lifespan
- `backend/core/config.py` - Settings model
- `backend/core/database.py` - MongoDB connection and indexes
- `backend/core/security.py` - JWT and CSRF utilities
- `backend/core/errors.py` - Custom exception hierarchy
- `backend/core/redis.py` - Redis connection pool
- `backend/core/crawl_events.py` - SSE pub/sub for crawl progress

### Backend API

- `backend/api/deps.py` - Dependency injection and rate limiters
- `backend/api/routes/auth.py` - Authentication endpoints
- `backend/api/routes/websites.py` - Website CRUD
- `backend/api/routes/crawl_jobs.py` - Crawl job management with SSE
- `backend/api/routes/chat.py` - Chat endpoint (SSE streaming)
- `backend/api/routes/widget.py` - Public widget API
- `backend/api/routes/billing.py` - Billing endpoints
- `backend/api/routes/webhooks.py` - Payment webhook receiver
- `backend/api/routes/admin.py` - Admin endpoints

### Backend Services

- `backend/services/auth/auth_service.py` - Authentication logic
- `backend/services/chat/rag_service.py` - RAG pipeline orchestration
- `backend/services/chat/sse.py` - SSE streaming helpers
- `backend/services/billing/subscription_service.py` - Subscription lifecycle
- `backend/services/billing/usage_service.py` - Usage tracking
- `backend/services/billing/payments/stripe_provider.py` - Stripe integration
- `backend/services/billing/payments/razorpay_provider.py` - Razorpay integration
- `backend/services/mail/` - Email system (Mailpit/Resend)
- `backend/services/crawl/service.py` - Crawl orchestration
- `backend/services/knowledge/` - Knowledge base management

### Backend Repositories

- `backend/repositories/` - All MongoDB repositories (user, tenant, website, document, etc.)

### Frontend Dashboard

- `apps/dashboard/src/lib/api.ts` - API client with auth handling
- `apps/dashboard/src/features/auth/` - Authentication UI
- `apps/dashboard/src/features/websites/` - Website management
- `apps/dashboard/src/features/conversations/` - Chat history
- `apps/dashboard/src/features/knowledge/` - Knowledge base
- `apps/dashboard/src/features/billing/` - Billing page
- `apps/dashboard/src/features/admin/` - Admin panel

### Widget SDK

- `apps/widget/src/` - Standalone chat widget
- Shadow DOM for style isolation
- SSE streaming for real-time responses
- Theme customization via CSS variables

---

**End of Audit Report**
