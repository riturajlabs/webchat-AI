/**
 * Shared developer-documentation content.
 *
 * Single source of truth for embed snippets and widget configuration data so
 * the docs never drift between surfaces. All snippets are derived from the
 * production helpers in `@/features/widget/embed` — never re-typed inline.
 */

import {
  buildEmbedScript,
  buildInitExample,
  buildMountExample,
  DASHBOARD_URL,
  DOCS_WIDGET_ID,
  WIDGET_API_URL,
  WIDGET_SCRIPT_URL,
} from '@/features/widget/embed';

export { DASHBOARD_URL, DOCS_WIDGET_ID, WIDGET_API_URL, WIDGET_SCRIPT_URL };

/** Ready-to-paste hosted-script snippet (placeholder widget id). */
export const SCRIPT_TAG = buildEmbedScript(DOCS_WIDGET_ID);

/** Hosted script with an explicit API-origin override. */
export const SCRIPT_TAG_WITH_API = `<script
  src="${WIDGET_SCRIPT_URL}"
  data-widget-id="${DOCS_WIDGET_ID}"
  data-api-base-url="${WIDGET_API_URL}"
  defer
></script>`;

/** SDK install command for bundler-based apps. */
export const INSTALL_COMMAND = `npm install @webchat/widget`;

/** Programmatic `init()` example (framework apps). */
export const INIT_EXAMPLE = buildInitExample(DOCS_WIDGET_ID, WIDGET_API_URL);

/** Programmatic `mount()` example (framework apps). */
export const MOUNT_EXAMPLE = buildMountExample(DOCS_WIDGET_ID);

/** CSP directive allowing the widget API origin. */
export const CSP_EXAMPLE = `connect-src 'self' ${WIDGET_API_URL};`;

/** Origin allowlist matching examples. */
export const ALLOWLIST_EXAMPLE = `https://example.com     → allowed
https://shop.example.com  → allowed (via *.example.com)
https://evil.example.net  → 403 Forbidden`;
