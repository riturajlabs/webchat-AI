import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  buildPublicConfigUrl,
  buildWidgetTestHtml,
  fetchPublicConfig,
  parseScriptSrc,
} from './widget-test';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('parseScriptSrc', () => {
  it('extracts the src attribute from a backend embed script', () => {
    expect(
      parseScriptSrc(
        '<script src="http://localhost:8080/webchat-widget.iife.min.js" ' +
          'data-widget-id="w-1" defer></script>',
      ),
    ).toBe('http://localhost:8080/webchat-widget.iife.min.js');
  });

  it('returns null when there is no script src', () => {
    expect(parseScriptSrc('no script here')).toBeNull();
    expect(parseScriptSrc('')).toBeNull();
  });
});

describe('buildWidgetTestHtml', () => {
  it('boots the SDK from the script src and widget id', () => {
    const html = buildWidgetTestHtml({
      scriptSrc: 'http://localhost:8080/webchat-widget.iife.min.js',
      widgetId: 'w-1',
    });
    expect(html).toContain('<!doctype html>');
    expect(html).toContain('src="http://localhost:8080/webchat-widget.iife.min.js"');
    expect(html).toContain('data-widget-id="w-1"');
    expect(html).toContain('defer');
  });

  it('is a self-contained document ready to render in an iframe srcdoc', () => {
    const html = buildWidgetTestHtml({
      scriptSrc: 'https://cdn.example.com/widget.js',
      widgetId: 'w-2',
    });
    expect(html).toMatch(/^<!doctype html>/);
    expect(html).toContain('</html>');
  });
});

describe('buildPublicConfigUrl', () => {
  it('appends the config route and tolerates a trailing slash', () => {
    expect(buildPublicConfigUrl('http://localhost:8000', 'w-1')).toBe(
      'http://localhost:8000/api/widget/v1/config/w-1',
    );
    expect(buildPublicConfigUrl('http://localhost:8000/', 'w-1')).toBe(
      'http://localhost:8000/api/widget/v1/config/w-1',
    );
  });
});

describe('fetchPublicConfig', () => {
  it('returns the allowed shape on a 200', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        text: () =>
          Promise.resolve(JSON.stringify({ enabled: true, allowed_domains: ['example.com'] })),
      }),
    );

    const result = await fetchPublicConfig('http://localhost:8000', 'w-1');
    expect(result).toEqual({
      statusCode: 200,
      enabled: true,
      allowedDomains: ['example.com'],
    });
  });

  it('surfaces the guard error envelope on a 403', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 403,
        text: () =>
          Promise.resolve(
            JSON.stringify({
              error: {
                code: 'WIDGET_ORIGIN_NOT_ALLOWED',
                message: 'Domain evil.example is not allowed for this widget.',
              },
            }),
          ),
      }),
    );

    const result = await fetchPublicConfig('http://localhost:8000', 'w-1');
    expect(result.statusCode).toBe(403);
    expect(result.errorCode).toBe('WIDGET_ORIGIN_NOT_ALLOWED');
    expect(result.message).toContain('evil.example');
  });

  it('reports an unreachable API without throwing', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    const result = await fetchPublicConfig('http://localhost:8000', 'w-1');
    expect(result.statusCode).toBe(0);
    expect(result.message).toContain('unreachable');
  });
});
