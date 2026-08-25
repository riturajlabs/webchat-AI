# WebChat AI — Dashboard

The customer-facing web application for [WebChat AI](../../README.md): a platform for building
website-connected AI chat assistants. The dashboard lets users connect websites, crawl them into a
retrieval-augmented knowledge base, monitor conversations and analytics, manage billing and API
keys, customize the embeddable chat widget, and (for platform super admins) operate the tenant
admin console. It also hosts the public marketing site and product documentation.

Part of the WebChat AI monorepo:

| Path              | Description                                        |
| ----------------- | -------------------------------------------------- |
| `apps/dashboard`  | This app — Next.js dashboard + marketing/docs site |
| `apps/widget`     | Embeddable chat widget loaded on customer sites    |
| `backend/`        | FastAPI backend (REST + SSE), MongoDB, ARQ workers |
| `packages/themes` | Shared design tokens                               |

## Tech stack

- **Next.js 15** (App Router, Turbopack) with **React 19** and **TypeScript 5**
- **Tailwind CSS v4** with shadcn-style UI primitives (`components/ui`), Radix `Slot`,
  `class-variance-authority`, `tailwind-merge`
- **TanStack Query v5** for server state; **sonner** for toasts; **next-themes** for dark mode;
  **lucide-react** icons; **recharts** for charts (code-split via `next/dynamic`)
- **Vitest** + React Testing Library (jsdom) for unit tests
- **ESLint 9** flat config (`eslint-config-next`) and `tsc --noEmit` type checking

## Development setup

Prerequisites: Node.js 20+, pnpm, and the FastAPI backend running locally.

```bash
# from the repository root
pnpm install

# start the backend first (see backend/ for setup) — expected at http://localhost:8000

# run the dashboard dev server (Turbopack)
pnpm --filter @webchat/dashboard dev
```

Open http://localhost:3000. Register an account, confirm the email verification code, and sign in.
Protected routes are guarded twice: `src/middleware.ts` performs a cookie-presence redirect to
`/login`, and `AuthGuard` enforces the real session client-side.

## Environment variables

All variables are optional and build-time inlined (`NEXT_PUBLIC_*`). Defaults suit local
development.

| Variable                          | Default                 | Purpose                                                 |
| --------------------------------- | ----------------------- | ------------------------------------------------------- |
| `NEXT_PUBLIC_API_URL`             | `http://localhost:8000` | Backend API base URL                                    |
| `NEXT_PUBLIC_SITE_URL`            | `http://localhost:3000` | Canonical origin used for SEO metadata, sitemap, robots |
| `NEXT_PUBLIC_REFRESH_COOKIE_NAME` | `refresh_token`         | Refresh cookie name checked by middleware               |
| `NEXT_PUBLIC_CSRF_COOKIE_NAME`    | `csrf_token`            | CSRF cookie name checked by middleware                  |

## Available scripts

Run via `pnpm --filter @webchat/dashboard <script>` (or inside `apps/dashboard`):

| Script      | Command                  | Description                |
| ----------- | ------------------------ | -------------------------- |
| `dev`       | `next dev --turbopack`   | Development server         |
| `build`     | `next build --turbopack` | Production build           |
| `start`     | `next start`             | Serve the production build |
| `lint`      | `eslint`                 | Lint                       |
| `typecheck` | `tsc --noEmit`           | Type check                 |
| `test`      | `vitest run`             | Unit tests                 |

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

Conventions: route groups separate public/authenticated trees; each feature owns its components,
hooks, types and tests; generic formatters live in `src/lib/format.ts`; shared primitives live in
`src/components/ui`. Historical audit and verification reports are archived in
[`reports/archive`](../../reports/archive).
