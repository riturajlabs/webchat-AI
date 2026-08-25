# UI/UX Complete Audit — `apps/dashboard`

Scope: `apps/dashboard/**` (Next.js 15 App Router) and its shared theme package `packages/themes`.
Method: codebase evidence only. No external product comparisons. No code was modified.

---

# Executive Summary

The audited application is a **multi-tenant AI chat SaaS dashboard** (`apps/dashboard`) built with Next.js 15, Tailwind CSS v4, React Query, Radix primitives (Slot only), Recharts, lucide-react and Sonner. It shares a widget theme engine (`packages/themes`).

**Single most important finding: there is no marketing website inside this app.** The `/` route is the authenticated dashboard home (`src/app/(dashboard)/page.tsx`). There is no landing page, navbar, hero, features section, pricing section, FAQ, footer, or trust signals anywhere under `apps/dashboard/src`. The only public-facing surface is the auth group (`/login`, `/signup`, `/forgot-password`, `/reset-password`, `/verify-email`). Every "Marketing Website" item in the audit scope is therefore reported as a gap (LP-001…LP-013), because conversion infrastructure — pricing visibility, docs visibility for prospects, CTAs to sign up, trust signals — simply does not exist in code.

Inside the authenticated product, quality is uneven but often good:

- **Strong**: mobile drawer implementation (`mobile-nav.tsx`), allowed-domains editor validation UX, embed environment awareness (dev vs prod snippets), structured API error surfacing (`lib/api.ts`), consistent skeleton/empty/error triads on most list pages, dark-mode token infrastructure.
- **Critical gaps**: brand colors are orphaned from the UI token system (widget is blue `#2563eb`/amber `#f59e0b`; the dashboard chrome is achromatic near-black), a data-corrupting React Query cache collision on Analytics feedback widgets, no unsaved-changes protection on the Widget builder (silent data loss), one dialog bypassing the accessible-dialog pattern, `window.confirm` used for destructive actions despite an owned styled ConfirmDialog, no skip link, no onboarding for first-time users, and pervasive light-only hardcoded palette classes that break dark mode.

Priority distribution: **8 P0**, **24 P1**, **20 P2** issues across landing/marketing gaps, dashboard UX, design system, accessibility and performance UX.

---

# Current Design Assessment

## What exists

| Layer         | Implementation                                                                                                                                         | Evidence                                                                                                      |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------- |
| Routing       | Next.js 15 App Router; route groups `(auth)` and `(dashboard)`; admin sub-routes                                                                       | `src/app/(auth)/*`, `src/app/(dashboard)/*`, `admin/{overview,users,tenants,revenue,crawl-jobs,audit,system}` |
| Layout shell  | Fixed sidebar (hidden `< md`), sticky header with welcome text + email + theme toggle + sign-out, scrollable content region                            | `src/components/layout/dashboard-shell.tsx:35-93`                                                             |
| Navigation    | Flat list of **14 nav items** (+ admin gated by role), icons + labels, `aria-current="page"`                                                           | `src/components/layout/nav-items.ts:27-42`, `dashboard-shell.tsx:44-64`                                       |
| Design tokens | shadcn-style HSL tokens in `globals.css` (`--primary` = near-black `hsl(0 0% 9%)`), radius `0.625rem`, ring token, Geist Sans/Mono via `next/font`     | `src/app/globals.css:5-48,70-85`, `src/app/layout.tsx:7-15`                                                   |
| Brand palette | Blue `#2563eb` / amber `#f59e0b` exist **only** as widget defaults in `@webchat/themes` and hardcoded literals in widget editor components             | `packages/themes/src/index.ts:15-16`, `theme-selector.tsx:14`, `color-picker.tsx:11-18`                       |
| Primitives    | Button (cva, 6 variants incl. destructive, focus-visible ring), Card, Input, Label, Skeleton, EmptyState, Toaster (sonner)                             | `src/components/ui/*`                                                                                         |
| Dialog infra  | Hand-rolled `useAccessibleDialog` hook (Esc, Tab trap, autofocus rAF, inert siblings, focus restore) used by 3 dialogs; API-key dialog does not use it | `src/hooks/use-accessible-dialog.ts`, consumers listed below                                                  |
| State/data    | React Query (`staleTime 30s`, `retry 1`), session kept in memory only (XSS-hardening trade-off → refresh round-trip before first paint)                | `src/app/providers.tsx:18-24`, `src/lib/session.ts`                                                           |
| Charts        | Recharts v3, statically imported in analytics + admin revenue                                                                                          | `analytics/analytics-page.tsx:6-18`, `admin/revenue-panel.tsx:5`                                              |

## Strengths worth preserving

1. **Mobile drawer** is exemplary: `aria-expanded`/`aria-controls`, `role="dialog" aria-modal`, Esc close, body-scroll lock, focus restore, closes on navigation (`mobile-nav.tsx:56-127`).
2. **Allowed domains editor** shows live "Will be saved as:" preview (`role="status"`), explicit inline errors, loopback helper, count limits (`allowed-domains-editor.tsx:86-179`).
3. **Embed install flow** distinguishes Development vs Production snippets with explanations (`embed-code.tsx:88-118`, `embed.ts:62-82`).
4. **API error layer** produces specific, actionable copy including timeout and network-failure messages (`lib/api.ts:48,98,250-256`).
5. **Consistent state triad** on most pages: `role="status"` skeletons, `role="alert"` error banner + "Try again", differentiated empty-vs-filtered EmptyStates (admin panels especially).
6. **Dark mode infrastructure** is correct at the token level (`globals.css`, `.dark` block, `next-themes` class strategy with `suppressHydrationWarning`).
7. **Verification reminder** persists per-user dismissal in localStorage with try/catch fallback and non-blocking placement (`verification-reminder.tsx:10,44-51`).

## Structural weaknesses

1. **No marketing/conversion layer** (see Landing Page Issues).
2. **Brand color orphaned from chrome**: the signature blue→amber gradient appears nowhere in the dashboard's own UI; `--primary` is near-black, so primary buttons, active nav pills and links render grayscale ("link blue" affordance absent everywhere).
3. **Copy-paste component drift**: ≥3 StatCard implementations, ≥4 status-badge implementations, ≥4 copy-button implementations, ≥7 duplicated error-banner blocks, ≥5 hand-styled native `<select>` instances, 2 date formatters, 2 seconds formatters, 3 competing secondary-KPI text sizes.
4. **Accessibility debt concentrated in patterns, not one-offs**: h1→h3 heading skips sit in the shared `Card` primitive (`card.tsx:25` renders `<h3>`) so every page inherits it; 1px focus rings sit in shared Button/Input; missing skip link sits in the shell.
5. **Silent failure modes**: 7 of 8 analytics queries have no error handling; `api.ts` resolves `undefined` after hard redirect instead of throwing; several pages return `null` while loading; invalid hex input silently reverts in the color picker.

