/**
 * Shared theme data model for the WebChat widget.
 *
 * Both the widget SDK (runtime styles) and the dashboard (preview + editor)
 * consume this package so a configured theme renders identically everywhere.
 *
 * A theme is either a preset (curated palette for light/dark mode) or the
 * classic fully-custom setup. `resolveTheme` merges the two: preset colors are
 * used unless the tenant explicitly overrode `primary_color` / `accent_color`
 * (a value equal to the platform default counts as "not overridden", so
 * selecting a preset actually changes the palette), while the direct overrides
 * (`header_color`, `background_color`, `text_color`) always win.
 */

export const DEFAULT_PRIMARY_COLOR = '#10A37F';

export const DEFAULT_ACCENT_COLOR = '#25D366';

export interface ThemeTokens {
  primary: string;
  accent: string;
  header: string;
  headerText: string;
  surface: string;
  surfaceElevated: string;
  text: string;
  muted: string;
  border: string;
  assistantBubble: string;
  userBubble: string;
  userText: string;
  inputBg: string;
  scrollbarThumb: string;
  scrollbarTrack: string;
  /**
   * Optional per-theme semantic overrides. When present they win; otherwise the
   * centralized resolver derives them from the canonical tokens via documented
   * fallbacks, so every theme still renders a fully-specified palette without
   * the renderers knowing which theme is active. A new theme may set these to
   * give, e.g., the Send/Officialify button a genuinely distinct look purely
   * through data — no renderer change required.
   */
  sendButton?: string;
  launcher?: string;
  onlineIndicator?: string;
  suggestionBg?: string;
  focusRing?: string;
}

export interface ThemePreset {
  /** snake_case id, mirrored by the backend `WIDGET_THEME_PRESETS` tuple */
  id: string;
  name: string;
  description: string;
  /** render the header as a primary→secondary gradient instead of a flat color */
  headerGradient: boolean;
  light: ThemeTokens;
  dark: ThemeTokens;
}

/** Subset of the widget config the theme engine understands. */
export interface ThemeConfig {
  theme_preset?: string | null;
  primary_color?: string | null;
  accent_color?: string | null;
  secondary_color?: string | null;
  header_color?: string | null;
  background_color?: string | null;
  text_color?: string | null;
}

/** Fully-resolved set of colors + gradients ready to apply as CSS custom props. */
export interface ResolvedTheme extends ThemeTokens {
  secondary: string;
  userBubble: string;
  // Conceptual aliases so renderers can consume intent-named tokens rather
  // than inventing their own color logic. All are derived centrally here.
  primaryForeground: string;
  messageUserForeground: string;
  messageAssistantForeground: string;
  headerForeground: string;
  /** Send-button background (explicit theme token → primary→secondary gradient). */
  sendButtonBackground: string;
  /** Send-button foreground (readable on `sendButtonBackground`/primary). */
  sendButtonForeground: string;
  /** Launcher-button background (explicit theme token → primary→accent gradient). */
  launcherBackground: string;
  /** Launcher-button foreground (readable on primary). */
  launcherForeground: string;
  /** Close-button background (transparent — sits on the header). */
  closeButtonBackground: string;
  /** Close-button foreground (header foreground). */
  closeButtonForeground: string;
  suggestionBackground: string;
  suggestionForeground: string;
  suggestionBorder: string;
  inputBackground: string;
  inputBorder: string;
  focusRing: string;
  onlineIndicator: string;
}

function preset(
  id: string,
  name: string,
  description: string,
  light: ThemeTokens,
  dark: ThemeTokens,
  headerGradient = false,
): ThemePreset {
  return { id, name, description, headerGradient, light, dark };
}

