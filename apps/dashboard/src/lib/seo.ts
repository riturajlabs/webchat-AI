import type { Metadata } from 'next';

import { SITE_DESCRIPTION, SITE_NAME, SITE_URL } from '@/lib/site';

export interface PageSeoOptions {
  /** Canonical path, e.g. `/features` or `/`. */
  path: string;
  /** Document title for the page (rendered as `{title} | Site Name`). */
  title: string;
  /** Render `title` verbatim instead of letting the layout template append the site name. */
  absoluteTitle?: boolean;
  /** Meta + Open Graph description. Defaults to the site description. */
  description?: string;
}

/**
 * Builds page `Metadata` with a canonical URL, Open Graph and Twitter tags for
 * the given path, so every public page emits `rel="canonical"` + `og:url` that
 * resolve to the deployed `SITE_URL` origin.
 */
export function seoPage({ path, title, absoluteTitle, description }: PageSeoOptions): Metadata {
  const canonical = new URL(path === '/' ? '/' : path, SITE_URL).toString();
  const metaDescription = description ?? SITE_DESCRIPTION;

  return {
    title: absoluteTitle ? { absolute: title } : title,
    description: metaDescription,
    alternates: { canonical },
    openGraph: {
      type: 'website',
      siteName: SITE_NAME,
      title,
      description: metaDescription,
      url: canonical,
    },
    twitter: {
      card: 'summary_large_image',
      title,
      description: metaDescription,
    },
  };
}
