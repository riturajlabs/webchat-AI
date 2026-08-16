import { describe, expect, it, vi } from 'vitest';
import { fetchPublicConfig, loadConfig } from './fetch';
import type { ConfigStore } from './fetch';
import type { WidgetPublicConfig } from './types';

const API_BASE = 'http://api.example.com/api/widget/v1';
const OPTIONS = { widgetId: 'widget_1', apiBaseUrl: API_BASE };

const CONFIG: WidgetPublicConfig = {
  widget_id: 'widget_1',
  enabled: true,
  theme: 'light',
  position: 'bottom-right',
  primary_color: '#2563eb',
  accent_color: '#f59e0b',
  font_size: 'md',
  theme_preset: '',
  logo_url: null,
  avatar_url: null,
  welcome_message: 'Hi!',
  placeholder: 'Type…',
  suggested_questions: ['a', 'b'],
  branding: true,
  dark_mode: false,
  auto_open: false,
  bot_name: 'WebChat AI',
  bot_status_text: 'Online',
  header_color: null,
  secondary_color: null,
  background_color: null,
  text_color: null,
  font_family: null,
  width: '380px',
  height: '600px',
  border_radius: '20px',
  launcher_size: '58px',
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function fakeStore(): ConfigStore {
  const data = new Map<string, { config: WidgetPublicConfig; cachedAt: number }>();
  return {
    get(widgetId: string) {
      return data.get(widgetId) ?? null;
    },
    set(widgetId: string, config: WidgetPublicConfig) {
      data.set(widgetId, { config, cachedAt: Date.now() });
    },
  };
}

describe('fetchPublicConfig', () => {
  it('fetches and caches the public config', async () => {
    const store = fakeStore();
    const fetchImpl = vi.fn(async () => jsonResponse(CONFIG));
    const config = await fetchPublicConfig(OPTIONS, fetchImpl, store);
    expect(config).toEqual(CONFIG);
    expect(fetchImpl).toHaveBeenCalledWith(
      `${API_BASE}/config/widget_1`,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(store.get('widget_1')?.config).toEqual(CONFIG);
  });

  it('serves from cache within the TTL without refetching', async () => {
    const store = fakeStore();
    const fetchImpl = vi.fn(async () => jsonResponse(CONFIG));
    await fetchPublicConfig(OPTIONS, fetchImpl, store);
    const second = await fetchPublicConfig(OPTIONS, fetchImpl, store);
    expect(second).toEqual(CONFIG);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('throws on non-OK responses', async () => {
    const store = fakeStore();
    const fetchImpl = vi.fn(async () => jsonResponse({}, 404));
    await expect(fetchPublicConfig(OPTIONS, fetchImpl, store)).rejects.toMatchObject({
      code: 'invalid',
    });
  });

  it('surfaces an invalid widget id from the backend error envelope', async () => {
    const store = fakeStore();
    const fetchImpl = vi.fn(async () =>
      jsonResponse({ error: { code: 'WIDGET_NOT_FOUND', message: 'Widget not found.' } }, 404),
    );
    await expect(fetchPublicConfig(OPTIONS, fetchImpl, store)).rejects.toMatchObject({
      code: 'widget_not_found',
      userMessage: 'Invalid widget ID',
      status: 404,
    });
  });

  it('surfaces a disabled widget from the backend error envelope', async () => {
    const store = fakeStore();
    const fetchImpl = vi.fn(async () =>
      jsonResponse(
        { error: { code: 'WIDGET_DISABLED', message: 'Widget is not available.' } },
        403,
      ),
    );
    await expect(fetchPublicConfig(OPTIONS, fetchImpl, store)).rejects.toMatchObject({
      code: 'widget_disabled',
      userMessage: 'This assistant is currently unavailable',
    });
  });
});

describe('loadConfig', () => {
  it('falls back to safe defaults when the fetch fails', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error('network down');
    });
    const config = await loadConfig(OPTIONS, fetchImpl);
    expect(config.widget_id).toBe('widget_1');
    expect(config.enabled).toBe(true);
    expect(config.position).toBe('bottom-right');
    expect(config.suggested_questions).toEqual([]);
  });

  it('returns the fetched config when available', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(CONFIG));
    const config = await loadConfig(OPTIONS, fetchImpl);
    expect(config).toEqual(CONFIG);
  });

  it('preserves an explicitly disabled config instead of defaulting', async () => {
    const store = fakeStore();
    const options = { ...OPTIONS, widgetId: 'widget_disabled_1' };
    const fetchImpl = vi.fn(async () =>
      jsonResponse({ ...CONFIG, widget_id: 'widget_disabled_1', enabled: false }),
    );
    const config = await loadConfig(options, fetchImpl, store);
    expect(config.enabled).toBe(false);
  });

  it('falls back to safe defaults when the widget id is rejected', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse({ error: { code: 'WIDGET_NOT_FOUND', message: 'Widget not found.' } }, 404),
    );
    const config = await loadConfig(OPTIONS, fetchImpl);
    expect(config.widget_id).toBe('widget_1');
    expect(config.enabled).toBe(true);
  });
});
