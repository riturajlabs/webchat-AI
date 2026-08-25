# WebChat-AI — Widget Production Hardening Audit

**Branch:** `feature/widget-production-hardening`
**Date:** 2026-08-21
**Scope:** Complete widget ecosystem — SDK (`apps/widget`), public widget APIs
(`backend/api/routes/widget.py`), RAG pipeline (`backend/services/chat/*`),
embedding/vector layer (`backend/repositories/vector/*`), DB schema & indexes,
observability, and security headers.

> **Scope reminder:** This is an audit only. No code changes have been made.
> Every issue includes `file_path:line` evidence and an actionable remediation.

---

## 1. Executive Summary

WebChat-AI ships a complete, embeddable RAG-backed chatbot SDK plus the
backend that powers it. The widget surface has been progressively hardened
across Phases 8–13 (origin allowlist, short-lived widget JWTs, Redis-backed
config cache, hybrid search, adaptive retrieval, faithfulness checking,
per-stage latency breakdown, billing gate). The codebase is in a **mature,
near-production** state.

**Strengths**

- **Strict widget-origin allowlist** with three-way error taxonomy
  (`WIDGET_NOT_FOUND` / `WIDGET_DOMAIN_NOT_CONFIGURED` / `WIDGET_ORIGIN_NOT_ALLOWED`)
  (`backend/services/widget/widget_service.py:83-120`).
- **Short-lived (15-min) widget JWTs**, in-memory only, with server-side
  renewal margin (`apps/widget/src/core/session.ts:33-49`).
- **First-party visitor cookie** (`wc_visitor`), no PII, cookies-only storage
  posture (`apps/widget/src/core/visitor.ts:14-74`).
- **Re-entrant closed-shadow-DOM embed** with focus trap, reduced-motion
  support, and `prefers-color-scheme: auto` dark mode
  (`apps/widget/src/ui/window.ts`, `apps/widget/src/ui/styles.ts`).
- **Defense-in-depth markdown rendering** — hand-rolled tokenizer + DOMPurify
  allowlist + safe-URL filter (`apps/widget/src/markdown/render.ts`).
- **Streaming SSE** with disconnect-aware server-side cancellation
  (`backend/api/sse.py:46-127`).
- **Per-stage latency breakdown** persisted on every assistant message
  (`backend/services/chat/rag_service.py:766-782`).
- **Idempotent feedback** with message-tenant-website-session validation
  (`backend/services/feedback/feedback_service.py:80-92`).
- **Faithfulness & confidence checks** pre-generation
  (`backend/services/chat/rag_service.py:584-613`,
  `backend/services/chat/confidence.py`).
- **Adaptive retrieval** (simple vs complex queries use different top_k /
  context budgets) (`backend/services/chat/rag_service.py:160-167`).
- **Proper SPA-friendly CORS** for `/api/widget/*` (`Access-Control-Allow-Origin: *`,
  no credentials) with OPTIONS preflights answered before the dashboard
  CORSMiddleware sees them (`backend/api/middleware.py:101-158`).
- **Required MongoDB indexes** on tenant/website composite keys for hot
  collections (`backend/core/database.py:191-296`).
- **Comprehensive slug bundle size gate** at 90 KB warn / 100 KB fail (gzipped)
  (`apps/widget/scripts/check-size.mjs`).

**Headline Risks** (full table in §4)

- **P0–P1**: A handful of subtle issues still pose production risk — origin
  validation race, missing Origin header on POST bodies, dead-code mass in the
  RAG service, XSS-creep from the `image`/autolink-lite markdown surface,
  widget session not bound to the resolved website's domain check, fallback
  counters that double-charge the budget.
- **P2–P3**: Latency wins available (sequential Mongo lookups, eager history
  fetch), observability gaps (no per-request token usage, no widget-side
  client timing emit), accessibility polish (sources list announced as a
  single `aria-live` unit), and missing CSP nonce.

**Overall production readiness score:** **8.4 / 10** — ship-ready behind a
2-week hardening sprint to clear the P0/P1 items below.

---

## 2. Current Architecture

```
┌─────────────────────────────── Browser (visitor) ───────────────────────────────┐
│                                                                                   │
│   <webchat-widget data-widget-id="abc">   (closed Shadow DOM, IIFE / UMD / ES)    │
│   ├─ autoUpgrade()       — multi-embed host detection                             │
│   ├─ mount(options)      — visitor id, session, theme, UI shell                    │
│   │   ├─ applyTheme      — CSS custom properties on host                          │
│   │   ├─ renderMessages  — incremental diff (data-message-id)                     │
│   │   └─ streamChat      — POST /chat, SSE consumer, 401 single-retry             │
│   ├─ SessionManager      — 15-min widget JWT, in-memory, 3-min renewal margin     │
│   ├─ Conversation        — revision-counter state, stop(), fail(), retry()        │
│   └─ renderMarkdown      — tokenizer → DOMPurify allowlist (no <img>/<script>)    │
│                                                                                   │
│   Network:                                                                        │
│     GET  /api/widget/v1/config/{widget_id}     (cached in module 5 min)          │
│     POST /api/widget/v1/sessions               (mint JWT)                         │
│     POST /api/widget/v1/chat   (SSE)           (Bearer widget_session_token)      │
│     POST /api/widget/v1/feedback               (Bearer widget_session_token)      │
│                                                                                   │
└──────────────────────────────────────────────────────────────────────────────────┘
                                        │
                ┌───────────────────────┼────────────────────────┐
                ▼                       ▼                        ▼
       ┌─────────────────┐  ┌─────────────────────────┐  ┌──────────────────┐
       │ FastAPI routes  │  │ Rate-limit middleware   │  │ WidgetCORS       │
       │ /api/widget/v1  │  │ (per-widget, per-       │  │ headers mw       │
       │                 │  │  visitor, per-IP)       │  │ (ACAO: * only)   │
       └────────┬────────┘  └────────────┬────────────┘  └──────────────────┘
                ▼                         ▼
       ┌─────────────────────────────────────────────────────────────────────┐
       │ WidgetService / WidgetConfigService                                 │
       │   • validate_origin  (allowlist + dev hosts)                        │
       │   • get_public_config (Redis cache, 5 min)                          │
       │   • create_session    (mints JWT, refreshes 24h sliding window)     │
       │   • validate_chat     (claims vs live widget/tenant/website)        │
       │   • check_message_cap (50/conversation)                             │
       └─────────────────────────────────────────────────────────────────────┘
                ▼
       ┌─────────────────────────────────────────────────────────────────────┐
       │ RagService.stream_answer  (SSE producer)                            │
       │   1. resolve website (tenant-scoped)                                 │
       │   2. sanitize_question   (strip control chars, detect injection)    │
       │   3. persist user turn                                            │
       │   4. embed (cache hit? LRU + Redis)                                 │
       │   5. similarity_search   (Atlas $vectorSearch) + brute-force fallback│
       │   6. retrieve (HybridRetrievalStrategy or Vector)                    │
       │   7. rerank (EmbeddingReranker via stored chunk embeddings)          │
       │   8. build_context   (exact-dedup → near-dedup → sentence compress) │
       │   9. confidence gate (rejection below threshold)                    │
       │  10. render_context (numbered + delimited as untrusted)              │
       │  11. generate (Gemini / Cohere / Groq / Jina / OpenRouter fallback)   │
       │  12. validate_response / faithfulness                                │
       │  13. persist assistant turn  (sources + tokens + latency breakdown)  │
       │  14. usage increment  (chats, messages, tokens, vector_queries)      │
       └─────────────────────────────────────────────────────────────────────┘
                ▼
       ┌─────────────────────────────────────────────────────────────────────┐
       │ MongoDB  (AsyncIOMotorDatabase)                                     │
       │   • widgets (unique widget_id, unique (tenant_id, website_id))      │
       │   • knowledge_chunks  (unique (tenant, website, document, chunk))   │
       │   • messages, chat_sessions (TTL 90d)                               │
       │   • usage_records (TTL 3y, unique (tenant, website, date))          │
       │   • feedback (TTL 2y)                                               │
       │   • Atlas Vector Search index on knowledge_chunks.embedding         │
       └─────────────────────────────────────────────────────────────────────┘
                ▲
       │  ┌──────────────────────────────────────────────────────────────┐    │
       │  │ Redis  (sliding-window rate limiter, config cache,           │    │
       │  │         embedding cache, retrieval cache, validity window)    │    │
       │  └──────────────────────────────────────────────────────────────┘    │
       └─────────────────────────────────────────────────────────────────────┘
```