export const THEME_PRESETS: readonly ThemePreset[] = [
  // --- NEW ADDITIONS ---
  preset(
    'whatsapp-classic',
    'WhatsApp Classic',
    'Familiar messaging aesthetic with teal headers and green bubbles',
    {
      primary: '#199347',
      accent: '#128C7E',
      header: '#075E54',
      headerText: '#ffffff',
      surface: '#efeae2',
      surfaceElevated: '#ffffff',
      text: '#111b21',
      muted: '#667781',
      border: '#d1d7db',
      assistantBubble: '#ffffff',
      userBubble: '#d9fdd3',
      userText: '#111b21',
      inputBg: '#ffffff',
      scrollbarThumb: 'rgba(11, 20, 26, 0.2)',
      scrollbarTrack: '#efeae2',
    },
    {
      primary: '#00a884',
      accent: '#00a884',
      header: '#1f2c34',
      headerText: '#e9edef',
      surface: '#0b141a',
      surfaceElevated: '#111b21',
      text: '#e9edef',
      muted: '#8696a0',
      border: '#222e35',
      assistantBubble: '#202c33',
      userBubble: '#005c4b',
      userText: '#e9edef',
      inputBg: '#202c33',
      scrollbarThumb: 'rgba(233, 237, 239, 0.2)',
      scrollbarTrack: '#0b141a',
    },
  ),
  preset(
    'ios-native',
    'iOS Native',
    'Clean, native iOS messaging feel with crisp blue bubbles',
    {
      primary: '#007AFF',
      accent: '#0051FF',
      header: '#f9f9f9',
      headerText: '#000000',
      surface: '#ffffff',
      surfaceElevated: '#f9f9f9',
      text: '#000000',
      muted: '#8e8e93',
      border: '#e5e5ea',
      assistantBubble: '#e5e5ea',
      userBubble: '#006de5',
      userText: '#ffffff',
      inputBg: '#ffffff',
      scrollbarThumb: 'rgba(0, 0, 0, 0.2)',
      scrollbarTrack: '#ffffff',
    },
    {
      primary: '#0A84FF',
      accent: '#0A84FF',
      header: '#1c1c1e',
      headerText: '#ffffff',
      surface: '#000000',
      surfaceElevated: '#1c1c1e',
      text: '#ffffff',
      muted: '#98989d',
      border: '#38383a',
      assistantBubble: '#262628',
      userBubble: '#0870d8',
      userText: '#ffffff',
      inputBg: '#1c1c1e',
      scrollbarThumb: 'rgba(255, 255, 255, 0.2)',
      scrollbarTrack: '#000000',
    },
  ),
  preset(
    'enterprise-slate',
    'Enterprise Slate',
    'Professional, high-contrast theme optimized for long reading sessions',
    {
      primary: '#5865F2',
      accent: '#4752C4',
      header: '#2B2D31',
      headerText: '#ffffff',
      surface: '#F2F3F5',
      surfaceElevated: '#ffffff',
      text: '#313338',
      muted: '#5C5E66',
      border: '#E3E5E8',
      assistantBubble: '#ffffff',
      userBubble: '#5865F2',
      userText: '#ffffff',
      inputBg: '#ffffff',
      scrollbarThumb: 'rgba(49, 51, 56, 0.2)',
      scrollbarTrack: '#F2F3F5',
    },
    {
      primary: '#6874f3',
      accent: '#4752C4',
      header: '#1E1F22',
      headerText: '#F2F3F5',
      surface: '#313338',
      surfaceElevated: '#2B2D31',
      text: '#DBDEE1',
      muted: '#949BA4',
      border: '#1E1F22',
      assistantBubble: '#2B2D31',
      userBubble: '#5865F2',
      userText: '#ffffff',
      inputBg: '#383A40',
      scrollbarThumb: 'rgba(30, 31, 34, 0.6)',
      scrollbarTrack: '#2B2D31',
    },
  ),
  // --- ORIGINAL THEMES ---
  preset(
    'ocean-blue',
    'Ocean Blue',
    'Trusted SaaS blue with crisp white surfaces',
    {
      primary: '#0284c7',
      accent: '#0369a1',
      header: '#0c4a6e',
      headerText: '#ffffff',
      surface: '#ffffff',
      surfaceElevated: '#f0f9ff',
      text: '#0c4a6e',
      muted: '#64748b',
      border: '#bae6fd',
      assistantBubble: '#e0f2fe',
      userBubble: '#0369a1',
      userText: '#ffffff',
      inputBg: '#ffffff',
      scrollbarThumb: 'rgba(2, 132, 199, 0.35)',
      scrollbarTrack: '#e0f2fe',
    },
    {
      primary: '#0284c7',
      accent: '#0369a1',
      header: '#082f49',
      headerText: '#ffffff',
      surface: '#082f49',
      surfaceElevated: '#0c4a6e',
      text: '#e0f2fe',
      muted: '#94a3b8',
      border: '#164e63',
      assistantBubble: '#0a3450',
      userBubble: '#0369a1',
      userText: '#ffffff',
      inputBg: '#0c4a6e',
      scrollbarThumb: 'rgba(2, 132, 199, 0.35)',
      scrollbarTrack: '#082f49',
    },
  ),
  preset(
    'midnight-dark',
    'Midnight Dark',
    'Bold dark-first theme for a modern product vibe',
    {
      primary: '#6366f1',
      accent: '#4f46e5',
      header: '#0b0f1a',
      headerText: '#ffffff',
      surface: '#0b0f1a',
      surfaceElevated: '#151b30',
      text: '#e2e8f0',
      muted: '#94a3b8',
      border: '#1e293b',
      assistantBubble: '#151b30',
      userBubble: '#3730a3',
      userText: '#ffffff',
      inputBg: '#151b30',
      scrollbarThumb: 'rgba(148, 163, 184, 0.3)',
      scrollbarTrack: '#0b0f1a',
    },
    {
      primary: '#7e86f6',
      accent: '#6366f1',
      header: '#020617',
      headerText: '#ffffff',
      surface: '#020617',
      surfaceElevated: '#0f172a',
      text: '#f1f5f9',
      muted: '#94a3b8',
      border: '#1e293b',
      assistantBubble: '#0f172a',
      userBubble: '#3730a3',
      userText: '#ffffff',
      inputBg: '#0f172a',
      scrollbarThumb: 'rgba(165, 180, 252, 0.3)',
      scrollbarTrack: '#020617',
    },
  ),
  preset(
    'emerald-support',
    'Emerald Support',
    'Friendly green for support and success teams',
    {
      primary: '#059669',
      accent: '#059669',
      header: '#064e3b',
      headerText: '#ffffff',
      surface: '#ffffff',
      surfaceElevated: '#ecfdf5',
      text: '#0f172a',
      muted: '#64748b',
      border: '#d9f2e7',
      assistantBubble: '#f0fdf9',
      userBubble: '#047857',
      userText: '#ffffff',
      inputBg: '#ffffff',
      scrollbarThumb: 'rgba(16, 185, 129, 0.4)',
      scrollbarTrack: '#e8f7f1',
    },
    {
      primary: '#059669',
      accent: '#059669',
      header: '#022c22',
      headerText: '#ffffff',
      surface: '#06231c',
      surfaceElevated: '#0a3328',
      text: '#ecfdf5',
      muted: '#94a3b8',
      border: '#14532d',
      assistantBubble: '#0a3328',
      userBubble: '#047857',
      userText: '#ffffff',
      inputBg: '#0a3328',
      scrollbarThumb: 'rgba(52, 211, 153, 0.35)',
      scrollbarTrack: '#06231c',
    },
  ),
  preset(
    'purple-ai',
    'Purple AI',
    'Violet accents for AI assistants and innovation',
    {
      primary: '#7c3aed',
      accent: '#a855f7',
      header: '#4c1d95',
      headerText: '#ffffff',
      surface: '#ffffff',
      surfaceElevated: '#f6f2ff',
      text: '#1e1b4b',
      muted: '#6b7280',
      border: '#e5dbfc',
      assistantBubble: '#f5f0ff',
      userBubble: '#7c3aed',
      userText: '#ffffff',
      inputBg: '#ffffff',
      scrollbarThumb: 'rgba(139, 92, 246, 0.4)',
      scrollbarTrack: '#f1ebff',
    },
    {
      primary: '#8b5cf6',
      accent: '#7c3aed',
      header: '#2e1065',
      headerText: '#ffffff',
      surface: '#140b2e',
      surfaceElevated: '#1f1445',
      text: '#f5f3ff',
      muted: '#9aa0b5',
      border: '#312e81',
      assistantBubble: '#1f1445',
      userBubble: '#7c3aed',
      userText: '#ffffff',
      inputBg: '#1f1445',
      scrollbarThumb: 'rgba(167, 139, 250, 0.35)',
      scrollbarTrack: '#140b2e',
    },
  ),
  preset(
    'minimal-white',
    'Minimal White',
    'Clean monochrome that fits any brand',
    {
      primary: '#18181b',
      accent: '#3f3f46',
      header: '#ffffff',
      headerText: '#18181b',
      surface: '#ffffff',
      surfaceElevated: '#fafafa',
      text: '#18181b',
      muted: '#71717a',
      border: '#e4e4e7',
      assistantBubble: '#f4f4f5',
      userBubble: '#18181b',
      userText: '#ffffff',
      inputBg: '#ffffff',
      scrollbarThumb: 'rgba(161, 161, 170, 0.4)',
      scrollbarTrack: '#f4f4f5',
    },
    {
      primary: '#fafafa',
      accent: '#d4d4d8',
      header: '#18181b',
      headerText: '#fafafa',
      surface: '#09090b',
      surfaceElevated: '#18181b',
      text: '#f4f4f5',
      muted: '#a1a1aa',
      border: '#27272a',
      assistantBubble: '#18181b',
      userBubble: '#fafafa',
      userText: '#0a0a0a',
      inputBg: '#18181b',
      scrollbarThumb: 'rgba(161, 161, 170, 0.35)',
      scrollbarTrack: '#09090b',
    },
  ),
  preset(
    'sunset',
    'Sunset',
    'Warm orange and red for friendly, approachable brands',
    {
      primary: '#ea580c',
      accent: '#dc2626',
      header: '#7c2d12',
      headerText: '#ffffff',
      surface: '#ffffff',
      surfaceElevated: '#fff7ed',
      text: '#1c1917',
      muted: '#78716c',
      border: '#fed7aa',
      assistantBubble: '#fef3c7',
      userBubble: '#c2410c',
      userText: '#ffffff',
      inputBg: '#ffffff',
      scrollbarThumb: 'rgba(234, 88, 12, 0.35)',
      scrollbarTrack: '#fef3c7',
    },
    {
      primary: '#fb923c',
      accent: '#f43f5e',
      header: '#1c0a00',
      headerText: '#ffffff',
      surface: '#1c0a00',
      surfaceElevated: '#2a1508',
      text: '#fef3c7',
      muted: '#a8a29e',
      border: '#431407',
      assistantBubble: '#2a1508',
      userBubble: '#c2410c',
      userText: '#ffffff',
      inputBg: '#2a1508',
      scrollbarThumb: 'rgba(251, 146, 60, 0.35)',
      scrollbarTrack: '#1c0a00',
    },
  ),
  preset(
    'modern-gradient',
    'Modern Gradient',
    'Vivid primary→accent gradient header',
    {
      primary: '#7c3aed',
      accent: '#ec4899',
      header: '#7c3aed',
      headerText: '#ffffff',
      surface: '#ffffff',
      surfaceElevated: '#faf5ff',
      text: '#1e1b4b',
      muted: '#6b7280',
      border: '#eadff7',
      assistantBubble: '#f6f0fd',
      userBubble: '#7c3aed',
      userText: '#ffffff',
      inputBg: '#ffffff',
      scrollbarThumb: 'rgba(124, 58, 237, 0.4)',
      scrollbarTrack: '#f3eafd',
    },
    {
      primary: '#9333ea',
      accent: '#ec4899',
      header: '#9333ea',
      headerText: '#ffffff',
      surface: '#150a28',
      surfaceElevated: '#221040',
      text: '#faf5ff',
      muted: '#9ca3af',
      border: '#3b2a63',
      assistantBubble: '#221040',
      userBubble: '#9333ea',
      userText: '#ffffff',
      inputBg: '#221040',
      scrollbarThumb: 'rgba(232, 121, 249, 0.35)',
      scrollbarTrack: '#150a28',
    },
    true,
  ),
];

