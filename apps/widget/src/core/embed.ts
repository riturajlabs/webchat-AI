/**
 * Embed auto-upgrade (plan §5.1).
 *
 * The one-line embed script carries `data-widget-id` on the `<script>` tag.
 * `autoUpgrade()` reads it, locates (or creates) the `<webchat-widget>` custom
 * element, and upgrades it with the widget id — no `init()` call required.
 */

import { mount, type WidgetController } from './mount';

export interface EmbedResult {
  widgetId: string;
  controller: WidgetController | null;
}

/**
 * Auto-upgrade from the current script tag. Returns `null` when the script
 * carries no `data-widget-id` (programmatic `init()` use instead).
 */
export function autoUpgrade(): EmbedResult | null {
  const script = document.currentScript as HTMLScriptElement | null;
  const widgetId = script?.dataset?.widgetId;
  if (!widgetId) {
    return null;
  }
  const apiBaseUrl = script?.dataset?.apiBaseUrl;

  let host = document.querySelector<HTMLElement>('webchat-widget');
  if (!host) {
    host = document.createElement('webchat-widget');
    document.body.appendChild(host);
  }

  const controller = mount({
    widgetId,
    apiBaseUrl,
    host,
    autoStart: true,
  });
  return { widgetId, controller };
}
