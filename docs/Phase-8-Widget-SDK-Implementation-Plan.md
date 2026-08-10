# Phase 8 — Widget SDK: Implementation Plan

**Status:** Ready for approval — audit complete, no code changed.
**Base:** `bec6d59` (`feat: implement phase 7 dashboard`, tag `v0.7-dashboard-complete`)
**Scope:** `docs/06-Implementation-Plan.md` Phase 8 (embeddable chatbot widget), governed by `docs/07-Architecture-Decisions.md` ADR-003/004/005/008.
**Rules honored:** backend auth, RAG pipeline, and knowledge processing are **unchanged**; only new additive modules. Secret-free public widget per ADR-004. `docs/06` is the active roadmap.

---

## 1. Requirement → Current-State Gap Analysis

| #   | Requirement (docs/06 Phase 8 + ADR-004)                                                                                               | Current state                                                                                                                                                                                                                                                                                               | Gap                                                                                    | Severity                                                                                              |
| --- | ------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| G1  | `GET /api/widget/v1/config/{widget_id}` (public, Redis-cached 5 min)                                                                  | No public widget router exists (`backend/api/routes/` has auth/chat/crawl_jobs/health/websites only). No `find_by_widget_id` on `MongoWidgetRepository` (`backend/repositories/widget_repository.py`); unique `widget_id` index exists (`backend/core/database.py:109`). No Redis caching of widget config. | Missing endpoint, missing repo method, missing cache                                   | **High**                                                                                              |
| G2  | `POST /api/widget/v1/sessions` (rate-limited; returns `{session_token, expires_at}`)                                                  | Widget session JWT purpose (`token_type=widget_session`) not defined. `backend/core/security.py` `TokenPurpose` = `access                                                                                                                                                                                   | email_verify                                                                           | password_reset`; `_encode`/`_decode` are private. No create/decode helpers for widget-session tokens. | Missing token type + endpoint                                                                                                                                | **High**                                                                                         |
| G3  | `POST /api/widget/v1/chat` (SSE, Bearer widget session token)                                                                         | `RagService.stream_answer` (`backend/services/chat/rag_service.py:93`) already accepts `tenant_id/website_id/question/session_id/visitor_id/user_id` and emits `sources                                                                                                                                     | message                                                                                | done                                                                                                  | error`SSE.`ChatRequest`caps`question`at 2000 chars (ADR-004 msg limit).`ChatSession`model already carries`visitor_id` (`backend/models/chat_session.py:30`). | No public chat wrapper resolving tenant/website from the session token; otherwise reusable as-is | **High** |
| G4  | Per-widget (60/min) + per-visitor (20/min) rate limits                                                                                | `SlidingWindowRateLimiter` (`backend/core/rate_limit.py`) is generic but `RateLimitDependency` (`backend/api/deps.py:194`) keys **only by path + client IP**. `chat_limiter` is IP-keyed.                                                                                                                   | Need keyed limiter (widget_id / visitor_id)                                            | **High**                                                                                              |
| G5  | Tenant validation on every widget request: widget enabled + website `ready` + tenant active                                           | `Widget.enabled`, `Widget.tenant_id`, `Website.status`, `Tenant.status` (`backend/models/tenant.py:19`) all exist. No orchestration loads widget → checks tenant/website status.                                                                                                                            | Missing validation flow                                                                | **High**                                                                                              |
| G6  | CORS: public widget API `ACAO: *` (no cookies); dashboard strict                                                                      | Global `CORSMiddleware` (`backend/main.py:53`) uses `allow_origins=cors_origins` + `allow_credentials=True` — cookie-mode CORS, no wildcard. One app serves both surfaces.                                                                                                                                  | Must add per-path public CORS (widget namespace only) without weakening dashboard CORS | **High**                                                                                              |
| G7  | Session: token 15 min (renew via `/sessions`), session validity 24 h sliding                                                          | Not implemented.                                                                                                                                                                                                                                                                                            | New token TTL + renewal policy                                                         | **Medium**                                                                                            |
| G8  | Max 50 messages per visitor session; basic spam filtering                                                                             | Not implemented (no per-session message counter, no spam heuristic).                                                                                                                                                                                                                                        | Add counters + filter                                                                  | **Medium**                                                                                            |
| G9  | Frontend SDK: floating launcher, chat window, streaming UI, markdown, suggested questions, theme customization, responsive; `<100 KB` | `apps/widget` builds ES/UMD/IIFE via Vite (`apps/widget/vite.config.ts`), `dompurify` already a dependency, folder skeleton (`config/ core/ markdown/ stream/ theme/ ui/`) present. `src/index.ts`/`src/core/mount.ts` are stubs (console.info only). No UI, no SSE client, no theme engine.                | Full SDK implementation                                                                | **High**                                                                                              |
| G10 | Embed script one-line (`data-widget-id`)                                                                                              | `WebsiteService.build_embed_script` (`backend/services/website/website_service.py:244`) already emits `<script src="{WIDGET_SCRIPT_URL}" data-widget-id=... defer>`. Dashboard widget page is read-only with copy button (Phase 7, verified).                                                               | No change needed; widget script must honor `data-widget-id`                            | None                                                                                                  |
| G11 | Live E2E / infra                                                                                                                      | Blocked — no running MongoDB/Redis/worker locally (known since Phase 6).                                                                                                                                                                                                                                    | Test via unit/integration + optional live smoke when infra available                   | —                                                                                                     |

