import { describe, expect, it } from 'vitest';
import { applyTheme, effectiveDarkMode } from './apply';
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
