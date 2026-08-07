import type { WidgetOptions } from '../index';

export interface WidgetContext {
  widgetId: string;
  apiBaseUrl: string;
}

/**
 * Mounts the widget into the document.
 * Phase 1: skeleton only - chat UI, streaming and theming land in Phase 7.
 */
export function mount(options: WidgetOptions): WidgetContext {
  const context: WidgetContext = {
    widgetId: options.widgetId,
    apiBaseUrl: options.apiBaseUrl ?? '/api/widget/v1',
  };

  console.info(`[WebChatAI] widget mounted for widget_id=${context.widgetId}`);

  return context;
}
