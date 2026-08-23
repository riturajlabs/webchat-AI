## Phase 4 - UX / Developer Experience

### P3-1. (from earlier) `widget_session_origin_guard` does not handle `Origin: null` explicitly

(this is a P3-low priority item, relisted for completeness in Phase 4 context)

1. **Issue name**: Origin: null explicit handling (P3-1)

2. **Why it matters**: Sandboxed iframes get a less-actionable error code than they should.

3. **Expected code changes**: Detect `Origin: null` and raise a dedicated error like `WIDGET_SANDBOXED_EMBED`.

4. **Risk level**: Low

---

### P3-2. Widget config cache on the SDK does not survive page reloads

(this is a P3-low priority item)

1. **Issue name**: Config cache ETag survival (P3-2)

2. **Why it matters**: Slow iteration during design/QA work.

3. **Expected code changes**: Honor `If-None-Match` (ETag) header from config endpoint.

4. **Risk level**: Low

---

### P3-3. The widget SDK does not expose a programmatic event hook for embedders

1. **Issue name**: Embedder event hook API (P3-3)

2. **Why it matters**: Embedders cannot integrate analytics, A/B testing, or session-replay hooks.

3. **Expected code changes**: Add `window.WebChatWidget.on(event, handler)` registration API for: `open`, `close`, `error`, `send`, `feedback`.

4. **Risk level**: Medium — new public API

---

### P3-4. Legacy UUID fallback

1. **Issue name**: Legacy UUID fallback (P3-4)

2. **Why it matters**: Negligible — IE unsupported elsewhere.

3. **Expected code changes**: Drop the legacy fallback or document that unsupported browsers will not load the widget.

4. **Risk level**: Trivial

---

### P3-5. Widget SDK inlines SVG icons — no sprite reuse, no cacheable asset

1. **Issue name**: SVG sprite reuse (P3-5)

2. **Why it matters**: Negligible (SVGs are tiny) but worth flagging.

3. **Expected code changes**: External sprite via a fetch + cache once per session, or shared CSS-only icons.

4. **Risk level**: Small

---

### P3-6. Missing TypeScript declarations entry point

1. **Issue name**: Missing TypeScript declarations (P3-6)

2. **Why it matters**: TypeScript embedders lose typing benefits. `apps/widget/package.json` — no `types` / `typings` field referenced in the dist output.

3. **Expected code changes**: Add `vite-plugin-dts` or hand-authored `webchat-widget.d.ts` to the build.

4. **Risk level**: Small — build configuration change

---

### P3-7. `/api/widget/v1/config/{widget_id}` returns `bot_name` / `welcome_message` / `placeholder` with no language fallback

(this was P3-7 in the audit, moving to Phase 4)

1. **Issue name**: Config i18n fields (P3-7)

2. **Why it matters**: Tenant configures welcome_message in English serves English-only to all visitors, regardless of browser locale.

3. **Expected code changes**: Allow `welcome_message_i18n: dict[str, str]` on widget config; widget picks by `navigator.language`.

4. **Risk level**: Medium — config schema change

---

### P3-8. Widget SDK does not announce typing state to screen readers during streaming

1. **Issue name**: Screen reader typing announcements (P3-8)

2. **Why it matters**: Screen-reader users see one "AI is typing" announce at start, then silence until the bubble appears in full. WCAG 4.1.3 polish.

3. **Expected code changes**: Announce "still typing" periodically (every 4-5 s) while streaming.

4. **Risk level**: Low — ARIA update

---

### P3-9. Widget does not support `dir="auto"` for RTL languages in composer

1. **Issue name**: RTL composer support

2. **Why it matters**: RTL visitors see mis-aligned input text. `apps/widget/src/ui/composer.ts:79-90` — `input.placeholder` is set but no `dir` attribute.