---

# Landing Page Issues

> Context established by route inventory: `src/app` contains only `(auth)`, `(dashboard)`, root `layout/loading/error/not-found`. No `marketing`, `(marketing)`, `landing`, `pricing`, or public-home route exists. Root metadata describes a product but no page markets it (`app/layout.tsx:17-24`).

---

**ID:** LP-001
**Priority:** P0
**Location:** `src/app/(dashboard)/page.tsx` (route `/`); absence of any `(marketing)` route group
**Problem:** The root URL is the authenticated Dashboard home. Unauthenticated visitors are redirected to `/login?redirect=%2F` by `AuthGuard` (`features/auth/auth-guard.tsx:14-20`). There is no public landing page at all.
**Why it matters:** The product's own root metadata advertises "Multi-tenant AI SaaS platform… zero code" (`app/layout.tsx:22-23`), yet no page communicates this value proposition. Every acquisition path dead-ends at a login form. This is the largest conversion gap in the codebase.
**Recommended fix:** Add a `(marketing)` route group with a real landing page at `/` and move the dashboard home under `/dashboard` (updating `nav-items.ts:28` and post-login redirects). Keep the existing empty-state copy ("Connect your first website…") as seed material.

---

**ID:** LP-002
**Priority:** P0
**Location:** No navbar exists; only `dashboard-shell.tsx:67-87` header and `mobile-nav.tsx`
**Problem:** No marketing navbar with logo, product links, Docs link, Pricing link and Sign-up CTA. The only header-like element requires authentication.
**Why it matters:** Prospects cannot discover features, docs or pricing without an account; there is no persistent signup entry point.
**Recommended fix:** Build a marketing navbar: wordmark (reuse the Bot-in-primary-square mark from `dashboard-shell.tsx:38-43`), anchors to Features / Pricing / FAQ / Docs, and a high-contrast "Get started" button linking to `/signup`.

---

**ID:** LP-003
**Priority:** P0
**Location:** No hero section exists anywhere under `apps/dashboard/src`
**Problem:** No hero with headline, subheadline, primary CTA, secondary CTA or product visual. The closest artifacts are the metadata description and the widget preview components that could serve as a visual.
**Why it matters:** First-impression value communication and the primary conversion moment do not exist.
**Recommended fix:** Hero with benefit-led headline, subcopy derived from existing positioning strings (`app/layout.tsx:23`, preset descriptions like "Trusted SaaS blue…" in `packages/themes/src/index.ts:79`), CTA pair (Sign up free / View docs), and a live widget mock reusing `WidgetPreview` styling language.

---

**ID:** LP-004
**Priority:** P1
**Location:** No features section exists
**Problem:** Feature capabilities exist only as scattered dashboard labels (Knowledge Base, Conversations, Analytics, Usage, API Keys, Widget builder) and docs-page config tables (`docs-page.tsx:30-83`). Nothing aggregates them into a scannable features grid.
**Why it matters:** Visitors must reverse-engineer the product from nav labels; feature discovery is a proven driver of trial starts.
**Recommended fix:** Features grid of 6 cards mirroring the six core nav capabilities (`nav-items.ts:28-37`), each with icon (reuse the existing lucide set), one-line benefit, and deep link into docs sections.

---

**ID:** LP-005
**Priority:** P1
**Location:** Docs live at `/docs` inside the authenticated shell (`(dashboard)/docs/page.tsx`); no public docs surface
**Problem:** Documentation requires login. The docs page itself links to a **hardcoded placeholder domain** rather than in-app routes (`docs-page.tsx:130-132,185-188,256-259` use `${DASHBOARD_URL}` = `'https://app.webchatai.example'` from `embed.ts:18`).
**Why it matters:** Docs are a top pre-signup evaluation asset; gating them behind auth suppresses conversion, and even logged-in users following doc links get bounced to a nonexistent domain.
**Recommended fix:** Publish docs publicly (or expose a read-only mirror); replace placeholder-domain anchors with in-app `<Link href="/widget">` style routes.

---

**ID:** LP-006
**Priority:** P0
**Location:** No CTA flow exists (no signup CTA anywhere outside auth forms)
**Problem:** The only signup entry point is direct URL access to `/signup`. No button, banner, or link anywhere in the product invites account creation. Post-signup, users land unguided on the dashboard (`signup-form.tsx:42` redirects to `'/'` always).
**Why it matters:** Without CTAs there is no funnel; with no post-signup guidance, whatever traffic converts churns at the empty dashboard.
**Recommended fix:** Define the CTA flow end-to-end: landing hero CTA → `/signup` → email verification interstitial → guided first-website flow (see DB-002). Wire the existing `EmptyState` action pattern (`empty-state.tsx`) into a step-based onboarding.

---

**ID:** LP-007
**Priority:** P1
**Location:** No pricing section exists; pricing data lives only in billing/admin types (`billing/types.ts`, plan names surfaced at `billing-page.tsx:96-105`, `167-170`)
**Problem:** Plans (trial, paid tiers, enterprise) are invisible pre-auth; even in-app, the Billing page has no plan comparison and marks nothing "Current".
**Why it matters:** Price opacity blocks purchase decisions both pre- and post-signup.
**Recommended fix:** Public pricing section with tier cards sourced from the same plan model used by billing; in-app, add a "Current" badge and disable/differentiate the owned plan's button (see DB-012).

---

**ID:** LP-008
**Priority:** P2
**Location:** No FAQ section exists; support-ish content exists only in docs Troubleshooting/Security sections (`docs-page.tsx` sections 5-6)
**Problem:** No FAQ addressing common pre-purchase objections (data privacy, self-host vs cloud, model choice, crawl limits).
**Why it matters:** FAQs deflect support load and remove final objections at the decision point.
**Recommended fix:** Seed 6–10 Q&As from the Troubleshooting and Security notes already written in the docs page.

---

**ID:** LP-009
**Priority:** P1
**Location:** No footer exists on any page
**Problem:** Neither marketing nor auth pages have a footer (links, legal, status, contact). Auth layout is a bare centered card (`(auth)/layout.tsx:5-15`).
**Why it matters:** Legal links (privacy/terms) are expected at signup time; their absence reads as unfinished and can block procurement.
**Recommended fix:** Footer with product/docs/pricing/company columns, legal links, and system-status indicator (the health-check endpoint already powering `use-system-status.ts`).

---

