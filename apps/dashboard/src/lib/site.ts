/**
 * Canonical site origin for SEO metadata, sitemap and robots.
 *
 * `NEXT_PUBLIC_SITE_URL` is baked in at build time when provided (production).
 * The fallback is the public marketing domain.
 */
export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL ?? 'https://webchatai.com').replace(
  /\/$/,
  '',
);

export const SITE_NAME = 'WebChat AI';

export const SITE_DESCRIPTION = 'Build intelligent AI assistants trained on your website content.';
