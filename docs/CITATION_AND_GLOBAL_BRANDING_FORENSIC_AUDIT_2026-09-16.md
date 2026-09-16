# Forensic Audit: Inline Citation Markers & Global Dynamic WebChat AI Logo System

**Date:** 2026-09-16
**Branch / HEAD (baseline):** `main` @ `bf24144`
**Phase:** 1 — read-only forensic audit (no code changes were made during this phase; the audit produced the evidence and design below)

---

## 1. Executive summary

Two product-visible behaviors are addressed:

1. **Part A — Inline citation markers.** Assistant answers currently render inline citation
   markers (`[1]`, `[2]`, `[3]`) as separate clickable chips inside the answer prose. The
   product wants the prose to be clean (no marker remnants) while the source material is
   still surfaced via the native **"Learn more" source cards** rendered below each answer.
   This is a pure presentation-layer change in the widget SDK — the backend SSE contract,
   the source payload ordering, and the source cards themselves are untouched.

2. **Part B — Global dynamic WebChat AI logo system.** Chatbot identity rendering must
   follow a single deterministic precedence:
   **custom chatbot logo/avatar → official WebChat AI logo (default)**.
   Today the widget's default identity is a _generic AI circle glyph_ plus a cascade of
   _host-website_ identity (website logo → website favicon → host page favicon) inherited
   from a prior multi-tenant branding audit. The product decision is that a chat widget's
   default identity is the **official WebChat AI brand mark**, not the host website's or a
   generic glyph. Every chatbot-identity surface must resolve the same way.

This document is the written forensic record: evidence, data flow, surface inventory,
design decisions, exact change map, and the verification plan. It supersedes the widget
logo fallback hierarchy defined in
`FRONTEND_LAYOUT_KNOWLEDGE_LOGO_FORENSIC_AUDIT_2026-09-14.md` (Issue 4) for chatbot
identity purposes.

---

## 2. Methodology

- The audit phase was **read-only**: every claim below is backed by a file/line reference
  of the repository at `bf24144`.
- Frozen subsystems (evidence only, no edits): `backend/ai/**`,
  `backend/services/chat/rag_service.py`, `backend/api/sse.py`, `crawler`, `worker`,
  `docker/**`, environment files.
- Implementation scope (Phase 2): `apps/widget/**` (renderer, bubbles, branding, styles,
  tests), `apps/dashboard/.../widget-preview.tsx` (presentation default), tests, this doc.
- Bundle-size gates for the widget SDK were measured against `dist/` artifacts at baseline
  (see §7.3) to decide how the official default logo can ship inside the self-contained
  embed bundle.

---

## 3. Part A — Inline citation markers: evidence & design

### 3.1 Where the `[n]` markers come from

- Assistant answers are RAG-grounded. The backend yields a **`sources` SSE event BEFORE
  the content deltas**:
  - `backend/services/chat/rag_service.py:1439` — `yield sources_event(...)` precedes
    generation deltas.
  - `backend/services/chat/rag_service.py:2232` — an empty `sources: []` is yielded on the
    no-rag path.
- The widget's stream (`apps/widget/src/stream/client.ts`) therefore has
  `message.sources` settled **before** the first content token arrives, for every frame.
- The model is prompted to emit `[n]` markers in the text pointing at the n-th source
  card. These markers are raw text tokens in `message.content`.

### 3.2 How markers render today (two separate mechanisms)

The SDK renders markdown in `apps/widget/src/markdown/render.ts`. `renderInline` runs a
single regex over inline text:

```
... | (`([^`]+)`) | (~~([^~]+)~~) | (?<!!)(\[([^\]]+)\]\(([^)\s]+)(?:\s+[^)]*)?\)) | (\[(\d{1,2})\])
```

Order matters: **bold → italic → inline code → strike → markdown links → citation
markers**. Fenced code blocks (`\`\`\``, handled by the block loop) never reach
`renderInline`, so `arr[1]` in code is protected by construction.

- **Render-time chips (streaming + completed).** When `countValidSources(sources) > 0`,
  an in-range marker `[n]` (`1 <= n <= maxCitations`) becomes
  `<button class="wc-citation" data-source-index="n">n</button>`
  (`render.ts:142-147`). Out-of-range markers stay literal escaped text.
- **Post-render upgrade (completed only), a second, redundant path.**
  `apps/widget/src/ui/bubbles.ts:509` `syncCitations()` walks the rendered text nodes and
  upgrades any remaining `[n]` text into buttons via `createCitationLink()`
  (`bubbles.ts:586`). It rejects nodes under `CODE`/`PRE`/`A`/`BUTTON`. The chip click is
  delegated in `wireMessageActions` (`bubbles.ts:831`) → `jumpToSource()`
  (`bubbles.ts:600`), which expands the collapsed "View all sources" list, scrolls the
  matching card into view, and flashes it (`wc-source-highlight`).