**ID:** LP-010
**Priority:** P1
**Location:** No trust signals anywhere (no testimonials, logos, security badges, SLA, uptime)
**Problem:** The product has real trust-worthy internals — WCAG-style contrast math in `readableText()` (`packages/themes/src/index.ts:396-407`), origin-guard sandboxing (`widget-test-page.tsx:129-146`), domain allowlists (`allowed-domains-editor.tsx`) — none surfaced publicly.
**Why it matters:** B2B buyers look for security/compliance evidence before trials; the assets already exist but aren't marketed.
**Recommended fix:** Trust strip on landing (security notes from `docs-page.tsx` Security section), uptime/status link, and concrete numbers where honest (preset count, supported providers from backend config).

---

**ID:** LP-011
**Priority:** P2
**Location:** Auth screens are the de-facto landing experience (`(auth)/layout.tsx`)
**Problem:** Minimal branding: generic Bot glyph + wordmark, no tagline, no value prop, light-only success banners (`forgot-password-form.tsx:42`, `reset-password-form.tsx:47`, `verify-email-form.tsx:58`, `resend-verification-form.tsx:63`).
**Why it matters:** For anyone arriving via direct link, these screens are the whole brand impression; they currently undersell and partially break in dark mode.
**Recommended fix:** Add tagline + product visual column to auth layout; convert success banners to token-based alert styles with `dark:` variants.

---

**ID:** LP-012
**Priority:** P2
**Location:** Conversion optimization: nothing measurable exists
**Problem:** No CTAs, no pricing anchors, no urgency/scarcity elements, no social proof — i.e., no conversion levers at all.
**Why it matters:** Cannot optimize what doesn't exist.
**Recommended fix:** After LP-001/003/007 ship, instrument funnel steps (landing → signup → verify → first website → first embed) using the existing events-free stack (simple route-level analytics).

---

**ID:** LP-013
**Priority:** P1
**Location:** Typography/spacing/responsive systems exist but were designed for app density only
**Problem:** Type scale tops out at `text-3xl` page titles (`dashboard-home.tsx:240`); no display-scale for marketing headlines; spacing rhythm is uniform `gap-4/gap-8` (`dashboard-shell.tsx:89`, pages). Responsive behavior is solid ≤ md (drawer, stacked grids) but has no marketing breakpoint treatment.
**Why it matters:** A marketing site bolted onto the current scale will look like a settings page.
**Recommended fix:** Extend the scale (`text-4xl/5xl/6xl` display tokens) and a wider container width when adding the marketing group, keeping the same radius/shadow tokens.

---

# Dashboard Issues

## Navigation & Shell

---

**ID:** DB-001
**Priority:** P1
**Location:** `src/components/layout/nav-items.ts:27-42`, `dashboard-shell.tsx:44-64`
**Problem:** 14 flat sidebar entries with no grouping (Product: Websites/Knowledge/Conversations; Insight: Analytics/Usage/Billing; Setup: Widget/API Keys/Docs; Account: Profile/Settings/Admin). Icons semantically mismatched: Bot for "Websites" (`nav-items.ts:29`), CreditCard for "Usage" while Receipt is "Billing" (`:33-34`), KeyRound reused for "Pages indexed" stat (`dashboard-home.tsx:287`), Webhook for Redis health (`dashboard-home.tsx:150`), Server double-booked for System and Crawl queue (`admin-nav.tsx:14,16`).
**Why it matters:** Flat IA forces serial scanning every visit; icon mismatches erode wayfinding and learnability.
**Recommended fix:** Group nav under labeled sections; remap icons (Globe/Globe2 for Websites, Gauge for Usage, distinct admin glyphs); add an icon-usage rule to lint review.

---

**ID:** DB-002
**Priority:** P0
**Location:** `features/auth/signup-form.tsx:42` (always redirects `'/'`), `features/dashboard/dashboard-home.tsx:296-301`, absence of any onboarding module
**Problem:** New tenants land on the dashboard whose only first-run affordance is a single EmptyState card. There is no step-by-step onboarding (add website → crawl → install widget → test), no progress indicator, no welcome tour. Signup success gives no toast; verification is a passive amber banner.
**Why it matters:** Time-to-first-value is unmanaged; the core activation event (widget installed on a site) depends on users discovering a 4-step sequence across separate pages by themselves.
**Recommended fix:** Add a dismissible onboarding checklist card on the home (steps derive entirely from existing entities: website created, crawl ready, domains configured, embed verified — all states already exposed by `websites/hooks.ts` and `widget-test` status report).

---

**ID:** DB-003
**Priority:** P2
**Location:** `dashboard-shell.tsx:70-72` vs `dashboard-home.tsx:240-243`
**Problem:** Header shows "Welcome, {name}" and the home page immediately repeats "Welcome, {name} — here is what is happening…". Header never shows the current page title or breadcrumb; page identity comes only from each page's `h1`.
**Why it matters:** Redundant greeting wastes prime header space while actual orientation info (where am I) is missing; deep-linked users see two conflicting context cues.
**Recommended fix:** Replace header greeting with current-route title (derive from `nav-items` labels) or breadcrumbs; keep greeting only on home.

---

## Dashboard Home

---

**ID:** DB-004
**Priority:** P1
**Location:** `features/dashboard/dashboard-home.tsx:82-109` (QuickActions)
**Problem:** "Start a crawl" quick action just navigates to `/websites` — identical target as "Add website". None of the three actions takes parameters (e.g., open add-dialog directly). RecentWebsites rows all link to `/websites` regardless of which site was clicked (`:210`).
**Why it matters:** Actions that don't do what they say train users to ignore quick actions; per-site links losing site identity breaks the mental model of drill-down.
**Recommended fix:** Deep-link quick actions (query param opening `AddWebsiteDialog`; crawl action targeting the crawl trigger shown in `website-card.tsx`), and route recent-site rows to a site detail anchor.

---

**ID:** DB-005
**Priority:** P2
**Location:** `features/dashboard/use-system-status.ts`, `dashboard-home.tsx:144-194`
**Problem:** API row conflates request failure with service being down (`ok: !isError`, `:148`). Status flips OK↔Down with no `aria-live` announcement. Retry button appears only after error (`:186-190`).
**Why it matters:** A transient network blip reports "Database OK / API Down" misleadingly; silent status flips are missed by SR users.
**Recommended fix:** Distinguish unknown (network) from down (health payload says unhealthy); wrap list in `role="status"` region; keep Retry visible during pending too.

---

## Widget Builder (configuration)

---