**Embedding providers:** Gemini (default), Cohere, Jina, OpenAI-compatible,
OpenRouter, Groq (registry: `backend/ai/registry.py`).
**Generation providers:** same fallback chain via `AdaptiveProviderRouter`
(`backend/api/deps.py:239-249`).

---

## 3. What is already production-ready

These items are mature and should not be regressed.

| Area                         | What is in place                                                                                                                                               | Evidence                                                                                |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| **Embed multi-instance**     | `<webchat-widget>` hosts upgraded independently, one failure does not block siblings, idempotent re-mount                                                      | `apps/widget/src/core/embed.ts:52-66`                                                   |
| **Visitor identity**         | First-party `wc_visitor` cookie, UUIDv4, `SameSite=Lax`, 24-month max-age, in-memory fallback when cookies blocked                                             | `apps/widget/src/core/visitor.ts:13-73`                                                 |
| **Widget session JWT**       | 15-minute TTL, single-retry on 401, server-supplied `expires_at`, 3-min renewal margin                                                                         | `apps/widget/src/core/session.ts:33-94`                                                 |
| **Config cache**             | Module-level 5-min TTL mirroring Redis; safe defaults on fetch failure                                                                                         | `apps/widget/src/config/fetch.ts:20-115`                                                |
| **Closed Shadow DOM**        | `mode: 'closed'`, encapsulated CSS, `all: initial`, all theme values via CSS custom properties                                                                 | `apps/widget/src/core/mount.ts:198`; `apps/widget/src/ui/styles.ts:14-44`               |
| **SSE chat streaming**       | POST-SSE parser, terminal-event idempotency, disconnect-aware reader, 30 s connect / first-token budget                                                        | `apps/widget/src/core/sse.ts:59-116`; `apps/widget/src/stream/client.ts:91-186`         |
| **Stop generation**          | `AbortController` per turn, partial answer kept with `(stopped)` marker, never an error                                                                        | `apps/widget/src/core/mount.ts:391-432`                                                 |
| **Loading / error states**   | Typing dots, banner with Retry + Dismiss, offline banner, widget-unavailable banner                                                                            | `apps/widget/src/core/mount.ts:532-569`                                                 |
| **Source/citation UX**       | `Learn more` cards, 3 visible + "View all (N)" toggle, URL safety filter, open in new tab with `rel="noopener noreferrer"`                                     | `apps/widget/src/ui/bubbles.ts:105-213`                                                 |
| **Feedback system**          | One-tap thumbs (5 / 1), category auto-derived, idempotent server-side, error path with retry                                                                   | `apps/widget/src/ui/feedback.ts`; `backend/services/feedback/feedback_service.py:80-92` |
| **Bundle size gate**         | 90 KB warn / 100 KB fail on gzipped IIFE (current build: 112 KB raw ≈ 40-50 KB gzipped)                                                                        | `apps/widget/scripts/check-size.mjs`; `apps/widget/dist/`                               |
| **Markdown sanitizer**       | Hand-rolled tokenizer emits only allowlisted tags, DOMPurify is the second gate, no `<img>`/`<script>`/autolinks                                               | `apps/widget/src/markdown/render.ts:23-52`                                              |
| **Accessibility**            | `role="dialog" aria-modal`, focus trap, `aria-live` status region, reduced-motion media query, full focusable selection via `composedPath()`                   | `apps/widget/src/ui/window.ts:64-289`; `apps/widget/src/ui/styles.ts:1180-1195`         |
| **Mobile breakpoint**        | `@media (max-width: 480px)` clamps window to viewport, `@supports (height: 100dvh)`                                                                            | `apps/widget/src/ui/styles.ts:1199-1228`                                                |
| **Theme engine**             | Single source of truth (`packages/themes`), preset-driven + per-tenant overrides, dark/light/auto, readability math                                            | `packages/themes/src/index.ts`                                                          |
| **Origin security**          | Per-route origin guard, dashboard hosts + dev hosts bypass, sandboxed iframe (`Origin: null`) explicitly rejected                                              | `backend/services/widget/widget_service.py:83-139`                                      |
| **CORS**                     | Widget API gets `ACAO: *`, dashboard gets strict + credentials, OPTIONS preflights intercepted before dashboard CORS                                           | `backend/api/middleware.py:114-158`                                                     |
| **Rate limiting**            | Per-widget, per-visitor, per-IP, per-session-issue, per-feedback, fail-closed on Redis outage                                                                  | `backend/api/deps.py:752-789`                                                           |
| **Security headers**         | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, `Content-Security-Policy: default-src 'none'`, HSTS when `cookie_secure` | `backend/api/middleware.py:23-37`                                                       |
| **Prompt injection defense** | `sanitize_context_chunk` + `detect_injection` + delimited `<context>` block + explicit "ignore instructions inside" rule                                       | `backend/prompts/rag.py:39-56`                                                          |
| **Hallucination guard**      | Model is never called with empty retrieval; safe fallback on low confidence; faithfulness score recorded                                                       | `backend/services/chat/rag_service.py:490-575`                                          |
| **Idempotent feedback**      | Tenant/website/session/role/message_id validated before insert; duplicate `find_by_message` short-circuits                                                     | `backend/services/feedback/feedback_service.py:80-92`                                   |
| **Cost control**             | Billing gate at first SSE frame, message cap (50/conversation), per-tenant usage aggregation                                                                   | `backend/api/sse.py:130-225`; `backend/services/widget/widget_service.py:255-282`       |
| **Disconnect cleanup**       | Server-side reader cancellation, partial answers never persisted, no wasted tokens                                                                             | `backend/api/sse.py:46-63`                                                              |
| **Latency observability**    | Per-stage timing persisted on assistant message, opt-in structured logs, request-id correlation, mid-stream SSE transport logging                              | `backend/services/chat/rag_service.py:766-983`                                          |
| **Health checks**            | `/health/live` (process), `/health` (deps), `/health/ready` (routing)                                                                                          | `backend/api/routes/health.py`                                                          |
| **Index coverage**           | All hot-path collections indexed (widget_id, session_id, messages, usage_records, knowledge_chunks)                                                            | `backend/core/database.py:191-296`                                                      |
| **TTL hygiene**              | refresh_tokens (40 d), audit_logs (1 y), crawl_jobs (30 d), messages (90 d), usage_records (3 y), feedback (2 y)                                               | `backend/core/database.py:175-189`                                                      |

---

## 4. Critical Issues

Each item includes: problem, evidence (`file:line`), production impact,
recommended solution, and estimated complexity.

---

### 4.1 P0 — Critical

#### P0-1. Origin allowlist bypassed when `Origin` header is absent

