# WebChat AI — Production Readiness Audit Report

**Date:** August 25, 2026
**Auditor:** Staff Full Stack Engineer + Product Designer
**Scope:** Complete application (Dashboard, Widget SDK, Backend API, Landing Page, Design System)

---

## Executive Summary

WebChat AI is a well-architected multi-tenant SaaS platform for AI-powered website chatbots. The backend is **production-grade** — 108 test files, Protocol-based DI, circuit breakers, rate limiting, and a sophisticated RAG pipeline. The widget SDK is **excellent** — Shadow DOM isolation, WCAG 2.2 AA accessibility, triple-layer XSS defense, and sub-100KB bundle size.

The **primary risks** are in the frontend/dashboard and marketing surfaces: inconsistent design system across three surfaces, missing confirmation dialogs on destructive actions, incomplete legal pages (Privacy/Terms), and placeholder UI for Settings and Widget Config. The chatbot pipeline has several non-atomic operations and dead infrastructure that need attention before scale.

**Code quality is high:** All lint passes, all typecheck passes, 624 frontend tests pass (303 widget + 321 dashboard), and the Python backend uses mypy strict + ruff.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     VISITOR'S WEBSITE                           │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  <script data-widget-id="abc"> (IIFE bundle)            │   │
│  │  └─ <webchat-widget> (closed Shadow DOM)                │   │
│  │     ├─ SessionManager (15-min JWT, memory only)         │   │
│  │     ├─ Conversation (state machine + streaming buffer)  │   │
│  │     ├─ StreamClient (POST + SSE parser)                 │   │
│  │     └─ UI (launcher, window, bubbles, composer)         │   │
│  └────────────────────────────┬────────────────────────────┘   │
└───────────────────────────────┼────────────────────────────────┘
                                │  POST + SSE (text/event-stream)
                                │  Origin allowlist guard
                                │  8 rate limiters per endpoint