export const THEME_PRESET_IDS: readonly string[] = THEME_PRESETS.map((t) => t.id);

export function getThemePreset(id: string): ThemePreset | undefined {
  return THEME_PRESETS.find((t) => t.id === id);
}

/** Classic (no preset) tokens. */
export function defaultTokens(dark: boolean): ResolvedTheme {
  const primary = DEFAULT_PRIMARY_COLOR;
  const accent = DEFAULT_ACCENT_COLOR;
  const secondary = accent;
  const header = `linear-gradient(135deg, ${primary}, ${accent})`;
  const headerText = '#ffffff';
  return {
    primary,
    accent,
    secondary,
    header,
    headerText,
    surface: dark ? '#0f172a' : '#ffffff',
    surfaceElevated: dark ? '#1e293b' : '#f8fafc',
    text: dark ? '#f1f5f9' : '#0f172a',
    muted: dark ? '#94a3b8' : '#64748b',
    border: dark ? '#334155' : '#e2e8f0',
    assistantBubble: dark ? '#1e293b' : '#f1f5f9',
    userBubble: primary,
    userText: '#ffffff',
    inputBg: dark ? '#1e293b' : '#ffffff',
    scrollbarThumb: dark ? 'rgba(148, 163, 184, 0.35)' : 'rgba(100, 116, 139, 0.35)',
    scrollbarTrack: dark ? '#0f172a' : '#eef2f7',
    primaryForeground: readableText(primary),
    messageUserForeground: '#ffffff',
    messageAssistantForeground: dark ? '#f1f5f9' : '#0f172a',
    headerForeground: headerText,
    sendButtonBackground: `linear-gradient(135deg, ${primary}, ${secondary})`,
    sendButtonForeground: readableText(primary),
    launcherBackground: `linear-gradient(135deg, ${primary}, ${accent})`,
    launcherForeground: readableText(primary),
    closeButtonBackground: 'transparent',
    closeButtonForeground: headerText,
    suggestionBackground: dark ? '#1e293b' : '#f8fafc',
    suggestionForeground: dark ? '#f1f5f9' : '#0f172a',
    suggestionBorder: dark ? '#334155' : '#e2e8f0',
    inputBackground: dark ? '#1e293b' : '#ffffff',
    inputBorder: dark ? '#334155' : '#e2e8f0',
    focusRing: accent,
    onlineIndicator: '#4ade80',
  };
}