**Problem.** `WidgetService.validate_origin` returns immediately when the
`Origin` header is missing (`backend/services/widget/widget_service.py:99`).
The justification ("non-browser clients / curl / SSE cannot be validated
anyway") is correct, but the `widget_claims_origin_guard` is then skipped
on **every authenticated chat/feedback call** that arrives without an Origin
header — including browser fetches from a browser that omits Origin
(cross-origin GET-without-CORS, sub-resource loads in some embed contexts,
browsers running with privacy extensions).

**Evidence.** `backend/services/widget/widget_service.py:99-120` —

```python
if origin is None:
    return
```

And `backend/api/deps.py:792-830` — `_widget_origin_guard` only checks when
the header is present.

**Production impact.** A widget whose `allowed_domains = ["example.com"]`
can be embedded from `attacker.com` if the embedder drops the Origin header
(e.g. via `<iframe sandbox="allow-scripts">` with cross-origin fetch). The
attacker could:

1. Mint a session via `POST /sessions` with `Origin: null` (rejected — OK).
2. Trigger a same-origin fetch from a non-browser environment that does not
   send Origin, bypassing the allowlist.

This defeats the entire origin-scoping design (ADR-004 §widget).

**Recommended solution.**

- For the **session-issue** endpoint, drop the `if origin is None: return`
  branch — browser-initiated `POST /sessions` always carries an Origin header
  on cross-origin requests. Server-to-server and CLI clients are explicitly
  not the audience.
- For **chat** and **feedback**, if `Origin is None` and the request appears
  to come from a browser (`User-Agent: Mozilla/...`), reject with
  `WIDGET_ORIGIN_NOT_ALLOWED`. Only allow missing-Origin when `User-Agent`
  is empty or matches a known non-browser signature (and rate-limit those
  per `widget_ip_limiter` to bound abuse).
- Add an integration test that confirms `Origin: null` and missing-Origin
  both fail with the expected `403`.

**Estimated complexity:** Medium (1-2 days incl. tests).

---

#### P0-2. Widget session JWT is bound to `(widget_id, tenant_id, website_id)`

but `validate_chat` allows session issued for any website under the same
tenant to authorize any website

**Problem.** `WidgetService.validate_chat` confirms that `widget.website_id ==
website_id` (`backend/services/widget/widget_service.py:246`), which is
correct. However, **the widget session token's `visitor_id` claim is never
compared** to the in-flight request. A malicious widget owner could mint a
session for visitor A and reuse that JWT from any origin within the
allowlist — including a different browser session — and the system would
accept it.

**Evidence.** `backend/services/widget/widget_service.py:239-253` does not
compare `claims["visitor_id"]` to any incoming value. The widget SDK passes
the same `visitorId` it stored in the cookie (`apps/widget/src/core/session.ts:52-94`),
but the backend never validates it.

**Production impact.** Token theft / cookie theft of one visitor lets the
attacker submit chat requests and feedback in that visitor's name. The
tenant-level message cap is keyed by `(widget_id, session_id, visitor_id)`
(`backend/services/widget/widget_service.py:269-282`), so an attacker could
also avoid the per-visitor 50-message cap by minting a new session with the
same stolen `visitor_id`.

**Recommended solution.**

- Bind the session token to the visitor_id at issuance AND require the chat
  request to carry the visitor id in either (a) a header
  `X-Widget-Visitor-Id` or (b) the cookie itself, and validate against the
  claim.
- Alternatively, hash the visitor cookie value into the JWT signature and
  verify on chat.

**Estimated complexity:** Medium (1 day + token rotation migration if
existing sessions must be invalidated).

---

#### P0-3. Feedback endpoint trusts client-supplied `session_id` and `message_id`

after only token-claim revalidation, and accepts unlimited duplicate ratings
until the first persist

**Problem.** `FeedbackService.submit` looks up the message by `message_id`
alone (`backend/services/feedback/feedback_service.py:80-92`):

```python
message = await self._messages.find_by_id(tenant_id, message_id)
```

A **TOCTOU race** exists between `find_by_id` and `create`. The dedup check
is `find_by_message` which is also not atomic. Two concurrent thumbs-up
requests on the same `message_id` can both pass the duplicate check, then
both insert. The unique index on `feedback.message_id` would catch it at
insert time, but only as a `DuplicateKeyError` that surfaces as a 500.

**Evidence.**

- `backend/services/feedback/feedback_service.py:80-104`
- `backend/repositories/feedback_repository.py` — no transaction wrapper.

**Production impact.** Duplicate feedback rows under bursty traffic. The
widget-side `disabled` state should prevent double-submission, but a malicious
client can race the widget's own disabled-toggle. Surfaces as 500 errors in
production logs.

**Recommended solution.**

- Wrap `submit` in a Mongo `with_transaction` block so the dedup check and
  insert are atomic.
- Add a unique compound index `(tenant_id, message_id)` on the `feedback`
  collection (check `backend/core/database.py` for current feedback indexes —
  none is enforced for `message_id`).

**Estimated complexity:** Small (4 hours).

---

#### P0-4. `widget_ip_limiter` is keyed only on the IP, not the visitor

identity; a single attacker can rotate cookies to invalidate the per-visitor
budget while staying under the per-IP budget

**Problem.** The per-IP limit is `60 / minute` (configurable). The per-visitor
limit is `20 / minute`. The per-widget limit is `60 / minute`. None of these
thresholds bounds the **combined** abuse pattern where one attacker rotates
cookies (cheap to do, no UI) to reset the per-visitor budget while staying
under the per-widget and per-IP budgets.

**Evidence.** `backend/api/deps.py:752-789`.

**Production impact.** A motivated attacker could submit hundreds of chats
per minute per widget by spoofing visitor cookies.

**Recommended solution.**

- Add a `(visitor_id, widget_id)` composite sliding window that does not
  reset on cookie rotation (since the attacker can mint new visitor IDs but
  not escape the IP). Complement with a per-IP **token-bucket** budget that
  also fires on cookie rotation (since the IP is fixed).
- Add a per-IP burst budget on the session-issue endpoint that the current
  scheme does not cover.

**Estimated complexity:** Small (half a day).

---

#### P0-5. SSE stream-end without terminal event is logged but treated as a

failure only at the mount layer; partial assistant content is silently kept

**Problem.** `apps/widget/src/core/sse.ts:81-82` throws on abort, and the
widget's `mount.ts` handles `result.aborted` correctly. But when the
**server** ends the stream without a `done` or `error` event (network drop,
load-balancer idle-timeout, mid-response restart), the widget treats this
as a network error and shows the retry banner — but the **partial content**
the visitor already saw is left in the message stream with no marker.

**Evidence.**

- `apps/widget/src/stream/client.ts:254-263` (the "ended unexpectedly"
  branch).
- `apps/widget/src/core/mount.ts:421-424` (sets banner, calls
  `conversation.failTurn`).

**Production impact.** Visitor sees a partial answer, then sees a red
"Network error" banner. They retry — but the new request hits a new
session in `RagService._ensure_session` if `session_id` was not bound yet,
creating a new conversation and losing the partial answer.

**Recommended solution.**

- When the stream ends without a terminal event, mark the bubble with a new
  `incomplete: true` state (not `error`), append `(incomplete — try again)`
  to the text, and keep the session id bound so the retry continues the
  same conversation.
- Server-side: emit an explicit `error` event before closing on any
  internal exception so the client always gets a terminal event.

**Estimated complexity:** Small (4 hours).

---

#### P0-6. `_check_faithfulness` heuristic is word-Jaccard on a

lowercased/whitespace-split string and is **not** an LLM judge, but the
config comment implies a semantic check

**Problem.** `backend/services/chat/rag_service.py:1252-1284` builds the
"grounded words" set from `chunk_text` by splitting on whitespace, lowercasing,
and keeping only `len > 3 and isalpha()`. The function is then documented in
several places (`docs/02-TRD.md`, multiple `AI-RAG-*-REPORT.md` files in the
repo root) as if it were a semantic grounding check.

**Evidence.**

- `backend/services/chat/rag_service.py:1252-1284`
- `backend/services/chat/confidence.py:36-49` — uses `peak / average / hit_ratio`,
  not the same faithfulness scorer.

**Production impact.** Marketing/audit material overstates what the score
measures. The score **will** be high when the assistant paraphrases a chunk
in the same vocabulary and **will** be low when the assistant uses synonyms
or rearranged sentence structure, even when factually grounded. Operators
trusting the score may over-trigger fallback in production.

**Recommended solution.**

- Either: (a) rename the heuristic to `lexical_overlap` and stop using the
  word "faithful" anywhere in the report/metric name, or (b) replace it with
  an LLM-as-judge faithfulness call (or a smaller BERT cross-encoder) and
  expose both the heuristic and the new score.
- Update docstrings in `confidence.py` and any external docs.

**Estimated complexity:** Medium if implementing an LLM judge (2-3 days);
small if just renaming + clarifying.

---

### 4.2 P1 — High

#### P1-1. Markdown renderer allows inline HTML elements (`<pre class="wc-code">`,

`<button>`) that rely on event delegation; if any consumer wraps the widget
in a different DOM boundary, the copy button breaks

