/**
 * Canonical public origin of the marketing site + dashboard.
 *
 * Used by root metadata (`metadataBase`, OpenGraph/Twitter URLs), the
 * sitemap and robots files. Override per environment with
 * `NEXT_PUBLIC_SITE_URL`; the fallback matches `next dev` defaults.
 */
export const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? 'http://localhost:3000';
