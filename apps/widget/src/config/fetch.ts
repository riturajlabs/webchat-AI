/**
 * Public config fetching (plan §5).
 *
 * `GET /api/widget/v1/config/{widget_id}` is cached in-module for 5 minutes
 * (mirroring the backend's Redis cache). Fetch failures fall back to safe
 * defaults so the launcher still renders, and lazy-retry in the background is
 * handled by the caller.
 */

import {
  defaultConfig,
  sanitizeApiBaseUrl,
  type WidgetPublicConfig,
  type WidgetOptions,
} from './types';
import { WidgetError } from '../core/errors';
import { fetchWithTimeout } from '../core/network';

export const CONFIG_CACHE_TTL_MS = 5 * 60 * 1000;

/** Config request timeout (plan §9). */
export const CONFIG_TIMEOUT_MS = 5 * 1000;

export interface ConfigStore {
  get(widgetId: string): { config: WidgetPublicConfig; cachedAt: number } | null;
  set(widgetId: string, config: WidgetPublicConfig): void;
}

interface CacheEntry {
  config: WidgetPublicConfig;
  cachedAt: number;
}

const memoryConfigData = new Map<string, CacheEntry>();

export const memoryConfigStore: ConfigStore = {
  get(widgetId: string) {
    return memoryConfigData.get(widgetId) ?? null;
  },
  set(widgetId: string, config: WidgetPublicConfig) {
    memoryConfigData.set(widgetId, { config, cachedAt: Date.now() });
  },
};

/**
 * Fetch the public config, using the in-module cache within its TTL.
 * Returns the config, or `null` on any failure (caller falls back to defaults).
 */
export async function fetchPublicConfig(
  options: WidgetOptions,
  fetchImpl: typeof fetch = fetch,
  store: ConfigStore = memoryConfigStore,
): Promise<WidgetPublicConfig | null> {
  const apiBaseUrl = sanitizeApiBaseUrl(options.apiBaseUrl ?? '/api/widget/v1');
  const cached = store.get(options.widgetId);
  if (cached && Date.now() - cached.cachedAt < CONFIG_CACHE_TTL_MS) {
    return cached.config;
  }

  let response: Response;
  try {
    response = await fetchWithTimeout(
      `${apiBaseUrl}/config/${encodeURIComponent(options.widgetId)}`,
      undefined,
      { timeoutMs: CONFIG_TIMEOUT_MS, fetchImpl },
    );
  } catch (cause) {
    throw new WidgetError({
      code: cause && (cause as Error).name === 'RequestTimeoutError' ? 'timeout' : 'network',
      message: 'Config request failed',
      cause,
    });
  }
  if (!response.ok) {
    throw new WidgetError({
      code: 'config',
      message: `Config request failed (${response.status})`,
      status: response.status,
    });
  }
  const config = (await response.json()) as WidgetPublicConfig;
  store.set(options.widgetId, config);
  return config;
}

/** Resolve a config, never throwing: falls back to safe defaults on failure. */
export async function loadConfig(
  options: WidgetOptions,
  fetchImpl?: typeof fetch,
  store?: ConfigStore,
): Promise<WidgetPublicConfig> {
  try {
    const config = await fetchPublicConfig(options, fetchImpl, store);
    if (config) {
      return config;
    }
  } catch {
    // Fall through to safe defaults; the launcher must never be blocked.
  }
  return defaultConfig(options.widgetId);
}
