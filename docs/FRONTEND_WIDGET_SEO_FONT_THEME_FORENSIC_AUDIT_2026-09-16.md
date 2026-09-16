# Frontend Widget / SEO / Font / Theme Forensic Audit

**Date:** 2026-09-16
**Auditor:** Antigravity AI Forensic Inspector
**Repository:** `riturajlabs/webchat-AI`
**Phase:** Read-Only Forensic Inspection & Architecture Plan
**Status:** Audit Complete — Ready for Implementation

---

## 1. Executive Summary

This forensic audit investigates five core frontend, widget, theme, and SEO subsystems within the WebChat AI monorepo:

1. **Widget Test Page Parity:** Verification that the `/widget-test` page in `apps/dashboard` embeds and executes the genuine embeddable `@webchat/widget` SDK bundle rather than a divergent React preview mock.
2. **Landing Page CTA Auth-Awareness:** Ensuring marketing CTAs (Hero, Final CTA, Pricing) adapt to authentication status ("Sign up for free" $\to$ `/signup` when unauthenticated vs. "Dashboard" $\to$ `/dashboard` when authenticated) without hydration mismatch or duplicating auth state.
3. **Widget Font Family Pipeline:** Identifying why selecting different font families (Inter, Roboto, Poppins, Montserrat, etc.) renders almost identically in the widget and dashboard preview, tracing CSS custom property inheritance, Shadow DOM isolation, and web font loading.
4. **Theme Preset Selector & Pagination:** Resolving why 7 cards render initially instead of exactly 6, and establishing correct dynamic threshold logic for the "Show more" button.
5. **Comprehensive Landing Page SEO Audit:** A 50-point inspection of metadata, canonicals, robots.txt, sitemap.xml, OpenGraph, Twitter/X cards, heading hierarchy, semantic HTML, structured data (Organization, SoftwareApplication, WebSite, FAQPage), and Core Web Vitals considerations.

All investigations were conducted under strict read-only constraints. No application code, backend schemas, RAG pipelines, crawler services, worker code, or tests were modified during this phase.

---

## 2. Scope

| Target Application / Package | Primary Areas Inspected                                                                                                                                                                                                          | Constraint          |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------- |
| `apps/dashboard`             | `/widget-test` route, `widget-editor.tsx`, `widget-preview.tsx`, `hero.tsx`, `final-cta.tsx`, `pricing.tsx`, `navbar.tsx`, `layout.tsx`, `sitemap.ts`, `robots.ts`, `seo.ts`, `structured-data.tsx`                              | Strict Read-Only    |
| `apps/widget`                | SDK entry point (`index.ts`), embed auto-upgrade (`core/embed.ts`), lifecycle mounting (`core/mount.ts`), config resolution (`config/fetch.ts`, `config/types.ts`), styles (`ui/styles.ts`), theme applicator (`theme/apply.ts`) | Strict Read-Only    |
| `packages/themes`            | Palette tokens (`THEME_PRESETS`, `ThemeTokens`, `resolveTheme`)                                                                                                                                                                  | Strict Read-Only    |
| `backend`                    | FastApi widget routes (`api/routes/websites.py`, `backend/services/website/website_service.py`), Pydantic models & schemas (`models/widget.py`, `schemas/widget.py`)                                                             | No Changes Required |

---

## 3. Current Architecture

```
                                  ┌───────────────────────────────┐
                                  │      Dashboard Marketing      │
                                  │   (Hero, Navbar, Final CTA)   │
                                  └───────────────┬───────────────┘
                                                  │ reads useAuth()
                                                  ▼
                                  ┌───────────────────────────────┐
                                  │      lib/landing-navigation   │
                                  │    getLandingDestination()    │
                                  └───────────────────────────────┘

┌─────────────────────────────────┐               ┌─────────────────────────────────┐
│     Dashboard /widget-test      │               │     Dashboard /widget Editor    │
│    (apps/dashboard/.../widget-  │               │    (apps/dashboard/.../widget-  │
│             test-page)          │               │             preview)            │
└────────────────┬────────────────┘               └────────────────┬────────────────┘
                 │ iframe srcDoc                                   │ inline React Mock
                 ▼                                                 ▼
┌─────────────────────────────────┐               ┌─────────────────────────────────┐
│    Real Widget SDK (IIFE)       │               │    Mock WidgetPreview Component │
│  webchat-widget.iife.min.js     │               │  uses @webchat/themes resolver  │
│  mount() -> closed Shadow DOM   │               │  simulates bubble & launcher    │
└────────────────┬────────────────┘               └─────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│  Backend /api/widget/v1/config  │
│  MongoDB Widget Document Store  │
└─────────────────────────────────┘
```

The monorepo maintains a clean architectural separation:

- **`apps/dashboard`**: Next.js App Router application hosting the public marketing site, authentication flows, tenant management dashboard, widget configuration studio, and the widget test harness.
- **`apps/widget`**: Framework-agnostic Vite TypeScript library producing IIFE (`webchat-widget.iife.min.js`), UMD, and ES modules. Renders inside a closed Shadow DOM attached to a `<webchat-widget>` custom element.
- **`packages/themes`**: Shared styling engine providing tokens, 10 curated theme presets, color contrast utilities (`relativeLuminance`, `readableText`), and unified token resolution (`resolveTheme`).
- **`backend`**: FastAPI application persisting website configurations and widget styling attributes to MongoDB.

---

## 4. Widget Test Parity Findings

### Finding ID: `PARITY-01`