**ID:** DB-006
**Priority:** P0
**Location:** `features/widget/widget-editor.tsx:203-226` (single Save button), `widget-page.tsx:100-127` (`key={selected}` remount), repo-wide absence of `beforeunload`/`useBlocker` (grep: zero matches)
**Problem:** No unsaved-changes protection anywhere in the app. In the widget builder: switching the website `<select>` remounts the editor and silently discards edits; sidebar navigation loses edits; closing the tab loses edits. The single Save control sits only at the top of a ~7-section scroll column (Branding alone has 14 fields), so after scrolling, users must return to top to save. No dirty-state indicator, no Discard/reset affordance.
**Why it matters:** Silent loss of multi-field configuration work is the most damaging class of UX defect (error prevention principle); it will be attributed to "the app lost my changes".
**Recommended fix:** Add `isDirty` guard on navigation/unload + confirm-on-switch for the website select; duplicate Save in a sticky bottom bar or make the header bar sticky; show dirty dot + "Discard changes" next to Save.

---

**ID:** DB-007
**Priority:** P1
**Location:** `features/widget/components/color-picker.tsx:8,31,55-68`
**Problem:** Invalid hex text is silently ignored with no message; `onBlur={() => setText(value)}` silently reverts half-typed values; hex textbox initializes once (`useState(value)`) so external value changes desync it; "Reset to default" flows show `value ?? '#000000'` (pure black) rather than the resolved default (`OptionalColorPicker` call sites, e.g. `widget-editor.tsx:133`).
**Why it matters:** Error prevention and feedback principles violated inside the highest-interaction surface of the product.
**Recommended fix:** Show inline invalid-hex error (mirror `allowed-domains-editor.tsx:115-119` pattern); sync text via effect on prop change; display effective theme-resolved color when unset.

---

**ID:** DB-008
**Priority:** P1
**Location:** `features/widget/components/theme-selector.tsx:45-115`, `color-picker.tsx:80-82`
**Problem:** Theme radiogroup items are plain buttons — all tab stops, no arrow-key roving tabindex required by the APG radiogroup pattern. Swatch buttons define hover/selected styles but no `focus-visible` ring. Preset selection ring uses `ring-offset` defaulting to white — jarring in dark mode.
**Why it matters:** Keyboard users traverse N+M tab stops for themes+colors; dark-mode focus halo looks broken.
**Recommended fix:** Implement roving tabindex + Arrow/Home/End keys; add shared `focus-visible:ring-*` classes to swatches; set `ring-offset-background`.

---

**ID:** DB-009
**Priority:** P1
**Location:** `features/widget/components/widget-preview.tsx:95-96,200-209,223-246`, `device-preview.tsx:48-63`
**Problem:** Preview chat window uses `role="dialog"` though it is not modal (SR announces a spurious dialog). Send button and composer render as interactive but have no handlers and no disabled state (fake affordance). Launcher `aria-label="Open assistant"` never changes while showing an X/close icon when open. Device-frame browser chrome hardcodes light-only colors (`bg-white`, `bg-slate-100`, `text-slate-500`) ignoring dashboard dark mode; fixed 480px height forces internal scrolling on short viewports.
**Why it matters:** The preview is the persuasion surface for the whole configuration; fake controls mislead, mislabeled states confuse SR and sighted users alike, and the frame visually breaks in dark mode.
**Recommended fix:** Drop `role="dialog"` (use `role="region"` + label); disable composer/send with tooltip "Preview only"; toggle launcher label/icon state; theme the device chrome with tokens; cap height responsively.

---

**ID:** DB-010
**Priority:** P2
**Location:** `features/widget/widget-preview.tsx:72`, `widget-test.ts:39`
**Problem:** Placeholder site screenshot fetched from external `placehold.co`; canvas backgrounds hardcoded (`#020617`/`#f8fafc`); iframe srcDoc background `#f1f5f9`.
**Why it matters:** Offline/adblock environments render a broken image in the marquee surface; hardcoded values bypass the theme engine the package was built for.
**Recommended fix:** Generate an inline SVG/CSS placeholder; move remaining literals through `resolveTheme` tokens.

---

**ID:** DB-011
**Priority:** P2
**Location:** `features/widget/widget-page.tsx:82-87`, `widget-test-page.tsx:83-88`, cross-linking in `embed-code.tsx` / `docs-page.tsx`
**Problem:** "No websites yet" empty states have no action button (dead end), while sibling pages prove the pattern (`EmptyState` with `onAction` at `dashboard-home.tsx:296-301`). Embed card never links to `/docs` or `/widget-test`; widget-test references "Widget → Allowed domains" as plain text, not links (`widget-test-page.tsx:183-186,264-265`).
**Why it matters:** Breaks the setup loop precisely where users need hand-off between configure → test → docs.
**Recommended fix:** Add CTA actions to both empty states; add contextual cross-links between widget builder, tester, and docs sections.

---

## Billing & Monetization

---

**ID:** DB-012
**Priority:** P0
**Location:** `features/billing/billing-page.tsx:111-185` (UpgradeCard)
**Problem:** Plan cards don't mark the tenant's current plan — every purchasable plan shows an identical "Upgrade" button, so clicking your own plan re-purchases it. No downgrade or cancel path exists; enterprise "Contact sales" is static text, not a mailto/link (`:167-170`); usage summary shows raw numbers with no "% of limit" bars although limits are available (`:219-231`).
**Why it matters:** Accidental repurchase is a billing-support incident generator; missing cancel/downgrade is a compliance/trust problem; invisible quota consumption removes upgrade motivation.
**Recommended fix:** Badge "Current plan", swap its button to disabled/"Manage"; add downgrade/cancel contact paths; reuse the `LimitBar` meter already built for usage (`usage-page.tsx:78-119`).

---

