import { describe, expect, it } from 'vitest';
import { defaultConfig } from '../config/types';
import {
  DEFAULT_BRAND_LOGO,
  getBrandLogoCandidates,
  isSafeImageUrl,
  renderBrandLogo,
} from './branding';

describe('isSafeImageUrl', () => {
  it('accepts http and https image URLs', () => {
    expect(isSafeImageUrl('https://example.com/logo.png')).toBe(true);
    expect(isSafeImageUrl('http://example.com/logo.png')).toBe(true);
  });

  it('rejects unsafe schemes, relative URLs, and empty values', () => {
    expect(isSafeImageUrl('javascript:alert(1)')).toBe(false);
    expect(isSafeImageUrl('data:image/png;base64,abc')).toBe(false);
    expect(isSafeImageUrl('//example.com/logo.png')).toBe(false);
    expect(isSafeImageUrl('/logo.png')).toBe(false);
    expect(isSafeImageUrl('')).toBe(false);
  });
});

describe('getBrandLogoCandidates (global dynamic logo precedence)', () => {
  it('returns an empty list when only the official default applies', () => {
    expect(getBrandLogoCandidates(defaultConfig('w1'))).toEqual([]);
  });

  it('builds candidates in strict priority order: avatar -> custom logo', () => {
    const config = {
      ...defaultConfig('w1'),
      avatar_url: 'https://cdn.example.com/avatar.png',
      logo_url: 'https://cdn.example.com/logo.png',
      website_logo_url: 'https://cdn.example.com/site-preview.png',
      website_favicon_url: 'https://cdn.example.com/favicon.ico',
    };

    expect(getBrandLogoCandidates(config)).toEqual([
      'https://cdn.example.com/avatar.png',
      'https://cdn.example.com/logo.png',
    ]);
  });

  it('skips a logo_url that is really the backend-injected website fallback', () => {
    const config = {
      ...defaultConfig('w1'),
      logo_url: 'https://cdn.example.com/site-preview.png',
      website_logo_url: 'https://cdn.example.com/site-preview.png',
      website_favicon_url: 'https://cdn.example.com/favicon.ico',
    };

    expect(getBrandLogoCandidates(config)).toEqual([]);
  });

  it('ignores website logo/favicon when no custom chatbot brand exists', () => {
    const config = {
      ...defaultConfig('w1'),
      website_logo_url: 'https://cdn.example.com/site-preview.png',
      website_favicon_url: 'https://cdn.example.com/favicon.ico',
    };

    expect(getBrandLogoCandidates(config)).toEqual([]);
  });

  it('deduplicates identical custom URLs across levels', () => {
    const config = {
      ...defaultConfig('w1'),
      avatar_url: 'https://cdn.example.com/shared.png',
      logo_url: 'https://cdn.example.com/shared.png',
    };

    expect(getBrandLogoCandidates(config)).toEqual(['https://cdn.example.com/shared.png']);
  });
});

describe('renderBrandLogo (official WebChat AI default)', () => {
  it('renders the official default logo when no custom brand is configured', () => {
    const container = document.createElement('span');
    renderBrandLogo(container, defaultConfig('w1'), 'wc-brand-logo');

    const img = container.querySelector<HTMLImageElement>('img.wc-brand-logo');
    expect(img).not.toBeNull();
    expect(img?.src).toBe(DEFAULT_BRAND_LOGO);
    expect(img?.alt).toBe('');
    expect(img?.referrerPolicy).toBe('no-referrer');
  });

  it('mounts the highest-priority custom candidate when available', () => {
    const container = document.createElement('span');
    const config = {
      ...defaultConfig('w1'),
      avatar_url: null,
      logo_url: 'https://cdn.example.com/logo.png',
      website_logo_url: 'https://cdn.example.com/site.png',
    };

    renderBrandLogo(container, config, 'wc-brand-logo');

    const img = container.querySelector<HTMLImageElement>('img.wc-brand-logo');
    expect(img?.src).toBe('https://cdn.example.com/logo.png');
  });

  it('advances to the next candidate when an image errors', () => {
    const container = document.createElement('span');
    const config = {
      ...defaultConfig('w1'),
      avatar_url: 'https://cdn.example.com/broken-avatar.png',
      logo_url: 'https://cdn.example.com/valid-logo.png',
    };

    renderBrandLogo(container, config, 'wc-brand-logo');

    const img = container.querySelector<HTMLImageElement>('img.wc-brand-logo')!;
    expect(img.src).toBe('https://cdn.example.com/broken-avatar.png');

    img.dispatchEvent(new Event('error'));
    expect(img.src).toBe('https://cdn.example.com/valid-logo.png');
  });

  it('falls back to the official default after every custom candidate fails', () => {
    const container = document.createElement('span');
    const config = {
      ...defaultConfig('w1'),
      avatar_url: 'https://cdn.example.com/broken-avatar.png',
      logo_url: 'https://cdn.example.com/broken-logo.png',
    };

    renderBrandLogo(container, config, 'wc-brand-logo');

    const img = container.querySelector<HTMLImageElement>('img.wc-brand-logo')!;
    img.dispatchEvent(new Event('error'));
    img.dispatchEvent(new Event('error'));

    expect(img.src).toBe(DEFAULT_BRAND_LOGO);
    expect(container.querySelector('img')).toBe(img);
  });

  it('skips unsafe custom schemes and renders the official default', () => {
    const container = document.createElement('span');
    const config = {
      ...defaultConfig('w1'),
      avatar_url: 'javascript:alert(1)',
      logo_url: 'data:image/png;base64,x',
    };

    renderBrandLogo(container, config, 'wc-brand-logo');

    expect(container.querySelector<HTMLImageElement>('img.wc-brand-logo')?.src).toBe(
      DEFAULT_BRAND_LOGO,
    );
  });

  it('replaces even a failed default with botGlyph (defensive, zero broken-image box)', () => {
    const container = document.createElement('span');
    renderBrandLogo(container, defaultConfig('w1'), 'wc-brand-logo');

    const img = container.querySelector<HTMLImageElement>('img.wc-brand-logo')!;
    img.dispatchEvent(new Event('error'));

    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('svg')).not.toBeNull();
  });

  it('ignores onerror if img was detached or superseded before error fired', () => {
    const container = document.createElement('span');
    const oldConfig = { ...defaultConfig('w1'), avatar_url: 'https://cdn.example.com/old.png' };
    renderBrandLogo(container, oldConfig, 'wc-brand-logo');
    const oldImg = container.querySelector<HTMLImageElement>('img')!;

    const newConfig = { ...defaultConfig('w1'), avatar_url: 'https://cdn.example.com/new.png' };
    renderBrandLogo(container, newConfig, 'wc-brand-logo');
    const newImg = container.querySelector<HTMLImageElement>('img')!;
    expect(newImg.src).toBe('https://cdn.example.com/new.png');

    oldImg.dispatchEvent(new Event('error'));

    expect(container.querySelector('img')).toBe(newImg);
    expect(newImg.src).toBe('https://cdn.example.com/new.png');
  });
});