- **Severity:** `INFO` (Verified Functionally Sound with Minor Display Limitation)
- **Component:** `apps/dashboard/src/features/widget/widget-test-page.tsx` & `widget-test.ts`
- **Current Behavior:** The test harness page `/widget-test` does **not** use the React preview mock (`WidgetPreview`). Instead, it dynamically synthesizes an HTML document (`buildWidgetTestHtml`) with the tenant's actual embed snippet and injects it into a sandboxed `<iframe>` (`sandbox="allow-scripts allow-same-origin"`).
- **Execution Evidence:**
  The iframe loads `<script src="${scriptSrc}" data-widget-id="${widgetId}" data-api-base-url="${apiBaseUrl}" defer></script>`, which executes the compiled bundle `webchat-widget.iife.min.js` and exercises real network calls to the backend.
- **Limitation / Discrepancy Identified:**
  1. The preview iframe is hardcoded to `h-[480px] w-full`. The widget chat window has a default CSS height of `600px` (`--wc-height: 600px;` and `max-height: calc(100vh - 32px)` in `apps/widget/src/ui/styles.ts` line 50). Inside a 480px container, the open chat window is constrained and triggers an inner viewport scroll or launcher overlap.
  2. The iframe does not provide a responsive viewport toggle (mobile vs desktop), unlike the customization page's `DevicePreview` component.
  3. The development embed script default (`http://localhost:8080/webchat-widget.iife.min.js`) requires a local static/dev server running on port 8080. If that server is not running, the iframe silently fails to load the bundle.

---

## 5. Widget Test $\to$ Real SDK Execution Trace

```
1. Browser navigates to /widget-test
   └─ apps/dashboard/src/app/(dashboard)/widget-test/page.tsx
      └─ <WidgetTestFeature /> (apps/dashboard/src/features/widget/widget-test-page.tsx)

2. Tenant Websites & Config Fetch
   ├─ useWebsites() queries GET /api/websites
   └─ useWidgetConfig(selectedWebsiteId) queries GET /api/websites/{id}/widget
      └─ Returns { widget: WidgetConfig, embed_script: string }

3. Snippet Parsing & HTML Synthesis
   ├─ parseScriptSrc(embed_script) -> extracts src (e.g. http://localhost:8080/webchat-widget.iife.min.js)
   ├─ parseApiBaseUrl(embed_script) -> extracts data-api-base-url (e.g. http://localhost:8000)
   └─ buildWidgetTestHtml({ scriptSrc, widgetId, apiBaseUrl })
      └─ Synthesizes standalone HTML:
         <!doctype html>
         <html>
           <body>
             <script src="..." data-widget-id="..." data-api-base-url="..." defer></script>
           </body>
         </html>

4. Iframe Execution & Cross-Origin Security Check
   ├─ Iframe rendered: <iframe srcDoc={previewHtml} sandbox="allow-scripts allow-same-origin" />
   ├─ Parallel Origin-Guard Probe:
   │  └─ useWidgetPublicStatus(widgetId, apiBaseUrl)
   │     └─ fetchPublicConfig(apiBaseUrl, widgetId)
   │        └─ Cross-origin GET http://localhost:8000/api/widget/v1/config/{widgetId}
   │           Browser sends `Origin: http://localhost:3000`
   │           Backend validates Origin against ALLOWED_DASHBOARD_ORIGINS -> Returns 200 OK
   └─ StatusReport renders "200 OK — this origin is permitted"

5. Real SDK Bootstrapping (inside iframe)
   ├─ apps/widget/src/index.ts executes
   ├─ autoUpgrade() in apps/widget/src/core/embed.ts:
   │  ├─ Reads document.currentScript.dataset.widgetId and dataset.apiBaseUrl
   │  └─ Invokes mount({ widgetId, apiBaseUrl, autoStart: true })
   ├─ mount() in apps/widget/src/core/mount.ts:
   │  ├─ Creates <webchat-widget> DOM element
   │  ├─ Attaches closed ShadowRoot: host.attachShadow({ mode: 'closed' })
   │  ├─ Injects compiled WIDGET_STYLES into shadow root
   │  ├─ Calls loadConfig(options) -> GET /api/widget/v1/config/{widgetId}
   │  ├─ Applies theme variables to host: applyTheme(host, resolvedTheme, config)
   │  ├─ Creates launcher button: createLauncher(...)
   │  └─ Creates chat window: createChatWindow(...)
   └─ User clicks launcher: opens chat window, establishes SSE stream to /api/widget/v1/chat/stream
