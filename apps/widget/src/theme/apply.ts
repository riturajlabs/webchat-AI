/**
 * Theme engine (plan §5.1, ADR-004, Phase 12).
 *
 * All colors/spacing/typography are CSS custom properties defined on the host
 * element (`--wc-primary`, `--wc-accent`, `--wc-font-size`, …). Shadow DOM
 * inherits custom properties from the host, so the config-driven theme sets
 * them on the host and the encapsulated UI consumes them.
 *
 * Phase 12: the resolved palette now comes from the shared `@webchat/themes`
 * package (`resolveTheme`), which fuses curated presets with the tenant's
 * explicit overrides — the same engine the dashboard preview uses, so the
 * editor preview and the real widget always match. The author-facing aliases
 * (`--wc-header-color`, `--wc-background`, `--wc-text-color`) are still set
 * only when explicitly configured so callers/embeds can read them.
 */

import { readableText, resolveTheme } from '@webchat/themes';
import type { WidgetPublicConfig } from '../config/types';

const PREFIX = '--wc';

const FONT_SIZES: Record<string, string> = {
  sm: '14px',
  md: '16px',
  lg: '18px',
};

/** Apply config values as CSS custom properties on the host element. */
export function applyTheme(host: HTMLElement, config: WidgetPublicConfig): void {
  const dark = effectiveDarkMode(config);
  const theme = resolveTheme(config, dark);

  // Resolved palette (always set; dark-aware via `resolveTheme`).
  setProp(host, `${PREFIX}-primary`, theme.primary);
  setProp(host, `${PREFIX}-accent`, theme.accent);
  setProp(host, `${PREFIX}-secondary`, theme.secondary);
  setProp(host, `${PREFIX}-surface`, theme.surface);
  setProp(host, `${PREFIX}-surface-elevated`, theme.surfaceElevated);
  setProp(host, `${PREFIX}-text`, theme.text);
  setProp(host, `${PREFIX}-muted`, theme.muted);
  setProp(host, `${PREFIX}-border`, theme.border);
  setProp(host, `${PREFIX}-bubble-bg`, theme.assistantBubble);
  setProp(host, `${PREFIX}-user-bubble`, theme.userBubble);
  setProp(host, `${PREFIX}-user-text`, theme.userText);
  setProp(host, `${PREFIX}-input-bg`, theme.inputBg);
  setProp(host, `${PREFIX}-header-bg`, theme.header);
  setProp(host, `${PREFIX}-header-text`, theme.headerText);
  // Foreground for the launcher/send controls, which sit on a primary→secondary
  // gradient. Computed so near-white primaries (e.g. minimal-white dark) stay
  // readable instead of forcing white-on-white.
  setProp(host, `${PREFIX}-on-primary`, readableText(theme.primary));
  setProp(host, `${PREFIX}-scrollbar-thumb`, theme.scrollbarThumb);
  setProp(host, `${PREFIX}-scrollbar-track`, theme.scrollbarTrack);

  // Structural/sizing/config passthrough.
  setProp(host, `${PREFIX}-font-size`, config.font_size);
  setProp(host, `${PREFIX}-font-size-px`, FONT_SIZES[config.font_size] ?? FONT_SIZES.md);
  setProp(host, `${PREFIX}-font-family`, config.font_family);
  setProp(host, `${PREFIX}-width`, config.width);
  setProp(host, `${PREFIX}-height`, config.height);
  setProp(host, `${PREFIX}-radius`, config.border_radius);
  setProp(host, `${PREFIX}-launcher-size`, config.launcher_size);
  setProp(host, `${PREFIX}-position`, config.position);
  setProp(host, `${PREFIX}-logo-url`, config.logo_url);
  setProp(host, `${PREFIX}-avatar-url`, config.avatar_url);
  setProp(host, `${PREFIX}-branding`, config.branding);
  setProp(host, `${PREFIX}-dark-mode`, config.dark_mode);
  setProp(host, `${PREFIX}-welcome-message`, config.welcome_message);
  setProp(host, `${PREFIX}-placeholder`, config.placeholder);

  // Author-facing aliases: only present when explicitly overridden, so embeds
  // that read them can distinguish "explicit" from "theme default".
  if (config.header_color) {
    setProp(host, `${PREFIX}-header-color`, config.header_color);
  } else {
    host.style.removeProperty(`${PREFIX}-header-color`);
  }
  if (config.background_color) {
    setProp(host, `${PREFIX}-background`, config.background_color);
  } else {
    host.style.removeProperty(`${PREFIX}-background`);
  }
  if (config.text_color) {
    setProp(host, `${PREFIX}-text-color`, config.text_color);
  } else {
    host.style.removeProperty(`${PREFIX}-text-color`);
  }

  host.style.setProperty(`${PREFIX}-dark`, dark ? '1' : '0');
  // `data-dark` drives the shadow stylesheet's remaining dark overrides
  // (banner/stop colors, shadow) that are not part of the resolved palette.
  if (dark) {
    host.dataset.dark = '1';
  } else {
    delete host.dataset.dark;
  }
}

function setProp(host: HTMLElement, property: string, value: unknown): void {
  if (value === null || value === undefined || value === '') {
    host.style.removeProperty(property);
  } else {
    host.style.setProperty(property, String(value));
  }
}

/** Map a `light|dark|auto` theme + dark_mode flag to an effective mode. */
export function effectiveDarkMode(config: WidgetPublicConfig): boolean {
  if (config.theme === 'dark') {
    return true;
  }
  if (config.theme === 'auto') {
    return (
      typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches
    );
  }
  return config.dark_mode;
}

/** Honor `prefers-reduced-motion` (WCAG 2.3.3): disables motion-only UI. */
export function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

/**
 * Re-resolve the theme when the OS light/dark preference changes (audit W-03):
 * `theme: 'auto'` used to be evaluated exactly once at mount, so flipping the
 * system theme had no effect until a page reload. Manual `light`/`dark`
 * overrides are unaffected — `effectiveDarkMode` ignores the system setting
 * for them, so the extra re-apply is a no-op there.
 *
 * Returns a disposer for `destroy()`. Tolerates matchMedia mocks without
 * listener support (test environments).
 */
export function wireSystemThemeChange(
  host: HTMLElement,
  getConfig: () => WidgetPublicConfig,
): () => void {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return () => {};
  }
  const query = window.matchMedia('(prefers-color-scheme: dark)');
  const onChange = (): void => applyTheme(host, getConfig());
  query.addEventListener?.('change', onChange);
  return () => query.removeEventListener?.('change', onChange);
}