**No schema migration required.** `widgets` (ADR-005 §5.3) already has every config field, `widget_id`, `enabled`, `widget_secret_hash`, `schema_version`. `chat_sessions`/`chat_messages` already carry `visitor_id` and TTL. All new backend work is additive.

---

## 2. Architecture

### 2.1 Public vs protected surface

```
Dashboard API   /api/*                 JWT + tenant + RBAC   (unchanged)
Public widget   /api/widget/v1/*       widget_id + scoped session token   (NEW)
```

### 2.2 Request flow (per ADR-004 §Tenant Validation Flow)

```
widget JS
  ├─ GET /api/widget/v1/config/{widget_id}          → theme/welcome/suggested questions/branding
  ├─ POST /api/widget/v1/sessions                   → {session_token, expires_at}   (rate-limited only)
  └─ POST /api/widget/v1/chat   (SSE, Bearer)       → sources / message* / done / error
        token → claims(widget_id, tenant_id, website_id, visitor_id, token_type=widget_session, jti)
        → load widget (Redis 5 min) → enabled? tenant active? website ready?
        → RagService.stream_answer(tenant_id, website_id, ...)   (unchanged service)
```

### 2.3 Reuse boundaries

- **RAG pipeline, auth, knowledge, ingestion, embedding:** untouched.
- **`RagService.stream_answer`:** reused verbatim as the chat engine; the public chat route only adapts principal + limits.
- **`SlidingWindowRateLimiter`:** reused; a new keyed dependency (below) supplies `widget_id`/`visitor_id` keys.
- **Conversation memory (Phase 6 F1):** already fixed — `list_recent` returns the latest `CHAT_MEMORY_TURNS` turns in chronological order (`backend/repositories/chat_message_repository.py:50-59`). Phase 8 only **verifies** this with a regression test; no fix task.

---

## 3. API Changes (new, additive — `backend/api/routes/widget.py`, mounted at `/api/widget/v1`)

| Method | Path                                | Auth                     | Request                    | Response                      | Notes                                                                          |
| ------ | ----------------------------------- | ------------------------ | -------------------------- | ----------------------------- | ------------------------------------------------------------------------------ |
| GET    | `/api/widget/v1/config/{widget_id}` | none                     | —                          | `WidgetPublicConfig`          | Redis-cached 5 min; 404 `WIDGET_NOT_FOUND`; suspended tenant → `enabled:false` |
| POST   | `/api/widget/v1/sessions`           | none (rate-limited)      | `{widget_id, visitor_id?}` | `{session_token, expires_at}` | Issues 15-min widget-session JWT                                               |
| POST   | `/api/widget/v1/chat`               | `Bearer <session_token>` | `{question, session_id?}`  | SSE (reuses event shapes)     | Rejects when widget disabled / tenant suspended / website not `ready`          |

### 3.1 Schemas (new, `backend/schemas/widget.py`)

- `WidgetPublicConfig` — mirror of dashboard `WidgetOut` **without** `website_id`/timestamps, plus `enabled`. Never includes `widget_secret_hash`. Never includes the raw secret (ADR-004; only the hash exists server-side).
- `CreateWidgetSessionRequest` — `widget_id: str` (min/max length), `visitor_id: str | None`.
- `WidgetSessionResponse` — `session_token: str`, `expires_at: datetime`.
- `WidgetChatRequest` — `question: str` (1–2000, whitespace-normalized like `ChatRequest`), `session_id: str | None` (the **conversation** id, distinct from the widget session token).

### 3.2 Widget session token (new, `backend/core/security.py` + `backend/core/config.py`)

- New `TokenPurpose` member `"widget_session"`; new helpers `create_widget_session_token(...)` and `decode_widget_session_token(...)`.
- Claims (ADR-003 token table): `widget_id`, `tenant_id`, `website_id`, `visitor_id`, `token_type=widget_session`, `jti`, `iat`, `exp`.
- TTL: `WIDGET_SESSION_TOKEN_MINUTES = 15` (env-tunable). Renewed by re-calling `/sessions`.
- Session validity: 24 h sliding per visitor per widget tracked in Redis (`ws:session:{widget_id}:{visitor_id}`) — a hard 24 h ceiling; the 15-min JWT is refreshed within it.

#### 3.2.1 `widget_session_token` vs `chat_session_id` — two distinct identifiers (never conflated)

