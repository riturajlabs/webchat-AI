# WebChat AI — Dashboard

The customer-facing web application for [WebChat AI](../../README.md): the
Next.js dashboard where tenants connect websites, crawl them into a
retrieval-augmented knowledge base, monitor conversations and analytics, manage
billing and API keys, and customize the embeddable chat widget. It also hosts
the public marketing site, product documentation, and — for platform super
admins — the tenant admin console.

Part of the WebChat AI monorepo:

| Path              | Description                                            |
| ----------------- | ------------------------------------------------------ |
| `apps/dashboard`  | This app — Next.js dashboard + marketing/docs site     |
| `apps/widget`     | Embeddable chat widget loaded on customer sites        |
| `backend/`        | FastAPI backend (REST + SSE), MongoDB, ARQ workers     |
| `packages/themes` | Shared widget theme presets + resolve engine           |
| `docs/`           | Design documents, ADRs, deployment docs, audit reports |

## Tech stack

- **Next.js 15** (App Router, Turbopack), React 19, TypeScript 5
- **Tailwind CSS v4** with shadcn-style primitives (`components/ui`), Radix
  `Slot`, `class-variance-authority`, `tailwind-merge`
- **TanStack Query v5** for server state; **sonner** toasts; **next-themes**
  dark mode; **lucide-react** icons; **recharts** charts (code-split via
  `next/dynamic`)
- **Vitest** + React Testing Library (jsdom) for unit tests
- **ESLint 9** flat config (`eslint-config-next`) and `tsc --noEmit` type checking

## How the dashboard talks to the backend

The dashboard and API are deployed to **different registrable domains** (e.g.
Vercel vs Railway). Auth cookies are host-only (`SameSite=Strict`) and are only
ever sent to the backend's own origin, so the browser can never call the backend
cross-origin with a session.

The dashboard therefore keeps **all browser API calls same-origin** under
`/api/*` and proxies them server-side to the real backend:

- `src/lib/api.ts` — `API_BASE_URL = NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'`.
  This is the origin the _browser_ calls (in production: the dashboard's own
  origin, so requests stay same-origin).
- `next.config.ts` — `next.config.ts` rewrites `/api/:path*` → `${BACKEND_ORIGIN}/api/:path*`
  where `BACKEND_ORIGIN = NEXT_PUBLIC_BACKEND_API_URL ?? 'https://webchat-ai-production-7e84.up.railway.app'`.
  This destination is deliberately independent of `NEXT_PUBLIC_API_URL`: it is
  the origin the _server_ forwards to (see ADR-003 in
  [docs/07-Architecture-Decisions.md](../../docs/07-Architecture-Decisions.md)).
- `src/middleware.ts` — cookie-presence redirect to `/login?redirect=…` for
  protected routes; `AuthGuard` enforces the real session client-side.

Path mapping is 1:1 — `/api/health/live` on the dashboard proxies to
`/api/health/live` on the backend (no `/api/api`).

## Development setup

Prerequisites: Node.js 20+, pnpm, and the FastAPI backend running locally.

```bash
# from the repository root
pnpm install

# start the backend first (see backend/README.md) — expected at http://localhost:8000

# run the dashboard dev server (Turbopack)
pnpm --filter @webchat/dashboard dev
```

Open http://localhost:3000. Register an account, confirm the email verification
code, and sign in. In development the `Rewrite` above is pointed at
`http://localhost:8000` via `NEXT_PUBLIC_BACKEND_API_URL`, or relies on the
default.

## Environment variables

All variables are build-time inlined (`NEXT_PUBLIC_*`). Defaults suit local
development.