- Chip styling lives in `apps/widget/src/ui/styles.ts:729-760` `.wc-citation`;
  the card flash animation lives at `styles.ts:762-777`.

### 3.3 Why this is a user-visible problem

- The screenshot example `... course commencement [3] [4] [6] [7].` renders with four
  chip buttons inline in the prose. The product wants plain prose:
  `.… course commencement.` with the cards below via the native Sources deck.
- Because two code paths reproduce chips, removing the markers cleanly is only safe if
  **both** are disabled (see §3.5 "single removal point").

### 3.4 Sources deck must stay intact

The source cards ("Learn more") are rendered/styled by `syncSources()` + `createSourceCard()`
(`bubbles.ts:118`, `bubbles.ts:346`), the `.wc-sources*` block in `styles.ts`,
`TRAILING_SOURCES_PATTERN` / `stripTrailingSources()` in `render.ts:211-219`, and the
sponsored "Learn more" label (`SOURCES_LABEL`). **None of these are touched.**

### 3.5 The fix: one removal point in the renderer

- In `renderInline`, an **in-range** `[n]` marker is now dropped (contributes nothing),
  instead of emitting a chip. Matcher/escaping/alternation order for code and links is
  unchanged, so:
  - `arr[1]` inside inline code → still `<code>arr[1]</code>`
  - `[1]` inside a fenced code block → still literal
  - `[text](url)` markdown links (incl. digit-`[ ]`-text links) → still anchors
  - out-of-range markers (`[99]`) → still literal text
  - **no sources** present (maxCitations = 0) → markers stay literal, so conversational
    answers are never altered
- **Whitespace normalization:** when an in-range marker is dropped, one adjacent space
  (leading preferred) is consumed so `Pricing is per seat [1].` renders as
  `Pricing is per seat.` and `... [3] [4] [6] [7].` renders as `... .` → `...`.
  This avoids double-space artifacts before punctuation.
- **No streaming flicker:** since `sources` settle before the first delta, `maxCitations`
  is constant for the whole answer. Every streamed frame that contains a complete `[n]`
  token therefore drops the same bytes it would drop when completed —
  **streaming output ≡ completed output**, and no chip→text→removal sequence is possible.
  During token delivery a partial `[3` shows the literal bracket until the `]` arrives,
  then the final text settles — identical to how every other mid-stream token behaves.
- **Chip code removal.** All three chip mechanisms die together: the render-time emission
  (`render.ts`), the completed-answer upgrade (`bubbles.ts: syncCitations` /
  `createCitationLink` / `jumpToSource` / `.wc-citation` click delegation), and the chip
  CSS (`styles.ts: .wc-citation` rules). The source-card flash animation
  (`wc-source-highlight`) is also removed because nothing can trigger it anymore.
- **Hardening follow-through:** `data-source-index` is removed from the DOMPurify
  `ALLOWED_ATTR` allowlist since no element emits it any longer. `button` stays (copy
  button uses it).

### 3.6 Explicitly NOT changed (Part A)

- `backend/.../rag_service.py` SSE `sources` event + ordering — frozen.
- `stream/client.ts` ChatSource parsing — untouched.
- Sources deck UI, expand/collapse, "Learn more" label, source cards — untouched.
- `stripTrailingSources` synthetic-block suppression — untouched.
- Single-source-of-citation index (dedup by URL in `countValidSources` /
  `deduplicateSources`) — untouched.

---

## 4. Part B — Global dynamic logo: evidence & design

### 4.1 Canonical brand asset inventory (byte-verified)

| Asset                     | Path                                         | Size                    | Notes                                                                                                                      |
| ------------------------- | -------------------------------------------- | ----------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Official logo (canonical) | `apps/dashboard/public/logo.png`             | 500×500 RGBA, 230,154 B | Source of truth for the brand mark. Served by the dashboard at `/logo.png` (same origin `LogoMark` uses).                  |
| Favicon derivative        | `apps/dashboard/src/app/icon.png`            | 64×64 RGBA, 7,972 B     | **Verified a pixel-perfect downscale of `logo.png`** (sharp resize 500→64, max channel diff = 0, 0/16384 differing bytes). |
| OG image component        | `apps/dashboard/src/app/opengraph-image.tsx` | —                       | Builds from `public/logo.png`. Untouched.                                                                                  |

