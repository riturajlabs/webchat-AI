/**
 * Multi-tenant brand logo resolution and fallback hierarchy (Issue 4).
 *
 * Fallback hierarchy:
 * 1. Custom uploaded widget logo / avatar (config.avatar_url / config.logo_url)
 * 2. Website logo / preview image (config.website_logo_url)
 * 3. Website favicon / icon (config.website_favicon_url or host page favicon)
 * 4. WebChat AI generic fallback icon (built-in SVG botGlyph)
 *
 * Runtime error handling:
 * An <img> element is mounted with the highest-priority candidate.
 * If image loading fails (HTTP 404, CORS, invalid image, timeout),
 * the onerror listener advances to the next candidate in the hierarchy.
 * If all candidates fail, it replaces the container content with the built-in botGlyph SVG.
 * A broken image placeholder is never rendered.
 */

import type { WidgetPublicConfig } from '../config/types';
import { botGlyph } from './icons';

/** Only http(s) URLs may be rendered (audit W-22). */
export function isSafeImageUrl(url: string): boolean {
  return /^https?:\/\//i.test(url);
}

/**
 * Discover host page favicon from the embedding document if available.
 */
export function getHostFaviconUrl(): string | null {
  try {
    if (typeof document !== 'undefined') {
      const link =
        document.querySelector<HTMLLinkElement>('link[rel~="icon"]') ||
        document.querySelector<HTMLLinkElement>('link[rel="shortcut icon"]');
      if (link && link.href && isSafeImageUrl(link.href)) {
        return link.href;
      }
    }
  } catch {
    // Non-browser or sandboxed context: safely ignore
  }
  return null;
}

/**
 * Build an ordered, deduplicated list of candidate image URLs following the fallback hierarchy.
 */
export function getBrandLogoCandidates(config: WidgetPublicConfig): string[] {
  const candidates: (string | null | undefined)[] = [
    config.avatar_url,
    config.logo_url,
    config.website_logo_url,
    config.website_favicon_url,
    getHostFaviconUrl(),
  ];

  const seen = new Set<string>();
  const valid: string[] = [];
  for (const c of candidates) {
    if (typeof c === 'string') {
      const trimmed = c.trim();
      if (trimmed && isSafeImageUrl(trimmed) && !seen.has(trimmed)) {
        seen.add(trimmed);
        valid.push(trimmed);
      }
    }
  }
  return valid;
}

/**
 * Render brand icon/logo with automatic cascading fallback and runtime onerror recovery.
 */
export function renderBrandLogo(
  container: HTMLElement,
  config: WidgetPublicConfig,
  className: string,
): void {
  container.replaceChildren();
  const candidates = getBrandLogoCandidates(config);

  if (candidates.length === 0) {
    container.appendChild(botGlyph());
    return;
  }

  let index = 0;
  const img = document.createElement('img');
  img.className = className;
  img.alt = '';
  img.referrerPolicy = 'no-referrer';

  img.onerror = () => {
    if (img.parentElement !== container) {
      return;
    }
    index++;
    if (index < candidates.length) {
      img.src = candidates[index];
    } else {
      img.onerror = null;
      container.replaceChildren(botGlyph());
    }
  };

  img.src = candidates[0];
  container.appendChild(img);
}