|            | `widget_session_token`                                          | `chat_session_id`                                                                          |
| ---------- | --------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| What it is | Short-lived **JWT** authorizing the visitor to the widget API   | **Conversation** identifier persisted in `chat_sessions` (docs/05 §9)                      |
| Issued by  | `POST /api/widget/v1/sessions` (public, rate-limited)           | `RagService._ensure_session` (`rag_service.py:249-274`), server-generated on first message |
| Carried    | `Authorization: Bearer` on `/chat`                              | Request body field `session_id` on `/chat`                                                 |
| Lifetime   | 15 min (renewed via `/sessions` within the 24 h sliding window) | 90 days retention TTL (`CHAT_RETENTION_DAYS`, ADR-005 §5.7)                                |
| Scope      | Bound to `widget_id + tenant_id + website_id + visitor_id`      | Bound to `tenant_id + website_id`; `_ensure_session` rejects cross-website reuse           |
| Rotated?   | Yes — every `/sessions` call mints a new token                  | No — reused across messages to keep one conversation; expired only by TTL                  |
| Owner      | Widget client (kept in memory while the page is open)           | Backend `chat_sessions` collection                                                         |

**Lifecycle rules:**

1. Widget opens → reads `visitor_id` (anonymous cookie) → `POST /sessions` → keeps the JWT **in memory only**.
2. First message → widget may omit `session_id`; the backend creates the `chat_sessions` doc and returns its id in the `done` event.
3. Subsequent messages → widget sends the **same** `chat_session_id` (conversation continuity) with a **fresh** `widget_session_token` if the old one is near expiry.
4. The widget never persists the JWT; `chat_session_id` (non-secret) may be kept in memory for the page session.

### 3.3 Widget lookup (new, `backend/repositories/widget_repository.py`)

- Add `find_by_widget_id(widget_id: str) -> Widget | None` (uses the existing unique `widget_id` index). This is a read path for the public API only; the tenant-scoped dashboard queries are unchanged.

### 3.4 Widget config cache

- `backend/services/widget/widget_service.py` (new): `get_public_config(widget_id)` → Redis cache `wk:config:{widget_id}` TTL 300 s, store serialized config; invalidate on widget update (future customization API). Miss → repo load → `WidgetPublicConfig`. Fails closed to DB on cache error.

### 3.5 Rate limiting (new keyed dependency, `backend/api/deps.py`)

- `RateLimitDependency` keeps IP-keyed behavior for dashboard routes. Add `WidgetRateLimitDependency` accepting a key factory:
  - per-widget `60/min`: key `rl:widget:{widget_id}`
  - per-visitor `20/min`: key `rl:visitor:{visitor_id}`
- Session-issue route: low limit (e.g., `30/min` per widget) to prevent token-minting abuse.
- Fails closed on Redis outage (503), matching existing behavior (`deps.py:214-218`).

### 3.6 Message cap + spam filter

- Per-session counter: Redis `ws:msgs:{chat_session_id}` INCR, TTL 24 h; reject at 50 (400 `MESSAGE_LIMIT_REACHED`).
- `backend/services/widget/spam_filter.py` (new, pure function, unit-testable): repeated-character runs, all-uppercase ratio, URL-only submissions, empty-after-normalization. Low-cost heuristics; conservative to avoid false positives on legitimate questions.

### 3.7 Tenant/website validation (widget chat + sessions)

- Widget chat dependency: decode token → `find_by_widget_id` → require `enabled` and tenant `status == active`; require `website.status == ready` (ADR-004 "website is ready"). Non-ready → SSE `error` event with `WEBSITE_NOT_READY`.
- Config endpoint: suspended tenant → `enabled: false` in response (ADR-005 §suspension semantics), never 403 to an anonymous visitor.

### 3.8 Widget API versioning strategy

- **Path-based versioning** at the router level: `/api/widget/v1/*` (`backend/api/routes/widget.py`, mounted with prefix `/api/widget/v1`), matching ADR-004's documented namespace. A future `/api/widget/v2` is a new router, not a rewrite of v1.
- **Compatibility contract (additive-only within a major version):** new fields may be added to response objects; existing fields never renamed, removed, or re-typed. New endpoints may be added freely. Breaking changes (rename/remove/retype, auth-scheme changes) require a new major version.
- **Client negotiation:** the SDK pins a supported version range (e.g., `v1`) and degrades gracefully if an unknown field is absent; unknown fields in responses are ignored (forward-compatible parsing).
- **Deprecation:** a version is deprecated with a `Deprecation` warning header on responses and a documented end-of-life window (min 2 majors) before removal. `docs/07` ADR-004 table stays the canonical endpoint reference; this plan's §3 table is mirrored there at implementation time.
- **Version-aware tests:** backend tests assert v1 shapes explicitly; SDK tests parse a frozen v1 fixture so accidental shape drift fails CI.

---

## 4. Security

