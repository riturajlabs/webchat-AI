import { describe, expect, it, vi } from 'vitest';
import { applyTheme, effectiveDarkMode, wireSystemThemeChange } from './apply';
import { defaultConfig } from '../config/types';

describe('applyTheme', () => {
  it('sets CSS custom properties on the host element', () => {
    const host = document.createElement('webchat-widget');
    const config = defaultConfig('widget_1');
    applyTheme(host, config);
    expect(host.style.getPropertyValue('--wc-primary')).toBe('#2563eb');
    expect(host.style.getPropertyValue('--wc-accent')).toBe('#f59e0b');
    expect(host.style.getPropertyValue('--wc-font-size-px')).toBe('16px');
    expect(host.style.getPropertyValue('--wc-position')).toBe('bottom-right');
  });

  it('maps font size tokens to pixel values', () => {
    const host = document.createElement('webchat-widget');
    const config = { ...defaultConfig('w'), font_size: 'lg' };
    applyTheme(host, config);
    expect(host.style.getPropertyValue('--wc-font-size-px')).toBe('18px');
  });

  it('marks the host with data-dark when dark mode is effective', () => {
    const host = document.createElement('webchat-widget');
    applyTheme(host, { ...defaultConfig('w'), theme: 'dark' });
    expect(host.dataset.dark).toBe('1');
    expect(host.style.getPropertyValue('--wc-dark')).toBe('1');
  });

  it('clears data-dark for a light theme', () => {
    const host = document.createElement('webchat-widget');
    applyTheme(host, { ...defaultConfig('w'), theme: 'dark' });
    applyTheme(host, { ...defaultConfig('w'), theme: 'light', dark_mode: false });
    expect(host.hasAttribute('data-dark')).toBe(false);
  });

  it('maps sizing and branding fields to CSS custom properties', () => {
    const host = document.createElement('webchat-widget');
    applyTheme(host, {
      ...defaultConfig('w'),
      width: '480px',
      height: '720px',
      border_radius: '24px',
      launcher_size: '64px',
    });
    expect(host.style.getPropertyValue('--wc-width')).toBe('480px');
    expect(host.style.getPropertyValue('--wc-height')).toBe('720px');
    expect(host.style.getPropertyValue('--wc-radius')).toBe('24px');
    expect(host.style.getPropertyValue('--wc-launcher-size')).toBe('64px');
  });

  it('falls back --wc-secondary to the accent color when secondary_color is null', () => {
    const host = document.createElement('webchat-widget');
    applyTheme(host, { ...defaultConfig('w'), accent_color: '#ff8800', secondary_color: null });
    expect(host.style.getPropertyValue('--wc-secondary')).toBe('#ff8800');
    applyTheme(host, { ...defaultConfig('w'), secondary_color: '#00cc00' });
    expect(host.style.getPropertyValue('--wc-secondary')).toBe('#00cc00');
  });

  it('clears nullable styling properties so theme fallbacks apply', () => {
    const host = document.createElement('webchat-widget');
    applyTheme(host, {
      ...defaultConfig('w'),
      header_color: '#123456',
      background_color: '#0a0a0a',
      font_family: 'Georgia',
    });
    expect(host.style.getPropertyValue('--wc-header-color')).toBe('#123456');
    expect(host.style.getPropertyValue('--wc-background')).toBe('#0a0a0a');
    expect(host.style.getPropertyValue('--wc-font-family')).toBe('Georgia');
    // Re-apply with nulls → properties removed, not set to "null".
    applyTheme(host, {
      ...defaultConfig('w'),
      header_color: null,
      background_color: null,
      font_family: null,
    });
    expect(host.style.getPropertyValue('--wc-header-color')).toBe('');
    expect(host.style.getPropertyValue('--wc-background')).toBe('');
    expect(host.style.getPropertyValue('--wc-font-family')).toBe('');
  });

  it('maps background/text overrides onto the tokens the stylesheet consumes', () => {
    const host = document.createElement('webchat-widget');
    applyTheme(host, {
      ...defaultConfig('w'),
      background_color: '#0a0a0a',
      text_color: '#fefefe',
    });
    // The stylesheet reads --wc-surface* / --wc-text, not the author tokens.
    expect(host.style.getPropertyValue('--wc-background')).toBe('#0a0a0a');
    expect(host.style.getPropertyValue('--wc-surface')).toBe('#0a0a0a');
    expect(host.style.getPropertyValue('--wc-surface-elevated')).toBe('#0a0a0a');
    expect(host.style.getPropertyValue('--wc-text-color')).toBe('#fefefe');
    expect(host.style.getPropertyValue('--wc-text')).toBe('#fefefe');
    // Unset → the override clears and the theme default (light) applies again.
    applyTheme(host, { ...defaultConfig('w'), background_color: null, text_color: null });
    expect(host.style.getPropertyValue('--wc-surface')).toBe('#ffffff');
    expect(host.style.getPropertyValue('--wc-text')).toBe('#0f172a');
  });
});