The single source of truth is **`public/logo.png`**. Every surface either references
`/logo.png` (dashboard `LogoMark`, preview default) or, in the self-contained widget SDK,
embeds a **derived build artifact** that is byte-identical to the committed favicon-grade
derivative (`icon.png`), not a new design (§7 bundle rationale).

### 4.2 Chatbot-identity surface inventory

| #   | Surface                                          | Location                                                                          | Today (default, no custom logo)    | Change                                                                                         |
| --- | ------------------------------------------------ | --------------------------------------------------------------------------------- | ---------------------------------- | ---------------------------------------------------------------------------------------------- |
| W1  | Widget header brand icon                         | `apps/widget/src/ui/window.ts:107` via `renderBrandLogo()`                        | `botGlyph` SVG (generic AI circle) | Default becomes official WebChat AI logo                                                       |
| W2  | Widget assistant bubble avatar                   | `apps/widget/src/ui/bubbles.ts:706` `createEmptyState()` → `renderBrandLogo()`    | `botGlyph` SVG                     | Same default switch                                                                            |
| W3  | Widget (SDK) — launcher                          | `apps/widget/src/ui/launcher.ts` (a chat-bubble SVG affordance)                   | generic chat icon                  | **Unchanged** — generic UI icon, not a brand surface (per "don't change unrelated icons" rule) |
| D1  | Dashboard live preview — header brand icon       | `apps/dashboard/src/features/widget/components/widget-preview.tsx:110-114`        | text `"AI"`                        | Default becomes official logo (`/logo.png`), custom avatar/logo override it                    |
| D2  | Dashboard live preview — assistant bubble avatar | same file `:155-160`                                                              | text `"AI"`                        | Same                                                                                           |
| D3  | Dashboard product chrome (navbar, auth, shells)  | `logo-mark.tsx` everywhere                                                        | official `LogoMark`                | **Already the official logo — unchanged**                                                      |
| D4  | Website cards                                    | `website-card.tsx` uses website `preview_image`                                   | website image                      | **Unchanged** — a _website_ surface, not chatbot identity                                      |
| D5  | Account avatar                                   | `avatar.tsx` (user upload)                                                        | user avatar                        | **Unchanged** — user identity, not chatbot identity                                            |
| D6  | Widget test / embed / setup-wizard pages         | `widget-test-page.tsx`, `WidgetTest`, `embed-code.tsx`, `widget-setup-wizard.tsx` | mount the real SDK                 | Flow through automatically (W1/W2 behaviour)                                                   |

### 4.3 Current widget fallback chain (to be superseded)

`apps/widget/src/ui/branding.ts:46-69` + prior audit `2026-09-14` (Issue 4):

```
avatar_url → logo_url → website_logo_url → website_favicon_url → host favicon → botGlyph
```

Backend also merges website identity into `logo_url` when a custom widget logo is absent:
`backend/schemas/widget.py` / `WidgetService.from_widget()`
(`widget_service.py`): `logo_url = widget.logo_url or website_logo_url or
website_favicon_url`. The widget therefore **cannot** distinguish "custom logo" from
"backend-injected website fallback" using `logo_url` alone — it must compare `logo_url`
against the independently-delivered `website_logo_url` / `website_favicon_url` fields.

### 4.4 New product decision (supersedes the 2026-09-14 chain)

Chatbot identity resolves as:

```
1. custom avatar    config.avatar_url                     (highest)
2. custom logo      config.logo_url, ONLY if it differs from
                    website_logo_url AND website_favicon_url
                    (i.e. not the backend-injected website fallback)
3. default          official WebChat AI logo (bundled mark)
4. last resort      botGlyph SVG — defensive only, effectively unreachable
                    (data-URI default cannot fail); renders no broken-image box
```

- `website_logo_url`, `website_favicon_url`, and the host page favicon are **removed from
  the chatbot identity chain**. Website identity still lives on website surfaces
  (D4 website cards preview image). This is a deliberate, documented product decision.
- Runtime recovery is preserved: `onerror` cascades avatar → logo → default, with the
  "'already detached/superseded' guard" retained.
- Unsafe image schemes (`javascript:`, `data:` from user config, protocol-relative)
  remain rejected by `isSafeImageUrl` and `normalizeConfig` (audit W-22) — they simply
  skip straight to the default.
- Alt text stays decorative (`alt=""`, `aria-hidden` already in place) — per requirement.

### 4.5 Why the widget default is a bundled data URI (not an external URL)

