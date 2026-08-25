/**
 * Canonical site origin for SEO metadata, sitemap and robots.
 *
 * `NEXT_PUBLIC_SITE_URL` is baked in at build time when provided (production);
 * the default mirrors the placeholder dashboard origin used across embed
 * documentation (`DASHBOARD_URL`).
 */
export const SITE_URL = (
  process.env.NEXT_PUBLIC_SITE_URL ?? 'https://app.webchatai.example'
).replace(/\/$/, '');

export const SITE_NAME = 'WebChat AI';

export const SITE_DESCRIPTION = 'Build intelligent AI assistants trained on your website content.';
