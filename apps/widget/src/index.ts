/**
 * WebChat AI Widget SDK
 *
 * Framework-independent embeddable chatbot widget.
 * Entry point for the ES + UMD builds (window.WebChatWidget).
 */
import { mount } from './core/mount';

export interface WidgetOptions {
  /** Public widget identifier generated in the dashboard. */
  widgetId: string;
  /** Backend base URL for the public widget API (see WIDGET_API_BASE_URL). */
  apiBaseUrl?: string;
}

export function init(options: WidgetOptions): void {
  mount(options);
}

export default { init };