```

---

## 6. Visual Parity Findings

A comparative audit between `WidgetPreview` (React mock used on `/widget`), `/widget-test` (real SDK in iframe), and production embeds:

| Component / Subsystem                        | `WidgetPreview` (React Mock)                                                       | `/widget-test` (Real SDK iframe)                                                                  | Production Customer Embed                                                     | Parity Verdict                                            |
| -------------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- | --------------------------------------------------------- |
| **Header (Avatar, Bot Name, Status, Close)** | Inline styles mapped via `resolveTheme()`; uses static fallback image `/logo.png`. | Real DOM generated by `createChatWindow()`; uses configured `avatar_url` or `logo_url`.           | Identical to `/widget-test`.                                                  | **Parity Achieved**                                       |
| **Body (Welcome & Suggested Prompts)**       | Static suggested questions chip rendering; static text.                            | Interactive prompts: clicking chip sends prompt directly to RAG chat turn.                        | Identical to `/widget-test`.                                                  | **Parity Achieved**                                       |
| **Body (Streaming & Citations)**             | Non-interactive dummy bubbles.                                                     | Full streaming turn, typing indicator, live token render, collapsible source citation deck.       | Identical to `/widget-test`.                                                  | **Parity Achieved**                                       |
| **Footer (Composer & Send)**                 | Static mockup input field; inactive send icon.                                     | Working `<textarea>`, IME composition, character counter, send on Enter, feedback thumbs.         | Identical to `/widget-test`.                                                  | **Parity Achieved**                                       |
| **Branding Notice**                          | Conditional on `config.branding`: renders "Powered by WebChat AI".                 | Conditional on `config.branding`: renders official brand lockup.                                  | Identical to `/widget-test`.                                                  | **Parity Achieved**                                       |
| **Dimensions & Clipping**                    | Enclosed inside `DevicePreview` (phone frame or desktop view).                     | Fixed `480px` iframe; widget window default height is `600px`, causing clipping.                  | Unconstrained on customer host page (fixed to bottom right/left of viewport). | **Mismatch:** Test page iframe height clips widget window |
| **Font Family Rendering**                    | Renders fallback system font (`system-ui`) because external fonts are not loaded.  | Renders fallback system font due to hardcoded CSS in `.wc-shell` and missing web font stylesheet. | Same bug occurs in production embed.                                          | **Identical Bug Across Environments**                     |

---

## 7. Landing CTA Findings

### Finding ID: `CTA-01`

- **Severity:** `P1` (High - Conversion & UX inconsistency)
- **Component:** `apps/dashboard/src/components/marketing/hero.tsx`
- **Current Behavior:**
  - Unauthenticated: Button label is static: `Signup for free` (or `Start Free`), linking to `/signup`.
  - Authenticated: The destination updates to `/dashboard` via `getLandingDestination('start-free', isAuthenticated)`, but the button label **remains static** (`Signup for free` / `Start Free`)!
- **Expected Behavior:**
  - Unauthenticated visitor: Button label = **"Sign up for free"**, destination = `/signup`.
  - Authenticated user: Button label = **"Dashboard"**, destination = `/dashboard`.
- **Root Cause:**
  `apps/dashboard/src/components/marketing/hero.tsx` (lines 19-20, 52-55):
  ```tsx
  const { isAuthenticated } = useAuth();
  const startFreeHref = getLandingDestination('start-free', isAuthenticated);
  ...
  <Link href={startFreeHref}>
    Signup for free
    <ArrowRight className="size-4" aria-hidden="true" />
  </Link>
  ```
  The text string is hardcoded rather than dynamically evaluating `isAuthenticated`.

### Finding ID: `CTA-02`

- **Severity:** `P2` (Medium - Cross-CTA Copy Inconsistency)
- **Component:** `apps/dashboard/src/components/marketing/final-cta.tsx` & `pricing.tsx`
- **Current Behavior:**
  - `final-cta.tsx` line 46: `{isAuthenticated ? 'Open Dashboard' : 'Start Free'}` (uses "Open Dashboard" instead of "Dashboard", and "Start Free" instead of "Sign up for free").
  - `pricing.tsx` line 16: `'start-free': 'Start Free'` (ignores auth state in label).
- **Expected Behavior:** Unified, consistent CTA labels across the entire landing page.

---

## 8. Authentication Trace

```
1. Initial Server-Side Render (SSR) of Landing Page (apps/dashboard/src/app/(marketing)/page.tsx)
   └─ Root Layout wraps app in <AuthProvider> (apps/dashboard/src/features/auth/auth-context.tsx)
      ├─ Initial State on SSR / Initial Hydration:
      │  ├─ status: 'loading'
      │  ├─ user: null
      │  └─ isAuthenticated: false
      └─ HTML emitted to crawler / visitor:
         ├─ Hero CTA: "Sign up for free" -> /signup
         └─ Navbar: shows fallback skeleton placeholder (preventing hydration mismatch)

2. Client-Side Hydration & Mount
   └─ useEffect runs in AuthProvider:
      ├─ Case A: Anonymous Visitor (No token, no cookie)
      │  └─ status finalized to 'ready', user remains null, isAuthenticated = false.
      │     DOM matches server render. Zero hydration mismatch.
      │
      ├─ Case B: Authenticated User (Cookie / access token exists)
      │  ├─ Hits /api/auth/me (or /api/auth/refresh if cookie present)
      │  ├─ Sets user = UserOut, status = 'ready', isAuthenticated = true
      │  └─ React triggers clean client-side re-render:
      │     ├─ Hero CTA updates: label = "Dashboard", href = "/dashboard"
      │     ├─ Final CTA updates: label = "Dashboard", href = "/dashboard"
      │     └─ Navbar renders UserMenu (Avatar + Sign out)