| Criterion                                                            | Bundled data URI (chosen)                 | External canonical URL (rejected)                                                                 |
| -------------------------------------------------------------------- | ----------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Self-containment (ADR-008; nginx widget host, offline, local embeds) | ✓ no network dependency                   | ✗ requires a public `webchatai.com` origin at runtime; breaks on blocked/origin-restricted embeds |
| Bundle budget                                                        | +~7.8 KB gzip (§7.3)                      | 0 (but flaky)                                                                                     |
| Brand consistency                                                    | uses the exact pixel-identical brand mark | depends on a remote file that may be replaced                                                     |
| Graceful failure                                                     | cannot fail (no network)                  | needs extra `onerror` handling against the remote copy                                            |

The embedded bytes are exactly the committed `icon.png` (64×64 pixel-identical downscale
of the canonical `logo.png`, §4.1). At every widget avatar size (28–56 px CSS) it is
visually identical to the full-res mark. No new/redesigned logo is introduced.

### 4.6 Dashboard preview default

`widget-preview.tsx` replaces the text-`"AI"` defaults in the header brand slot
(`:110-114`) and assistant bubble avatar (`:155-160`) with

```
config.avatar_url ?? config.logo_url ?? '/logo.png'   (as a plain <img>, object-cover)
```

using the same canonical `/logo.png` the `LogoMark` component references. The dashboard
preview stays a faithful reflection of the real SDK (raw `<img>`, matching the file's
existing `use client` + raw-`<img>` pattern; no `next/image` is introduced into a
test-rendered tree).

### 4.7 Explicitly NOT changed (Part B)

- `apps/widget/src/ui/launcher.ts` chat-bubble toggle icon (generic UI affordance).
- `website-card.tsx` website preview image surface.
- `avatar.tsx` (account avatar) and profile upload flow.
- Dashboard product chrome `LogoMark` usages (already official).
- `apps/widget/src/theme/apply.ts` CSS variable injection (`--wc-logo-url` /
  `--wc-avatar-url`) — host-styling contract stays.
- The `Powered by WebChat AI` footer, footer lockup, widget footer logo.

---

## 5. Change map (Phase 2, proposed)

| File                                                               | Change                                                                                                                                                                         |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `apps/widget/src/markdown/render.ts`                               | Drop in-range `[n]` markers (no chip emission); consume one adjacent space; remove `data-source-index` from `ALLOWED_ATTR`.                                                    |
| `apps/widget/src/ui/bubbles.ts`                                    | Remove `CITATION_MARKER`, `syncCitations()`, `createCitationLink()`, `jumpToSource()`, and the `.wc-citation` click branch in `wireMessageActions`.                            |
| `apps/widget/src/ui/styles.ts`                                     | Remove `.wc-citation` rules and `wc-source-highlight` flash (nothing triggers it).                                                                                             |
| `apps/widget/src/ui/branding.ts`                                   | New precedence (avatar → custom logo → official default data URI → defensive botGlyph); remove `getHostFaviconUrl` + website-chain tie-ins; add `DEFAULT_BRAND_LOGO` constant. |
| `apps/widget/src/ui/window.test.ts`                                | Update "unsafe scheme → glyph" expectation to "unsafe scheme → official default logo".                                                                                         |
| `apps/widget/src/ui/branding.test.ts`                              | Rewrite for new precedence + default logo + onerror cascade.                                                                                                                   |
| `apps/widget/src/markdown/render.test.ts`                          | Rewrite citation tests: markers stripped, code/links/out-of-range preserved, split-delta & streaming==completed coverage.                                                      |
| `apps/widget/src/ui/bubbles.test.ts`                               | Rewrite the W-09 citation describe block, `Sources: [1], [2]` assertion, and empty-state avatar fallback test.                                                                 |
| `apps/dashboard/src/features/widget/components/widget-preview.tsx` | Header + bubble avatar: `avatar_url ?? logo_url ?? '/logo.png'`.                                                                                                               |

---

## 6. Test plan (maps 1:1 to the requested verification items)

**Citations (widget):**

1. `[1]`, `[2]`, `[3]` markers render as clean prose (no `.wc-citation` anywhere).
2. Split-token streaming `[` `3` `]` (three deltas) settles to clean prose.
3. `[3` + `]` split-token arrangement settles to clean prose.
4. Paragraph-end / newline-boundary markers are removed cleanly.
5. Multiple markers in prose are all removed, no double-space before punctuation.
6. Out-of-range / invalid markers (`[0]`, `[99]`, `[abc]`) remain literal.
7. Sources deck (`Learn more` + cards) still renders for the same answer.
8. `arr[1]` inline code unchanged; fenced `[1]` unchanged.
9. Markdown links (incl. numeric link text) still render as anchors.
10. No end-of-stream snap: streaming output === completed output (token-by-token frames).
11. No sources present → markers remain literal (conversational answers untouched).

