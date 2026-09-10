import type { NextConfig } from 'next';

/**
 * Backend (Railway) origin the Dashboard proxies `/api/*` to.
 *
 * The Dashboard and API are deployed to different registrable domains
 * (Vercel vs Railway). Auth cookies are host-only (no `Domain`) and
 * `SameSite=Strict`, so they are only sent to the backend's own origin — the
 * Vercel-side middleware can never see a session issued by the Railway host.
 * Making browser API calls same-origin (via `NEXT_PUBLIC_API_URL` = the
 * Dashboard origin) and proxying `/api/*` back to this backend restores the
 * cookie security model (ADR-003) and lets the middleware gate `/dashboard`.
 *
 * This destination is deliberately independent of `NEXT_PUBLIC_API_URL`:
 * that variable chooses what the *browser* calls (the same-origin Dashboard
 * URL in production), whereas this rewrite target is the actual backend the
 * *server* forwards to.
 *
 * Path mapping is 1:1 (no `/api/api`): the request `/api/health/live` rewrites
 * to `https://webchat-ai-production-7e84.up.railway.app/api/health/live`.
 */
const BACKEND_ORIGIN =
  process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'https://webchat-ai-production-7e84.up.railway.app';

/** The relative path prefix the Dashboard serves as its same-origin API. */
const API_PATH_PREFIX = '/api';

const nextConfig: NextConfig = {
  output: 'standalone',
  transpilePackages: ['@webchat/themes'],
  async rewrites() {
    return [
      {
        source: `${API_PATH_PREFIX}/:path*`,
        destination: `${BACKEND_ORIGIN}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