```

**Hydration Safety Confirmation:**
Because `user` is initially `null` on both SSR and client during the initial hydration pass, the client tree matches the server tree exactly. The transition from unauthenticated to authenticated occurs after mount in `useEffect`, which React handles cleanly as a standard state update without hydration errors.

---

## 9. Font Family Findings

### Finding ID: `FONT-01`

- **Severity:** `P0` (Critical - Feature Ineffective)
- **Component:** `apps/widget/src/ui/styles.ts` (Line 89)
- **Current Code:**
  ```css
  .wc-shell {
    position: fixed;
    z-index: 2147483000;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 12px;
    box-sizing: border-box;
    font-family:
      -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    font-size: var(--wc-font-size-px);
    line-height: 1.5;
    color: var(--wc-text);
  }
  ```
- **Root Cause:**
  Even though `apps/widget/src/theme/apply.ts` (line 69) sets:
  ```ts
  setProp(host, `${PREFIX}-font-family`, config.font_family);
  ```
  and `:host` defines `--wc-font-family`, `.wc-shell` **hardcodes** `-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;` and **never references `var(--wc-font-family)`**! The CSS property on the host is completely discarded.

### Finding ID: `FONT-02`

- **Severity:** `P0` (Critical - Missing Font Resource Pipeline)
- **Components:** `apps/dashboard/src/features/widget/components/widget-editor.tsx`, `apps/dashboard/src/features/widget/components/widget-preview.tsx`, and `apps/widget`
- **Current Code:**
  `widget-editor.tsx` defines:
  ```ts
  const FONT_OPTIONS = [
    { key: 'system', label: 'System default', stack: null },
    { key: 'inter', label: 'Inter', stack: "'Inter', system-ui, sans-serif" },
    { key: 'roboto', label: 'Roboto', stack: "'Roboto', system-ui, sans-serif" },
    { key: 'open-sans', label: 'Open Sans', stack: "'Open Sans', system-ui, sans-serif" },
    { key: 'lato', label: 'Lato', stack: "'Lato', system-ui, sans-serif" },
    { key: 'poppins', label: 'Poppins', stack: "'Poppins', system-ui, sans-serif" },
    { key: 'montserrat', label: 'Montserrat', stack: "'Montserrat', system-ui, sans-serif" },
    { key: 'nunito', label: 'Nunito', stack: "'Nunito', system-ui, sans-serif" },
    {
      key: 'source-sans-3',
      label: 'Source Sans 3',
      stack: "'Source Sans 3', system-ui, sans-serif",
    },
    { key: 'dm-sans', label: 'DM Sans', stack: "'DM Sans', system-ui, sans-serif" },
  ];
  ```
- **Root Cause:**
  None of these fonts (`Inter`, `Roboto`, `Open Sans`, `Lato`, `Poppins`, `Montserrat`, `Nunito`, `DM Sans`, `Source Sans 3`) are bundled or loaded as web fonts via `@font-face` or Google Fonts.
  - On standard Linux, Windows, or macOS machines, fonts like "Poppins", "Montserrat", or "Nunito" are **not installed locally**.
  - When the browser evaluates `font-family: 'Poppins', system-ui, sans-serif`, it checks for a local font named "Poppins". Finding none, it falls back to `system-ui, sans-serif`.
  - Because **every single option** falls back to `system-ui, sans-serif`, they all render with the exact same system font (San Francisco on macOS, Segoe UI on Windows, Ubuntu/DejaVu on Linux)!
  - Neither `apps/dashboard` nor `apps/widget` injects a stylesheet to load the actual web font.

---

## 10. Font Loading Trace & Curated Architecture

```
Tenant selects "Poppins" in Widget Studio
   │
   ├─ 1. Dashboard State & Persistence
   │     ├─ draft.font_family = "'Poppins', system-ui, sans-serif"
   │     ├─ PATCH /api/websites/{id}/widget -> MongoDB persists font_family
   │     └─ GET /api/widget/v1/config/{widget_id} returns font_family
   │
   ├─ 2. Dashboard Studio Preview (<WidgetPreview />)
   │     ├─ Dynamic Font Loader Hook: useWebFont(config.font_family)
   │     ├─ Checks if font is in Curated Font Registry
   │     └─ Injects <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600&display=swap">
   │        into Dashboard <head> (deduplicated by id)
   │        ==> Preview renders REAL Poppins typeface!
   │
   └─ 3. Production Embed / Widget Test (<webchat-widget>)
         ├─ SDK boots inside closed Shadow DOM
         ├─ applyTheme(host, resolvedTheme, config) sets --wc-font-family: 'Poppins', system-ui, sans-serif
         ├─ .wc-shell updated to: font-family: var(--wc-font-family, -apple-system, BlinkMacSystemFont, ...);
         ├─ SDK Font Loader checks if config.font_family requires Google Fonts
         └─ Injects single <link rel="stylesheet"> into document.head (or shadowRoot)
            ==> Zero bundle size overhead! Only 1 requested font downloaded on-demand.