**Branding (widget):** 12. No custom logo → official default logo renders (data URI) in header + bubble + empty state. 13. Custom avatar overrides default. 14. Custom logo (≠ website fallback) overrides default when no avatar. 15. `logo_url` equal to website fallback is ignored (backend-merged case) → default. 16. Broken/missing custom avatar and logo → onerror cascades to official default; no broken-image box. 17. Unsafe avatar schemes skip to official default. 18. Header and bubble avatar resolve the same value on the same config.

**Dashboard:** 19. WidgetPreview header + bubble avatar default to `/logo.png`; custom avatar/logo override. 20. Mobile/desktop preview render the same default (the same component drives both).

**Build/gates:** 21. `pnpm --filter widget` test/lint/typecheck/build(↳ check-assets + copy-stable) and
`build:size` (90 KB warn / 100 KB hard gzip) pass. Dashboard widget tests pass.

---

## 7. Verification commands & gates

### 7.1 Baseline (measured 2026-09-16, `dist/` at `bf24144`)

| Bundle                       | Raw bytes | gzip bytes |
| ---------------------------- | --------- | ---------- |
| `webchat-widget.iife.min.js` | 136,494   | **41,012** |
| `webchat-widget.umd.cjs`     | 136,689   | 41,082     |
| `webchat-widget.js`          | 172,727   | 46,839     |

### 7.2 Bundle budget math for the embedded default logo

- `icon.png` bytes → base64 data URI: **10,655 chars**; gzip(9) ≈ **7,800 B**.
- Projected IIFE gzip: **~41 KB → ~48.8 KB** — passes the 90 KB warn and 100 KB hard
  gates (`apps/widget/scripts/check-size.mjs`) with ample headroom.
- `check-assets.mjs` (no external CSS `url()`/`@import`/`@font-face`, no loopback hosts):
  a JS string constant `data:image/png;base64,…` triggers no rule; only user-supplied
  http(s) URLs are allowed through `isSafeImageUrl`/`normalizeConfig` (audit W-22).

### 7.3 Commands

```bash
pnpm --filter widget test
pnpm --filter widget lint
pnpm --filter widget typecheck
pnpm --filter widget build          # tsc + vite + copy-stable + check-assets
pnpm --filter widget build:size     # …+ check-size
pnpm --filter widget check:size
pnpm fmt                            # (or repo-equivalent format check)
pnpm --filter dashboard test        # widget-preview/editor affected tests
```

---

## 8. Risks & mitigations

| Risk                                                                | Mitigation                                                                                                                   |
| ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Streaming partial token `[3` visible transiently                    | Same as any mid-stream token; final text equals completed text (tested). No chip flash possible since chip code is deleted.  |
| Double-space / space-before-punctuation artifacts after removal     | Adjacent-space normalization in the renderer (tested with `[1]` and `[3] [4] [6] [7]` cases).                                |
| Embedded logo inflates bundle                                       | Measured: +7.8 KB gzip, final ≈ 48.8 KB vs 100 KB gate.                                                                      |
| Embedded logo drifts from official brand                            | Documented derivation: byte-identical to committed `icon.png`, which is a verified 0-diff downscale of canonical `logo.png`. |
| `logo_url` with backend-merged website fallback treated as "custom" | Compare against `website_logo_url`/`website_favicon_url` before honoring; covered by test item 15.                           |
| Legacy website-identity regression on website-card surface          | Website surfaces untouched (D4); decision documented.                                                                        |
| `next/image` in jsdom for preview default                           | Use the file's existing raw-`<img>` pattern for the default too; no `next/image` introduced into test-rendered tree.         |

---

## 9. Frozen zones (verified zero edits)

- `backend/ai/**`, `backend/services/chat/rag_service.py`, `backend/api/sse.py`
- `crawler/**`, `worker/**`, `docker/**`, `apps/widget/scripts/**` (read-only)
- Environment / secrets files
- Git: no commit/push will be performed; baseline `bf24144` stays untouched by the work
  session unless the user explicitly requests otherwise.

---

## 10. Conclusion

The evidence supports a **single removal point in `renderMarkdown`** for Part A (with the
redundant chip path deleted) and a **three-rung identity precedence with a bundled
pixel-exact official default** for Part B. Both changes are confined to presentation
layers; backend contracts, SSE ordering, the source deck, and unrelated UI icons stay
untouched. Phase 2 implements §5 and verifies §6/§7.