function parseHex(hex: string): [number, number, number] {
  let value = hex.replace('#', '').trim();
  if (value.length === 3) {
    value = value
      .split('')
      .map((c) => c + c)
      .join('');
  }
  const num = Number.parseInt(value, 16);
  if (value.length !== 6 || Number.isNaN(num)) {
    return [255, 255, 255];
  }
  return [(num >> 16) & 255, (num >> 8) & 255, num & 255];
}

/** WCAG-style relative luminance for a hex color (0 = black, 1 = white). */
export function relativeLuminance(hex: string): number {
  const [r, g, b] = parseHex(hex).map((channel) => {
    const s = channel / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** Readable on-color text (`#ffffff` or `#18181b`) for a given background hex. */
export function readableText(hex: string): string {
  return relativeLuminance(hex) > 0.4 ? '#18181b' : '#ffffff';
}

function isDefaultColor(color: string | null | undefined, fallback: string): boolean {
  return !color || color.trim().toLowerCase() === fallback.toLowerCase();
}

export function resolveTheme(config: ThemeConfig, dark: boolean): ResolvedTheme {
  const preset = config.theme_preset ? getThemePreset(config.theme_preset) : undefined;
  const base = preset ? (dark ? preset.dark : preset.light) : defaultTokens(dark);

  const primary = preset
    ? isDefaultColor(config.primary_color, DEFAULT_PRIMARY_COLOR)
      ? base.primary
      : (config.primary_color as string)
    : config.primary_color || base.primary;
  const accent = preset
    ? isDefaultColor(config.accent_color, DEFAULT_ACCENT_COLOR)
      ? base.accent
      : (config.accent_color as string)
    : config.accent_color || base.accent;
  const secondary = config.secondary_color ?? accent;

  let header: string;
  let headerText: string;
  if (config.header_color) {
    header = config.header_color;
    headerText = readableText(config.header_color);
  } else if (preset) {
    header = preset.headerGradient
      ? `linear-gradient(135deg, ${primary}, ${secondary})`
      : base.header;
    headerText = base.headerText;
  } else {
    header = `linear-gradient(135deg, ${primary}, ${secondary})`;
    headerText = '#ffffff';
  }

  const baseBg = config.background_color ?? base.surface;
  const baseText = config.text_color ?? base.text;
  const inputBg = base.inputBg;
  const border = base.border;
  const primaryForeground = readableText(primary);

  const resolved: ResolvedTheme = {
    primary,
    accent,
    secondary,
    header,
    headerText,
    surface: baseBg,
    surfaceElevated: config.background_color ?? base.surfaceElevated,
    text: baseText,
    muted: base.muted,
    border,
    assistantBubble: base.assistantBubble,
    userBubble: preset ? base.userBubble : primary,
    userText: base.userText,
    inputBg,
    scrollbarThumb: base.scrollbarThumb,
    scrollbarTrack: base.scrollbarTrack,
    // Conceptual aliases / derived semantic tokens (centralized here so the
    // dashboard preview, the widget SDK and tests all read ONE resolved value).
    primaryForeground,
    messageUserForeground: base.userText,
    messageAssistantForeground: baseText,
    headerForeground: headerText,
    // Send button: explicit preset token → primary→secondary gradient.
    sendButtonBackground:
      (preset && base.sendButton) || `linear-gradient(135deg, ${primary}, ${secondary})`,
    sendButtonForeground:
      preset && base.sendButton ? readableText(base.sendButton) : primaryForeground,
    // Launcher: explicit preset token → primary→accent gradient.
    launcherBackground:
      (preset && base.launcher) || `linear-gradient(135deg, ${primary}, ${accent})`,
    launcherForeground: primaryForeground,
    // Close button: transparent on the header, foreground follows header text.
    closeButtonBackground: 'transparent',
    closeButtonForeground: headerText,
    suggestionBackground: base.surfaceElevated,
    suggestionForeground: baseText,
    suggestionBorder: border,
    inputBackground: inputBg,
    inputBorder: border,
    focusRing: (preset && base.focusRing) || accent,
    onlineIndicator: (preset && base.onlineIndicator) || '#4ade80',
  };
  return resolved;
}
