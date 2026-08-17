/**
 * Widget customization domain types (Phase 11.5), mirroring the backend
 * `WidgetOut` / `WidgetConfigUpdate` contract (backend/schemas/websites.py +
 * backend/schemas/widget.py).
 */

export type WidgetTheme = 'light' | 'dark' | 'auto';

export type WidgetPosition = 'bottom-right' | 'bottom-left';

/** Theme preset id (`@webchat/themes`); empty string = classic custom colors. */
export type WidgetThemePreset =
  | ''
  | 'ocean-blue'
  | 'midnight-dark'
  | 'emerald-support'
  | 'purple-ai'
  | 'minimal-white'
  | 'sunset'
  | 'modern-gradient';

export type WidgetFontSize = 'sm' | 'md' | 'lg';

/** The prefix of `Widget` that the dashboard builder can edit. */
export type WidgetConfigChanges = Pick<
  WidgetConfig,
  | 'theme'
  | 'theme_preset'
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
  | 'bot_name'
  | 'bot_status_text'
  | 'header_color'
  | 'secondary_color'
  | 'background_color'
  | 'text_color'
  | 'font_family'
  | 'width'
  | 'height'
  | 'border_radius'
  | 'launcher_size'
>;

export interface WidgetConfig {
  widget_id: string;
  website_id: string;
  theme: WidgetTheme;
  /** Curated palette id (`@webchat/themes`); '' → classic custom colors. */
  theme_preset: WidgetThemePreset;
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
  /** Bot name shown in the widget header. */
  bot_name: string;
  /** Presence line under the bot name (e.g. "Online", "Away"). */
  bot_status_text: string;
  /** Header background; null → primary/secondary gradient. */
  header_color: string | null;
  /** Gradient partner for primary; null → accent. */
  secondary_color: string | null;
  /** Window surface color; null → theme default. */
  background_color: string | null;
  /** Primary text color; null → theme default. */
  text_color: string | null;
  /** UI font family; null → system stack. */
  font_family: string | null;
  /** Window width as a CSS length (px/em/rem/vh/vw/%). */
  width: string;
  /** Window height as a CSS length (px/em/rem/vh/vw/%). */
  height: string;
  /** Window/launcher corner radius (px/em/rem/%). */
  border_radius: string;
  /** Launcher button size (px/em/rem/%). */
  launcher_size: string;
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