describe('applyTheme with theme presets', () => {
  it('applies the preset palette through the shared engine', () => {
    const host = document.createElement('webchat-widget');
    applyTheme(host, { ...defaultConfig('w'), theme_preset: 'emerald-support' });
    expect(host.style.getPropertyValue('--wc-primary')).toBe('#059669');
    expect(host.style.getPropertyValue('--wc-accent')).toBe('#059669');
    expect(host.style.getPropertyValue('--wc-user-bubble')).toBe('#047857');
    expect(host.style.getPropertyValue('--wc-user-text')).toBe('#ffffff');
    expect(host.style.getPropertyValue('--wc-on-primary')).toBe('#ffffff');
    expect(host.style.getPropertyValue('--wc-input-bg')).toBe('#ffffff');
    expect(host.style.getPropertyValue('--wc-header-bg')).toBe('#064e3b');
    expect(host.style.getPropertyValue('--wc-header-text')).toBe('#ffffff');
  });

  it('uses the preset dark palette when dark mode is effective', () => {
    const host = document.createElement('webchat-widget');
    applyTheme(host, { ...defaultConfig('w'), theme_preset: 'emerald-support', theme: 'dark' });
    expect(host.style.getPropertyValue('--wc-surface')).toBe('#06231c');
    expect(host.style.getPropertyValue('--wc-user-bubble')).toBe('#047857');
    expect(host.dataset.dark).toBe('1');
  });

  it('lets an explicit primary override the preset palette', () => {
    const host = document.createElement('webchat-widget');
    applyTheme(host, {
      ...defaultConfig('w'),
      theme_preset: 'ocean-blue',
      primary_color: '#c026d3',
    });
    expect(host.style.getPropertyValue('--wc-primary')).toBe('#c026d3');
  });

  it('maps the scrollbar + input tokens onto the host', () => {
    const host = document.createElement('webchat-widget');
    applyTheme(host, { ...defaultConfig('w'), theme_preset: 'modern-gradient' });
    expect(host.style.getPropertyValue('--wc-scrollbar-thumb')).toBeTruthy();
    expect(host.style.getPropertyValue('--wc-scrollbar-track')).toBeTruthy();
    expect(host.style.getPropertyValue('--wc-header-bg')).toContain('linear-gradient');
  });

  it('keeps author-facing header alias only when explicitly overridden', () => {
    const host = document.createElement('webchat-widget');
    applyTheme(host, {
      ...defaultConfig('w'),
      theme_preset: 'ocean-blue',
      header_color: '#123456',
    });
    expect(host.style.getPropertyValue('--wc-header-color')).toBe('#123456');
    expect(host.style.getPropertyValue('--wc-header-bg')).toBe('#123456');
    expect(host.style.getPropertyValue('--wc-header-text')).toBe('#ffffff');
    applyTheme(host, { ...defaultConfig('w'), theme_preset: 'ocean-blue', header_color: null });
    expect(host.style.getPropertyValue('--wc-header-color')).toBe('');
    expect(host.style.getPropertyValue('--wc-header-bg')).toBe('#0c4a6e');
  });
});

describe('effectiveDarkMode', () => {
  it('returns true for the dark theme', () => {
    expect(effectiveDarkMode({ ...defaultConfig('w'), theme: 'dark' })).toBe(true);
  });

  it('returns the explicit dark_mode flag for light theme', () => {
    expect(effectiveDarkMode({ ...defaultConfig('w'), theme: 'light', dark_mode: true })).toBe(
      true,
    );
    expect(effectiveDarkMode({ ...defaultConfig('w'), theme: 'light', dark_mode: false })).toBe(
      false,
    );
  });

  it('follows prefers-color-scheme for auto theme', () => {
    const original = window.matchMedia;
    window.matchMedia = (query: string) =>
      ({
        matches: query.includes('dark'),
        media: query,
        onchange: null,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
        addListener: () => undefined,
        removeListener: () => undefined,
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList;
    try {
      expect(effectiveDarkMode({ ...defaultConfig('w'), theme: 'auto' })).toBe(true);
    } finally {
      window.matchMedia = original;
    }
  });
});

describe('wireSystemThemeChange (audit W-03)', () => {
  type Listener = (event?: unknown) => void;

  function fakeMatchMedia(matches: boolean) {
    const state = { matches };
    const listeners = new Set<Listener>();
    return {
      get matches() {
        return state.matches;
      },
      addEventListener: (_: string, listener: Listener) => listeners.add(listener),
      removeEventListener: (_: string, listener: Listener) => listeners.delete(listener),
      flip(next: boolean) {
        // A real MediaQueryList updates `matches` before dispatching 'change'.
        state.matches = next;
        for (const listener of listeners) listener();
      },
    };
  }

  it('re-applies the theme when the OS preference flips under theme:auto', () => {
    const mq = fakeMatchMedia(false);
    window.matchMedia = vi.fn().mockReturnValue(mq) as unknown as typeof window.matchMedia;
    const host = document.createElement('webchat-widget');
    const config = { ...defaultConfig('w'), theme: 'auto' };
    applyTheme(host, config);
    expect(host.dataset.dark).toBeUndefined();

    const dispose = wireSystemThemeChange(host, () => config);
    try {
      mq.flip(true); // visitor switches their system to dark
      expect(host.dataset.dark).toBe('1');
      mq.flip(false);
      expect(host.hasAttribute('data-dark')).toBe(false);
    } finally {
      dispose();
    }
  });

  it('stops listening after dispose (destroy wiring)', () => {
    const mq = fakeMatchMedia(false);
    window.matchMedia = vi.fn().mockReturnValue(mq) as unknown as typeof window.matchMedia;
    const host = document.createElement('webchat-widget');
    const dispose = wireSystemThemeChange(host, () => ({ ...defaultConfig('w'), theme: 'auto' }));

    dispose();
    mq.flip(true);
    expect(host.dataset.dark).toBeUndefined();
  });

  it('leaves manual light/dark overrides untouched on system flips', () => {
    const mq = fakeMatchMedia(true);
    window.matchMedia = vi.fn().mockReturnValue(mq) as unknown as typeof window.matchMedia;
    const host = document.createElement('webchat-widget');
    const config = { ...defaultConfig('w'), theme: 'light' };
    applyTheme(host, config);

    const dispose = wireSystemThemeChange(host, () => config);
    try {
      mq.flip(true); // system goes dark; explicit light must win
      expect(host.dataset.dark).toBeUndefined();
    } finally {
      dispose();
    }
  });
});
