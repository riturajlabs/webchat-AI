import { afterEach, describe, expect, it } from 'vitest';
import { resolveApiBaseUrl, sanitizeApiBaseUrl } from './types';

const ENV_KEY = 'VITE_WIDGET_API_BASE_URL';

function setEnvBaseUrl(value: string | undefined): void {
  const env = (import.meta.env ?? {}) as Record<string, string | undefined>;
  if (value === undefined) {
    delete env[ENV_KEY];
  } else {
    env[ENV_KEY] = value;
  }
}

afterEach(() => {
  setEnvBaseUrl(undefined);
});

describe('resolveApiBaseUrl', () => {
  it('appends the versioned path to a host-only base', () => {
    expect(resolveApiBaseUrl('https://api.example.com')).toBe(
      'https://api.example.com/api/widget/v1',
    );
  });

  it('keeps an already-versioned base unchanged', () => {
    expect(resolveApiBaseUrl('https://api.example.com/api/widget/v1')).toBe(
      'https://api.example.com/api/widget/v1',
    );
  });

  it('handles trailing slashes', () => {
    expect(resolveApiBaseUrl('https://api.example.com/api/widget/v1/')).toBe(
      'https://api.example.com/api/widget/v1',
    );
  });

  it('falls back to the same-origin base when no base is configured', () => {
    setEnvBaseUrl(undefined);
    expect(resolveApiBaseUrl(undefined)).toBe('/api/widget/v1');
  });

  it('uses the build-time env base when no explicit base is given', () => {
    setEnvBaseUrl('https://cdn.webchat-ai.example/api/widget/v1');
    expect(resolveApiBaseUrl(undefined)).toBe('https://cdn.webchat-ai.example/api/widget/v1');
  });

  it('resolves an empty explicit base to the same-origin base', () => {
    expect(resolveApiBaseUrl('')).toBe('/api/widget/v1');
  });
});

describe('sanitizeApiBaseUrl', () => {
  it('strips trailing slashes', () => {
    expect(sanitizeApiBaseUrl('https://api.example.com///')).toBe('https://api.example.com');
  });
});
