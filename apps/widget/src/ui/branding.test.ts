import { describe, expect, it } from 'vitest';
import { defaultConfig } from '../config/types';
import {
  getBrandLogoCandidates,
  getHostFaviconUrl,
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

describe('getBrandLogoCandidates & getHostFaviconUrl', () => {
  it('discovers link[rel="icon"] from the document if safe', () => {
    const link = document.createElement('link');
    link.rel = 'icon';
    link.href = 'https://host.example.com/favicon.png';
    document.head.appendChild(link);

    expect(getHostFaviconUrl()).toBe('https://host.example.com/favicon.png');

    document.head.removeChild(link);
  });

  it('builds candidates in strict priority order: avatar -> logo -> website_logo -> website_favicon -> host_favicon', () => {
    const config = {
      ...defaultConfig('w1'),
      avatar_url: 'https://cdn.example.com/avatar.png',
      logo_url: 'https://cdn.example.com/logo.png',
      website_logo_url: 'https://cdn.example.com/site-preview.png',
      website_favicon_url: 'https://cdn.example.com/favicon.ico',
    };

    const candidates = getBrandLogoCandidates(config);
    expect(candidates).toEqual([
      'https://cdn.example.com/avatar.png',
      'https://cdn.example.com/logo.png',
      'https://cdn.example.com/site-preview.png',
      'https://cdn.example.com/favicon.ico',
    ]);
  });

  it('deduplicates identical URLs across fallback levels', () => {
    const config = {
      ...defaultConfig('w1'),
      avatar_url: 'https://cdn.example.com/shared.png',
      logo_url: 'https://cdn.example.com/shared.png',
      website_logo_url: 'https://cdn.example.com/shared.png',
      website_favicon_url: 'https://cdn.example.com/favicon.ico',
    };

    const candidates = getBrandLogoCandidates(config);
    expect(candidates).toEqual([
      'https://cdn.example.com/shared.png',
      'https://cdn.example.com/favicon.ico',
    ]);
  });
});

describe('renderBrandLogo fallback hierarchy and onerror recovery', () => {
  it('renders botGlyph immediately when no safe image candidates exist', () => {
    const container = document.createElement('span');
    const config = {
      ...defaultConfig('w1'),
      avatar_url: 'javascript:alert(1)',
      logo_url: null,
      website_logo_url: null,
      website_favicon_url: null,
    };

    renderBrandLogo(container, config, 'wc-brand-logo');

    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('svg')).not.toBeNull();
  });

  it('mounts the first candidate when available', () => {
    const container = document.createElement('span');
    const config = {
      ...defaultConfig('w1'),
      avatar_url: null,
      logo_url: 'https://cdn.example.com/logo.png',
      website_logo_url: 'https://cdn.example.com/site.png',
    };

    renderBrandLogo(container, config, 'wc-brand-logo');

    const img = container.querySelector<HTMLImageElement>('img.wc-brand-logo');
    expect(img).not.toBeNull();
    expect(img?.src).toBe('https://cdn.example.com/logo.png');
    expect(img?.alt).toBe('');
    expect(img?.referrerPolicy).toBe('no-referrer');
  });

  it('advances to next candidate when image encounters an error', () => {
    const container = document.createElement('span');
    const config = {
      ...defaultConfig('w1'),
      avatar_url: 'https://cdn.example.com/broken-avatar.png',
      logo_url: 'https://cdn.example.com/valid-logo.png',
      website_logo_url: 'https://cdn.example.com/site.png',
    };

    renderBrandLogo(container, config, 'wc-brand-logo');

    const img = container.querySelector<HTMLImageElement>('img.wc-brand-logo')!;
    expect(img.src).toBe('https://cdn.example.com/broken-avatar.png');

    // Simulate 404/network failure on avatar_url
    img.dispatchEvent(new Event('error'));

    // Should now point to logo_url
    expect(img.src).toBe('https://cdn.example.com/valid-logo.png');
  });

  it('cascades through multiple failures until reaching website logo or favicon', () => {
    const container = document.createElement('span');
    const config = {
      ...defaultConfig('w1'),
      avatar_url: 'https://cdn.example.com/broken-avatar.png',
      logo_url: 'https://cdn.example.com/broken-logo.png',
      website_logo_url: 'https://cdn.example.com/site-preview.png',
      website_favicon_url: 'https://cdn.example.com/favicon.ico',
    };

    renderBrandLogo(container, config, 'wc-brand-logo');
    const img = container.querySelector<HTMLImageElement>('img.wc-brand-logo')!;

    // 1st error: avatar fails -> logo
    img.dispatchEvent(new Event('error'));
    expect(img.src).toBe('https://cdn.example.com/broken-logo.png');

    // 2nd error: logo fails -> website_logo
    img.dispatchEvent(new Event('error'));
    expect(img.src).toBe('https://cdn.example.com/site-preview.png');

    // 3rd error: website_logo fails -> website_favicon
    img.dispatchEvent(new Event('error'));
    expect(img.src).toBe('https://cdn.example.com/favicon.ico');
  });

  it('replaces image with botGlyph when all image candidates fail (zero broken image box)', () => {
    const container = document.createElement('span');
    const config = {
      ...defaultConfig('w1'),
      avatar_url: 'https://cdn.example.com/broken-avatar.png',
      logo_url: null,
      website_logo_url: null,
      website_favicon_url: null,
    };

    renderBrandLogo(container, config, 'wc-brand-logo');
    const img = container.querySelector<HTMLImageElement>('img.wc-brand-logo')!;
    expect(img).not.toBeNull();

    // Trigger error on the only candidate
    img.dispatchEvent(new Event('error'));

    // img is removed and replaced by SVG botGlyph
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('svg')).not.toBeNull();
  });

  it('ignores onerror if img was detached or superseded before error fired', () => {
    const container = document.createElement('span');
    const oldConfig = {
      ...defaultConfig('w1'),
      avatar_url: 'https://cdn.example.com/old-broken.png',
    };
    renderBrandLogo(container, oldConfig, 'wc-brand-logo');
    const oldImg = container.querySelector<HTMLImageElement>('img')!;

    // Re-render container with a new valid logo
    const newConfig = {
      ...defaultConfig('w1'),
      avatar_url: 'https://cdn.example.com/new-valid.png',
    };
    renderBrandLogo(container, newConfig, 'wc-brand-logo');
    const newImg = container.querySelector<HTMLImageElement>('img')!;
    expect(newImg.src).toBe('https://cdn.example.com/new-valid.png');

    // Late error event arrives for oldImg
    oldImg.dispatchEvent(new Event('error'));

    // Container should still contain the newImg, not reverted to botGlyph
    expect(container.querySelector('img')).toBe(newImg);
    expect(newImg.src).toBe('https://cdn.example.com/new-valid.png');
  });
});