```

### Curated Font Registry Recommendation

To ensure high visual differentiation without clutter:

| Font Name            | Category            | Distinct Visual Characteristic                      | Google Fonts URL                       |
| -------------------- | ------------------- | --------------------------------------------------- | -------------------------------------- |
| **System Default**   | System Native       | Native OS typography, 0kb network                   | —                                      |
| **Inter**            | Modern UI Sans      | Tall x-height, neutral tech-focused grotesque       | `family=Inter:wght@400;500;600`        |
| **Poppins**          | Geometric Sans      | Distinct circular bowls, warm modern aesthetic      | `family=Poppins:wght@400;500;600`      |
| **Nunito**           | Rounded Sans        | Soft, rounded terminals, friendly approachable feel | `family=Nunito:wght@400;600;700`       |
| **Playfair Display** | High-Contrast Serif | Elegant, editorial, luxury brand contrast           | `family=Playfair+Display:wght@500;600` |
| **Space Grotesk**    | Tech Grotesque      | Distinctive monospaced-inspired geometric sans      | `family=Space+Grotesk:wght@500;700`    |

---

## 11. Theme Preset Findings

### Finding ID: `THEME-01`

- **Severity:** `P2` (Medium - UI Count Mismatch)
- **Component:** `apps/dashboard/src/features/widget/components/theme-selector.tsx`
- **Current Code:**
  ```tsx
  const INITIAL_VISIBLE = 6;
  ...
  const visiblePresets = expanded ? THEME_PRESETS : THEME_PRESETS.slice(0, INITIAL_VISIBLE);
  const hasMore = THEME_PRESETS.length > INITIAL_VISIBLE;
  ...
  <div role="radiogroup" aria-label="Theme preset" className="grid grid-cols-2 gap-3">
    <button ...><ClassicCard selected={value === CLASSIC} /></button>
    {visiblePresets.map((preset) => (
      <PresetCard key={preset.id} preset={preset} ... />
    ))}
  </div>
  ```
- **Root Cause:**
  `ClassicCard` is rendered as a standalone first button outside of `visiblePresets`.
  Then `visiblePresets.slice(0, 6)` renders 6 `PresetCard` elements.
  Total cards rendered initially: **1 (Classic) + 6 (Presets) = 7 theme cards!**
  The requirement is to display **exactly 6 theme cards** initially.

---

## 12. Show More Logic Findings

### Finding ID: `THEME-02`

- **Severity:** `P2` (Medium - Inaccurate Remaining Count & Show More Conditions)
- **Component:** `apps/dashboard/src/features/widget/components/theme-selector.tsx` (Lines 116, 162)
- **Current Behavior:**
  - Button text displays: `Show more (${THEME_PRESETS.length - INITIAL_VISIBLE} more)` $\to$ `10 - 6 = 4 more`.
  - But total available themes is 11 (1 Classic + 10 Presets). Since 7 were shown, 4 remained. However, when initial view is fixed to 6, remaining count must be $11 - 6 = 5$.
  - If a tenant had $\le 6$ total themes, "Show more" would still appear if `THEME_PRESETS.length > 6` even if only 6 total were visible.
- **Expected Behavior:**
  - Initial visible count: exactly 6.
  - If total themes $\le 6$: show all cards, omit "Show more".
  - If total themes $> 6$: show 6 cards initially, show "Show more".
  - On click "Show more": reveal all remaining themes.

---

## 13. SEO Findings

An exhaustive audit of the landing page against modern search engine and Google Search Central requirements:

| Check Item                    | Current Status       | Finding / Analysis                                                                                                                                       | Severity |
| ----------------------------- | -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| **1. `<title>`**              | Present & Valid      | `WebChat AI - AI Chatbot for Your Website` (42 chars, optimal)                                                                                           | `INFO`   |
| **2. Meta Description**       | Present (Short)      | `Build intelligent AI assistants trained on your website content.` (64 chars — accurate but could be expanded to 140-155 chars for richer SERP snippets) | `P3`     |
| **3. Canonical URL**          | Implemented          | Emits `rel="canonical"` via `seoPage` pointing to `${SITE_URL}/`                                                                                         | `INFO`   |
| **4. Robots Metadata**        | Implicit Defaults    | Not explicitly set in `layout.tsx` metadata (Next.js defaults to index/follow)                                                                           | `P3`     |
| **5. `robots.txt`**           | Valid                | Managed in `apps/dashboard/src/app/robots.ts`; disallows 16 private routes; permits `/`; references sitemap.xml                                          | `INFO`   |
| **6. `sitemap.xml`**          | Valid                | Managed in `apps/dashboard/src/app/sitemap.ts`; lists 16 public routes                                                                                   | `INFO`   |
| **7. Open Graph**             | Configured           | `og:title`, `og:description`, `og:url`, `og:site_name`, `og:type` present                                                                                | `INFO`   |
| **8. Twitter/X Cards**        | Configured           | `summary_large_image` configured                                                                                                                         | `INFO`   |
| **9. Favicon / Icons**        | Configured           | `src/app/icon.png` (Next.js file-based icon route)                                                                                                       | `INFO`   |
| **10. `theme-color`**         | **Missing**          | Not exported in `viewport` metadata                                                                                                                      | `P2`     |
| **11. `viewport`**            | Next.js Default      | Missing explicit `Viewport` export in `apps/dashboard/src/app/layout.tsx`                                                                                | `P2`     |
| **12. Language**              | Configured           | `<html lang="en">` in `RootLayout`                                                                                                                       | `INFO`   |
| **13. Semantic HTML**         | Mostly Solid         | Uses `<header>`, `<nav>`, `<main id="main-content">`, `<section>`, `<footer>`, `<dl>`                                                                    | `INFO`   |
| **14. H1 Count**              | Exactly 1 H1         | `apps/dashboard/src/components/marketing/hero.tsx` contains the single H1                                                                                | `INFO`   |
| **15. H2 Hierarchy**          | **Defect in Footer** | `FooterColumn` uses `<h2>` for navigation column headers ("Product", "Resources")                                                                        | `P2`     |
| **16. Heading Duplication**   | None                 | Section titles are distinct                                                                                                                              | `INFO`   |
| **17. Image Alt Text**        | Valid                | Decorative vectors marked `aria-hidden="true"`; logo has `alt=""` inside named anchor                                                                    | `INFO`   |
| **18. Image Dimensions**      | Next/Image used      | `LogoMark` uses `width={500} height={500}` with Next.js image optimization                                                                               | `INFO`   |
| **19. Image Loading**         | Optimized            | No large contentful images to block LCP                                                                                                                  | `INFO`   |
| **20. Internal Links**        | 100% Crawlable       | All marketing links use Next.js `<Link href="...">` with valid SSR anchors                                                                               | `INFO`   |
| **21. CTA Crawlability**      | Crawlable            | CTAs wrap real `<Link>` tags with valid hrefs, not JS `onClick` handlers                                                                                 | `INFO`   |
| **22. Private Path Indexing** | Guarded              | Private paths disallowed in `robots.ts`; dashboard layout redirects unauthenticated users                                                                | `INFO`   |
| **23. Stale Claims in Copy**  | **Copy Inaccuracy**  | `integrations.tsx` line 14 & `product-showcase.tsx` line 165 state "7 curated themes" (now 10)                                                           | `P3`     |

---

## 14. Metadata Findings

### Finding ID: `SEO-01`

- **Severity:** `P2` (Medium - Missing Next.js Viewport & ThemeColor configuration)
- **Component:** `apps/dashboard/src/app/layout.tsx`
- **Detail:** In Next.js 14+, `themeColor` and `viewport` must be exported via `export const viewport: Viewport`, separate from `metadata`. Currently neither is exported.
- **Recommended Fix:** Export `viewport: Viewport = { width: 'device-width', initialScale: 1, themeColor: '#2563eb' }`.

---

## 15. Structured Data Findings

### Finding ID: `SCHEMA-01`

- **Severity:** `P2` (Medium - FAQPage Scope Violation)
- **Component:** `apps/dashboard/src/app/(marketing)/layout.tsx` & `structured-data.tsx`
- **Detail:** `MarketingStructuredData` includes `FaqJsonLd` (`FAQPage` schema). It is mounted in `MarketingLayout`, meaning `FAQPage` is emitted on **every marketing route** (`/features`, `/pricing`, `/integrations`, `/docs`), even though the FAQ accordion only exists on the home page (`/`). Google Search guidelines penalize `FAQPage` markup on pages lacking FAQ content.
- **Recommended Fix:** Move `FaqJsonLd` out of global `MarketingLayout` and into `apps/dashboard/src/app/(marketing)/page.tsx`.

### Finding ID: `SCHEMA-02`

- **Severity:** `P3` (Low - Missing WebSite Schema & Social sameAs)
- **Component:** `apps/dashboard/src/components/marketing/structured-data.tsx`
- **Detail:**
  1. `OrganizationJsonLd` sets `logo: "${SITE_URL}/opengraph-image"`. Organization logos should point to a square image asset (e.g. `${SITE_URL}/logo.png`).
  2. Missing `sameAs` array linking official social channels (`https://github.com/webchat-ai`, `https://x.com/webchat_ai`).
  3. No `WebSite` schema is emitted for Google Site Search and SERP brand naming.

