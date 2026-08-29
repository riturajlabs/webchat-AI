/**
 * Helpers for the widget test environment (/widget-test).
 *
 * The test page embeds the *real* widget SDK inside an `<iframe srcdoc>`. The
 * srcdoc document inherits the dashboard's origin, so the widget's API calls
 * carry `Origin: <dashboard origin>` — a configured dashboard origin is always
 * permitted by the backend origin guard, which is exactly what the page wants
 * to demonstrate.
 */

/**
 * Extract the `src="…"` value from a backend-generated embed script, or `null`
 * when the snippet has no script source. The regex targets exactly the script
 * `src` attribute (the `data-api-base-url` attribute never contains `src=`).
 */
export function parseScriptSrc(embedScript: string): string | null {
  const match = embedScript.match(/src="([^"]+)"/);
  return match ? match[1] : null;
}

/**
 * Extract the `data-api-base-url="…"` value from a backend-generated embed
 * script, or `null` when absent. This pins the API origin the SDK resolves to
 * (the backend includes it so the embed does not fall back to same-origin).
 */
export function parseApiBaseUrl(embedScript: string): string | null {
  const match = embedScript.match(/data-api-base-url="([^"]+)"/);
  return match ? match[1] : null;
}

/**
 * A standalone HTML document that boots the real widget SDK for a widget id.
 * Sized to fill its iframe; the SDK injects the launcher automatically from
 * `data-widget-id` (no init() call required).
 *
 * `apiBaseUrl` is forwarded as `data-api-base-url` on the script tag so the SDK
 * resolves the API origin to the backend instead of falling back to the srcdoc
 * iframe's own origin (the dashboard), which made config/session calls 404.
 */
export function buildWidgetTestHtml({
  scriptSrc,
  widgetId,
  apiBaseUrl,
}: {
  scriptSrc: string;
  widgetId: string;
  apiBaseUrl?: string;
}): string {
  const apiAttr = apiBaseUrl ? ` data-api-base-url="${apiBaseUrl}"` : '';
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Widget test — ${widgetId}</title>
    <style>
      html, body { margin: 0; height: 100%; }
      body { font-family: ui-sans-serif, system-ui, sans-serif; background: #f1f5f9; }
    </style>
  </head>
  <body>
    <script src="${scriptSrc}" data-widget-id="${widgetId}"${apiAttr} defer></script>
  </body>
</html>`;
}

/** The public widget config endpoint for a widget id. */
export function buildPublicConfigUrl(apiBaseUrl: string, widgetId: string): string {
  return `${apiBaseUrl.replace(/\/$/, '')}/api/widget/v1/config/${widgetId}`;
}

/** Shape of the public config / error envelope returned by the backend. */
export interface PublicConfigResponse {
  statusCode: number;
  enabled?: boolean;
  allowedDomains?: string[];
  errorCode?: string;
  message?: string;
}

/**
 * Call the public widget config endpoint from the dashboard origin.
 *
 * The browser sends `Origin: <dashboard origin>` on this cross-origin request,
 * so the response doubles as a live check of the origin guard: `200` means the
 * dashboard origin is permitted, `403` shows the exact guard code
 * (WIDGET_ORIGIN_NOT_ALLOWED / WIDGET_DOMAIN_NOT_CONFIGURED) to debug.
 */
export async function fetchPublicConfig(
  apiBaseUrl: string,
  widgetId: string,
): Promise<PublicConfigResponse> {
  let response: Response;
  try {
    response = await fetch(buildPublicConfigUrl(apiBaseUrl, widgetId), {
      headers: { Accept: 'application/json' },
    });
  } catch {
    return { statusCode: 0, message: 'The widget API is unreachable from this origin.' };
  }
  const text = await response.text();
  let payload: {
    enabled?: boolean;
    allowed_domains?: string[];
    error?: { code?: string; message?: string };
  } | null = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = null;
  }
  if (response.ok && payload) {
    return {
      statusCode: response.status,
      enabled: payload.enabled,
      allowedDomains: payload.allowed_domains,
    };
  }
  return {
    statusCode: response.status,
    errorCode: payload?.error?.code,
    message: payload?.error?.message,
  };
}
