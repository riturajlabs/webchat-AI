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
  /**
   * Backend origin for the public widget API, e.g. `https://api.example.com`
   * (the SDK appends `/api/widget/v1`). A fully versioned base such as
   * `https://api.example.com/api/widget/v1` is also accepted. When omitted,
   * the build-time `VITE_WIDGET_API_BASE_URL` env is used, falling back to a
   * same-origin `/api/widget/v1`.
   */
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

/** Versioned public widget API prefix (ADR-004). */
export const WIDGET_API_VERSION = '/api/widget/v1';

/** Same-origin fallback used when no API base is configured (local dev). */
export const DEFAULT_API_BASE_URL = WIDGET_API_VERSION;

/**
 * Build-time configured widget API base (`VITE_WIDGET_API_BASE_URL`), e.g.
 * `https://api.webchat-ai.example` or a fully versioned path. The SaaS host
 * bakes this into the served bundle so customers only provide `data-widget-id`.
 * Unset → same-origin `/api/widget/v1` (never a hardcoded localhost).
 */
export function defaultApiBaseUrl(): string {
  const configured = import.meta.env?.VITE_WIDGET_API_BASE_URL;
  return configured ? sanitizeApiBaseUrl(configured) : DEFAULT_API_BASE_URL;
}

/**
 * Resolve the full versioned widget API base used for every request.
 *
 * Accepts either a host origin (`https://api.example.com`) or an already
 * versioned path (`https://api.example.com/api/widget/v1`) and always returns
 * a base ending in `/api/widget/v1`. The default comes from the build-time env
 * config, so an embed that only carries `data-widget-id` still reaches the API.
 */
export function resolveApiBaseUrl(apiBaseUrl?: string): string {
  const base = sanitizeApiBaseUrl(apiBaseUrl ?? defaultApiBaseUrl());
  return base.endsWith(WIDGET_API_VERSION) ? base : `${base}${WIDGET_API_VERSION}`;
}

export function defaultConfig(widgetId: string): WidgetPublicConfig {
  return { widget_id: widgetId, ...DEFAULT_CONFIG };
}

export function sanitizeApiBaseUrl(value: string): string {
  return value.replace(/\/+$/, '');
}
