/**
 * Multi-tenant brand logo resolution and fallback hierarchy.
 *
 * Global dynamic WebChat AI logo system (2026-09-16): chatbot identity resolves
 * with a single deterministic precedence:
 *
 *   1. Custom chatbot avatar  (config.avatar_url)
 *   2. Custom chatbot logo    (config.logo_url) — only when it is NOT the
 *      backend-injected website fallback. The API defaults `logo_url` to
 *      `website_logo_url`/`website_favicon_url` when the host configures no
 *      logo, so a `logo_url` equal to either website field is website identity,
 *      not a custom logo, and is skipped.
 *   3. Official WebChat AI logo (bundled default mark) — the product default.
 *   4. botGlyph SVG — defensive last resort only (the bundled default is a
 *      data URI that cannot fail), so a broken-image placeholder never renders.
 *
 * Website logo / website favicon / host-page favicon deliberately do NOT take
 * part in the chatbot identity chain; website identity stays on website
 * surfaces (e.g. the website preview card). Runtime errors cascade down the
 * source list via <img> onerror; user-supplied custom logos must be http(s)
 * (audit W-22) or they are skipped straight to the default.
 */

import type { WidgetPublicConfig } from '../config/types';
import { botGlyph } from './icons';

/**
 * Official WebChat AI logo mark, bundled as a data URI so the self-contained
 * embed SDK renders the product default without network access. The bytes are
 * identical to `apps/dashboard/src/app/icon.png`, a verified pixel-perfect
 * 64×64 downscale of the canonical `apps/dashboard/public/logo.png`; the single
 * source of truth for the brand mark remains `public/logo.png`.
 */
export const DEFAULT_BRAND_LOGO =
  'data:image/png;base64,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';

/** Only http(s) URLs may be rendered from user config (audit W-22). */
export function isSafeImageUrl(url: string): boolean {
  return /^https?:\/\//i.test(url);
}

/** True when `logo_url` is a genuinely custom host logo, not the website fallback. */
function isCustomLogo(config: WidgetPublicConfig): boolean {
  if (!config.logo_url) {
    return false;
  }
  const websiteFallbacks = [config.website_logo_url, config.website_favicon_url].filter(
    (value): value is string => typeof value === 'string',
  );
  return !websiteFallbacks.includes(config.logo_url);
}

/**
 * Build an ordered, deduplicated list of custom-brand candidates following the
 * global precedence. The official default mark is appended by `renderBrandLogo`.
 */
export function getBrandLogoCandidates(config: WidgetPublicConfig): string[] {
  const candidates = [config.avatar_url, isCustomLogo(config) ? config.logo_url : null];

  const seen = new Set<string>();
  const valid: string[] = [];
  for (const candidate of candidates) {
    if (typeof candidate === 'string') {
      const trimmed = candidate.trim();
      if (trimmed && isSafeImageUrl(trimmed) && !seen.has(trimmed)) {
        seen.add(trimmed);
        valid.push(trimmed);
      }
    }
  }
  return valid;
}

/**
 * Render brand icon/logo with automatic cascading fallback and runtime onerror
 * recovery: custom avatar → custom logo → official WebChat AI default →
 * defensive botGlyph. A broken-image placeholder is never rendered.
 */
export function renderBrandLogo(
  container: HTMLElement,
  config: WidgetPublicConfig,
  className: string,
): void {
  container.replaceChildren();
  const sources = [...getBrandLogoCandidates(config), DEFAULT_BRAND_LOGO];

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
    if (index < sources.length) {
      img.src = sources[index];
    } else {
      img.onerror = null;
      container.replaceChildren(botGlyph());
    }
  };

  img.src = sources[0];
  container.appendChild(img);
}