┌───────────────────────────────▼────────────────────────────────┐
│                     BACKEND (FastAPI)                           │
│  ┌──────────────────────────────────────────────────────┐     │
│  │  15 API Routers                                       │     │
│  │  ├─ /api/auth/* (register, login, refresh, verify)    │     │
│  │  ├─ /api/websites/* (CRUD + crawl trigger)            │     │
│  │  ├─ /api/chat/* (SSE RAG streaming)                   │     │
│  │  ├─ /api/widget/v1/* (public: config, session, chat)  │     │
│  │  ├─ /api/billing/* (subscription, usage, checkout)    │     │
│  │  ├─ /api/admin/* (super_admin: tenants, users, etc.)  │     │
│  │  └─ /metrics (Prometheus)                             │     │
│  ├──────────────────────────────────────────────────────┤     │
│  │  Services Layer (16 modules)                          │     │
│  │  ├─ AuthService (JWT, Argon2, RBAC, rate limiting)   │     │
│  │  ├─ RagService (23-step pipeline)                     │     │
│  │  ├─ CrawlService (Playwright headless Chromium)       │     │
│  │  ├─ KnowledgeService (chunking, embedding, vector)    │     │
│  │  ├─ WidgetService (session mint, origin guard, spam)  │     │
│  │  └─ BillingService (Stripe + Razorpay abstraction)    │     │
│  ├──────────────────────────────────────────────────────┤     │
│  │  Repositories (21 MongoDB repos + vector/search)      │     │
│  │  ├─ Atlas $vectorSearch (primary)                     │     │
│  │  ├─ Brute-force cosine (fallback)                     │     │
│  │  ├─ Hybrid RRF (vector + keyword)                     │     │
│  │  └─ Cosine reranker (optional)                        │     │
│  └──────────────────────────────────────────────────────┘     │
│  ┌──────────────────────────────────────────────────────┐     │
│  │  AI Provider Chain (with circuit breakers)            │     │
│  │  ├─ Generation: Gemini → Groq → OpenRouter            │     │
│  │  └─ Embedding: Gemini → Jina → Cohere                 │     │
│  └──────────────────────────────────────────────────────┘     │
└──────┬────────────────────┬────────────────────┬───────────────┘
       │                    │                    │
┌──────▼──────┐    ┌───────▼──────┐    ┌───────▼──────┐
│  MongoDB 7  │    │  Redis 7     │    │  ARQ Worker  │
│  (primary)  │    │  (cache +    │    │  (crawl +    │
│  + Atlas    │    │   queue +    │    │   embed +    │
│  Vector     │    │   rate limit)│    │   email)     │
│  Search     │    │              │    │              │
└─────────────┘    └──────────────┘    └──────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     DASHBOARD (Next.js 15)                      │
│  ┌──────────────────────────────────────────────────────┐     │
│  │  16 Feature Modules (Auth, Websites, Knowledge,       │     │
│  │  Conversations, Analytics, Billing, Widget, Admin...)  │     │
│  │  └─ React Query v5 (server state)                     │     │
│  ├──────────────────────────────────────────────────────┤     │
│  │  Auth: Custom JWT (access in memory + refresh cookie) │     │
│  │  UI: shadcn/ui (New York) + Tailwind v4              │     │
│  │  Theme: next-themes (light/dark/system)              │     │
│  └──────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Flows

### 1. User Registration Flow

```
Landing Page → /signup → POST /api/auth/register
  → Creates Tenant + User + Member
  → Sends verification email (via ARQ worker → Resend)
  → Returns access_token (in-memory) + refresh_token (httpOnly cookie)
  → Client redirects to /dashboard
  → AuthProvider calls GET /api/auth/me to load user profile
  → Dashboard renders with OnboardingChecklist
```

### 2. Website + Knowledge Base Flow

```
Dashboard → Add Website (POST /api/websites)
  → Website created with status: "pending"
  → User clicks "Start Crawl" (POST /api/websites/:id/crawl)
  → CrawlJob enqueued in ARQ
  → Worker runs Playwright headless Chromium
  → Pages extracted, cleaned, saved as Documents
  → Worker fans out embedding jobs (per document)
  → Document chunked (500-800 tokens, 100 overlap)
  → Chunks embedded via provider chain (Gemini → Jina → Cohere)
  → Chunks stored in MongoDB with vector embeddings
  → Atlas $vectorSearch index enables retrieval
```

### 3. Chat Request Flow (Widget)

```
Visitor types message
  → Intent check (greeting/thanks → local reply, skip API)
  → POST /api/widget/v1/chat { question, session_id }
    → Origin guard validates allowlist
    → Rate limit check (per-widget, per-visitor, per-IP)
    → Spam filter check
    → Message cap check (50/conversation)
    → RAG Pipeline:
      1. Session resolve
      2. Persist user message
      3. Query rewrite (anaphora detection)
      4. Adaptive classification (SIMPLE/MEDIUM/COMPLEX)
      5. Embed question (cached per normalized text)
      6. Vector search (Atlas $vectorSearch or brute-force)
      7. Optional hybrid/RRF merge
      8. Optional reranking
      9. Confidence gate (pre-generation)
      10. Context build (dedup, compression, budget cap)
      11. Prompt construction (versioned)
      12. Generation streaming (Gemini → Groq → OpenRouter)
      13. Citation validation
      14. Output validation (prompt injection check)
      15. Faithfulness check (optional)
    → SSE events: sources → message deltas → done
  → Widget renders streaming tokens in real-time
  → Conversation state tracked by session_id
```

### 4. Widget Embedding Flow

```
User copies embed code from dashboard:
  <script src="https://cdn.example/webchat-widget.iife.min.js"
          data-widget-id="YOUR_ID" defer></script>

On page load:
  1. IIFE bundle auto-executes
  2. autoUpgrade() reads data-widget-id from currentScript
  3. Creates <webchat-widget> custom element if not present
  4. mount() creates closed Shadow DOM
  5. loadConfig() fetches GET /api/widget/v1/config/:id
  6. Theme applied as CSS custom properties on host
  7. Launcher button rendered in shadow DOM
  8. Session pre-warmed (POST /api/widget/v1/sessions)
  9. Ready for visitor interaction
```

---

## P0 Critical Bugs

### P0-1: Rate Limiter Race Condition (Non-Atomic Check-and-Add)

**Problem:** The sliding window rate limiter performs `zremrangebyscore` → `zadd` → `zcard` as separate Redis commands, not atomically. Two concurrent requests can both see `count <= limit` before either's `zadd` is committed.

**Impact:** Under concurrent load, rate limits can be exceeded. Attackers can exploit this to exceed per-visitor/per-widget budgets.

**Root Cause:** Non-atomic multi-step Redis operation in sliding window implementation.

**File:** `backend/core/rate_limit.py:38-48`

**Recommended Fix:** Use a Redis Lua script to make the check-and-add atomic, or use `MULTI`/`EXEC` pipeline. The Lua script approach is preferred for performance:

```lua
local key = KEYS[1]
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count < limit then
    redis.call('ZADD', key, now, now .. '-' .. math.random())
    redis.call('EXPIRE', key, window)
    return 1
end
return 0
```

---

### P0-2: Subscription Expiry Not Enforced in Database

**Problem:** Subscriptions whose `end_date` has passed remain `active` in MongoDB. The `get_report` method patches this in-memory with `_expired_copy`, but `find_active_by_tenant` still returns expired subscriptions as "active".

**Impact:** Users with expired subscriptions retain plan limits (message caps, document limits) until the next manual read. This is a revenue leak.

**Root Cause:** No background job updates subscription status when `end_date` passes.

**File:** `backend/services/billing/subscription_service.py:133-167`

**Recommended Fix:** Add an ARQ cron job that runs daily to expire subscriptions past their `end_date`, or add a check in `find_active_by_tenant` to filter out expired subscriptions.

---

### P0-3: Redis Connection Leak in Worker Jobs

**Problem:** `_build_cache()` in both `crawl.py` and `knowledge.py` creates a `Redis` instance via `Redis.from_url()` that is never closed. Each crawl/embed job leaks one Redis connection.

**Impact:** Over many crawl jobs, idle Redis connections accumulate, eventually hitting Redis `maxclients` and causing connection failures across the entire system.

**Root Cause:** No cleanup/teardown of the Redis connection after job completion.

**File:** `backend/workers/jobs/crawl.py:58-75`, `backend/workers/jobs/knowledge.py:64-81`

**Recommended Fix:** Use `async with` context manager or add `finally` block to close the connection. Better: use the shared Redis connection from worker startup instead of creating per-job connections.

---

### P0-4: Privacy Policy & Terms Are Incomplete (Legal Risk)

**Problem:** Both privacy policy and terms of service pages contain summary-level text with "full policy will be published before general availability." The product is live and accepting signups.

**Impact:** Legal non-compliance with GDPR, CCPA, and other data protection regulations. Potential lawsuits and App Store/Play Store rejection.

**Root Cause:** Legal documents were never finalized.

**File:** `apps/dashboard/src/app/(marketing)/privacy/page.tsx`, `apps/dashboard/src/app/(marketing)/terms/page.tsx`

**Recommended Fix:** Complete full Privacy Policy and Terms of Service before any production launch. Include data processing details, user rights, deletion procedures, and liability limitations.

---

## P1 High Priority Bugs

### P1-1: Missing Confirmation Dialogs on Destructive Actions

**Problem:** Two destructive, irreversible actions execute immediately on button click with no confirmation:

1. Conversation deletion (`conversations-page.tsx:147`)
2. API key revocation (`api-keys-page.tsx:119`)

**Impact:** Accidental clicks permanently delete conversation history or revoke API keys (breaking integrations).

**File:** `apps/dashboard/src/features/conversations/conversations-page.tsx:147`, `apps/dashboard/src/features/api-keys/api-keys-page.tsx:119`

**Recommended Fix:** Add a confirmation dialog (use the existing `ConfirmDialog` pattern from admin features) before executing destructive mutations.

---

### P1-2: RBAC Editor = Viewer Role Rank

**Problem:** Both `editor` and `viewer` have rank 20, meaning `has_role("viewer", "editor")` returns `True`. A viewer is treated as having editor permissions.

**Impact:** Role-based access control is effectively broken for the editor/viewer distinction. If the intent is editors can edit and viewers can only view, this doesn't work.

**Root Cause:** Identical rank values for distinct roles.

**File:** `backend/core/rbac.py:31-37`

**Recommended Fix:** Give `editor` rank 25 and `viewer` rank 15 (or similar), ensuring editor > viewer in the hierarchy.

---

### P1-3: KnowledgeBadge Component Duplicated

**Problem:** `KnowledgeBadge` is defined twice — once in `features/websites/knowledge-badge.tsx` (canonical) and again inline in `features/knowledge/knowledge-page.tsx:28-39`.

**Impact:** Changes to one copy don't propagate to the other. Visual drift is guaranteed over time.

**File:** `apps/dashboard/src/features/knowledge/knowledge-page.tsx:28-39` (duplicate), `apps/dashboard/src/features/websites/knowledge-badge.tsx:11` (canonical)

**Recommended Fix:** Remove the inline copy from `knowledge-page.tsx` and import the canonical version.

---

### P1-4: SectionHeading Component Duplicated 4 Times

**Problem:** `SectionHeading` is defined in 4 locations: marketing `section-heading.tsx` + private inline copies in `analytics-page.tsx:142`, `billing-page.tsx:36`, and `usage-page.tsx:19`.

**Impact:** Inconsistent section heading styling across dashboard pages. Maintenance burden.

**File:** Multiple feature files as listed above.

**Recommended Fix:** Extract a shared `SectionHeading` component to `components/ui/` and import everywhere.

---

### P1-5: Widget Config Cache Not Invalidated on Tenant Suspension

**Problem:** When a tenant is suspended via admin panel, the widget config cache (`widget_config_cache_seconds` TTL) still shows `enabled: true`. The widget continues functioning for up to the cache TTL after suspension.

**Impact:** A suspended tenant's widget remains operational until the cache expires. Security/compliance gap.

**File:** `backend/services/widget/widget_service.py:171-194`

**Recommended Fix:** Call `invalidate_public_config` when a tenant is suspended/activated via the admin service.

---

### P1-6: RBAC Role Rank Inconsistency — Editor = Viewer

**Problem:** Both `editor` and `viewer` have rank 20 in the RBAC hierarchy.

**Impact:** An `editor` can do everything a `viewer` can and vice versa. There is no permission distinction between the two roles.

**File:** `backend/core/rbac.py:31-37`

**Recommended Fix:** Assign `editor` rank 25 and `viewer` rank 15 (or document that they are intentionally equivalent).

---

### P1-7: Profile Page Uses Raw API Calls Instead of React Query

**Problem:** Profile mutations (`profile-page.tsx:49,57`) use raw `api.post()` calls instead of `useMutation` from React Query. This is inconsistent with every other feature module.

**Impact:** No optimistic updates, no automatic cache invalidation, manual `loading` state instead of `isPending`, inconsistent error handling pattern.

**File:** `apps/dashboard/src/features/profile/profile-page.tsx:49,57`

**Recommended Fix:** Migrate to React Query `useMutation` with `useQueryClient().invalidateQueries()` on success.

---

## P2 Medium Priority Issues

### P2-1: Widget CSS Fallback Accent Color Mismatch

**Problem:** Widget CSS fallback accent is `#4f46e5` (indigo) in `styles.ts:17`, but the shared theme package's `DEFAULT_ACCENT_COLOR` is `#f59e0b` (amber). If `applyTheme` fails, the widget shows indigo instead of amber.

**File:** `apps/widget/src/ui/styles.ts:17` vs `packages/themes/src/index.ts:16`

**Recommended Fix:** Change `--wc-accent: #4f46e5` to `--wc-accent: #f59e0b` in `styles.ts`.

---

### P2-2: Marketing Pages Hardcode `blue-600` Instead of Using `--primary`

**Problem:** Marketing buttons use `bg-blue-600` instead of `bg-primary`. If the brand primary color changes, marketing stays blue while dashboard adapts.

**File:** `apps/dashboard/src/components/marketing/hero.tsx:49`, `navbar.tsx:47`, `pricing.tsx:119`, etc.

**Recommended Fix:** Replace hardcoded `blue-600` with CSS-variable-based `bg-primary` or a shared token.

---

### P2-3: Three Different Dark Mode Palettes

**Problem:** Dashboard uses pure grey (`#0a0a0a`), theme package defaults use slate (`#0f172a`), widget CSS fallback uses gray (`#111827`). Dark mode looks different across surfaces.

**File:** `apps/dashboard/src/app/globals.css:41-65`, `packages/themes/src/index.ts:359-377`, `apps/widget/src/ui/styles.ts:46-58`

**Recommended Fix:** Unify dark mode palette. Pick one neutral scale and apply it everywhere via the `@webchat/themes` package as the single source of truth.

---

### P2-4: Widget Uses System Fonts While Dashboard Uses Geist Sans

**Problem:** Widget uses `-apple-system, BlinkMacSystemFont, ...` while dashboard/marketing use Geist Sans. Visitors see different typography in the widget vs the product.

**File:** `apps/widget/src/ui/styles.ts:23`

**Recommended Fix:** Either load Geist Sans in the widget via `@font-face` or document the system-font choice as intentional (performance-first for visitors).

---

### P2-5: Widget Uses `px` for Base Font Size (Claiming rem/em Resilience)

**Problem:** `styles.ts:7` comments claim "rem/em units for 200%-zoom resilience" but `--wc-font-size-px: 16px` uses absolute `px` units.

**File:** `apps/widget/src/ui/styles.ts:7,22`

**Recommended Fix:** Use `rem` for the base font size to inherit browser zoom scaling.

---

### P2-6: Widget Input Shape (22px Pill) vs Dashboard Input (8px Rounded-md)

**Problem:** Widget input is a fully rounded pill (22px radius) with `color-mix` focus ring. Dashboard input is `rounded-md` (8px) with `ring-1 ring-ring`. Completely different shapes and focus treatments.

**File:** `apps/widget/src/ui/styles.ts:1060-1091` vs `apps/dashboard/src/components/ui/input.tsx`

**Recommended Fix:** Decide on a shared input shape philosophy. The widget's pill shape is appropriate for a chat input; the dashboard's rounded-md is appropriate for form inputs. Document this as intentional if they should differ.

---

### P2-7: Widget Default Border Radius (20px) vs Dashboard (10px)

**Problem:** Widget default `--wc-radius: 20px` is 2× the dashboard default `rounded-lg` (10px). The surfaces look rounder in the widget.

**File:** `apps/widget/src/config/types.ts` (default), `apps/dashboard/src/app/globals.css:32`

**Recommended Fix:** This is likely intentional — the widget should feel softer/more conversational. Document the deliberate divergence.

---

### P2-8: Marketing "Social Proof" Section Has No Actual Social Proof

**Problem:** The section titled "Why teams choose WebChat AI" contains feature blurbs, not actual social proof (logos, testimonials, usage numbers).

**File:** `apps/dashboard/src/components/marketing/social-proof.tsx`

**Recommended Fix:** Replace with actual customer logos, testimonials with names/photos, usage metrics, or star ratings. Until real social proof exists, rename the section to "Why teams choose WebChat AI" and keep it as features, or remove it.

---

### P2-9: Enterprise "Contact Sales" Links to `/signup`

**Problem:** The Enterprise pricing tier CTA says "Contact Sales" but links to the self-serve signup page.

**File:** `apps/dashboard/src/components/marketing/pricing.tsx:53`

**Recommended Fix:** Link to a contact form or `mailto:` address, or create a dedicated enterprise contact page.

---

### P2-10: No Password Strength Indicator

**Problem:** Password fields in signup and profile have no strength meter or requirements shown. Users don't know minimum length until they get a backend error.

**File:** `apps/dashboard/src/features/auth/signup-form.tsx`, `apps/dashboard/src/features/profile/profile-page.tsx:117-128`

**Recommended Fix:** Add a password strength indicator and display requirements (minimum 8 characters, etc.) below the field.

---

### P2-11: Billing Plan Comparison Table Not Responsive

**Problem:** The billing page uses a 4-column `<table>` that overflows on narrow viewports (< 640px). No horizontal scroll wrapper or stacked layout.

**File:** `apps/dashboard/src/features/billing/billing-page.tsx:154-204`

**Recommended Fix:** Add `overflow-x-auto` wrapper or convert to a stacked card layout on mobile.

---

### P2-12: Admin Audit Table Not Responsive

**Problem:** 8-column audit table (`When/Action/Actor/Tenant/User/Plan/IP/User agent`) with no horizontal scroll on mobile.

**File:** `apps/dashboard/src/features/admin/admin-audit-panel.tsx:145-196`

**Recommended Fix:** Add `overflow-x-auto` wrapper for the table container.

---

### P2-13: Session Misplacement Error Message is Misleading

**Problem:** When a session exists but belongs to a different website, the error says "Chat session not found." This confuses debugging.

**File:** `backend/services/chat/rag_service.py:1213-1218`

**Recommended Fix:** Return a specific error like "Session belongs to a different website" with a distinct error code.

---

### P2-14: Embedding Cost Not Tracked in Usage Rollup

**Problem:** The usage rollup records generation tokens/cost but not the embedding API cost for embedding the user's question.

**File:** `backend/services/chat/rag_service.py:985-999`

**Recommended Fix:** Track embedding cost separately in the usage rollup or add it to the `estimated_cost_micros`.

---

### P2-15: No Maximum Content Length on Chat Questions

**Problem:** There's no explicit max-length cap on the `question` field. Megabyte-scale text could be embedded and searched, consuming significant tokens and causing timeouts.

**File:** `backend/schemas/widget.py`, `backend/schemas/chat.py`

**Recommended Fix:** Add `max_length=2000` (matching the widget's frontend limit) to the Pydantic schema.

---

### P2-16: Settings Page is a Placeholder

**Problem:** The Settings page shows "No settings available." but is still in the navigation and accessible to users.

**File:** `apps/dashboard/src/features/settings/settings-page.tsx:10-13`, `apps/dashboard/src/features/layout/nav-items.ts:36`

**Recommended Fix:** Either remove from nav until implemented, or clearly mark as "Coming Soon" with a brief explanation.

---

### P2-17: Widget Config Feature Directory is Empty

**Problem:** `features/widget-config/` contains only `.gitkeep` — no code.

**File:** `apps/dashboard/src/features/widget-config/.gitkeep`

**Recommended Fix:** Remove the empty directory.

---

### P2-18: Widget Setup Wizard vs Widget Editor Duplication

**Problem:** Both `widget-setup-wizard.tsx` (4-step guided flow) and `widget-page.tsx` (full form editor) customize the same `WidgetConfig`. They overlap significantly — a user could customize in either and get confused.

**File:** `apps/dashboard/src/features/widget/widget-setup-wizard.tsx`, `apps/dashboard/src/features/widget/widget-page.tsx`

**Recommended Fix:** Merge into a single widget customization page. Use the wizard for first-time setup (onboarding), then switch to the full editor for ongoing customization. Or clearly separate: wizard = first-time only, editor = always available.

---

## P3 Low Priority Issues

| ID    | Issue                                                                     | File                                                |
| ----- | ------------------------------------------------------------------------- | --------------------------------------------------- |
| P3-1  | Onboarding checklist dismiss only clears localStorage, reappears on clear | `features/dashboard/onboarding-checklist.tsx:30`    |
| P3-2  | Add Website dialog has no name validation (empty/whitespace allowed)      | `features/websites/add-website-dialog.tsx:46`       |
| P3-3  | Knowledge retry has no per-document loading indicator                     | `features/knowledge/knowledge-page.tsx:129`         |
| P3-4  | Admin system health panel has no auto-refresh/polling                     | `features/admin/system-panel.tsx`                   |
| P3-5  | Analytics charts have no error boundary for dynamic import failure        | `features/analytics/analytics-chart.tsx`            |
| P3-6  | Top websites list hard-truncates to 5 without "show more"                 | `features/analytics/analytics-page.tsx:175`         |
| P3-7  | Usage warning threshold (80%) is hardcoded, not configurable              | `features/usage/usage-page.tsx:64`                  |
| P3-8  | Clipboard copy toast has no ARIA live region announcement                 | `features/api-keys/api-keys-page.tsx:56`            |
| P3-9  | Widget domain editor has no format validation                             | Widget editor domain input                          |
| P3-10 | Widget test page has no iframe error handling                             | `features/widget/widget-test-page.tsx`              |
| P3-11 | Conversation detail has no loading/error state                            | `features/conversations/conversation-detail.tsx`    |
| P3-12 | Crawl job `_build_cache` creates unclosed Redis connection                | `backend/workers/jobs/crawl.py:67`                  |
| P3-13 | Dead code: `RagService._load_all_chunks` (documented as dead)             | `backend/services/chat/rag_service.py:1241-1259`    |
| P3-14 | Dead infrastructure: widget session validity window never enforced        | `backend/services/widget/widget_service.py:247-257` |
| P3-15 | `AnalyticsFilters` interface exported but never imported                  | `features/analytics/hooks.ts:39`                    |
| P3-16 | 10 empty `.gitkeep`-only directories across codebase                      | Multiple                                            |
| P3-17 | `sameAs: []` empty in structured data (SEO waste)                         | `components/marketing/structured-data.tsx:44`       |
| P3-18 | Marketing FAQ missing key questions (languages, LLM, data training)       | `components/marketing/faq-section.tsx`              |
| P3-19 | No docs search functionality                                              | `components/marketing/docs-nav.tsx`                 |
| P3-20 | Marketing hardcoded stats in product showcase look fabricated             | `components/marketing/product-showcase.tsx:16-18`   |
| P3-21 | "Theme Presets" listed as an integration (incorrect categorization)       | `components/marketing/integrations.tsx:14`          |
| P3-22 | Crawl job website-not-found path missing audit log                        | `backend/workers/jobs/crawl.py:126-133`             |

---

## UX Problems

### Missing Confirmation Dialogs

- Conversation delete executes immediately
- API key revoke executes immediately
- Both are irreversible actions

### Inconsistent Mutation Patterns

- Profile page uses raw `api.post()` instead of React Query `useMutation`
- Every other feature uses React Query consistently

### Settings Page is a Stub

- Shows "No settings available" but is in the navigation
- Users clicking it will be confused

### Duplicate Widget Customization

- Widget Setup Wizard and Widget Editor both customize the same config
- Users may not know which one "saves"

### No Global Error Boundary

- If root layout providers throw, the entire app crashes with a white screen
- No recovery mechanism

### Missing Loading Differentiation

- No distinction between initial load and background refetch
- Stale data shown during refetches instead of subtle loading indicators

### Mobile Navigation Gaps

- Admin sub-navigation not accessible from mobile nav drawer
- Billing table overflows on narrow screens
- Audit table overflows on narrow screens

### No Password Strength Indicator

- Users don't know password requirements until backend rejects them

### Analytics Charts No Fallback

- Dynamic import of chart library has no error boundary
- Failed import silently hides the chart area

---

## Chatbot Problems

### Rate Limiter Race Condition (P0-1)

- Non-atomic check-and-add allows concurrent requests to exceed limits
- Needs Lua script or pipeline

### Dead Session Validity Infrastructure (P3-14)

- Redis key written for sliding session window but never read back
- No enforcement point exists

### Context Optimizer O(n*m) Performance (Code Smell)

- Seen-sentence comparison becomes quadratic with large knowledge bases
- Could become a latency bottleneck

### No Embedding Cost Tracking (P2-14)

- Generation tokens tracked but not embedding API costs
- Incomplete billing picture

### No Max Question Length (P2-15)

- No explicit cap on question size in API schema
- Widget frontend limits to 2000 chars but API doesn't enforce

### Misleading Session Error (P2-13)

- "Session not found" when session exists but belongs to different website
- Makes debugging harder

### Faithfulness Check Imports `re` Inside Function (Code Smell)

- Module-level `import re` exists but function re-imports it

---

## Authentication Problems

### Strengths (Keep These)

- No token storage in browser storage (memory-only access tokens)
- Atomic refresh token rotation with `findOneAndUpdate`
- Refresh token reuse detection (revokes all sessions + sends alert)
- Constant-time CSRF comparison via `hmac.compare_digest`
- Account lockout after 5 failed attempts (15-minute window)
- JWT purpose separation (access, verify, reset, widget)
- Live state re-validation on every authenticated request

### Weaknesses to Fix

1. **CSRF cookie name hardcoded in client** — `api.ts:32` hardcodes `csrf_token` while backend uses `settings.csrf_cookie_name`. If backend name changes, CSRF silently breaks.
2. **No `SameSite=Strict` on auth cookies** — Both use `SameSite=Lax`. Acceptable with current `path=/api/auth` restriction, but defense-in-depth suggests `Strict`.
3. **Email verification not enforced** — Users can access the full dashboard without verifying email. Design choice but reduces trust.
4. **Access tokens not revocable** — 15-minute window is acceptable but worth noting.
5. **Password reset doesn't invalidate access tokens** — 15-minute bounded window.

---

## Architecture Problems

### 1. Three Inconsistent Design Surfaces

Dashboard (shadcn/ui + Tailwind), Widget (raw CSS + CSS custom properties), Marketing (Tailwind + hardcoded colors) look like different products. No shared design token system.

### 2. Dead/Orphaned Backend Routes

Several backend routes have no frontend callers:

- `/api/analytics/questions`
- `/api/feedback` (list endpoint)
- Various health/metrics endpoints (used by infra, not frontend)

### 3. Worker Connection Management

Each worker job creates its own Redis connection instead of using the shared connection from worker startup. This leads to connection leaks.

### 4. 13-Element Return Tuple in RAG Service

`_retrieve()` returns a 13-element tuple that's unwieldy and error-prone. Should be a dataclass.

### 5. Module-Level Singletons in Workers

Both `crawl.py` and `knowledge.py` maintain separate `_pool` and `_arq_redis()` functions with identical patterns. Should be unified.

### 6. No End-to-End Integration Tests

Backend has 108 test files and widget has 28 E2E tests, but no full-stack integration test that goes from widget → backend → database → response.

### 7. Empty Feature Directory

`features/widget-config/` is empty scaffolding that should be removed.

---

## Design Improvements

### Unified Design System Proposal

| Token         | Current Dashboard | Current Widget           | Proposed Unified                |
| ------------- | ----------------- | ------------------------ | ------------------------------- |
| Primary       | `#2563eb`         | `#2563eb`                | `#2563eb` (keep)                |
| Accent        | `#f59e0b`         | `#4f46e5` (CSS fallback) | `#f59e0b` (fix CSS)             |
| Dark surface  | `#0a0a0a`         | `#111827`                | `#0f172a` (slate-900)           |
| Font          | Geist Sans        | System stack             | Geist Sans (add to widget)      |
| Radius        | 10px (rounded-lg) | 20px (configurable)      | 10px default, widget keeps 20px |
| Input shape   | 8px rounded-md    | 22px pill                | Keep different (form vs chat)   |
| Button height | h-9 (36px)        | 32px circle              | Keep different (form vs chat)   |

### Recommendations

1. **Fix widget CSS accent fallback** to match theme package default
2. **Unify dark mode palette** across all three surfaces
3. **Add Geist Sans to widget** for brand consistency
4. **Replace hardcoded `blue-600`** in marketing with CSS variable approach
5. **Standardize marketing card radii** — pick one radius for all sections
6. **Document intentional divergences** (widget pill input, 20px radius, etc.)

---

## Landing Page Audit

### Conversion Flow Issues

1. No social proof (customer logos, testimonials, usage numbers)
2. Enterprise "Contact Sales" links to self-serve signup
3. No annual pricing toggle (standard SaaS pattern)
4. No video content or interactive demo
5. No "How it works" link in navigation
6. Privacy Policy and Terms are incomplete

### Missing vs. Competitors (Chatbase, Crisp, Botpress)

- No customer logos or testimonials
- No live/interactive demo
- No comparison tables ("vs competitors")
- No blog/content marketing
- No status page
- No docs search
- "Social Proof" section is actually features, not proof

### Strengths

- Clear value proposition in hero
- Good SEO structured data (Organization, SoftwareApplication, FAQPage)
- Clean, accessible markup
- Responsive design
- Well-structured docs with code examples

---

## Code Quality Audit

### Lint/Typecheck/Test Results

| Tool                   | Result                                             |
| ---------------------- | -------------------------------------------------- |
| ESLint (dashboard)     | **PASS** — 0 errors, 0 warnings                    |
| ESLint (widget)        | **PASS** — 0 errors, 0 warnings                    |
| TypeScript (dashboard) | **PASS** — 0 errors                                |
| TypeScript (widget)    | **PASS** — 0 errors                                |
| Vitest (dashboard)     | **PASS** — 41 test files, 321 tests, all pass      |
| Vitest (widget)        | **PASS** — 28 test files, 303 tests, all pass      |
| Ruff (Python)          | **N/A** — `ruff` not installed in this environment |

### Dead Code Found

| Type                         | Count | Examples                                                         |
| ---------------------------- | ----- | ---------------------------------------------------------------- |
| Dead component               | 1     | `components/layout/page-header.tsx` (never imported)             |
| Duplicate components         | 4     | `KnowledgeBadge` (2x), `SectionHeading` (4x)                     |
| Empty feature directory      | 1     | `features/widget-config/`                                        |
| Empty `.gitkeep` directories | 10    | widget src subdirs, backend templates/prompts, dashboard types   |
| Dead exports                 | 1     | `AnalyticsFilters` in analytics hooks                            |
| Orphaned backend routes      | 4+    | analytics/questions, feedback/list, chat/stream (used by widget) |
| Dead service method          | 1     | `RagService._load_all_chunks` (documented as dead)               |

---

## Recommended Implementation Roadmap

### Phase 1: Critical Functionality Fixes (Week 1-2)

**Goal:** Fix production-breaking bugs and security issues

1. **Fix rate limiter race condition** — Convert to Lua script or atomic pipeline
2. **Fix subscription expiry enforcement** — Add cron job or DB-level check
3. **Fix Redis connection leaks in workers** — Use shared connection, add cleanup
4. **Fix RBAC editor/viewer rank** — Differentiate roles
5. **Fix widget config cache invalidation on tenant suspension**
6. **Complete Privacy Policy and Terms of Service** (legal requirement)
7. **Add max_length to chat question schema** (2000 chars)
8. **Fix widget CSS accent color fallback** (`#4f46e5` → `#f59e0b`)

### Phase 2: UX Improvements (Week 3-4)

**Goal:** Eliminate broken states and dangerous flows

1. **Add confirmation dialogs** for conversation delete and API key revoke
2. **Migrate profile mutations to React Query** for consistency
3. **Remove or implement Settings page** (remove from nav if placeholder)
4. **Remove empty `widget-config/` directory**
5. **Merge duplicate `KnowledgeBadge`** — use canonical import
6. **Extract shared `SectionHeading`** component
7. **Add password strength indicator** in signup and profile
8. **Add responsive wrappers** for billing and admin audit tables
9. **Add loading/error states** for conversation detail and widget test
10. **Fix misleading session error message** (different website case)

### Phase 3: Design Polish (Week 5-6)

**Goal:** Unify the three surfaces into one cohesive product

1. **Unify dark mode palette** — pick slate-900, apply everywhere
2. **Add Geist Sans to widget** — `@font-face` or Google Fonts
3. **Replace hardcoded `blue-600`** in marketing with `bg-primary`
4. **Standardize marketing card radii** — pick `rounded-xl` everywhere
5. **Fix widget base font size** to use `rem` instead of `px`
6. **Document intentional design divergences** (widget vs dashboard shapes)

### Phase 4: Production Optimization (Week 7-8)

**Goal:** Performance, monitoring, and completeness

1. **Add global error boundary** around root layout
2. **Add password verification on password change** in profile
3. **Track embedding costs** in usage rollup
4. **Optimize context optimizer** O(n*m) sentence comparison
5. **Add polling** to admin system health panel
6. **Clean up dead code** (dead exports, empty directories, dead service methods)
7. **Add docs search** (Algolia/DocSearch or similar)
8. **Add social proof** to landing page (logos, testimonials, usage metrics)
9. **Complete marketing FAQ** with missing questions
10. **Add annual pricing toggle** to pricing section

---

## Score Summary

| Area                  | Score    | Notes                                                              |
| --------------------- | -------- | ------------------------------------------------------------------ |
| Backend Architecture  | **9/10** | Excellent layered architecture, DI, fallback chains, rate limiting |
| Widget SDK            | **9/10** | Outstanding — Shadow DOM, accessibility, security, streaming       |
| Backend Code Quality  | **8/10** | Clean, well-tested, minor issues (rate limiter, connection leaks)  |
| Frontend Code Quality | **8/10** | Clean, typed, well-tested, minor inconsistencies                   |
| Dashboard UX          | **7/10** | Good structure, missing confirmations, placeholder pages           |
| Design System         | **5/10** | Three inconsistent surfaces, no unified token system               |
| Landing Page          | **6/10** | Clear value prop, missing social proof, incomplete legal           |
| Authentication        | **9/10** | Custom, secure, well-designed with minor improvements needed       |
| Chatbot Pipeline      | **8/10** | Sophisticated RAG, non-atomic rate limiter, good streaming         |
| Testing               | **8/10** | 624 frontend tests, 108 backend test files, no integration tests   |

**Overall Production Readiness: 7.7/10** — The core architecture is excellent. The primary gaps are in design consistency, UX safety (confirmation dialogs), and marketing completeness. With the Phase 1-2 fixes, this could be production-ready.