3. **Expected code changes**: Set `input.dir = 'auto'` (and the same on assistant bubbles' content blocks).

4. **Risk level**: Trivial — one attribute addition

---

### P3-10. Security headers could include CSP nonce for dynamic inline scripts

1. **Issue name**: CSP nonce support

2. **Why it matters**: `backend/api/middleware.py:23-37` — `Content-Security-Policy: default-src 'none'` is set. While the widget doesn't inline risky scripts, a CSP nonce would tighten security without breaking the widget.

3. **Expected code changes**: Generate and share CSP nonce with widget embed; widget uses nonce for inline script/style tags.

4. **Risk level**: Medium — CSP policy change, requires coordination between backend and widget SDK

---

## Recommended Implementation Order

Based on risk, dependencies, and production impact, the following order is recommended:

### Immediate (P0 — must fix before ship)

1. **P0-1**: Origin allowlist missing-Origin handling (`backend/services/widget/widget_service.py`)
   - Depends on: P0-6 (faithfulness naming — cosmetic, can run in parallel)

2. **P0-2**: Widget session visitor_id binding (`backend/services/widget/widget_service.py`, `apps/widget/src/core/session.ts`)
   - Depends on: Token signature change; migration script for existing sessions

3. **P0-3**: Feedback submit atomicity (`backend/services/feedback/feedback_service.py`, `backend/core/database.py`)
   - Enables: Reliable duplicate prevention for P1-3

4. **P0-4**: Visitor rotation bypass (`backend/api/deps.py`)
   - Complements: P1-10 (NAT-friendly rate limit keys)

5. **P0-5**: SSE partial-content preservation (`apps/widget/src/stream/client.ts`)
   - Prevents: Lost partial answers on network-drop retry

6. **P0-6**: Faithfulness scorer honesty (`backend/services/chat/rag_service.py`, docs)
   - Renaming only: low risk, high clarity improvement

### Short-term (P1 — ship within hardening sprint)

7. **P1-6**: Cache `allowed_domains` per config (`backend/services/widget/widget_service.py`)
   - Offloads: MongoDB on every config fetch (overlaps with P0-4 optimization)

8. **P1-9**: Don't bill `vector_queries` on cache hit (`backend/services/chat/rag_service.py`)
   - Fixes: Tenant billing accuracy

9. **P1-10**: NAT-friendly rate limit keys (`backend/api/deps.py`)
   - Complements: P0-4 (visitor-aware composite limiter)

10. **P1-4**: Add `visitor_id` to analytics/usage (`backend/services/chat/rag_service.py`, repo models, widget chat body)
    - Enables: Visitor-level observability for growth/abuse analysis

11. **P1-7**: `_retrieve` → dataclass (`backend/services/chat/rag_service.py`)
    - Maintainability: Refactor for future metric additions

12. **P1-5**: SSE chat `Accept-Language` localization (`backend/prompts/rag.py`, `rag_service.py`)
    - UX: Non-English tenants get localized answers

13. **P1-3**: Rate limit fails closed with metrics (`backend/api/deps.py`)
    - Observability: Distinguish Redis down from other failures

14. **P1-2**: Per-tenant rate limit override (`backend/api/deps.py`, `config.py`)
    - Plan-tier differentiation: enterprise feature enablement

15. **P1-1**: Markdown renderer HTML event delegation (`apps/widget/src/ui/bubbles.ts`)
    - Future-proofing: "export chat" / inline preview feature safety

### Medium-term (P2 — performance & polish)

16. **P2-9**: RTL support in composer & bubbles (`apps/widget/src/ui/composer.ts`, `bubbles.ts`)
    - `dir="auto"` on input and content blocks

17. **P2-1**: Lazy `loading` on logo/avatar images (`apps/widget/src/ui/bubbles.ts`, `window.ts`)
    - LCP improvement: `loading="lazy"` + `decoding="async"`

18. **P2-5**: Lazy-import DOMPurify (`apps/widget/src/markdown/render.ts`, build config)
    - Bundle: Faster initial paint, ~30 KB gzipped saved

19. **P2-8**: ConfidenceMetrics tunable weights (`backend/services/chat/confidence.py`, `config.py`)
    - Per-tenant sensitivity tuning

20. **P2-4**: Plan-aware message cap (`backend/services/widget/widget_service.py`, `config.py`)
    - Enterprise cap scaling per subscription plan

21. **P2-7**: Embedding compatibility check surfacing (`backend/repositories/vector/mongodb.py`)
    - Warning when incompatible chunks detected

22. **P2-3**: Widget SDK `console.error` for production failures (`apps/widget/src/core/mount.ts`)
    - Debugging: embedder `window.WebChatWidget.onError` callback

23. **P2-2**: Session validity window refresh on activity (`backend/services/widget/widget_service.py`)
    - TTL slides with chat activity

### Longer-term (P3 — polish & DX)

24. **P3-8**: Screen reader typing announcements (`apps/widget/src/ui/window.ts`)
    - Periodic "still typing" every 4-5s during SSE streaming

25. **P3-10**: CSP nonce support (`backend/api/middleware.py`, widget SDK)
    - Tightens `default-src 'none'` without breaking widget

26. **P3-7**: Config i18n fields (`backend/api/routes/widget.py`, `apps/widget/src/config/fetch.ts`)
    - `welcome_message_i18n` with `navigator.language` pick

27. **P3-3**: Embedder event hook API (`apps/widget/src/core/mount.ts`, public API)
    - `window.WebChatWidget.on(event, handler)` for `open/close/error/send/feedback`

28. **P3-1**: Origin: null explicit handling (`backend/services/widget/widget_service.py`, `backend/utils/origin.py`)
    - `WIDGET_SANDBOXED_EMBED` error code for sandboxed iframes

29. **P3-6**: TypeScript declarations (`apps/widget/package.json`, build config)
    - `vite-plugin-dts` or hand-authored `.d.ts` entry point

30. **P3-5**: SVG sprite cache (`apps/widget/src/ui/icons.ts`, build pipeline)
    - External sprite fetched once per session

31. **P3-2**: Config cache ETag survival (`apps/widget/src/config/fetch.ts`, backend ETag)
    - 304 honors, immediate config updates reflected

32. **P3-4**: Legacy UUID fallback drop (`apps/widget/src/core/visitor.ts`)
    - Drop Math.random fallback, require `crypto.randomUUID`

### Optional / Future (P3-low / post-hardening)

- P3-9: `dir="auto"` already covered in P2-9
- P2-6: WeakMap memory leak — informational, no fix needed per audit
- P1-9 billing fix already in short-term order

**Ship-ready checkpoint**: After completing items 1–15 (P0 + most P1), the widget is production-ready with all critical security and data-integrity issues resolved. Items 16–31 can be shipped in subsequent releases without blocking.
