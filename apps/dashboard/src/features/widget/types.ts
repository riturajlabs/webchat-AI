/**
 * Widget customization domain types (Phase 11.5), mirroring the backend
 * `WidgetOut` / `WidgetConfigUpdate` contract (backend/schemas/websites.py +
 * backend/schemas/widget.py).
 */

export type WidgetTheme = 'light' | 'dark' | 'auto';

export type WidgetPosition = 'bottom-right' | 'bottom-left';

export type WidgetFontSize = 'sm' | 'md' | 'lg';

/** The prefix of `Widget` that the dashboard builder can edit. */
export type WidgetConfigChanges = Pick<
  WidgetConfig,
  | 'theme'
  | 'position'
  | 'primary_color'
  | 'accent_color'
  | 'font_size'
  | 'logo_url'
  | 'avatar_url'
  | 'welcome_message'
  | 'placeholder'
  | 'suggested_questions'
  | 'branding'
  | 'dark_mode'
  | 'auto_open'
  | 'enabled'
  | 'allowed_domains'
>;

export interface WidgetConfig {
  widget_id: string;
  website_id: string;
  theme: WidgetTheme;
  position: WidgetPosition;
  primary_color: string;
  accent_color: string;
  font_size: WidgetFontSize;
  logo_url: string | null;
  avatar_url: string | null;
  welcome_message: string;
  placeholder: string;
  suggested_questions: string[];
  branding: boolean;
  dark_mode: boolean;
  auto_open: boolean;
  enabled: boolean;
  /**
   * Embed-origin allowlist (normalized bare hostnames / `*.`-wildcards). An
   * empty list blocks browser embeds (WIDGET_DOMAIN_NOT_CONFIGURED) until
   * domains are configured; use the literal `*` for open embedding.
   */
  allowed_domains: string[];
  created_at: string;
  updated_at: string;
}

export interface WidgetResponse {
  widget: WidgetConfig;
  /** The copy-paste embed snippet for the current config (never changes with config). */
  embed_script: string;
}

export interface UpdateWidgetConfigInput {
  websiteId: string;
  changes: Partial<WidgetConfigChanges>;
}