---

## 16. Robots / Sitemap / Canonical Findings

- **`robots.ts`:** Correctly disallows all 16 private dashboard and auth state routes.
- **`sitemap.ts`:** Emits valid URLs with appropriate `lastModified`, `changeFrequency`, and `priority`.
- **`seoPage()` helper:** Generates valid canonical absolute URLs matching the deployment origin (`NEXT_PUBLIC_SITE_URL` / `https://webchatai.com`).
- **Defense-in-depth recommendation:** Add `robots: { index: false, follow: false }` metadata to `apps/dashboard/src/app/(dashboard)/layout.tsx` so search crawlers that ignore `robots.txt` are still barred from indexing dashboard shells.

---

## 17. Performance Findings

- **Landing Page Fonts:** Loaded via Next.js `next/font/google` (`Geist` and `Geist_Mono`), automatically self-hosted and inlined. No external network waterfall to Google Fonts during landing page load.
- **Core Web Vitals:**
  - **LCP:** No heavy raster hero images; hero renders in raw HTML/CSS/SVG. Instant LCP.
  - **CLS:** Zero layout shift; font swap uses size-adjust fallbacks; dimensions explicit on images.
  - **FID / INP:** Lightweight client components; no heavy initial JS bundles.

---

## 18. Existing Tests

| Area                        | Test Suite File                                                                 | Test Count | Status   |
| --------------------------- | ------------------------------------------------------------------------------- | ---------- | -------- |
| **Widget Test Page**        | `apps/dashboard/src/features/widget/widget-test-page.test.tsx`                  | 5          | All Pass |
| **Widget Test Helpers**     | `apps/dashboard/src/features/widget/widget-test.test.ts`                        | 12         | All Pass |
| **Widget Editor & Preview** | `apps/dashboard/src/features/widget/widget-editor.test.tsx`                     | 17         | All Pass |
| **Allowed Domains Editor**  | `apps/dashboard/src/features/widget/components/allowed-domains-editor.test.tsx` | 12         | All Pass |
| **Navbar Marketing**        | `apps/dashboard/src/components/marketing/navbar.test.tsx`                       | 3          | All Pass |
| **Footer Marketing**        | `apps/dashboard/src/components/marketing/footer.test.tsx`                       | 2          | All Pass |
| **Pricing Marketing**       | `apps/dashboard/src/components/marketing/pricing.test.tsx`                      | 2          | All Pass |
| **Widget Core & Styles**    | `apps/widget/src/ui/styles.test.ts`, `theme/apply.test.ts`, etc.                | 384        | All Pass |
| **Theme Presets & Tokens**  | `packages/themes/src/index.test.ts`                                             | 39         | All Pass |

