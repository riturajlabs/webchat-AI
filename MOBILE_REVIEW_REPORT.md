# WebChat AI — Mobile UI Review: Final Report

Date: 2026-09-12 · Branch: `main` · Base HEAD: `89cab5b` (do not reset)

## 1. Scope & Method

Verified the production web app (`apps/dashboard`) for real mobile/tablet layout defects at widths 320–430px using **DOM bounding-box / computed-layout proxy checks** (Playwright 1.63), not pixel heuristics. Auth bypassed via `csrf_token` session cookie + route mocks for `localhost:8000/api`, fixtures shape worst-case payloads (very long site names/URLs/file names). Run against the Turbopack dev server on `:3001` (port 3000 is the stale Docker build).

## 2. Results — all automated checks pass

| Check                                                                        | Result                  |
| ---------------------------------------------------------------------------- | ----------------------- |
| Proxy suite (10 assertion kinds, 13 app routes × 6 widths + 4 marketing × 6) | **0 failures**          |
| Overflow matrix (17 routes × 11 widths, 320→1920)                            | **187 / 187 pass**      |
| Drawer proxies (320x568, 375x480, 375x667, 390x844, 412x915)                 | pass                    |
| Dialog proxies (incl. extreme 375x300)                                       | pass                    |
| Unit tests (`vitest` `apps/dashboard`)                                       | **428 pass** (52 files) |
| `pnpm --filter @webchat/dashboard typecheck` (tsc --noEmit)                  | pass                    |
| `pnpm --filter @webchat/dashboard lint` (eslint)                             | pass                    |
| `pnpm --filter @webchat/dashboard build` (next build)                        | pass                    |
| `git diff --check`                                                           | clean                   |

## 3. Layout failures found by proxies this pass — every one fixed at the root cause

1. **`/websites` @320–430** — URL link `inline-flex … truncate` overflows card line box (L=33 R=152+ on 254px card). Root cause: inline-level `overflow-hidden` boxes are sized to their text's max-content by browsers and overflow their line → replaced with block-level `flex min-w-0` link + inner `min-w-0 truncate` span.
2. **`/websites` @320** — card grid `grid gap-4 md:…` base track is an `auto` track sized by max-content → long nowrap content blew the track out. Root cause: missing base `grid-cols-1` (minmax(0,1fr)). Applied to both grids.
3. **`/dashboard` @320** — bottom `grid gap-4 lg:grid-cols-3` auto base track; same root cause → added base `grid-cols-1`. Stretched "Quick Actions" links that sat in the grid collapsed back to content width.
4. **`/widget` + `/widget-test` @320–390** — native `<select>` width = width of its longest `<option>` (a long website name → 512px) inside a full-width actions row. Root cause: intrinsic select sizing → `min-w-0 max-w-full` on the selects + `max-w-full min-w-0` on the `PageHeader` actions wrapper so the actions row can clamp.
5. **`/widget` + `/widget-test` @320** — editor grid `grid gap-6 lg:grid-cols-[minmax(0,420px)_1fr] …` auto base track; same root cause → added base `grid-cols-1` (widget-editor.tsx:294 and widget-page.tsx skeleton). Pane scroll width dropped 528px → 329px.
6. **`/widget` @320** — last residual: "Add localhost testing" nowrap button (W=178) in the loopback-hosts card overflows to R=329 inside a `justify-between gap-3` row in a 254px card. Root cause: fixed single-line fill-width row with an unshrinkable button → added `flex-wrap` to that row (button wraps to its own line below the description). Pane scroll width 329 → 320 (clean).

Intentional horizontal scrolling (admin tables, docs nav strip, widget setup step nav, `<pre>` code, `overflow-x-auto` containers) was preserved and exempted in the proxies.

## 4. Drawer (mobile nav) — verified

Panel = full viewport height & width (0..320 × 0..568 etc.); nav region `overflow-y: auto`; scroll range fully used (e.g. 242/242, 330/330); the last item ("Settings", bottom) reachable and visible after scroll at every checked viewport; no bottom clipping; `document.body` never overflows. Existing fixes retained: `gap-2` p-3 header, drain relationships, click-away, Escape, count + auto-scan focus.

## 5. Dialogs — verified

AddWebsite dialog: fully inside viewport at 320–412 (incl. 375x300 forced), single scrollable `overflow-y: auto` panel, no page scroll, opens/closes by animation name, auto-focus summary, refocus trigger. Consistent across AddWebsite / delete / create-key / tenant dialogs.

## 6. Files changed for the root-cause fixes (this pass)

- `apps/dashboard/src/features/websites/website-card.tsx` — URL link `flex min-w-0` + inner `truncate` span.
- `apps/dashboard/src/features/websites/website-list.tsx` — both grids get base `grid-cols-1`.
- `apps/dashboard/src/features/dashboard/dashboard-home.tsx` — bottom grid base `grid-cols-1`.
- `apps/dashboard/src/features/widget/widget-page.tsx` — select `min-w-0 max-w-full`; editor grid base `grid-cols-1`.
- `apps/dashboard/src/features/widget/widget-test-page.tsx` — select `min-w-0 max-w-full`.
- `apps/dashboard/src/features/widget/components/widget-editor.tsx` — editor grid base `grid-cols-1`.
- `apps/dashboard/src/components/ui/page-header.tsx` — actions wrapper `max-w-full min-w-0`.
- `apps/dashboard/src/features/widget/components/allowed-domains-editor.tsx` — loopback-hosts row `flex-wrap`.
- `apps/dashboard/src/features/websites/website-card.test.tsx` — test updated to lock in the corrected link/truncate structure (was asserting the old buggy `truncate` on the anchor).

Earlier WIP fixes (verified, unchanged in spirit): drawer nav scroll container + safe-area padding, scrollable shared `use-accessible-dialog`, `dashboard-shell` `h-dvh overflow-hidden` + in-page scroll, text wrapping in conversations/details, knowledge failed-docs list, SSE banner, mobile-menu, device-preview fit, website-card actions `flex-wrap`.

## 7. Regression proof

- Proxies re-run on the final code → **0 failures** (`proxy-run.mjs` → "TOTAL proxy fail + drawer/dialog fail count: 0").
- Overflow matrix re-run → **187/187**.
- Unit tests re-run after the source changes → **428 pass** (after updating the one website-card test to match the corrected markup).

## 8. Committed?

No. Working tree retains all changes uncommitted for your review (`git status --short` shows 24 modified + 1 new file). Nothing was reset/restashed.

## 9. Artifacts

- Screenshots: `/tmp/opencode/pw/screens/` (98 PNGs, 6 mobile widths × app routes, drawer + dialog states, freshly regenerated on final code).
- Latest proxy results: `/tmp/opencode/pw/proxy-report.json`; overflow matrix: `/tmp/opencode/pw/report.json`.
- Harness: `/tmp/opencode/pw/` (`proxies.mjs`, `proxy-run.mjs`, `matrix.mjs`, `fixtures.mjs`, `lib.mjs`, probe scripts).

## 10. Notes / caveats

- Test port is `:3001` (dev). `:3000` is an unrelated old Docker build — ignore it.
- I could not visually inspect the screenshots (no image capability); they are for your human review. All layout assertions are mechanical and pass.
