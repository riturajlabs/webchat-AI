import { describe, expect, it, vi } from 'vitest';
import { mount } from '../core/mount';
import { createLauncher } from './launcher';
import { WIDGET_STYLES } from './styles';
import { defaultConfig } from '../config/types';

const API_BASE = 'http://api.example.com/api/widget/v1';

/**
 * Production-readiness guards (audit): the widget must ship fully self-contained
 * and visually isolated from the embedding page.
 *   1. No external assets: styles reference no fonts/images (no `url()`,
 *      `@font-face`, `@import` or font files) and the launcher icon is a text
 *      glyph — the bundle cannot break on CSP or lose a cached asset.
 *   2. CSS isolation: styles live inside the closed shadow root only and reset
 *      inherited host styles (`all: initial`), so embedding-page CSS cannot
 *      leak into the widget UI.
 */

describe('asset self-containment', () => {
  it('WIDGET_STYLES references no external assets', () => {
    expect(WIDGET_STYLES).not.toMatch(/url\(/);
    expect(WIDGET_STYLES).not.toMatch(/@font-face/);
    expect(WIDGET_STYLES).not.toMatch(/@import/);
    expect(WIDGET_STYLES).not.toMatch(/\.(woff2?|ttf|eot|otf|svg|png|jpe?g|gif|webp)\b/i);
  });

  it('launcher icon is a text glyph, not an external image', () => {
    const onToggle = vi.fn();
    const button = createLauncher({ position: 'bottom-right', onToggle, isOpen: () => false });
    const icon = button.querySelector('.wc-launcher-icon');
    expect(icon?.textContent).toBe('💬');
    expect(button.querySelector('img')).toBeNull();
    expect(button.querySelector('[src]')).toBeNull();
  });
});

describe('CSS isolation from the embedding page', () => {
  it('starts with a host reset so page styles cannot leak in', () => {
    // `all: initial` on `:host` neutralizes inherited colors/fonts/layout the
    // embedding page would otherwise pass through the shadow boundary.
    expect(WIDGET_STYLES).toMatch(/:host\s*{[^}]*all:\s*initial/);
  });

  it('mounts styles into the shadow root only, never the document', async () => {
    const fetchImpl = vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      if (url.endsWith('/config/widget_1')) {
        return new Response(JSON.stringify({ ...defaultConfig('widget_1'), enabled: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url.endsWith('/sessions')) {
        return new Response(
          JSON.stringify({ session_token: 'tok', expires_at: '2030-01-01T00:00:00Z' }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      throw new Error(`unexpected URL: ${url}`);
    });

    // An open root is only used so the test can inspect; production uses the
    // closed default (asserted in core/mount.test.ts).
    const host = document.createElement('webchat-widget');
    host.attachShadow({ mode: 'open' });
    const controller = mount({ widgetId: 'widget_1', apiBaseUrl: API_BASE, fetchImpl, host });
    await controller.ready();

    const shadow = host.shadowRoot as ShadowRoot;
    const shadowStyle = shadow.querySelector('style');
    expect(shadowStyle).toBeTruthy();
    expect(shadowStyle?.textContent).toBe(WIDGET_STYLES);

    // No widget-authored <style> ever lands in the embedding document.
    const documentStyles = Array.from(document.querySelectorAll('style'));
    expect(documentStyles.some((s) => s.textContent === WIDGET_STYLES)).toBe(false);

    // All widget UI is scoped inside the shadow root.
    expect(shadow.querySelector('.wc-launcher')).toBeTruthy();
    expect(document.querySelector('.wc-launcher')).toBeNull();

    controller.destroy();
  });
});
