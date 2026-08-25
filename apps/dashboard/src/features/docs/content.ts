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

/** Widget builder fields (PATCH /api/websites/{id}/widget). */
export const CONFIG_OPTIONS: { key: string; values: string; description: string }[] = [
  { key: 'theme', values: 'light | dark | auto', description: 'Color scheme of the widget.' },
  {
    key: 'position',
    values: 'bottom-right | bottom-left',
    description: 'Corner of the viewport where the launcher sits.',
  },
  {
    key: 'primary_color',
    values: '#rrggbb',
    description: 'Primary action color (launcher, send button, header).',
  },
  { key: 'accent_color', values: '#rrggbb', description: 'Secondary accent color.' },
  { key: 'font_size', values: 'sm | md | lg', description: 'Base font size inside the chat.' },
  { key: 'logo_url', values: 'https://…', description: 'Custom logo shown in the header.' },
  { key: 'avatar_url', values: 'https://…', description: 'Assistant avatar image.' },
  {
    key: 'welcome_message',
    values: 'text',
    description: 'Greeting shown above the first message.',
  },
  { key: 'placeholder', values: 'text', description: 'Composer placeholder text.' },
  {
    key: 'suggested_questions',
    values: 'string[] (max 5)',
    description: 'Quick-prompt chips offered to new visitors.',
  },
  {
    key: 'branding',
    values: 'true | false',
    description: 'Show the "Powered by WebChat AI" badge.',
  },
  {
    key: 'dark_mode',
    values: 'true | false',
    description: 'Force the dark theme regardless of the visitor system theme.',
  },
  {
    key: 'auto_open',
    values: 'true | false',
    description: 'Open the chat automatically for new visitors.',
  },
  {
    key: 'enabled',
    values: 'true | false',
    description: 'Hide the widget from the page entirely.',
  },
  {
    key: 'allowed_domains',
    values: 'string[] (max 50)',
    description:
      'Origins permitted to embed the widget. Empty = blocked until configured; use "*" for open embedding.',
  },
];

/** Public REST API endpoints exposed by the platform (tenant-scoped). */
export const API_ENDPOINTS: { method: string; path: string; description: string }[] = [
  { method: 'GET', path: '/api/websites', description: 'List registered websites.' },
  { method: 'POST', path: '/api/websites', description: 'Register a website for indexing.' },
  { method: 'GET', path: '/api/websites/{id}', description: 'Website detail and status.' },
  { method: 'PATCH', path: '/api/websites/{id}', description: 'Update website settings.' },
  { method: 'DELETE', path: '/api/websites/{id}', description: 'Delete a website and its data.' },
  {
    method: 'POST',
    path: '/api/websites/{id}/crawl',
    description: 'Queue a fresh crawl (202 Accepted).',
  },
  {
    method: 'GET',
    path: '/api/websites/{id}/widget',
    description: 'Widget configuration plus the authoritative embed script.',
  },
  {
    method: 'PATCH',
    path: '/api/websites/{id}/widget',
    description: 'Update widget appearance and behavior.',
  },
  {
    method: 'GET',
    path: '/api/conversations',
    description: 'Paginated conversations with search and website filters.',
  },
  {
    method: 'GET',
    path: '/api/conversations/{session_id}',
    description: 'Full message history for one conversation.',
  },
  {
    method: 'DELETE',
    path: '/api/conversations/{session_id}',
    description: 'Delete a conversation.',
  },
  { method: 'GET', path: '/api/analytics/summary', description: 'KPI summary for your tenant.' },
  { method: 'GET', path: '/api/analytics/timeseries', description: 'Daily usage timeseries.' },
  {
    method: 'GET',
    path: '/api/analytics/top-websites',
    description: 'Most active websites by conversations.',
  },
  {
    method: 'GET',
    path: '/api/analytics/performance',
    description: 'Response latency and quality metrics.',
  },
  {
    method: 'GET',
    path: '/api/api-keys',
    description: 'List API keys (secrets are shown once at creation).',
  },
  { method: 'POST', path: '/api/api-keys', description: 'Mint a new `wc_*` API key.' },
  { method: 'DELETE', path: '/api/api-keys/{key_id}', description: 'Revoke an API key.' },
];