| Variable                          | Default                                             | Purpose                                                                                |
| --------------------------------- | --------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `NEXT_PUBLIC_API_URL`             | `http://localhost:8000`                             | Backend API base URL the **browser** calls (same-origin in prod: the dashboard origin) |
| `NEXT_PUBLIC_BACKEND_API_URL`     | `https://webchat-ai-production-7e84.up.railway.app` | Backend origin the **server** proxies `/api/*` to                                      |
| `NEXT_PUBLIC_SITE_URL`            | `https://webchatai.com`                             | Canonical origin for SEO metadata (`src/lib/site.ts`)                                  |
| `NEXT_PUBLIC_REFRESH_COOKIE_NAME` | `refresh_token`                                     | Refresh cookie name checked by middleware                                              |
| `NEXT_PUBLIC_CSRF_COOKIE_NAME`    | `csrf_token`                                        | CSRF cookie name checked by middleware                                                 |
| `NEXT_PUBLIC_WIDGET_SCRIPT_URL`   | —                                                   | URL of the hosted widget bundle used in embed snippets                                 |
| `NEXT_PUBLIC_WIDGET_API_URL`      | —                                                   | Widget API origin used in embed snippets                                               |
| `NEXT_PUBLIC_DASHBOARD_URL`       | falls back to `NEXT_PUBLIC_SITE_URL`                | Public dashboard origin for embed snippets                                             |

The production build runs `scripts/check-production-env.mjs` first and fails fast
if `NEXT_PUBLIC_API_URL` is unset or a loopback/placeholder (the same guard the
CD deployment enforces — see [docker/README.md](../../docker/README.md)).

## Available scripts

Run via `pnpm --filter @webchat/dashboard <script>` (or inside `apps/dashboard`):

| Script      | Command                                                           | Description                    |
| ----------- | ----------------------------------------------------------------- | ------------------------------ |
| `dev`       | `next dev --turbopack`                                            | Development server             |
| `build`     | `node scripts/check-production-env.mjs && next build --turbopack` | Production build (proxy guard) |
| `start`     | `next start`                                                      | Serve the production build     |
| `lint`      | `eslint`                                                          | Lint                           |
| `typecheck` | `tsc --noEmit`                                                    | Type check                     |
| `test`      | `vitest run`                                                      | Unit tests                     |

## Folder architecture

```
src/
├── app/
│   ├── (auth)/          # Public auth flows: login, register, verify-email (+ loading/error states)
│   ├── (dashboard)/     # Authenticated app: all feature routes under the DashboardShell layout
│   ├── (marketing)/     # Public landing page, pricing/legal pages, /docs section
│   ├── globals.css      # Tailwind v4 theme tokens (brand palette in CSS variables)
│   ├── layout.tsx       # Root layout, fonts, SEO metadata base
│   ├── sitemap.ts       # Generated sitemap (app + docs routes)
│   └── robots.ts        # Robots rules
├── components/
│   ├── layout/          # DashboardShell, nav groups/items, PageHeader, MobileNav, admin nav
│   ├── theme/           # Theme toggle/provider helpers
│   └── ui/              # shadcn-style primitives (button, card, dialog, input, status-badge, …)
├── features/            # Domain modules — one folder per feature
│   ├── admin/           # Super-admin console: tenants, users, revenue, crawl jobs, system, audit
│   ├── analytics/       # Usage dashboards and code-split recharts visualisations
│   ├── api-keys/        # Developer API key management
│   ├── auth/            # Session context, AuthGuard, login/register forms, verification
│   ├── billing/         # Plans, checkout, invoices
│   ├── conversations/   # Chat history list/detail
│   ├── dashboard/       # Home overview cards and system status
│   ├── docs/            # Shared documentation content and code blocks
│   ├── knowledge/       # Knowledge base browser
│   ├── profile/         # Profile management
│   ├── settings/        # Workspace settings
│   ├── websites/        # Site connection, crawling, crawl-job tracking (SSE)
│   └── widget/          # Widget appearance builder, embed snippet generation, test harness
├── lib/                 # API client, session storage, shared formatters, utilities, site config
└── middleware.ts        # Route protection (cookie presence check → /login?redirect=…)
```

## Further reading

- Backend API + RAG pipeline: [`backend/README.md`](../../backend/README.md)
- Widget SDK: [`apps/widget/README.md`](../widget/README.md)
- Index of all docs (design, ADRs, deployment, audit reports):
  [`docs/README.md`](../../docs/README.md)
