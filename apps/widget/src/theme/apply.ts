/**
 * Theme engine (plan §5.1, ADR-004).
 *
 * All colors/spacing/typography are CSS custom properties defined on the host
 * element (`--wc-primary`, `--wc-accent`, `--wc-font-size`, …). Shadow DOM
 * inherits custom properties from the host, so the config-driven theme sets
 * them on the host and the encapsulated UI consumes them.
 */

import type { WidgetPublicConfig } from '../config/types';

const PREFIX = '--wc';

const HOST_PROPERTIES: Record<string, string> = {
  [`${PREFIX}-primary`]: 'primary_color',
  [`${PREFIX}-accent`]: 'accent_color',
  [`${PREFIX}-font-size`]: 'font_size',
  [`${PREFIX}-position`]: 'position',
  [`${PREFIX}-logo-url`]: 'logo_url',
  [`${PREFIX}-avatar-url`]: 'avatar_url',
  [`${PREFIX}-branding`]: 'branding',
  [`${PREFIX}-dark-mode`]: 'dark_mode',
  [`${PREFIX}-welcome-message`]: 'welcome_message',
  [`${PREFIX}-placeholder`]: 'placeholder',
};

const FONT_SIZES: Record<string, string> = {
  sm: '14px',
  md: '16px',
  lg: '18px',
};

/** Apply config values as CSS custom properties on the host element. */
export function applyTheme(host: HTMLElement, config: WidgetPublicConfig): void {
  for (const [property, field] of Object.entries(HOST_PROPERTIES)) {
    const value = String((config as unknown as Record<string, unknown>)[field]);
    host.style.setProperty(property, value ?? '');
  }
  host.style.setProperty(`${PREFIX}-font-size-px`, FONT_SIZES[config.font_size] ?? FONT_SIZES.md);
  const dark = effectiveDarkMode(config);
  host.style.setProperty(`${PREFIX}-dark`, dark ? '1' : '0');
  // `data-dark` drives the shadow stylesheet's dark token overrides.
  if (dark) {
    host.dataset.dark = '1';
  } else {
    delete host.dataset.dark;
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