| Control                 | Design                                                                                                                                                                                                                                                                                                                                                                                  |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| No secrets in client JS | Widget bundle contains only `widget_id` (public). Session tokens are server-issued JWTs, never the widget secret. Raw secret exists nowhere after creation (only hash persisted).                                                                                                                                                                                                       |
| Scoped session token    | HS256 JWT bound to `widget_id + tenant_id + website_id + visitor_id`; 15-min TTL; verified on every chat request. A token minted for widget A cannot query widget B (claims → repo re-check on every request, not just claims trust).                                                                                                                                                   |
| Tenant isolation        | Every widget DB read filters by the resolved `tenant_id` from the token; `RagService._ensure_session` already rejects sessions bound to another website (`rag_service.py:269-274`).                                                                                                                                                                                                     |
| Abuse protection        | Per-widget + per-visitor sliding-window limits; session-issue rate limit; 50-msg/session cap; 2000-char question cap (exists); spam filter; fail-closed limiter.                                                                                                                                                                                                                        |
| CORS                    | **Public widget namespace only:** `Access-Control-Allow-Origin: *`, no credentials, `Allow-Methods: GET,POST,OPTIONS`, `Allow-Headers: Authorization, Content-Type` — implemented as a narrow ASGI middleware matching `/api/widget/` (preflight + actual). Dashboard surface keeps strict origin + credentials CORS. **This must not regress dashboard CORS — see migration risk M2.** |
| Content safety          | Widget renders assistant markdown via `DOMPurify.sanitize` (dependency already present); `default-src 'none'` CSP on API responses is unchanged. **Markdown is restricted to an allowlist (§4.1)**; rendering happens inside the shadow root, never on the host document.                                                                                                               |
| No CSRF needed          | Public widget API is bearer-token only, no cookies (ADR-003 §CSRF exemption). The `wc_visitor` identity cookie is not a session cookie and is never sent to the API.                                                                                                                                                                                                                    |

### 4.1 Markdown security restrictions (assistant-rendered content)

Assistant output is model-generated (untrusted until sanitized). The renderer implements a **strict allowlist** — anything else is escaped or dropped, never passed through:

| Construct                                                                | Policy                                                                                                                                                                   |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Inline `**bold**`, `*italic*`, `` `code` ``, `[text](url)`               | Allowed                                                                                                                                                                  |
| Links                                                                    | `href` scheme must be `https:`, `http:`, or relative; `javascript:`/`data:`/`vbscript:` schemes rejected. Rendered with `target="_blank"` + `rel="noopener noreferrer"`. |
| Headings `#`–`####`                                                      | Allowed (maps to styled text; **no** raw `<h1>` semantics leak)                                                                                                          |
| Unordered/ordered lists, blockquotes, fenced code blocks                 | Allowed                                                                                                                                                                  |
| Raw HTML tags / attributes                                               | **Rejected** — stripped before DOMPurify, never rendered as elements                                                                                                     |
| Images (`![](...)`)                                                      | **Rejected** — no third-party image loading (privacy + SSRF-adjacent fingerprinting)                                                                                     |
| Autolinks, email autolinking                                             | Escaped to text                                                                                                                                                          |
| `<script>`, event handlers (`on*`), `style`, `iframe`, `object`, `embed` | **Rejected** (defense-in-depth; also removed by DOMPurify config)                                                                                                        |

Implementation: a tokenizer emits only the allowlisted constructs; output passes through `DOMPurify.sanitize(..., { ALLOWED_TAGS, ALLOWED_ATTR })` with a locked-down config as a second gate. Both layers are unit-tested with an XSS payload corpus (see §10.2).

---

## 5. Frontend SDK Structure (`apps/widget/src`)

```
src/
  index.ts          registers <webchat-widget> custom element; init() → mount, returns handle
  core/
    mount.ts        lifecycle: create custom element, attach shadow root, wire launcher, teardown
    visitor.ts      anonymous visitor_id: first-party cookie (not localStorage); in-memory fallback
    session.ts      widget_session_token lifecycle: mint on start, pre-emptive refresh at 12/15 min
    sse.ts          fetch + ReadableStream SSE parser → callback stream (POST-based; EventSource can't POST)
    embed.ts        reads data-widget-id from the <script> tag; upgrades the custom element automatically
  config/
    types.ts        WidgetPublicConfig, WidgetOptions, theme tokens
    fetch.ts        GET config (cached in module for 5 min), error/retry
  stream/
    client.ts       POST /chat, auth header, dispatch sources/message/done/error events
    chat.ts         conversation state: chat_session_id, message list, streaming buffer
  ui/
    launcher.ts     floating button (position from config)
    window.ts       chat window shell, open/close, auto-open, welcome message
    bubbles.ts      message list, user/assistant styles
    composer.ts     textarea (2000 cap), send, disabled-while-streaming, error banner
    suggested.ts    suggested questions (from config), tap-to-send
  markdown/
    render.ts       restricted markdown → sanitized HTML via DOMPurify (allowlist, see §4)
  theme/
    apply.ts        CSS custom properties injected into the shadow root (primary/accent/font-size/branding/dark-mode/position)
```

#### 5.1 Web Component + Shadow DOM architecture (decision)

