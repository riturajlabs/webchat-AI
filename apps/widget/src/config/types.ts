/**
 * Public types for the WebChat widget SDK.
 *
 * Field names mirror the v1 widget API contract exactly (snake_case), see
 * `backend/schemas/widget.py`. The SDK pins v1 and parses forward-compatibly:
 * unknown response fields are ignored.
 */

export interface WidgetPublicConfig {
  widget_id: string;
  enabled: boolean;
  theme: string;
  position: string;
  primary_color: string;
  accent_color: string;
  font_size: string;
  logo_url: string | null;
  avatar_url: string | null;
  welcome_message: string;
  placeholder: string;
  suggested_questions: string[];
  branding: boolean;
  dark_mode: boolean;
  auto_open: boolean;
}

export interface WidgetOptions {
  /** Public widget identifier generated in the dashboard. */
  widgetId: string;
  /** Backend base URL for the public widget API (see WIDGET_API_BASE_URL). */
  apiBaseUrl?: string;
}

/** Values the widget itself may override at embed time. */
export interface WidgetOverride {
  position?: 'bottom-right' | 'bottom-left';
  primaryColor?: string;
  accentColor?: string;
}

/** Safe fallback config used when the public config cannot be fetched. */
export const DEFAULT_CONFIG: Omit<WidgetPublicConfig, 'widget_id'> = {
  enabled: true,
  theme: 'light',
  position: 'bottom-right',
  primary_color: '#2563eb',
  accent_color: '#f59e0b',
  font_size: 'md',
  logo_url: null,
  avatar_url: null,
  welcome_message: 'Hi! How can I help you?',
  placeholder: 'Type your message…',
  suggested_questions: [],
  branding: true,
  dark_mode: false,
  auto_open: false,
};

export const DEFAULT_API_BASE_URL = '/api/widget/v1';

export function defaultConfig(widgetId: string): WidgetPublicConfig {
  return { widget_id: widgetId, ...DEFAULT_CONFIG };
}

export function sanitizeApiBaseUrl(value: string): string {
  return value.replace(/\/+$/, '');
}
