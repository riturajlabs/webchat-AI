/**
 * Embed auto-upgrade (plan §5.1).
 *
 * The one-line embed script carries `data-widget-id` on the `<script>` tag.
 * `autoUpgrade()` reads it and upgrades **every** `<webchat-widget>` element
 * on the page (multi-embed). Each host is mounted independently with its own
 * widget id / API base (from the host's `data-widget-id` / `data-api-base-url`
 * attributes, falling back to the script tag's), keeps its own config and
 * session, and one failing host never blocks the others. Already-mounted hosts
 * are skipped. When no host exists, a single `<webchat-widget>` is created and
 * upgraded (original embed flow).
 */

import { mount, type WidgetController } from './mount';

export interface EmbedResult {
  widgetId: string;
  controller: WidgetController | null;
}

/**
 * Auto-upgrade every `<webchat-widget>` in the document from the current
 * script tag. Returns one result per mounted host — empty when there is
 * nothing to upgrade (no widget id anywhere) or every mount failed.
 */
export function autoUpgrade(): EmbedResult[] {
  const script = document.currentScript as HTMLScriptElement | null;
  const scriptWidgetId = script?.dataset?.widgetId;
  const scriptApiBaseUrl = script?.dataset?.apiBaseUrl;

  const hosts = document.querySelectorAll<HTMLElement>('webchat-widget');
  const results: EmbedResult[] = [];

  if (hosts.length === 0) {
    if (!scriptWidgetId) {
      return results;
    }
    // Original embed flow: no host on the page yet, create and upgrade one.
    try {
      const controller = mount({
        widgetId: scriptWidgetId,
        apiBaseUrl: scriptApiBaseUrl,
        autoStart: true,
      });
      results.push({ widgetId: scriptWidgetId, controller });
    } catch {
      // Ignored: there is nothing else to upgrade.
    }
    return results;
  }

  for (const host of hosts) {
    // A host's own attributes win; fall back to the script tag's.
    const widgetId = host.dataset.widgetId ?? scriptWidgetId;
    if (!widgetId) {
      continue;
    }
    const apiBaseUrl = host.dataset.apiBaseUrl ?? scriptApiBaseUrl;
    try {
      const controller = mount({ widgetId, apiBaseUrl, host, autoStart: true });
      results.push({ widgetId, controller });
    } catch {
      // Failure in one widget must not prevent the others from mounting.
    }
  }
  return results;
}