- **Render as a custom element** (`<webchat-widget>`) backed by `HTMLElement`; the embed script (`data-widget-id`) upgrades the element declaratively. `init()` is sugar for `document.createElement` + attribute assignment for framework users.
- **Encapsulate in a shadow DOM root** (`attachShadow({ mode: 'closed' })`):
  - Style isolation — host-page CSS cannot leak in, widget CSS cannot leak out; no class-name collisions with the customer's site.
  - DOM isolation — widget internals are invisible to the host page's scripts and selectors (hardening against page-level interference).
  - Aria/roles and focus are managed inside the shadow root; the widget remains reachable to assistive tech via a labelled host element.
- **Theming:** all colors/spacing/typography are CSS **custom properties** defined on the host element (`--wc-primary`, `--wc-accent`, `--wc-font-size`, …). Shadow DOM explicitly inherits custom properties from the host, so the config-driven theme engine sets them on the host and the encapsulated UI consumes them — no `:host` leaks needed.
- **Content rendering:** assistant markdown is sanitized (DOMPurify) and injected into the shadow root's own DOM (never `innerHTML` on the host document). See markdown restrictions in §4.
- **Caveats tested:** `closed` mode means the host page cannot style internals — acceptable per the theme contract. Verify SSR/`document.currentScript` detection in embed flows, and confirm no interaction with `content-visibility`/`display` on lazy-loaded embeds.

**Bundle budget (gzip gate):** the SDK ships as three builds (ES / UMD / IIFE). The embeddable IIFE must be **≤ 100 KB gzipped** (`gzip -9`, CI-enforced) — the ADR-008 Phase 12 target. Hard fail over 100 KB; warn over 90 KB. Measured on the minified IIFE with `gzip -9c dist/webchat-widget.iife.min.js | wc -c` and asserted by a vitest/CI size gate. Baseline the current stub first (`pnpm --filter widget build`), then enforce per-PR. DOMPurify is the only runtime dependency; the markdown renderer is hand-rolled (no `marked`/`react-markdown` — avoids a heavy dependency for a small feature set).

**Embedding:** the existing `data-widget-id` embed script must work with no `init()` call — `embed.ts` reads `document.currentScript.dataset.widgetId`, then **upgrades** the matching `<webchat-widget>` custom element. Absolute `WIDGET_API_BASE_URL` is supplied at build/embed time for cross-origin deployment.

**SSE without EventSource:** `EventSource` only does GET; the chat endpoint is POST. Use `fetch` + `response.body.getReader()` and parse the SSE wire format (`event:`/`data:` lines), buffering partial events — matches the backend event shapes in `backend/api/routes/chat.py`.

**Visitor identity (anonymous cookie, not localStorage):** `visitor.ts` sets a first-party cookie on the host page domain:

