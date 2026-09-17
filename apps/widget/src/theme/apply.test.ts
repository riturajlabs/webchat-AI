import { describe, expect, it, vi } from 'vitest';
import { applyTheme, effectiveDarkMode, wireSystemThemeChange } from './apply';
import { CURATED_FONTS, loadWebFont, matchCuratedFont } from './font';
import { defaultConfig } from '../config/types';

describe('applyTheme', () => {
  it('sets CSS custom properties on the host element', () => {
    const host = document.createElement('webchat-widget');
    const config = defaultConfig('widget_1');
    applyTheme(host, config);
    expect(host.style.getPropertyValue('--wc-primary')).toBe('#10A37F');
    expect(host.style.getPropertyValue('--wc-accent')).toBe('#25D366');
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

describe('Web font loading pipeline', () => {
  it('contains exactly 10 curated fonts in the registry', () => {
    expect(CURATED_FONTS).toHaveLength(10);
    const keys = CURATED_FONTS.map((f) => f.key);
    expect(new Set(keys).size).toBe(10);
    const labels = CURATED_FONTS.map((f) => f.label);
    expect(new Set(labels).size).toBe(10);
  });

  it('configures system default with null stylesheetUrl and valid stack', () => {
    const system = CURATED_FONTS.find((f) => f.key === 'system');
    expect(system).toBeDefined();
    expect(system?.label).toBe('System default');
    expect(system?.stylesheetUrl).toBeNull();
    expect(system?.stack).toBeTruthy();
  });

  it('configures all 9 web fonts with valid Google Fonts URLs and correct weights', () => {
    const expectedWeights: Record<string, string> = {
      inter: 'wght@400;500;600',
      poppins: 'wght@400;500;600',
      nunito: 'wght@400;600;700',
      roboto: 'wght@400;500;700',
      'open-sans': 'wght@400;500;600;700',
      montserrat: 'wght@400;500;600;700',
      lato: 'wght@400;700',
      'playfair-display': 'wght@500;700',
      'space-grotesk': 'wght@500;700',
    };

    const webFonts = CURATED_FONTS.filter((f) => f.key !== 'system');
    expect(webFonts).toHaveLength(9);

    for (const font of webFonts) {
      expect(font.stylesheetUrl).toMatch(/^https:\/\/fonts\.googleapis\.com\/css2\?family=/);
      expect(font.stylesheetUrl).toContain('display=swap');
      const weightPattern = expectedWeights[font.key];
      expect(weightPattern).toBeDefined();
      expect(font.stylesheetUrl).toContain(weightPattern);
    }
  });

  it('matches all 9 web fonts by key, label, and full stack', () => {
    for (const font of CURATED_FONTS) {
      if (font.key === 'system') continue;
      expect(matchCuratedFont(font.key)?.key).toBe(font.key);
      expect(matchCuratedFont(font.label)?.key).toBe(font.key);
      expect(matchCuratedFont(font.stack)?.key).toBe(font.key);
      expect(matchCuratedFont(font.label.toLowerCase())?.key).toBe(font.key);
    }
  });

  it('does not misidentify system font stack as Roboto', () => {
    const systemStack =
      "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";
    expect(matchCuratedFont(systemStack)).toBeNull();
    expect(matchCuratedFont('system')).toBeNull();
    expect(matchCuratedFont('system default')).toBeNull();
  });

  it('rejects untrusted strings, unknown fonts, and arbitrary URLs', () => {
    expect(matchCuratedFont('')).toBeNull();
    expect(matchCuratedFont(null)).toBeNull();
    expect(matchCuratedFont(undefined)).toBeNull();
    expect(matchCuratedFont('Comic Sans MS')).toBeNull();
    expect(matchCuratedFont('<script>alert("xss")</script>')).toBeNull();
    expect(matchCuratedFont('https://evil.com/font.css')).toBeNull();
  });

  it('does not inject link for system default font or null/undefined', () => {
    const headCountBefore = document.head.querySelectorAll('link[data-webchat-font]').length;
    loadWebFont('system');
    loadWebFont(null);
    loadWebFont(undefined);
    loadWebFont(
      "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
    );
    const headCountAfter = document.head.querySelectorAll('link[data-webchat-font]').length;
    expect(headCountAfter).toBe(headCountBefore);
  });

  it('injects stylesheet link for each curated web font into target document head', () => {
    const webFonts = CURATED_FONTS.filter((f) => f.key !== 'system');
    for (const font of webFonts) {
      loadWebFont(font.key);
      const link = document.head.querySelector(`link[data-webchat-font="${font.key}"]`);
      expect(link).not.toBeNull();
      expect(link?.getAttribute('rel')).toBe('stylesheet');
      expect(link?.getAttribute('href')).toBe(font.stylesheetUrl);
    }
  });

  it('deduplicates multiple calls for the same font', () => {
    loadWebFont('Inter');
    loadWebFont('Inter');
    loadWebFont("'Inter', system-ui, sans-serif");
    const links = document.head.querySelectorAll('link[data-webchat-font="inter"]');
    expect(links).toHaveLength(1);
  });

  it('applyTheme applies font-family to host style and triggers font loading', () => {
    const host = document.createElement('webchat-widget');
    const config = {
      ...defaultConfig('w'),
      font_family: "'Space Grotesk', system-ui, -apple-system, sans-serif",
    };
    applyTheme(host, config);

    expect(host.style.getPropertyValue('--wc-font-family')).toBe(
      "'Space Grotesk', system-ui, -apple-system, sans-serif",
    );
    const link = document.head.querySelector('link[data-webchat-font="space-grotesk"]');
    expect(link).not.toBeNull();
  });
});
