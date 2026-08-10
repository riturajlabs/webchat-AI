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
  logo_url: null,
  avatar_url: null,
  welcome_message: 'Hi!',
  placeholder: 'Type…',
  suggested_questions: ['a', 'b'],
  branding: true,
  dark_mode: false,
  auto_open: false,
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
      code: 'config',
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
});