- Name `wc_visitor`, value `crypto.randomUUID()`, `SameSite=Lax`, `Secure` (when served over HTTPS), `Path=/`, 24-month max-age.
- Cookie read/written via `document.cookie` (the widget controls its own namespace to avoid clobbering the host's cookies).
- **No PII** — the id is random and anonymous; it only keys per-visitor rate limits and session continuity. It is **not** the `widget_session_token` and is never used for auth.
- Fallback: when cookies are disabled/unavailable (e.g., `localStorage` blocked, cookies off), keep the id in memory for the page session and continue (rate limiting then falls back to per-widget/IP keys). Do **not** use `localStorage`/`sessionStorage` — consistent with the project's storage posture (ADR-003) and avoids cross-domain surprises.

---

## 6. Dashboard Integration

- **No dashboard code changes required** for the SDK itself; `apps/dashboard/src/features/widget/widget-page.tsx` remains read-only (Phase 7). The copy button already embeds the one-line script.
- Optional (separate decision, out of ADR-004 public scope): a dashboard-side `PATCH /api/websites/{id}/widget` customization API to make the widget page editable. Recommended as a **follow-up after Phase 8 core**, to keep the phase focused on the public embeddable surface.
- `docs/04-UI-UX-Brief.md` §Widget + §embed flow: plan is consistent; theme fields already exposed by config.

---

## 7. Configuration (`backend/core/config.py` + `.env.example`)

| Setting                                                | Default                      | Purpose                         |
| ------------------------------------------------------ | ---------------------------- | ------------------------------- |
| `widget_session_token_minutes`                         | 15                           | Widget session JWT TTL          |
| `widget_session_validity_hours`                        | 24                           | Sliding session ceiling (Redis) |
| `widget_config_cache_seconds`                          | 300                          | Public config Redis cache TTL   |
| `widget_per_widget_limit` / `widget_per_visitor_limit` | 60 / 20 per min              | ADR-004 abuse table             |
| `widget_max_messages_per_session`                      | 50                           | Per-conversation cap            |
| `widget_rate_limit_enabled`                            | same as `rate_limit_enabled` | Master kill switch              |

No changes to `WIDGET_SCRIPT_URL`/`WIDGET_API_BASE_URL` semantics; **production must set both to the public domain** (currently `http://localhost:8080` / `http://localhost:8000` — dev defaults).

---

## 8. Accessibility Requirements (WCAG 2.2 AA)

| Requirement              | Standard / target | Notes                                                                                                                                                                                                                                                           |
| ------------------------ | ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Keyboard operable        | WCAG 2.1.1/2.1.2  | Full focus trap inside the open chat window; `Tab`/`Shift+Tab` navigate composer ↔ close ↔ messages; `Esc` closes; `Enter` sends, `Shift+Enter` newline; launcher toggles with `Space`/`Enter`.                                                                 |
| Visible focus            | 2.4.7             | Visible focus ring on all interactive elements (theme color, ≥2:1 against adjacent).                                                                                                                                                                            |
| Landmarks & semantics    | 1.3.1, 4.1.2      | Host element labelled (`aria-label="Chat widget"`); window is `role="dialog"` with `aria-modal="true"` + `aria-labelledby`; launcher is a real `<button>`; message list `aria-live="polite"`; streaming region marked live so assistive tech announces updates. |
| Color contrast           | 1.4.3             | Text ≥ 4.5:1, large text ≥ 3:1, computed against theme `primary`/`accent` and surface backgrounds; default theme must pass with dark mode too.                                                                                                                  |
| Text resizing / zoom     | 1.4.4, 1.4.10     | Layout must not break at 200% zoom; font-size `sm/md/lg` from config; relative units (`rem`/`em`) in shadow CSS.                                                                                                                                                |
| Target size              | 2.5.8             | Interactive targets ≥ 24×24 px (launcher, send, close, suggested-question chips).                                                                                                                                                                               |
| Respect user settings    | 1.4.10, 1.4.12    | Theme `auto` follows `prefers-color-scheme`; no motion-only interactions; honor `prefers-reduced-motion` (disable auto-open animations).                                                                                                                        |
| Error + status messaging | 4.1.3             | Stream errors, network offline state, and retry actions surfaced both visually and via live regions.                                                                                                                                                            |
| Testing                  | —                 | Vitest assertions for focus trap + aria attributes; manual keyboard walk-through; axe-core pass in the demo harness (add `axe-core` as a devDependency only — not in the shipped bundle).                                                                       |

---

## 9. Offline & Network-Failure Handling

The widget runs on third-party sites where the API may be slow, down, or blocked by the host page's CSP. It must fail gracefully, never block the host page.

| Scenario                                          | Behavior                                                                                                                                                                                                                       |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| API unreachable (network error / 5xx)             | User message is **not lost**: it stays in the composer or moves to an "unsent" state with a **retry** action; a non-intrusive banner shows "Can't reach the assistant" with retry + dismiss.                                   |
| Timeout (config/chat/SSE open)                    | Client-side timeout on each fetch (config 5 s, chat connect 10 s, first token 20 s — env-tunable via `WIDGET_TIMEOUT_*`); aborts stream, surfaces error, allows retry.                                                         |
| SSE mid-stream drop / reconnection                | Buffer partial tokens already received; on reconnect, **do not auto-requeue** (would duplicate); show retry for the unanswered turn. `done`/`error` terminal events are honored exactly once (idempotency guard in `chat.ts`). |
| Session token expired mid-flight                  | `sse.ts`/`client.ts` intercept `401` → re-mint via `/sessions` → retry the in-flight request **once** (mirrors the dashboard's single-retry refresh); second `401` → clear state + prompt reload.                              |
| Offline (navigator.onLine / first failed request) | Widget keeps rendering, disables send, shows offline indicator; auto-re-enables + resends nothing automatically (user-driven retry only).                                                                                      |
| Config fetch failure                              | Render with **safe defaults** (theme `light`, position `bottom-right`, welcome "Hi! How can I help you?", no suggested questions) and lazy-retry in background; never block launcher render.                                   |
| Host CSP blocking `connect-src`/`img-src`         | Detect `CSP`/`SecurityError` on fetch, surface the console-visible error banner; document `connect-src` requirement in embed README.                                                                                           |
| Clock skew                                        | Session refresh timing uses server-provided `expires_at`, not client clock, for the pre-emptive 12/15 min renew.                                                                                                               |
| Error taxonomy                                    | Map to user-facing strings: network / timeout / unauthorized / limit / server; all sanitized, never raw.                                                                                                                       |

These paths are covered in the vitest suite via mocked `fetch` (reject/resolve/abort) and a fake clock (`session.ts`, `sse.ts`, `stream/client.ts`).

---

## 10. Testing Strategy

### 10.1 Backend (pytest; ruff + mypy gates; existing 302+ test suite must stay green)

- `security.py` — widget-session token create/decode: correct claims, expiry, wrong `token_type` rejection, tampered signature rejection.
- `widget_service` — config cache hit/miss, cache invalidation, DB fallback on Redis error, suspended tenant → `enabled:false`.
- `widget routes` — config 404; sessions rate limit; chat: valid token streams events, disabled widget → error, tenant suspended → error, website not `ready` → `WEBSITE_NOT_READY`, foreign visitor token rejected, cross-widget token rejected.
- `rate limit` — per-widget vs per-visitor counters independent; fail-closed on store error.
- `spam filter` — each heuristic + safe/legit pass-through.
- 50-msg cap — counter increments and 51st rejected.
- **CORS isolation (dashboard vs widget)** — explicit cross-surface tests:
  - Widget namespace (`/api/widget/v1/*`): preflight `OPTIONS` and actual responses return `Access-Control-Allow-Origin: *`, no `Access-Control-Allow-Credentials`, correct `Allow-Methods`/`Allow-Headers`, for arbitrary origins.
  - Dashboard namespace (`/api/*` except widget): behavior **unchanged** — no wildcard; `allow_credentials` present only when an allowed origin is sent; unallowed origins get **no** CORS headers.
  - Assert the two never bleed: a request to `/api/widget/v1/...` must not receive dashboard-style credentialed headers, and a dashboard request must never receive `*`.
- **Integration:** reuse the existing `RagService`-level tests pattern; verify the public chat route delegates to `stream_answer` with token-derived `tenant_id`/`website_id`.

### 10.2 Widget SDK (vitest — extend existing `apps/widget` suite)

- `visitor.ts` — anonymous cookie written once, same id across "reloads", in-memory fallback when cookies disabled, no `localStorage` usage.
- `session.ts` — token mint + refresh timing (server `expires_at`), expiry race handling, single-retry on `401`.
- `sse.ts` — parse multi-line/partial/combined events; backpressure; abort; terminal-event idempotency.
- `markdown/render.ts` — allowlist constructs render correctly; XSS corpus (raw HTML, `javascript:` links, `on*`, images, autolinks, event handlers) is sanitized/escaped; **no raw HTML passthrough**.
- `ui/*` — launcher toggle, composer 2000-char cap, streaming buffer appends, suggested-question tap, error banner, responsive positioning.
- `embed.ts` — auto-upgrade of `<webchat-widget>` from `data-widget-id`.
- `theme/*` — CSS custom properties applied on host element; shadow DOM style isolation (host CSS cannot break widget, widget CSS cannot leak).
- `offline/*` — fetch reject/5xx/timeout/abort scenarios, offline banner, retry, config-fallback defaults, `401`-then-reissue single retry.
- Bundle size gate — `gzip -9` on the IIFE must be ≤ 100 KB (fail) / warn ≥ 90 KB.

### 10.3 Gates

```
pnpm lint && pnpm typecheck && pnpm test && pnpm build        # dashboard + widget
cd backend && ruff check . && ruff format --check . && mypy .  # plus pytest
git diff -- backend                                           # confirm no auth/RAG/knowledge changes
```

Live E2E stays **blocked** until MongoDB/Redis/worker infra exists (unchanged since Phase 6); record in the Phase 8 verification report.

---

## 11. Migration Risks & Mitigations

| #   | Risk                                                                                                                                                                                                                                                                                                                                                          | Impact                                           | Mitigation                                                                                                                                                                                                      |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| M1  | **F1 conversation-memory ordering (Phase 6, Medium)** — `_load_history` previously returned the **oldest** turns. **Already fixed in Phase 6:** `MongoChatMessageRepository.list_recent` (`backend/repositories/chat_message_repository.py:50-59`) sorts `created_at` DESC, applies `limit`, then reverses → chronological, latest `CHAT_MEMORY_TURNS` turns. | None (resolved)                                  | **Verification only:** add/keep a regression test asserting memory is the latest `N` turns in chronological order; no code change to the RAG pipeline. No fix task in Phase 8.                                  |
| M2  | **CORS regression on dashboard API** — naive wildcard CORS could leak `allow_credentials` semantics or weaken the dashboard surface.                                                                                                                                                                                                                          | Break or weaken existing auth'd API              | Narrow ASGI middleware scoped to `/api/widget/` only; dashboard CORS config untouched; **CORS isolation tests** (§10.1) assert wildcard on widget surface and unchanged credentialed CORS on dashboard surface. |
| M3  | **Widget config cache staleness / leakage** — cached config could serve stale theme or, worse, a disabled widget.                                                                                                                                                                                                                                             | Wrong appearance / disabled widget still serving | Cache `WidgetPublicConfig` only (never secret/hash); TTL 300 s; `enabled` re-checked on chat regardless of cache; invalidation hook on widget mutation.                                                         |
| M4  | **Public endpoint abuse via token minting** — `/sessions` unauthenticated by design.                                                                                                                                                                                                                                                                          | Cost/abuse                                       | Session-issue rate limit per widget/IP; per-visitor + per-widget chat limits; fail-closed limiter.                                                                                                              |
| M5  | **Bundle budget creep** — adding UI + markdown could push past 100 KB.                                                                                                                                                                                                                                                                                        | Perf gate failure (ADR-008 Phase 12)             | Hand-rolled markdown; no framework; **CI gzip gate** (`gzip -9` ≤ 100 KB on the IIFE, warn ≥ 90 KB); size-assert test; audit gzip size per PR.                                                                  |
| M6  | **`widget_script_url`/`api_base_url` dev defaults** — localhost URLs shipped to prod break embedding.                                                                                                                                                                                                                                                         | Widget 404s / CORS errors in prod                | Env-driven; production config validated at deploy; `WIDGET_SCRIPT_URL` must be the public nginx/CDN URL.                                                                                                        |
| M7  | **New endpoint surface increases attack area** — public unauth'd config + sessions endpoints.                                                                                                                                                                                                                                                                 | Recon, scraping                                  | Config is intentionally public (theme/branding); no sensitive data in it (no website_url, no secret, no owner). Validated by security review gate.                                                              |
| M8  | **Existing tenants' widgets** (created Phase 4/7) must work immediately.                                                                                                                                                                                                                                                                                      | Breaking existing deployments                    | No schema change; public config derives from existing `widgets` docs; verify with an existing widget_id in tests.                                                                                               |
| M9  | **Backend rule: no auth/RAG/knowledge changes** — public chat must not fork the pipeline.                                                                                                                                                                                                                                                                     | Divergent behavior                               | Chat route only adapts auth/limits; all pipeline logic stays in `RagService`. Diff gate in CI.                                                                                                                  |

---

## 12. Rollout Milestones

1. **M1 — Backend foundations:** **verify F1 memory-ordering fix (regression test only, no fix task)**; `find_by_widget_id`; widget-session token helpers; config cache; keyed rate limiter; spam filter; message cap.
2. **M2 — Public API:** `widget.py` router (`config`/`sessions`/`chat`), schemas, tenant-validation dependencies, public CORS middleware, config wiring, backend tests + gates.
3. **M3 — SDK core:** visitor cookie/session/sse/embed modules + Web Component + shadow DOM scaffolding + unit tests.
4. **M4 — SDK UI:** launcher, window, composer, bubbles, suggested questions, streaming; restricted markdown sanitizer; theme engine; responsive pass; accessibility (focus trap, aria, contrast) pass.
5. **M5 — Integration & polish:** gzip bundle gate, offline/retry states, error taxonomy, accessibility audit, README/embed docs.
6. **M6 — Verification:** full gates (lint/typecheck/test/build + ruff/mypy/pytest), CORS isolation tests, live smoke when infra available, write `docs/Phase-8-Verification-Report.md`, tag `v0.8-widget-sdk-complete`.

## 13. Definition of Done

- [ ] Public widget endpoints live under `/api/widget/v1` (versioned, additive-only contract); dashboard + auth API unchanged.
- [ ] Widget session tokens verified on every chat request; tenant/website/visitor scoping proven by tests.
- [ ] `widget_session_token` and `chat_session_id` lifecycles explicitly separated (§3.2.1) and covered by tests.
- [ ] Per-widget and per-visitor rate limits, session-issue limit, 50-msg cap, spam filter enforced and tested.
- [ ] Widget config cached (Redis 5 min) and correct under tenant suspension.
- [ ] Widget SDK renders as a **custom element with a closed shadow DOM root**; theme via CSS custom properties; style-isolation verified.
- [ ] Markdown renderer enforces the §4.1 allowlist; XSS corpus tests pass (raw HTML, dangerous schemes, images, handlers all rejected).
- [ ] Visitor identity via anonymous **cookie** (`wc_visitor`) with in-memory fallback — no `localStorage`/`sessionStorage`.
- [ ] SDK mounts from `data-widget-id`; launcher/chat/streaming/markdown/suggested/theming/responsive all functional.
- [ ] **Gzip gate:** IIFE `gzip -9` ≤ 100 KB (warn ≥ 90 KB), CI-enforced.
- [ ] **Accessibility:** keyboard operable, visible focus, `role="dialog"`, `aria-live` streaming, contrast ≥ 4.5:1, reduced-motion honored (WCAG 2.2 AA).
- [ ] **Offline handling:** timeouts, SSE drop, 401 single-retry, config-fallback defaults, offline banner + retry — all tested.
- [ ] **CORS isolation** between dashboard and widget surfaces proven by tests.
- [ ] All automated gates green; Phase 8 verification report written.
- [ ] No changes to auth, RAG, or knowledge code (`git diff -- backend` shows only additive widget modules); F1 verified, not re-fixed.

---

## 14. Files touched (planned)

**Backend (additive only):** `backend/api/routes/widget.py` · `backend/schemas/widget.py` · `backend/services/widget/widget_service.py` · `backend/services/widget/spam_filter.py` · `backend/api/middleware.py` (widget CORS) · `backend/api/deps.py` (keyed limiter) · `backend/core/security.py` (widget-session token) · `backend/core/config.py` (widget settings) · `backend/core/database.py` (no change expected) · `backend/repositories/widget_repository.py` (`find_by_widget_id`) · tests.

**Frontend:** `apps/widget/src/**` (custom element + shadow DOM modules above) + tests (SDK core, markdown XSS corpus, offline/network, a11y, CORS-adjacent fetch mocks) + gzip bundle-size gate. `apps/dashboard` unchanged (read-only widget page; embed already works). `axe-core` as a devDependency only (test harness, never shipped).

**Docs:** `docs/Phase-8-Widget-SDK-Implementation-Plan.md` (this file) → `docs/Phase-8-Verification-Report.md` at completion.