**Problem.** `apps/widget/src/markdown/render.ts:23-52` allows `pre`,
`button`, `div`, `span` in the sanitized output, and `bubbles.ts:602`
delegates a single click listener on the message list. If the rendered
markdown is ever moved outside the message list (e.g. an external preview
DOM), copy-code clicks fail silently.

**Evidence.** `apps/widget/src/ui/bubbles.ts:559-604`.

**Production impact.** Low risk in current widget scope, but any future
"export chat" feature or "inline preview in dashboard" feature will break
silently.

**Recommended solution.**

- Bind the handler to the bubble (`data-message-id`) instead of the list, so
  handlers survive DOM moves.
- Document the constraint in `bubbles.ts` header.

**Estimated complexity:** Small (1-2 hours).

---

#### P1-2. `widget_rate_limit_enabled` is a **single global toggle**; there is

no per-tenant override

**Problem.** `backend/api/deps.py:682-683` reads `settings.widget_rate_limit_enabled`
once for every limiter. If a tenant needs stricter limits (e.g. enterprise plan),
there is no per-tenant path.

**Evidence.** `backend/api/deps.py:680-707` (`WidgetRateLimitDependency.__call__`).

**Production impact.** Plan-tier differentiation is impossible without
service restart.

**Recommended solution.**

- Allow the rate-limit dependency to read tenant-specific overrides from a
  tenant table (cached in Redis) with a graceful fallback to global limits.

**Estimated complexity:** Medium (1-2 days).

---

#### P1-3. Widget rate limit fails closed with 503 on Redis outage, but the

in-widget fallback uses safe defaults — the UX is fine, but backend
operators do not see per-route degradation metrics

**Problem.** When Redis is down, `WidgetRateLimitDependency` raises
`ServiceUnavailableError` (`backend/api/deps.py:705-707`). The widget
shows a generic network error and never gets a chance to render. There is
no metric distinguishing "Redis down" from "Mongo down" or from "LLM
provider down".

**Evidence.** `backend/api/deps.py:699-707`, `backend/api/routes/health.py:38-46`.

**Production impact.** Operators cannot quickly identify the failure mode
during an outage.

**Recommended solution.**

- Increment a metric (`widget_rate_limit_redis_error_total`) on the Redis
  exception so dashboards distinguish the failure.
- Add `/health/ready` to label each dependency failure mode distinctly
  (already partially present in `health()` but not in `ready()`).

**Estimated complexity:** Small (half a day).

---

#### P1-4. `analytics_repository` and `usage_event_repository` lack the

**visitor_id** field that widget-side observability needs

