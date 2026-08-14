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

/**
 * Describe which environment an embed snippet targets.
 *
 * The backend serves the dashboard its authoritative `embed_script`: local
 * `WIDGET_SCRIPT_URL`/`WIDGET_API_BASE_URL` values in development, the CDN and
 * public API in production. This powers the "environment notes" panel so a
 * developer never pastes a localhost snippet into a live page.
 */
export function describeEmbedEnvironment(embedScript: string): {
  kind: 'development' | 'production';
  title: string;
  message: string;
} {
  const isLocal = /localhost|127\.0\.0\.1|0\.0\.0\.0|::1/.test(embedScript);
  if (isLocal) {
    return {
      kind: 'development',
      title: 'Development snippet',
      message:
        'This snippet points at your local widget dev server and API (localhost), so you can test the embed on your machine. When you deploy, the dashboard serves the production CDN snippet automatically.',
    };
  }
  return {
    kind: 'production',
    title: 'Production snippet',
    message:
      'This snippet loads the production widget bundle from the CDN and talks to the public widget API, so you can paste it straight into your site.',
  };
}