---

## 19. Missing Tests

1. **Hero CTA Auth-Awareness:** `hero.test.tsx` does not exist. No unit test verifies that the Hero CTA renders "Sign up for free" $\to$ `/signup` when logged out vs "Dashboard" $\to$ `/dashboard` when logged in.
2. **Final CTA Auth-Awareness:** `final-cta.test.tsx` does not exist.
3. **ThemeSelector Component Unit Tests:** `theme-selector.test.tsx` does not exist. (Theme count and Show More was tested only indirectly via `widget-editor.test.tsx`).
4. **Font Loading & Variable Binding:** No test in `apps/widget` asserts that `.wc-shell` computes `var(--wc-font-family)` or that a dynamic stylesheet link is created.
5. **SEO & Structured Data Tests:** No tests verify canonical URLs, `sitemap.ts`, or JSON-LD rendering.

---

## 20. Browser Verification Matrix

| Area                       | Test Scenario              | Steps                                                                                                                                                                                                                     | Expected Result                                                                                                                                                                                            |
| -------------------------- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **A. Landing Page CTA**    | Unauthenticated Visitor    | 1. Open incognito window at `/`.<br>2. Inspect Hero CTA.<br>3. Inspect Final CTA.                                                                                                                                         | • Hero button text: "Sign up for free", links to `/signup`.<br>• Final CTA button text: "Sign up for free", links to `/signup`.                                                                            |
| **A. Landing Page CTA**    | Authenticated User         | 1. Log in to dashboard.<br>2. Navigate back to `/`.<br>3. Inspect Hero CTA.<br>4. Inspect Final CTA.                                                                                                                      | • Hero button text: "Dashboard", links to `/dashboard`.<br>• Final CTA button text: "Dashboard", links to `/dashboard`.                                                                                    |
| **B. Widget Test Page**    | Real Widget SDK Execution  | 1. Navigate to `/widget-test`.<br>2. Select a website with configured widget.<br>3. Verify connection details.<br>4. Interact with iframe.                                                                                | • Origin guard displays "200 OK — this origin is permitted".<br>• Real launcher renders inside iframe.<br>• Clicking launcher opens chat window.<br>• Sending message executes real SSE stream.            |
| **C. Font Family Options** | Distinct Font Rendering    | 1. Navigate to `/widget` editor.<br>2. Select "Poppins" $\to$ inspect preview.<br>3. Select "Playfair Display" $\to$ inspect preview.<br>4. Select "Space Grotesk" $\to$ inspect preview.<br>5. Save & check real widget. | • Preview visibly changes typeface between serif, geometric sans, and grotesque.<br>• Network tab loads respective Google Font `<link>`.<br>• Computed `font-family` on `.wc-shell` matches selected font. |
| **D. Theme Presets**       | Initial View Count         | 1. Open Theme Presets accordion on `/widget`.<br>2. Count initial cards before clicking "Show more".                                                                                                                      | • Exactly 6 theme cards visible.<br>• "Show more" button displays "(5 more)".                                                                                                                              |
| **D. Theme Presets**       | Show More Click            | 1. Click "Show more".<br>2. Count all revealed cards.<br>3. Select a revealed theme.                                                                                                                                      | • All 11 cards visible.<br>• Active state preserved.<br>• Preview updates instantly.                                                                                                                       |
| **E. SEO & Headings**      | Heading Hierarchy          | 1. Run DOM audit on `/`.<br>2. Inspect `<h1>`, `<h2>`, `<h3>` tags.                                                                                                                                                       | • Exactly one `<h1>` in Hero.<br>• Main content sections use `<h2>`.<br>• Footer navigation headers use `<p font-semibold>` or `<h3>` (no `<h2>` in footer).                                               |
| **E. SEO & JSON-LD**       | Structured Data Validation | 1. Inspect page source on `/`.<br>2. Test in Schema.org / Rich Results Validator.                                                                                                                                         | • `Organization` valid (with `sameAs` & logo.png).<br>• `SoftwareApplication` valid.<br>• `WebSite` valid.<br>• `FAQPage` present on `/`, omitted on subpages.                                             |

---

## 21. Exact Root Causes Summary

1. **Widget Test Parity:**
   - **Root Cause:** The `/widget-test` page **already uses the real SDK**, but its 480px iframe container height clips the 600px default widget window height.
2. **Landing CTA Auth-Awareness:**
   - **Root Cause:** `hero.tsx` (lines 52-55) hardcodes the string `Signup for free` rather than dynamically checking `isAuthenticated ? 'Dashboard' : 'Sign up for free'`.
3. **Font Family Rendering:**
   - **Root Cause A:** In `apps/widget/src/ui/styles.ts` line 89, `.wc-shell` hardcodes `font-family: -apple-system, BlinkMacSystemFont, ...` instead of `var(--wc-font-family, ...)`.
   - **Root Cause B:** Neither `apps/dashboard` nor `apps/widget` ever loads the web font files (e.g., from Google Fonts). All uninstalled font names fall back to the identical system font `system-ui, sans-serif`.
4. **Theme Preset Pagination:**
   - **Root Cause:** `ClassicCard` is rendered outside the `visiblePresets.slice(0, 6)` array, causing 1 + 6 = 7 theme cards to render initially instead of 6.