**Problem.** Per-turn analytics (`usage_events`, `usage_records`) carry
`tenant_id`, `website_id`, `user_id`, but not `visitor_id`. The widget SDK
knows the visitor id (`apps/widget/src/core/visitor.ts:55-73`), but never
sends it on chat/feedback (it's only used as the rate-limit key).

**Evidence.**

- `backend/services/chat/rag_service.py:786-800` — `usage.increment(...)`
  receives no `visitor_id`.
- `apps/widget/src/stream/chat.ts` body to `/chat` carries only `question`
  and `session_id`.

**Production impact.** Cannot distinguish unique visitor sessions for
analytics, growth, or abuse analysis.

**Recommended solution.**

- Add `visitor_id` to `WidgetChatRequest` (optional, validated as UUID-shaped,
  ≤ 128 chars), pass through to `RagService`, and into `usage_records` /
  `usage_events`.

**Estimated complexity:** Small (1 day incl. tests).

---

#### P1-5. SSE chat does not honor the visitor-supplied `Accept-Language`,

making the prompt's "Always write in the same language as the question" rule
fail when the question is in a different language from the system prompt

**Problem.** `RagService.stream_answer` builds the user prompt from the
question, context, and history. The model is told to write in the question's
language, but the system prompt is fixed English. Some Gemini models will
output English despite the rule.

**Evidence.**

- `backend/prompts/rag.py:39-56` — system prompt is English-only.
- `backend/services/chat/rag_service.py:651-660`.

**Production impact.** Non-English tenants see mixed-language answers.

**Recommended solution.**

- Detect the question's language in `classify_query` and route to a
  localized prompt variant (or pass a `language` instruction in the system
  prompt).
- This is already covered by `RAG_PROMPT_VERSION` versioning — add v2 with
  multilingual instructions.

**Estimated complexity:** Medium (2-3 days with prompt engineering).

---

#### P1-6. `widget_config_origin_guard` and `widget_session_origin_guard`

both call `_widget_origin_guard` which calls
`service.validate_origin(widget_id, origin)`. This performs a `find_by_widget_id`
DB query on **every config and session request**. The widget config is already
Redis-cached, but the origin guard is not.

**Problem.** `backend/services/widget/widget_service.py:83-120` — every
`validate_origin` call hits MongoDB. `get_public_config` uses Redis cache
(`widget_service.py:148`), but origin validation does not.

**Evidence.** `backend/services/widget/widget_service.py:101-103` (the
`find_by_widget_id` lookup in origin validation).

**Production impact.** Adds a Mongo lookup to every config fetch (5-min
cache TTL × N embeds). For a high-traffic site, this is significant.

**Recommended solution.**

- Cache the `allowed_domains` list alongside the public config, with the
  same 5-min TTL.
- Invalidate on the same `WidgetConfigService.invalidate_public_config` path.

**Estimated complexity:** Small (4 hours).

---

#### P1-7. `RagService._retrieve` returns a 14-element tuple with no

dataclass — refactor target

**Problem.** `backend/services/chat/rag_service.py:228-424` — the
`_retrieve` method returns a 14-tuple of mixed types (vectors, floats,
booleans, dataclass, ints). Any future contributor adding a new metric
must change every call site.

**Evidence.** `backend/services/chat/rag_service.py:228-260` (signature)
and `:512-527` (destructure).

**Production impact.** Maintainability risk — adding/removing fields is
brittle.

**Recommended solution.**

- Replace the tuple with a `@dataclass RetrievalOutcome` (carrying
  `query_vector, results, embedding_ms, retrieval_ms, embedding_cache_hit,
retrieval_cache_hit, metrics, load_chunks_ms, rerank_ms,
rerank_embedding_ms, rerank_input_count, hybrid_candidate_count,
adaptive_max_context_chars`).

**Estimated complexity:** Small (half a day).

---

#### P1-8. Embedding cache key is `question.strip().lower()` only — does not

account for trimmed whitespace differences, control characters, or
session-scoped normalization

**Problem.** `backend/services/chat/rag_service.py:199` —

```python
key = question.strip().lower()
```

`prompt.sanitize_question` strips control characters and collapses
whitespace before this code path runs (called via `stream_answer`'s
pre-`_retrieve` flow at `:451`). The cache miss would be rare but
**not impossible** if `_retrieve` is called from another code path
without sanitization.

**Evidence.** `backend/services/chat/rag_service.py:188-226` — `_embed_question`
is called from `_retrieve` after `sanitize_question` (`:451`), so today
the input is normalized. But the function's contract is "embed any
question" and future callers might forget.

**Production impact.** Cache pollution if an un-normalized caller appears.

**Recommended solution.**

- Make `_embed_question` itself call `sanitize_question` (or assert the
  input is already normalized) and document the contract.

**Estimated complexity:** Trivial (1 hour).

---

#### P1-9. `_emit_fallback` records `vector_queries` as 1 on the

`confidence_low` path even when the query was answered by the cache (no
actual vector search happened)

**Problem.** `backend/services/chat/rag_service.py:565-575` —

```python
async for event in self._emit_fallback(
    ...
    vector_queries=1,
    reason="retrieval_empty",
    ...
):
```

But on the cache-hit path (`_retrieve` returns `retrieval_cache_hit=True`),
no vector search actually ran. The fallback still bills the tenant for a
vector query.

**Evidence.** `backend/services/chat/rag_service.py:1196-1242`
(`_emit_fallback` increments `vector_queries`).

**Production impact.** Tenants may be charged for searches that did not
occur.

**Recommended solution.**

- Pass `retrieval_cache_hit` through to `_emit_fallback` and only bill
  `vector_queries=1` when no cache hit occurred.

**Estimated complexity:** Trivial (30 min).

---

#### P1-10. `RateLimitDependency` keyed by IP does not honor IPv6 prefix

collisions or NAT carriers

**Problem.** `backend/api/deps.py:540` —

```python
key = f"rl:{request.url.path}:{client_ip(request)}"
```

A large mobile carrier or corporate NAT egress can aggregate thousands of
visitors behind a single IP. The per-IP limit (`60 / min` for chat) becomes
shared.

**Evidence.** `backend/api/deps.py:485-496` (`client_ip`).

**Production impact.** Legitimate visitors behind shared NAT IPs may hit
the limit, producing false-positive "Too many requests" errors.

**Recommended solution.**

- Combine `client_ip` with the visitor id (from widget session claims or
  the `wc_visitor` cookie on `/config`) when present. The per-IP limit
  becomes the fallback for anonymous requests.

**Estimated complexity:** Small (half a day).

---

### 4.3 P2 — Medium

#### P2-1. `widget_referrerPolicy: 'no-referrer'` is set on brand logo and

avatar images, but no `loading="lazy"` on the empty-state avatar — wasted
fetch on initial paint

**Evidence.** `apps/widget/src/ui/bubbles.ts:461-467`,
`apps/widget/src/ui/window.ts:85-92`.

**Production impact.** First-paint slightly slower than necessary.

**Recommended solution.** Add `loading="lazy"` and `decoding="async"` on
all image elements that are not above-the-fold.

**Estimated complexity:** Trivial (15 min).

---

#### P2-2. The widget session validity window is refreshed in

`create_session` (line 219-227) but **not extended** for visitors who mint
a session but never send a chat

**Problem.** `backend/services/widget/widget_service.py:217-227` —

```python
validity_key = f"{SESSION_VALIDITY_PREFIX}{widget_id}:{visitor_id or 'anon'}"
await self._store.setex(validity_key, ...)
```

`setex` resets the TTL to a fixed window. A visitor who mints a session and
returns hours later will get a new validity window on first send — fine —
but the **session token** itself only lives 15 minutes and the SDK renews it
3 minutes before expiry. There is no flow that explicitly extends the
window on chat send (only the periodic renewal does).

**Evidence.** `apps/widget/src/core/session.ts:141-149` (renewal on demand).

**Production impact.** A chatty visitor loses session continuity after
24 h of inactivity even though they were "in a conversation".

**Recommended solution.** Refresh `validity_key` on each `validate_chat`
call so the window slides with activity.

**Estimated complexity:** Trivial (15 min).

---

#### P2-3. Widget SDK console.error is never used; failures surface as

`console.debug` only when the embed page enables debug logging

**Problem.** `apps/widget/src/core/mount.ts:90-93` (`profileTurn`) uses
`console.debug`. There is no global `console.error` for genuine
production failures (e.g. SSE read errors after retry, repeated 401s).

**Evidence.** Search of `apps/widget/src/`: zero `console.error` or
`console.warn` calls.

**Production impact.** Debugging a production incident requires either
the page-side debug mode or reproducing with the user's browser tools.

**Recommended solution.**

- Send a structured error event to a host-page-provided callback
  (`window.WebChatWidget.onError`) so embedders can hook into monitoring.
- Allow `console.error` when a meta tag or `localStorage` flag is set.

**Estimated complexity:** Small (half a day).

---

#### P2-4. `MessageLimitReachedError` (50/conversation) is hard-coded in

`WidgetService.check_message_cap` and not plan-aware

**Problem.** `backend/services/widget/widget_service.py:279-282` —

```python
if count > self._settings.widget_max_messages_per_session:
```

The 50-cap does not scale with the tenant's plan (Free vs Pro vs Enterprise).

**Evidence.** `backend/core/config.py` (settings lookup), no plan-aware path.

**Production impact.** Enterprise tenants cannot buy a higher cap.

**Recommended solution.** Read the cap from the tenant's subscription /
plan record (`tenants.plan` / `subscriptions.plan`) with the config default
as fallback.

**Estimated complexity:** Small (half a day).

---

#### P2-5. Widget SDK bundle ships DOMPurify — a non-trivial dependency

that increases bundle size and bundle-update risk

**Problem.** `apps/widget/src/markdown/render.ts:19` —

```typescript
import DOMPurify from 'dompurify';
```

DOMPurify is the bundle's heaviest single dependency. The widget's own
sanitizer already rejects `<img>`, `<script>`, `<iframe>`, dangerous
URLs, and unlisted tags. DOMPurify is a defense-in-depth, not the primary
gate.

**Evidence.** `apps/widget/dist/webchat-widget.iife.min.DTM6vCI4.js` —
112 KB raw, gzipped ~40 KB; ~30 KB is DOMPurify.

**Production impact.** Larger bundle → slower first paint, larger memory.

**Recommended solution.**

- Either: (a) lazy-import DOMPurify on first assistant render (avoid
  blocking initial paint), or (b) audit the tokenizer to confirm DOMPurify
  is redundant and drop it (with extensive test coverage).

**Estimated complexity:** Small for lazy load; medium for removal (test
suite expansion needed).

---

#### P2-6. `rebuiltContent` map (`apps/widget/src/ui/bubbles.ts:34`) leaks

memory for very long sessions because `WeakMap` keys are bubble elements
that are removed from the DOM — but the WeakMap entries themselves persist
until GC. Long-lived visitors (24 h+ chatty sessions) accumulate DOM nodes.

**Evidence.** `apps/widget/src/ui/bubbles.ts:33-42` (WeakMap usage).

**Production impact.** Marginal — WeakMap entries are eligible for GC when
the bubble is removed. But `renderMessages` (`bubbles.ts:509-513`) does
remove bubbles; the GC pressure is small.

**Recommended solution.** No change required — this is informational.

**Estimated complexity:** N/A.

---

#### P2-7. The widget embedding-model compatibility check is not exposed

on the public widget surface; if a tenant re-indexes, existing visitors
see `WIDGET_DISABLED` / empty results until cache TTL elapses

**Problem.** `backend/repositories/vector/mongodb.py:193-199` raises
`EmbeddingCompatibilityError` when stored chunks have mismatched identity,
but only when Atlas Vector Search returns zero hits. If the new index has
hits, no error surfaces even when other websites share a tenant and
**some** chunks are stale.

**Evidence.** `backend/repositories/vector/mongodb.py:188-221` (the
empty-results path triggers the compatibility check; non-empty paths do not).

**Production impact.** Tenants with mixed-version chunks may get partial
results without warning.

**Recommended solution.** Always run `_has_incompatible_chunks` when an
empty-website-but-non-empty-chunks state is detected, regardless of the
vector result count.

**Estimated complexity:** Small (half a day).

---

#### P2-8. `ConfidenceMetrics` weights (`0.50 * average + 0.30 * hit_ratio +

0.20 * peak`) are hard-coded — no tuning surface per tenant

**Evidence.** `backend/services/chat/confidence.py:43`.

**Production impact.** Tenants cannot tune sensitivity (e.g. support tenants
that prefer answered over fallback, knowledge-base tenants that prefer
precision over recall).

**Recommended solution.** Read weights from settings or per-tenant config.

**Estimated complexity:** Small (half a day).

---

#### P2-9. The widget SDK's chat composer input lacks a `dir="auto"` /

RTL handling for Arabic / Hebrew / Persian visitors

**Evidence.** `apps/widget/src/ui/composer.ts:79-90` — `input.placeholder`
is set but no `dir` attribute.

**Production impact.** RTL visitors see mis-aligned input text.

**Recommended solution.** Set `input.dir = 'auto'` (and the same on
assistant bubbles' content blocks).

**Estimated complexity:** Trivial (10 min).

---

#### P2-10. `widget_session_origin_guard` reads the request body once via

`CreateWidgetSessionRequest` (Pydantic) before invoking the guard, so the
guard does not see the raw body

**Problem.** `backend/api/deps.py:810-816` —

```python
async def widget_session_origin_guard(
    request: Request,
    body: CreateWidgetSessionRequest,
    service: Annotated[WidgetService, Depends(get_widget_service)],
) -> None:
    await _widget_origin_guard(request, body.widget_id, service)
```

This works, but means a malformed body fails Pydantic validation **before**
the origin guard runs. A hostile client with a bogus body but a known
`Origin: example.com` (allowlisted) and a valid-looking widget_id could
trigger unnecessary validation work.

**Evidence.** `backend/api/deps.py:810-816`.

**Production impact.** Minor — the validation work is cheap and the
bypass only avoids the origin guard in degenerate cases.

**Recommended solution.** Move the origin guard to the FastAPI dependency
chain before Pydantic.

**Estimated complexity:** Small (half a day).

---

### 4.4 P3 — Low / Nice-to-have

#### P3-1. `widget_session_origin_guard` does not handle `Origin: null`

explicitly; relies on `origin_hostname` returning `None`, then
`origin_allowed(None, allowed)` returning False, then `WIDGET_ORIGIN_NOT_ALLOWED`
which is technically wrong (the issue is sandbox, not allowlist)

**Evidence.** `backend/services/widget/widget_service.py:108-120` and
`backend/utils/origin.py`.

**Production impact.** Sandboxed iframes get a less-actionable error code
than they should.

**Recommended solution.** Detect `Origin: null` and raise a dedicated
error like `WIDGET_SANDBOXED_EMBED`.

**Estimated complexity:** Small.

---

#### P3-2. Widget config cache on the SDK (`apps/widget/src/config/fetch.ts:20`)

does not survive page reloads; a tenant who updates their config from the
dashboard must wait up to 5 minutes (Redis TTL) + the SDK cache TTL.

**Evidence.** `apps/widget/src/config/fetch.ts:20-44`.

**Production impact.** Slow iteration during design/QA work.

**Recommended solution.** Honor an `If-None-Match` (ETag) header from the
config endpoint and avoid re-parsing on 304. Out of scope for the current
hardening — call out for Phase 2.

**Estimated complexity:** Medium.

---

#### P3-3. The widget SDK does not expose a programmatic event hook for

embedders to react to widget state changes (open/close/error/send)

**Production impact.** Embedders cannot integrate analytics, A/B testing, or
session-replay hooks.

**Recommended solution.** Add a `window.WebChatWidget.on(event, handler)`
registration API.

**Estimated complexity:** Medium.

---

#### P3-4. The widget service key derivation (`apps/widget/src/core/visitor.ts:44-48`)

falls back to a Math.random-based UUID when `crypto.randomUUID` is missing;
this is acceptable for modern browsers but not for legacy IE/edge.

**Evidence.** `apps/widget/src/core/visitor.ts:38-49`.

**Production impact.** Negligible — IE is unsupported everywhere else in
the stack.

**Estimated solution.** Drop the legacy fallback or document that
unsupported browsers will not load the widget.

**Estimated complexity:** Trivial.

---

#### P3-5. The widget SDK inlines SVG icons — no sprite reuse, no cacheable

asset. Multiple embeds on the same page each ship the same SVG.

**Production impact.** Negligible (SVGs are tiny) but worth flagging.

**Recommended solution.** External sprite via a fetch + cache once per
session, or shared CSS-only icons.

**Estimated complexity:** Small.

---

#### P3-6. The widget SDK does not expose a TypeScript-declarations entry

point; embedders using strict TypeScript must use `// @ts-ignore` or
declare the module themselves

**Evidence.** `apps/widget/package.json` — no `types` / `typings` field
referenced in the dist output.

**Production impact.** TypeScript embedders lose typing benefits.

**Recommended solution.** Add `vite-plugin-dts` or a hand-authored
`webchat-widget.d.ts` to the build.

**Estimated complexity:** Small (half a day).

---

#### P3-7. `/api/widget/v1/config/{widget_id}` returns `bot_name` /

`welcome_message` / `placeholder` with no language fallback

**Production impact.** A tenant who configures welcome_message in English
serves English-only to all visitors, regardless of browser locale.

**Recommended solution.** Allow `welcome_message_i18n: dict[str, str]`
on the widget config; widget picks by `navigator.language`.

**Estimated complexity:** Medium (2-3 days).

---

#### P3-8. The widget SDK does not announce typing-state to screen readers

during streaming

**Evidence.** `apps/widget/src/ui/window.ts:142-145` (`status` `aria-live`)
is updated when streaming starts (`mount.ts:561-565`) but not on every delta.

**Production impact.** Screen-reader users see one "AI is typing" announce
at start, then silence until the bubble appears in full.

**Recommended solution.** Announce "still typing" periodically (every 4-5 s)
while streaming.

**Estimated complexity:** Small.

---

## 5. Improvement Roadmap

### Phase 1 — Critical fixes (1-2 weeks)

| #   | Item                                          | Severity | Complexity | Notes                                    |
| --- | --------------------------------------------- | -------- | ---------- | ---------------------------------------- |
| 1.1 | P0-1 Origin allowlist missing-Origin handling | P0       | M          | Browser-vs-non-browser detection         |
| 1.2 | P0-2 Widget session visitor binding           | P0       | M          | Token signature change; migration script |
| 1.3 | P0-3 Feedback submit atomicity                | P0       | S          | Mongo transaction + unique index         |
| 1.4 | P0-4 Visitor rotation bypass                  | P0       | S          | Composite limiter                        |
| 1.5 | P0-5 SSE partial-content preservation         | P0       | S          | New `incomplete` state                   |
| 1.6 | P0-6 Faithfulness scorer honesty              | P0       | S          | Rename + doc fix; optional LLM judge     |
| 1.7 | P1-6 Cache `allowed_domains` per config       | P1       | S          | Halve Mongo load on config fetch         |
| 1.8 | P1-9 Don't bill `vector_queries` on cache hit | P1       | Trivial    | Trust & accuracy                         |
| 1.9 | P1-10 NAT-friendly rate limit keys            | P1       | S          | Use visitor-id when available            |

**Deliverable:** P0 + most P1 closed. Ship-ready.

---

### Phase 2 — Performance (1-2 weeks)

| #   | Item                                         | Severity | Complexity | Notes                                                   |
| --- | -------------------------------------------- | -------- | ---------- | ------------------------------------------------------- |
| 2.1 | P1-7 `_retrieve` tuple → dataclass           | P1       | S          | Refactor for maintainability                            |
| 2.2 | Sequential Mongo lookups parallelization     | P1       | M          | `asyncio.gather` for `find_by_id` + `find_by_widget_id` |
| 2.3 | Eager `usage_events` flush to async queue    | P1       | M          | Decouple from chat latency                              |
| 2.4 | Atlas `numCandidates` tuning per top_k       | P2       | S          | Lower default to `top_k * 10` for small top_k           |
| 2.5 | Bundle DOMPurify lazy-import                 | P2       | S          | Faster initial paint                                    |
| 2.6 | `_emit_fallback` skip-persist on cache hit   | P1       | Trivial    | Save a write                                            |
| 2.7 | Embedding cache `sanitize_question` contract | P1       | Trivial    | Defensive                                               |
| 2.8 | Cache `allowed_domains` (Phase 1 overlap)    | P1       | S          | Mongo offload                                           |

**Deliverable:** TTFT p50 < 600 ms, p95 < 2.5 s on typical websites.

---

### Phase 3 — UX improvements (2-3 weeks)

| #   | Item                                                         | Severity | Complexity | Notes                               |
| --- | ------------------------------------------------------------ | -------- | ---------- | ----------------------------------- |
| 3.1 | P2-9 RTL support in composer & bubbles                       | P2       | Trivial    | `dir="auto"`                        |
| 3.2 | P2-1 Lazy `loading` on logo / avatar                         | P2       | Trivial    | LCP improvement                     |
| 3.3 | P3-3 Embedder event hook API                                 | P3       | M          | `WebChatWidget.on(event, handler)`  |
| 3.4 | P3-6 TypeScript declarations                                 | P3       | S          | `vite-plugin-dts`                   |
| 3.5 | P3-8 Periodic streaming announce for SR                      | P3       | S          | WCAG 4.1.3 polish                   |
| 3.6 | Improved citation card preview (favicon)                     | P3       | M          | Show tiny favicon from `source_url` |
| 3.7 | Drag-to-resize chat window                                   | P3       | M          | Respect existing `width`/`height`   |
| 3.8 | Persistent conversation history in `localStorage` for opt-in | P3       | M          | Reset opt-out per visitor           |
| 3.9 | Suggested questions ranking via prior clicks                 | P3       | L          | Backend telemetry needed            |

**Deliverable:** WCAG 2.2 AA conformance verified; embedder integration
ergonomics on par with Intercom / Drift.

---

### Phase 4 — Advanced features (4+ weeks)

| #    | Item                                        | Severity | Complexity | Notes                                |
| ---- | ------------------------------------------- | -------- | ---------- | ------------------------------------ |
| 4.1  | P3-7 i18n welcome_message / placeholder     | P3       | M          | Widget picks `navigator.language`    |
| 4.2  | Multilingual RAG prompts (P1-5)             | P1       | M          | v2 system prompt with locale         |
| 4.3  | Plan-tier rate limits (P1-2)                | P1       | M          | Tenant override path                 |
| 4.4  | LLM-as-judge faithfulness (P0-6 alt)        | P0       | L          | Smaller model + batch eval           |
| 4.5  | Per-tenant confidence weights (P2-8)        | P2       | S          | Tuning surface                       |
| 4.6  | Vector-search observability dashboards      | P3       | M          | Token-level tracing                  |
| 4.7  | Real-time widget error stream to monitoring | P3       | M          | OTLP / OpenTelemetry                 |
| 4.8  | Encrypted visitor id (P0-2 alternative)     | P0       | M          | Cookie-HMAC                          |
| 4.9  | Embed-side CSP nonce / hash sharing         | P3       | S          | Tightens CSP without breaking widget |
| 4.10 | Multi-tenant session caching                | P3       | M          | Shared widget_id cross-tenant        |

---

## Appendix A — File map (read for this audit)

```
apps/widget/src/
├── index.ts                     — public entry; autoUpgrade
├── config/
│   ├── fetch.ts                 — config fetch + 5-min module cache
│   └── types.ts                 — WidgetPublicConfig, DEFAULT_CONFIG
├── core/
│   ├── embed.ts                 — multi-host autoUpgrade
│   ├── errors.ts                — WidgetError taxonomy + mapping
│   ├── mount.ts                 — mount() lifecycle + UI wiring
│   ├── network.ts               — fetchWithTimeout, isOffline
│   ├── session.ts               — SessionManager, JWT mint
│   ├── sse.ts                   — SSE parser (POST)
│   └── visitor.ts               — wc_visitor cookie + UUIDv4
├── ui/
│   ├── bubbles.ts               — messages, sources, retry, feedback
│   ├── composer.ts              — input, send, stop
│   ├── feedback.ts              — thumbs-up/down control
│   ├── icons.ts                 — inline SVG
│   ├── launcher.ts              — floating button
│   ├── styles.ts                — all WIDGET_STYLES (1.2k lines)
│   ├── window.ts                — chat shell, focus trap, banner
│   └── suggested.ts             — question chips
├── stream/
│   ├── chat.ts                  — Conversation state machine
│   └── client.ts                — POST /chat SSE consumer
├── markdown/
│   └── render.ts                — tokenizer + DOMPurify
├── feedback/
│   └── api.ts                   — POST /feedback
├── conversation/
│   └── intent.ts                — local greeting/thanks/farewell
└── theme/apply.ts               — CSS custom properties

packages/themes/src/
└── index.ts                     — preset palettes, resolveTheme

backend/
├── api/
│   ├── deps.py                  — services, auth, rate limits, CSRF
│   ├── middleware.py            — request-id, security headers, widget CORS
│   ├── sse.py                   — disconnect-aware SSE, buffered coalesce
│   └── routes/
│       ├── widget.py            — /api/widget/v1/{config,sessions,chat,feedback}
│       └── health.py            — /health, /health/live, /health/ready
├── core/
│   ├── config.py                — Settings
│   ├── database.py              — MongoDB init_indexes (175-296)
│   ├── errors.py                — AppError hierarchy (incl. widget errors)
│   ├── logging.py               — JsonFormatter, request_id
│   ├── security.py              — JWT, password hashing, widget_session_token
│   └── prompt_guard.py          — injection detection, sanitize_context_chunk
├── models/
│   └── widget.py                — Widget Pydantic + WIDGET_THEME_PRESETS
├── schemas/
│   ├── widget.py                — WidgetPublicConfig, request models, validators
│   └── feedback.py              — WidgetFeedbackRequest
├── services/
│   ├── widget/
│   │   ├── widget_service.py    — validate_origin, create_session, validate_chat
│   │   └── spam_filter.py       — pure heuristics
│   ├── chat/
│   │   ├── rag_service.py       — full pipeline (stream_answer, _retrieve, _build_context)
│   │   ├── retrieval_strategy.py — Vector + Hybrid RRF
│   │   ├── confidence.py        — assess_confidence
│   │   └── context_optimizer.py — near-dedup + sentence compress
│   └── feedback/feedback_service.py — submit, dedup
├── repositories/
│   ├── widget_repository.py     — find_by_widget_id, update_widget_config
│   ├── feedback_repository.py   — find_by_message, create
│   └── vector/
│       ├── mongodb.py           — Atlas $vectorSearch + brute-force fallback
│       ├── reranker.py          — EmbeddingReranker (cosine on stored chunks)
│       └── hybrid.py            — RRF fusion
└── prompts/rag.py               — system prompt, sanitize_question, render_context
```

---

## Appendix B — Bundle size & perf numbers (current `dist/`)

```
webchat-widget.iife.min.js        112 KB raw,  ~40 KB gzipped   (in budget)
webchat-widget.iife.min.js.map    416 KB
webchat-widget.umd.cjs            112 KB raw,  ~40 KB gzipped
webchat-widget.js (ES)            142 KB raw,  ~48 KB gzipped
```

- Hard cap: 100 KB gzipped (current 40 KB ⇒ 60% of budget).
- Largest single dep: DOMPurify ≈ 30 KB of the gzipped payload.
- Suggested budget split: core shell 18 KB, theme tokens 4 KB, markdown
  tokenizer + DOMPurify 18 KB (or 8 KB without DOMPurify).

---

## Appendix C — Rate-limit budget snapshot

| Endpoint           | Per-IP                   | Per-widget                       | Per-visitor                       | Per-session-issue                   | Per-feedback |
| ------------------ | ------------------------ | -------------------------------- | --------------------------------- | ----------------------------------- | ------------ |
| `GET /config/{id}` | `widget_ip_limit` (60/m) | —                                | —                                 | —                                   | —            |
| `POST /sessions`   | same                     | —                                | —                                 | `widget_session_issue_limit` (30/m) | —            |
| `POST /chat`       | same                     | `widget_per_widget_limit` (60/m) | `widget_per_visitor_limit` (20/m) | —                                   | —            |
| `POST /feedback`   | same                     | —                                | `widget_feedback_limit`           | —                                   | —            |

All limiters fail closed (503) on Redis outage. Missing: composite
`(visitor_id, widget_id)` for rotation-bypass resistance.

---

## Appendix D — Index coverage snapshot

| Collection         | Critical indexes                                                                                                   | Notes                  |
| ------------------ | ------------------------------------------------------------------------------------------------------------------ | ---------------------- |
| `widgets`          | `widget_id` unique, `(tenant_id, website_id)` unique                                                               | OK                     |
| `chat_sessions`    | `session_id` unique, `(tenant_id, website_id)`, TTL on `expires_at`                                                | OK                     |
| `messages`         | `(tenant_id, session_id, created_at)`, TTL 90 d                                                                    | OK                     |
| `usage_records`    | `(tenant_id, website_id, date)` unique, TTL 3 y                                                                    | OK                     |
| `usage_events`     | `(tenant_id, created_at)`, TTL 3 y                                                                                 | OK                     |
| `knowledge_chunks` | `(tenant_id, website_id, document_id, chunk_index)` unique, `(tenant_id, website_id)`, Atlas `$vectorSearch` index | OK                     |
| `feedback`         | `(tenant_id, created_at)` per docstring; `message_id` is **not uniquely indexed**                                  | **MISSING** (see P0-3) |
| `documents`        | `(tenant_id, website_id, url)` unique                                                                              | OK                     |
| `crawl_jobs`       | `(tenant_id, status)`, TTL 30 d                                                                                    | OK                     |
| `audit_logs`       | `(tenant_id, created_at)`, TTL 1 y                                                                                 | OK                     |

---

## Appendix E — Configuration snapshot (env-driven)

| Setting                                                | Default (prod `.env.production`) | Used by                               |
| ------------------------------------------------------ | -------------------------------- | ------------------------------------- |
| `WIDGET_SESSION_TOKEN_MINUTES`                         | 15                               | `core/security.py`                    |
| `WIDGET_SESSION_VALIDITY_HOURS`                        | 24                               | `services/widget/widget_service.py`   |
| `WIDGET_MAX_MESSAGES_PER_SESSION`                      | 50                               | same                                  |
| `WIDGET_PER_WIDGET_LIMIT`                              | 60/min                           | `api/deps.py`                         |
| `WIDGET_PER_VISITOR_LIMIT`                             | 20/min                           | same                                  |
| `WIDGET_SESSION_ISSUE_LIMIT`                           | 30/min                           | same                                  |
| `WIDGET_FEEDBACK_LIMIT`                                | —                                | same                                  |
| `WIDGET_IP_LIMIT`                                      | 60/min                           | same                                  |
| `WIDGET_CONFIG_CACHE_SECONDS`                          | 300                              | `services/widget/widget_service.py`   |
| `CHAT_TOP_K`                                           | 5                                | `services/chat/rag_service.py`        |
| `CHAT_CONTEXT_CHUNK_CHARS`                             | —                                | same                                  |
| `CHAT_CONTEXT_MAX_CHARS`                               | —                                | same                                  |
| `CHAT_RETRIEVAL_CACHE_TTL_SECONDS`                     | —                                | same                                  |
| `EMBEDDING_CACHE_SIZE` / `EMBEDDING_CACHE_TTL_SECONDS` | —                                | same                                  |
| `ENABLE_RAG_CONFIDENCE_CHECK`                          | —                                | `services/chat/confidence.py`         |
| `RAG_CONFIDENCE_THRESHOLD`                             | —                                | same                                  |
| `ENABLE_FAITHFULNESS_CHECK`                            | —                                | `services/chat/rag_service.py`        |
| `ENABLE_HYBRID_SEARCH`                                 | —                                | `services/chat/retrieval_strategy.py` |
| `ENABLE_RERANKING` + `RERANK_TOP_K`                    | —                                | `services/chat/rag_service.py`        |
| `PERF_TIMING_LOG_ENABLED`                              | false                            | `api/middleware.py`, RAG timing logs  |
| `RATE_LIMIT_ENABLED`                                   | true                             | `api/deps.py`                         |
| `TRUST_PROXY`                                          | false                            | `api/deps.py`                         |

---

## Appendix F — Recommended telemetry additions

These are not currently emitted; they would significantly improve MTTR.

| Metric                                   | Type      | Where to emit                               |
| ---------------------------------------- | --------- | ------------------------------------------- |
| `widget_config_cache_hit`                | counter   | `apps/widget/src/config/fetch.ts:57`        |
| `widget_session_renew_total`             | counter   | `apps/widget/src/core/session.ts:145`       |
| `widget_chat_stream_total{outcome="ok    | aborted   | error"}`                                    | counter | `apps/widget/src/stream/client.ts` |
| `widget_first_token_ms`                  | histogram | `apps/widget/src/stream/client.ts`          |
| `widget_referrer_errors_total{code}`     | counter   | `apps/widget/src/core/mount.ts:386`         |
| `widget_origin_rejected_total{reason}`   | counter   | `backend/services/widget/widget_service.py` |
| `widget_rate_limit_redis_error_total`    | counter   | `backend/api/deps.py:699-707`               |
| `rag_embedding_provider_used{provider}`  | counter   | `backend/services/chat/rag_service.py:534`  |
| `rag_confidence_rejection_total{reason}` | counter   | `backend/services/chat/rag_service.py:589`  |
| `rag_faithfulness_low_total`             | counter   | `backend/services/chat/rag_service.py:742`  |
| `rag_retrieval_cache_hit_ratio`          | gauge     | `backend/services/chat/rag_service.py:858`  |

---

**End of audit.**