**ID:** DB-013
**Priority:** P2
**Location:** `features/billing/billing-page.tsx:40-46,258-287`, `usage-page.tsx:28`
**Problem:** Payment table `<th>` lacks `scope="col"`, no caption/`aria-label`; horizontal-scroll wrapper lacks `tabIndex={0}` (keyboard can't scroll). Billing StatusBadge uses `bg-emerald-500/15 text-emerald-600`/sky without `dark:` variants. Page h1 says "Usage & Billing" (`usage-page.tsx:28`) while a separate `/billing` exists; neither page cross-links the other.
**Why it matters:** Table semantics, dark-mode legibility, and page-name conflation all confuse the money workflow — the least forgiving area for confusion.
**Recommended fix:** Add scope/caption/tabIndex; adopt profile-page's dark-safe badge recipe; rename Usage h1 and cross-link both pages.

---

## API Keys

---

**ID:** DB-014
**Priority:** P0
**Location:** `features/api-keys/create-api-key-dialog.tsx:67-173` vs `hooks/use-accessible-dialog.ts` (used at `add-website-dialog.tsx:45`, `confirm-dialog.tsx:44`, `tenant-panel.tsx:64`)
**Problem:** The create-API-key dialog is a hand-rolled `role="dialog" aria-modal="true"` overlay with **no Esc handling, no focus trap, no initial focus, no focus restore, no inert background, no body-scroll lock** — while the repo owns a complete hook solving exactly this and three other dialogs already use it. Additionally the hook's inert pass only covers the immediate backdrop sibling, not the rest of the page (dialogs render inline, not portaled), so its "background is inert" contract is overstated for all dialogs (`use-accessible-dialog.ts:71-81,33-34`).
**Why it matters:** Keyboard/SR users can Tab behind the modal into live page content; Esc is the expected exit; this is the app's most sensitive secret-handling flow.
**Recommended fix:** Retrofit `useAccessibleDialog` (and add portal or document the inline limitation); consider promoting the hook to a shared `Dialog` primitive so future dialogs can't skip it.

---

**ID:** DB-015
**Priority:** P1
**Location:** `features/api-keys/api-keys-page.tsx:29,104-122`, `types.ts:11`
**Problem:** Revoke uses blocking native `window.confirm` (unstyled, main-thread-blocking, inconsistent with owned `ConfirmDialog`); revoke trigger is `ghost` variant so destructive intent rides only on a trash glyph; `last_used_at` exists in the type but is never displayed, so stale-key identification is impossible before revoking.
**Why it matters:** Same destructive-action inconsistency repeats across the app (also `website-list.tsx:91`, `conversation-detail.tsx:75`); missing last-used data makes revocation risky.
**Recommended fix:** Replace all three `window.confirm`s with the styled ConfirmDialog (destructive variant); show `last_used_at` (or "never used") per key; keep shown-once reveal flow as-is (it's good).

---

## Analytics

---

**ID:** DB-016
**Priority:** P0
**Location:** `features/analytics/hooks.ts:31-32` vs `:85-91` vs `:109-115`
**Problem:** `useFeedbackSummary` (endpoint `/api/feedback/summary`) and `useAnalyticsFeedback` (endpoint `/api/analytics/feedback`) share the **identical queryKey** (`analyticsKeys.feedback(days, websiteId)`), so the two queries overwrite each other's cache slot; the "User satisfaction" StatCard and Positive/Negative tiles can render each other's payloads depending on resolution order.
**Why it matters:** This is a correctness bug manifesting purely in the UI data layer — displayed satisfaction metrics can be silently wrong.
**Recommended fix:** Give one hook a distinct key segment (e.g., `['feedback-summary', …]` vs `['feedback', …]`) and add a regression test asserting different keys.

---

**ID:** DB-017
**Priority:** P1
**Location:** `features/analytics/analytics-page.tsx:85` (skeleton def `:82-97`), `:409-422`
**Problem:** `StatGridSkeleton` renders 7 tiles while 8 render in data state (visible reflow). Only the summary query's error surfaces; the other seven (timeseries, topWebsites, performance, feedback, overview, questions, feedbackAnalytics) fail silently — charts/tiles render zeros/empties with no indication. Range toggle buttons convey selection solely via fill variant — no `aria-pressed`.
**Why it matters:** Silent partial failure undermines trust in analytics numbers; reflow and unlabeled toggles are polish/a11y defects on the most data-dense page.
**Recommended fix:** Match skeleton count (or drive from constant); add per-widget error micro-states (icon + retry) for the seven queries; add `aria-pressed` to range buttons.

---

**ID:** DB-018
**Priority:** P2
**Location:** `features/analytics/analytics-page.tsx:49-55,119-130,327-330`, chart block generally
**Problem:** Five hardcoded series hexes (`#6366f1/#10b981/#f59e0b/#8b5cf6/#ec4899`) ignore tokens and don't adapt to dark mode (axes/grid do). `ChartPlaceholder` gates on a `mounted` flag rather than data readiness — cached data still flashes "Loading chart", then a pending fetch renders empty axes indistinguishable from "no data" (only questions/satisfaction get EmptyState branches). Y-axis question labels truncate at 22 chars with full text recoverable only by pointer hover; no Legend and no textual alternative for any chart.
**Why it matters:** Chart comprehension and dark-mode coherence suffer; loading-vs-empty ambiguity generates false "it's broken" impressions.
**Recommended fix:** Move series colors into CSS variables (dark-aware); gate placeholders on `isPending`; add loading spinner overlay for refetch-with-data; provide accessible summary lists alongside charts.

---

## Usage

---

**ID:** DB-019
**Priority:** P1
**Location:** `features/usage/usage-page.tsx:92-116`
**Problem:** Over-limit (>100%) renders identically to exactly-100%: width capped via `Math.min(100, percent)`, no red/critical state, no over-limit banner, no upgrade CTA; `aria-valuenow` reports the capped width instead of true percentage and there's no `aria-valuetext` ("1,234 of 5,000 messages"). Single warning threshold (80%, amber) only. Quota proximity never surfaces on the dashboard home despite data availability.
**Why it matters:** Users discover hard-stops (blocked crawls/messages) with zero prior signal beyond an amber tint at 80%.
**Recommended fix:** Add ≥100% critical state (red bar + banner + upgrade link), true `aria-valuenow` + `aria-valuetext`, and surface a compact quota line on the home KPI row.

---

## Admin

---

**ID:** DB-020
**Priority:** P1
**Location:** `features/admin/user-panel.tsx:235-257`, `tenant-panel.tsx:435-450`, tables throughout admin (`user-panel.tsx:190-263` etc.)
**Problem:** Row action buttons ("Suspend"/"Force logout"/"Details") repeat identically for every row with no row-context in accessible name; no table captions or `aria-sort` (sorting doesn't exist at all); truncated cells rely on CSS `truncate` with no `title` (full error/user-agent unrecoverable); raw UUIDs (`tenant_id`, payment IDs, IPs) rendered as mono text without copy affordance (`crawl-panel.tsx:151`, `admin-audit-panel.tsx:191-195`).
**Why it matters:** Admin tables are power-user surfaces; identical-label buttons and unrecoverable truncation slow every operational task and lock out SR users.
**Recommended fix:** Compose accessible names (`Suspend user — {email}`); add `title`/expander for truncated cells; add copy-to-clipboard on IDs; consider sortable headers later.

---

**ID:** DB-021
**Priority:** P2
**Location:** `features/admin/overview-page.tsx:72` vs other `admin/*/page.tsx:19`; `revenue-panel.tsx:47-51,138-170`; `crawl-panel.tsx:94,105`; `features/admin/audit-panel.tsx` (whole file)
**Problem:** Overview embeds `AdminNav` inside the feature while every other route puts it in the page file (maintenance drift). Revenue chart renders a blank area between load and post-mount `mounted` gate. Crawl empty states use a `Loader2` spinner glyph as the "nothing here" icon (semantically wrong). Dead ~200-line duplicate `AuditPanel` component ships unused (route uses `AdminAuditPanel`). Plan-change in tenant detail dialog performs a billing-affecting mutation with **no confirmation** (`tenant-panel.tsx:78-88,159-166`).
**Why it matters:** Small inconsistencies compound in the highest-stakes area of the product; the unconfirmed plan change is an error-prevention miss.
**Recommended fix:** Normalize nav placement; replace mounted-gate with `isPending`-driven rendering; swap empty-state icons; delete dead panel; confirm plan changes via ConfirmDialog.

---

**ID:** DB-022
**Priority:** P2
**Location:** `features/admin/admin-guard.tsx:36`, `:11-13`
**Problem:** Non-admin "Back to dashboard" uses `window.location.assign('/')` (full reload); guard is client-side only (no middleware), and admin hooks fire before the 403 arrives.
**Why it matters:** Hard reload discards client state and flashes; wasted requests occur on every unauthorized visit.
**Recommended fix:** Use router push; gate hook execution behind the role check (or add route middleware).

---

## Auth & Verification

---

**ID:** DB-023
**Priority:** P1
**Location:** `verification-reminder.tsx:40,12-21`; `(auth)/login/page.tsx:14`, `reset-password/page.tsx:14`, `verify-email/page.tsx:14`; auth success banners (LP-011)
**Problem:** localStorage read during first render causes dismissed banner to flash then vanish post-hydration. Three auth pages wrap forms in `<Suspense fallback={null}>` so card bodies render momentarily empty instead of skeletons. All four green success banners lack `dark:` variants.
**Why it matters:** Flash-of-wrong-state and blank frames read as jank on the very first and very last screens of the lifecycle.
**Recommended fix:** Compute dismissal in `useEffect`; give Suspense a small skeleton; apply the profile-page dark-safe recipe to banners.

---

**ID:** DB-024
**Priority:** P2
**Location:** `reset-password-form.tsx:73-84` vs `signup-form.tsx:87-94`; password fields generally
**Problem:** Signup documents complexity rules ("three of: lowercase, uppercase, digit, symbol"); reset-password omits them though the same policy applies. No show/hide password toggle anywhere; browser-native validation bubbles are the only inline feedback; login has no client email format check while signup does.
**Why it matters:** Rule opacity at reset time causes failed submissions exactly when users are least patient.
**Recommended fix:** Mirror the hint text; add a shared PasswordInput with visibility toggle and live rule checklist.

---

**ID:** DB-025
**Priority:** P2
**Location:** `profile-page.tsx:116-135,197`
**Problem:** Two adjacent buttons ("Send Verification Email" and "Resend Email") trigger the identical function. Email status conveyed via ✓/❌ emoji glyphs (awkward SR announcements, inconsistent with the lucide badge idiom 40 lines above). Verification success uses an inline paragraph instead of the app-wide toast channel.
**Why it matters:** Duplicate CTAs guarantee hesitation; emoji-as-status breaks the established icon system.
**Recommended fix:** Keep one labeled button with cooldown state; replace emoji with the existing badge pattern (`profile-page.tsx:58-71`); unify feedback channel.

---

**ID:** DB-026
**Priority:** P1
**Location:** `settings/settings-page.tsx:17-34`, `nav-items.ts:39-40`, `profile-page.tsx:214-216`
**Problem:** Settings page is a placeholder EmptyState ("not available yet") while the sidebar subtitle promises "Configure your account and workspace preferences"; Profile is read-only with a "future phase" note; there is no password change, session management, workspace rename, member management, or danger zone (delete tenant) anywhere in the app.
**Why it matters:** Nav promises unfulfilled promises erode trust; absence of account deletion/danger zone is a platform-completeness gap.
**Recommended fix:** Short-term: relabel nav item ("Settings — coming soon" pattern or hide until real). Roadmap: implement workspace prefs + password change + danger zone behind the existing ConfirmDialog.

---

## Global States, Feedback & Data Layer

---

**ID:** DB-027
**Priority:** P1
**Location:** Error banner duplicated ≥7×: e.g. `dashboard-home.tsx:248-260`, `usage-page.tsx:131-139`, `billing-page.tsx:337-349`, api-keys `:76-84`, knowledge `:293-305`, conversations `:115-127`, admin panels; two divergent root error screens (`app/error.tsx:18-26` vs `(dashboard)/error.tsx:19-28`)
**Problem:** The `role="alert"` + destructive-border + "Try again" block is copy-pasted with slight variations instead of being a primitive; two different error screens exist for the same failure class (one with icon, one with `font-mono` paragraph); neither shows a digest/reference ID.
**Why it matters:** Visual inconsistency in failure moments (when users scrutinize UI most) and maintenance drag.
**Recommended fix:** Create `ErrorBanner`/`Alert` primitive (message + retry + optional digest); consolidate the two error boundaries into one component with the icon version.

---

**ID:** DB-028
**Priority:** P1
**Location:** `lib/api.ts:226-234`; null-render guards at `website-list.tsx:53`, `conversation-detail.tsx:131`, `knowledge-page.tsx:78`, `profile-page.tsx:29`
**Problem:** After a failed silent-refresh the API layer clears the session, hard-redirects, then **resolves `undefined as T`** instead of throwing — callers treat it as successful data. Several components return `null` (blank regions) when data is absent rather than distinguishing loading/empty/error.
**Why it matters:** Mid-session expiry can produce silently empty UI with no explanation; blank regions violate the "no unexplained emptiness" baseline.
**Recommended fix:** Throw a typed `AuthExpiredError` (redirect handled centrally); replace bare `null` returns with the loading skeleton branches already present elsewhere.

---

**ID:** DB-029
**Priority:** P2
**Location:** `(dashboard)/loading.tsx:1-8` + `components/ui/page-skeleton.tsx:3-27` (applies to every dashboard route)
**Problem:** One generic `PageSkeleton` (stat-grid + rows) serves all 14 routes, so navigating to e.g. Conversations flashes a stats-shaped skeleton then swaps to list shape. Loading wrapper duplicates the shell's `px-4 py-8 md:px-10` padding (double padding risk during route transitions). Several custom skeletons are silent (billing `billing-page.tsx:56-69`, widget `widget-page.tsx:13-25`, widget-test `:23-33`, profile `:165-171` lack `role="status"` that siblings have).
**Why it matters:** Skeletons that don't match layout cause layout-shift-driven perceived jank; inconsistent announcement granularity confuses SR users.
**Recommended fix:** Route-specific skeleton variants (list/detail/chart); centralize container padding in the shell; standardize `role="status"`+label on every skeleton.

---

**ID:** DB-030
**Priority:** P1
**Location:** Copy-button implementations ×4: `code-block.tsx:33-51`, `embed-code.tsx:12-38`, `create-api-key-dialog.tsx:49-61`, plus inline instance in add-website flow
**Problem:** Four bespoke implementations diverge on label ("Copied!" vs "Copied"), feedback channel (silent fail vs toast), and mutate their own accessible name on click. Related: `<pre>` blocks in docs/embed lack `tabIndex={0}`, so keyboard users cannot scroll clipped code (`code-block.tsx:49`, `embed-code.tsx:52`); payments-table overflow wrapper lacks it too (`billing-page.tsx:258`).
**Why it matters:** Copy-to-clipboard is a monetization-critical micro-interaction (install snippets, secrets); inconsistent behavior reads as bugginess and excludes keyboard users from core setup content.
**Recommended fix:** One `CopyButton` + `ScrollableCode` primitive (stable name, announced state, `tabIndex={0}` scrollables); adopt everywhere.

---

**ID:** DB-031
**Priority:** P2
**Location:** `toaster.tsx:5-14` (sonner `richColors`, bottom-right); admin mutation toasts (`user-panel.tsx:68-81`, `tenant-panel.tsx:84-87,249-257`)
**Problem:** Toast errors drop backend-provided detail that inline alerts would show ("Failed to suspend user" vs the ApiError message available); bottom-right placement can overlap pagination controls on small screens; sonner's richColors introduces a third color system beside tokens and pastel chips.
**Why it matters:** Feedback messages are the app's voice; generic failures force users to retry blindly.
**Recommended fix:** Pass `error.message` into toast descriptions; add responsive position or margin; align toast palette with tokens.

---

## Accessibility (cross-cutting)

---

**ID:** DB-032
**Priority:** P0
**Location:** `dashboard-shell.tsx:35-66` (no skip link anywhere; grep confirms zero matches in `src`)
**Problem:** No "skip to content" link. Keyboard users must tab through up to 14 sidebar items + header controls on every page before reaching content.
**Why it matters:** WCAG 2.4.1 Bypass Blocks violation; the single cheapest high-impact a11y fix available.
**Recommended fix:** Visually-hidden-until-focused skip link as first focusable element targeting `<main id="main-content">`.

---

**ID:** DB-033
**Priority:** P1
**Location:** `card.tsx:25` (CardTitle renders `<h3>`) inherited by every page; heading sequences h1→h3 throughout (e.g., `dashboard-home.tsx:240`→CardTitles, `docs-page.tsx` sections)
**Problem:** Heading levels skip h2 on essentially every page because the shared Card primitive hardcodes h3.
**Why it matters:** Broken heading outline cripples SR navigation-by-headings — the second most common browsing strategy.
**Recommended fix:** Add an `as`/level prop to CardTitle (default h2) and pass h3 for nested cases.

---

**ID:** DB-034
**Priority:** P1
**Location:** `button.tsx:8`, `input.tsx:11` (1px `focus-visible:ring-1`); all `next/link` elements lack custom focus styles (`dashboard-shell.tsx:52-57`, `mobile-nav.tsx:110-115`, `admin-nav.tsx:32-35`, auth inline links)
**Problem:** Focus indication is a 1px ring (below WCAG 2.2 focus-appearance heuristics) and inconsistently applied — interactive links get only UA outlines tinted by `outline-ring/50`, so sidebar/mobile/admin/auth links look different from buttons when focused.
**Why it matters:** Focus visibility is the foundation of keyboard operability; inconsistency makes focus effectively invisible for many users.
**Recommended fix:** Bump to `ring-2` with offset globally; add a shared link class (or global `a:focus-visible` rule) matching button rings.

---

**ID:** DB-035
**Priority:** P1
**Location:** Progress meters: `website-card.tsx:154-163` (no `role="progressbar"`/values), `usage-page.tsx:104-111` (role present, capped/wrong valuenow, no valuetext), `knowledge-page.tsx:87-93` (correct pattern)
**Problem:** Three progress-bar implementations with three accessibility levels; the websites crawl progress — the most-watched number during onboarding — is the least accessible.
**Why it matters:** Users watching a crawl depend on that feedback; SR users get none of it on one screen and wrong values on another.
**Recommended fix:** Extract one `ProgressMeter` primitive (role, min/max/now, valuetext) used by all three.

---

## Performance UX

---

**ID:** DB-036
**Priority:** P1
**Location:** `analytics/analytics-page.tsx:6-18`, `admin/revenue-panel.tsx:5`; grep: zero `next/dynamic` usage in app
**Problem:** Recharts (~large dependency) statically imported into both the analytics route and entire admin segment initial JS; revenue panel even renders nothing until a post-mount flag, making it a lazy-load candidate already. No dynamic imports exist anywhere in the app.
**Why it matters:** Bundle weight lands on first paint of exactly the pages operators wait on; the mounted-gate flash is itself a symptom.
**Recommended fix:** `next/dynamic` (ssr false) for chart components; measure route bundles before/after.

---

**ID:** DB-037
**Priority:** P2
**Location:** Repo-wide animation inventory: `skeleton.tsx:4` (`animate-pulse`), `app/loading.tsx:5` (`animate-spin`), ubiquitous `transition-colors`
**Problem:** No `prefers-reduced-motion` handling anywhere (`motion-safe:` absent); pulse/spin animations run unconditionally.
**Why it matters:** Vestibular-sensitive users get continuous motion with no opt-out; trivial to remediate.
**Recommended fix:** Gate decorative animation behind `motion-safe:` variants (theme provider already sets `disableTransitionOnChange` for theme swaps).

---

# Design System Improvements

## 1. Brand color: reconnect the blue/yellow identity

- **Evidence:** Brand defaults live only in `packages/themes/src/index.ts:15-16` (`#2563eb`, `#f59e0b`) and literal copies in `theme-selector.tsx:14`, `color-picker.tsx:11-18`. The dashboard token `--primary` is near-black (`globals.css:12,35`); `--ring` follows it (`:24,47`). Analytics adds five unrelated series hexes (`analytics-page.tsx:49-55`); admin revenue adds `#10b981` (`revenue-panel.tsx:166`).
- **Consequence:** Primary buttons, active-nav pills, links (`text-primary underline` in docs — renders black-underlined, `docs-page.tsx:130-132`), and focus rings carry no brand identity; the product's signature gradient exists only inside the widget it configures. Meanwhile ad-hoc hexes create dark-mode-hostile accents.
- **Recommendations:**
  - Introduce brand tokens: map `--primary` to blue-600 family (light/dark tuned) and reserve amber as `--accent-brand`/gradient pair; keep neutral `--secondary` for quiet actions.
  - Register chart series colors as CSS variables with `.dark` overrides; consume via `var(--chart-1…n)`.
  - Import (not re-hardcode) `DEFAULT_PRIMARY_COLOR/ACCENT_COLOR` wherever the classic gradient is referenced.

## 2. Consolidate duplicated primitives (component consistency)

- **Status badges ×4** (websites `status-badge.tsx:5-11`, knowledge `knowledge-page.tsx:20-25`, conversations `format.ts:12-15`, billing `billing-page.tsx:39-54`, profile inline `:58-71`): extract one `Badge` with semantic variants; mandate `dark:` variants (profile-page is the reference implementation).
- **StatCard ×3** (`dashboard-home.tsx:40`, `analytics-page.tsx:57`, `usage-page.tsx:36`): one component with size/hint props.
- **Error banner ×7** and **EmptyState ×2 idioms** (shared `empty-state.tsx` vs websites' inline dashed box `website-list.tsx:224-235`): one Alert/ErrorBanner; always use shared EmptyState.
- **CopyButton ×4** and **hand-styled `<select>` ×5** (`conversations-page.tsx:92`, `analytics-page.tsx:496`, `widget-page.tsx:104`, `widget-editor.tsx:253,270,296`, `widget-test-page.tsx:104`, admin selects): build Select/Input-select primitives.
- **Delete `TERMINAL_CRAWL_STATUSES` duplicate** (`websites/hooks.ts:28` vs unused `website-list.tsx:23`) and dead `features/admin/audit-panel.tsx`.

## 3. Typography scale

- Main KPI tiles consistently `text-3xl font-bold tracking-tight` — good baseline. Drift: secondary stats use `text-2xl` (`dashboard-home.tsx:128-136`), `text-xl` (`analytics-page.tsx:695-703`), `text-lg` (`:644,652`). Redundant `font-sans` on nearly every heading (body already sans, `globals.css:84`). No display sizes for future marketing (LP-013).
- Recommendation: publish a type ramp (display-4xl/3xl, title-2xl/xl, body-sm/base, caption-xs) in comments/tokens; strip redundant `font-sans`; assign each secondary-stat tier explicitly.

## 4. Radius & shadows

- Base radius `0.625rem` with sm/md/lg/xl derivations (`globals.css:70-73`) is sound. Drift: inner tiles pick `rounded-md`/`rounded-lg` ad hoc (`billing-page.tsx:151`, `widget-editor.tsx:141`, `allowed-domains-editor.tsx:130`); elevations mix `shadow-sm` (cards), `shadow-md` (menus `theme-toggle.tsx:65`), `shadow-lg`/`shadow-xl` (dialogs/previews) with no stated rule.
- Recommendation: codify elevation ladder (overlay > popover > card) and inner-tile radius (= `radius-md` inside `radius-lg` cards); note `ring-offset` needs `ring-offset-background` for dark (DB-008).

## 5. Spacing system

- Rhythm is disciplined (`gap-4` grids, `gap-8` page stacks, `py-8 md:px-10` content) — the main risks are the double-padding interaction between route loaders and the shell (DB-029) and one-off paddings in dialogs. Keep the 4-point rhythm; fix loader padding ownership.

## 6. Color semantics

- Success/error currently expressed four ways: pastel chips (`bg-green-100 text-green-800`), soft alpha (`bg-emerald-500/15`), strong text (`text-green-700`/`emerald-600`), and raw greens in success boxes (`add-website-dialog.tsx:131-134`). Most lack `dark:` variants; two files prove the intended dark-safe recipe (`profile-page.tsx:61-100`, `verification-reminder.tsx:57-80`).
- Recommendation: semantic tokens `--success/--warning/--info` (+ foreground/border/subtle variants) added to `globals.css`; migrate chips/banners; forbid raw `*-100/*-800` pairs in review.

---

# Recommended Implementation Plan

## P0 — ship first (correctness, data-loss, blocking a11y/conversion)

| ID                 | Fix                                                                                      |
| ------------------ | ---------------------------------------------------------------------------------------- |
| LP-001/002/003/006 | Marketing route group: landing + navbar + hero + end-to-end CTA flow (single initiative) |
| DB-002             | Onboarding checklist for new tenants on dashboard home                                   |
| DB-006             | Unsaved-changes guards + sticky save in widget builder                                   |
| DB-012             | "Current plan" marker; prevent self-repurchase; downgrade/cancel path                    |
| DB-016             | Split colliding analytics feedback queryKeys (+ regression test)                         |
| DB-014             | Retrofit accessible dialog into API-key dialog; harden hook (inert scope)                |
| DB-032             | Skip link in shell                                                                       |

## P1 — next wave (trust, consistency, keyboard usability)

DB-001 (nav grouping/icons) · DB-003 (header title) · DB-004 (real quick actions) · DB-005 (status honesty + live region) · DB-007 (color-picker validation/sync) · DB-008 (radiogroup keyboard + swatch focus) · DB-009 (preview semantics/fake controls) · DB-011 (empty-state CTAs + cross-links) · DB-015 (ConfirmDialog for all destroys + last_used_at) · DB-017 (skeleton count + 7-query error states + aria-pressed) · DB-019 (over-limit state + meters a11y) · DB-020 (admin table a11y/context) · DB-023 (hydration flash + Suspense skeletons + dark banners) · DB-026 (settings promise vs reality) · DB-027 (Alert primitive, unify error screens) · DB-028 (throw on auth-expiry; kill null-regions) · DB-030 (one CopyButton + scrollable code) · DB-033 (heading levels) · DB-034 (focus ring strength/consistency) · DB-035 (ProgressMeter) · DB-036 (dynamic charts) · LP-004/005/007/009/010/013 (features grid, public docs, pricing, footer, trust, display type)

## P2 — polish wave

DB-018 (chart tokens/loading-vs-empty/legends) · DB-010 (preview externals) · DB-013 (table semantics + naming) · DB-021 (admin drift cleanup + plan-change confirm + dead code) · DB-022 (guard navigation) · DB-024 (password rules/visibility) · DB-025 (duplicate CTA/emoji) · DB-029 (per-route skeletons) · DB-031 (toast detail/palette) · DB-037 (reduced motion) · LP-008/011/012 (FAQ, auth branding, funnel instrumentation) — plus the design-system migrations above (semantic color tokens, Badge/Select/StatCard consolidation, typography ramp, elevation ladder).

---

_End of audit. Sources: file-path + line-number citations inline throughout; no runtime testing performed; all findings derive from static codebase evidence._