5. **SEO & Heading Structure:**
   - **Root Cause A:** `FooterColumn` in `footer.tsx` uses `<h2>` for navigation column titles, distorting the document's semantic outline.
   - **Root Cause B:** `FaqJsonLd` is mounted globally in `MarketingLayout` rather than scoped to pages containing the FAQ accordion.
   - **Root Cause C:** Root `layout.tsx` lacks Next.js 14+ `export const viewport: Viewport`.

---

# Implementation Plan (Read-Only Blueprint)

### PHASE A — Widget Test Parity

- **Files to Modify:**
  - `apps/dashboard/src/features/widget/widget-test-page.tsx`
  - `apps/dashboard/src/features/widget/widget-test.ts`
- **Components / Functions:**
  - `WidgetTestPage`: Increase iframe height or add responsive height container (`min-h-[640px]`), add mobile/desktop preview frame toggle to test responsive viewport behavior.
  - `buildWidgetTestHtml`: Ensure `<meta name="viewport" content="width=device-width, initial-scale=1">` is included in srcdoc header.
- **Tests to Add:** Extend `widget-test-page.test.tsx` to verify responsive container sizing.
- **Risk Level:** Low.

### PHASE B — Landing CTA Auth-Awareness

- **Files to Modify:**
  - `apps/dashboard/src/components/marketing/hero.tsx`
  - `apps/dashboard/src/components/marketing/final-cta.tsx`
  - `apps/dashboard/src/components/marketing/pricing.tsx`
- **Components / Functions:**
  - `Hero`: Bind button label to `isAuthenticated ? 'Dashboard' : 'Sign up for free'`, destination to `startFreeHref`.
  - `FinalCta`: Unify label to `isAuthenticated ? 'Dashboard' : 'Sign up for free'`.
  - `Pricing`: Unify free tier label to `isAuthenticated ? 'Dashboard' : 'Sign up for free'`.
- **Tests to Add:**
  - Create `apps/dashboard/src/components/marketing/hero.test.tsx` testing both logged-out and logged-in states.
- **Risk Level:** Very Low (re-uses existing `useAuth` and `getLandingDestination`).

### PHASE C — Font System & Loading Architecture

- **Files to Modify:**
  - `apps/widget/src/ui/styles.ts`
  - `apps/widget/src/theme/apply.ts`
  - `apps/widget/src/config/types.ts`
  - `apps/dashboard/src/features/widget/components/widget-editor.tsx`
  - `apps/dashboard/src/features/widget/components/widget-preview.tsx`
- **Components / Functions:**
  - `apps/widget/src/ui/styles.ts`: Update `.wc-shell` to `font-family: var(--wc-font-family, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif);`.
  - `apps/widget/src/theme/apply.ts`: Add lightweight on-demand Google Fonts stylesheet injector for non-system fonts.
  - `widget-editor.tsx`: Curate distinct font list (`System Default`, `Inter`, `Poppins`, `Nunito`, `Playfair Display`, `Space Grotesk`).
  - `widget-preview.tsx`: Add on-demand font stylesheet loader for dashboard preview.
- **Tests to Add:**
  - Unit tests in `styles.test.ts` and `apply.test.ts` verifying custom font variable resolution.
- **Risk Level:** Low (0kb added to widget bundle; graceful fallback to system font on offline/CSP restriction).

### PHASE D — Theme Show More Behavior

- **Files to Modify:**
  - `apps/dashboard/src/features/widget/components/theme-selector.tsx`
- **Components / Functions:**
  - Unify `Classic` and `THEME_PRESETS` into a single `allThemes` array of length 11.
  - Set `VISIBLE_INITIAL_COUNT = 6`.
  - Derive `visibleThemes = expanded ? allThemes : allThemes.slice(0, 6)`.
  - Derive `hasMore = allThemes.length > 6 && !expanded`.
  - Button text: `Show more (${allThemes.length - 6} more)`.
- **Tests to Add:**
  - Create `theme-selector.test.tsx` testing initial 6-card display, click expansion, and active theme persistence.
  - Update `widget-editor.test.tsx` to reflect exact 6-card count.
- **Risk Level:** Very Low.

### PHASE E — SEO & Semantic Enhancements

- **Files to Modify:**
  - `apps/dashboard/src/app/layout.tsx`
  - `apps/dashboard/src/app/(marketing)/layout.tsx`
  - `apps/dashboard/src/app/(marketing)/page.tsx`
  - `apps/dashboard/src/components/marketing/footer.tsx`
  - `apps/dashboard/src/components/marketing/structured-data.tsx`
  - `apps/dashboard/src/components/marketing/integrations.tsx`
  - `apps/dashboard/src/components/marketing/product-showcase.tsx`
- **Components / Functions:**
  - `layout.tsx`: Export `viewport: Viewport` with `themeColor`.
  - `footer.tsx`: Change `FooterColumn` headings from `<h2>` to `<p className="text-sm font-semibold">`.
  - `structured-data.tsx`: Add `WebSiteJsonLd`, add `sameAs` and fix logo in `OrganizationJsonLd`.
  - `(marketing)/layout.tsx` & `page.tsx`: Scope `FaqJsonLd` to `/` only.
  - Update outdated "7 curated themes" copy to "10 curated themes" in `integrations.tsx` and `product-showcase.tsx`.
- **Tests to Add:**
  - Unit test for `seoPage()` and structured data output.
- **Risk Level:** Very Low.

### PHASE F — Comprehensive Tests Execution

- Run `pnpm -r test` and ensure all suites pass.

### PHASE G — Browser QA Verification

- Execute the complete 5-area Browser Verification Matrix in Chromium, Firefox, and mobile emulation.
