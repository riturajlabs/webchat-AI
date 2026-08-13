/**
 * Embed-code generation for the widget builder and developer docs.
 *
 * Production-style hosts (never localhost): the dashboard and API use the
 * deployed origins, and the widget SDK bundle is served from the CDN. In local
 * development the dashboard embed script comes from the backend API response
 * (`WidgetResponse.embed_script`); these helpers are used for the static
 * "advanced usage" examples and the developer documentation page.
 */

/** Where the built widget SDK bundle is served from. */
export const WIDGET_SCRIPT_URL = 'https://cdn.webchatai.example/webchat-widget.iife.min.js';

/** Public widget API origin (the SDK appends `/api/widget/v1`). */
export const WIDGET_API_URL = 'https://api.webchatai.example/api/widget/v1';

/** Dashboard origin shown in documentation links. */
export const DASHBOARD_URL = 'https://app.webchatai.example';

/** Placeholder widget id used in static documentation examples. */
export const DOCS_WIDGET_ID = 'YOUR_WIDGET_ID';

/**
 * Build the ready-to-paste embed script for a widget id.
 *
 * `defer` keeps the script from blocking page render; the launcher appears
 * once the bundle has run and auto-upgrades from `data-widget-id`.
 */
export function buildEmbedScript(widgetId: string, scriptSrc: string = WIDGET_SCRIPT_URL): string {
  return `<script src="${scriptSrc}" data-widget-id="${widgetId}" defer></script>`;
}

/** Programmatic `init()` example for framework apps. */
export function buildInitExample(widgetId: string, apiBaseUrl?: string): string {
  const override = apiBaseUrl ? `  apiBaseUrl: '${apiBaseUrl}',\n` : '';
  return `import { init } from '@webchat/widget';

const controller = init({
  widgetId: '${widgetId}',
${override}});`;
}

/** Programmatic `mount()` example for mounting into an existing element. */
export function buildMountExample(widgetId: string, apiBaseUrl?: string): string {
  const override = apiBaseUrl ? `  apiBaseUrl: '${apiBaseUrl}',\n` : '';
  return `import { mount } from '@webchat/widget';

const controller = mount({
  widgetId: '${widgetId}',
${override}  host: document.querySelector('#my-chat'), // optional
});`;
}
