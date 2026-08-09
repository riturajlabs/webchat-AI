import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { api, ApiError } from '@/lib/api';
import {
  clearSession,
  getAccessToken,
  getCsrfToken,
  setAccessToken,
  setCsrfToken,
} from '@/lib/session';

const BASE = 'http://localhost:8000';

const USER = {
  id: 'user-1',
  name: 'Jane Doe',
  email: 'jane@example.com',
  role: 'owner',
  email_verified: true,
  status: 'active',
  tenant_id: 'tenant-1',
  created_at: '2026-08-01T00:00:00Z',
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function stubLocation(assign: ReturnType<typeof vi.fn>) {
  Object.defineProperty(window, 'location', {
    configurable: true,
    writable: true,
    value: { pathname: '/websites', search: '', hash: '', assign },
  });
}

describe('api client', () => {
  beforeEach(() => {
    clearSession();
    localStorage.clear();
    sessionStorage.clear();
    document.cookie = 'csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    clearSession();
  });

  it('attaches the bearer access token from memory', async () => {
    setAccessToken('access-1');
    vi.mocked(fetch).mockResolvedValue(jsonResponse([]));

    await api.get('/api/websites');

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe(`${BASE}/api/websites`);
    expect((init!.headers as Headers).get('Authorization')).toBe('Bearer access-1');
    expect((init!.headers as Headers).get('X-CSRF-Token')).toBeNull();
  });

  it('refreshes the token once on a 401 and retries the original request', async () => {
    setAccessToken('expired-token');
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ error: { code: 'token_expired' } }, 401))
      .mockResolvedValueOnce(jsonResponse({ access_token: 'fresh-token', user: USER }))
      .mockResolvedValueOnce(jsonResponse([{ id: 'site-1' }]));

    const result = await api.get<{ id: string }[]>('/api/websites');

    expect(result).toEqual([{ id: 'site-1' }]);
    expect(fetchMock).toHaveBeenCalledTimes(3);

    const refreshCall = fetchMock.mock.calls[1];
    expect(refreshCall[0]).toBe(`${BASE}/api/auth/refresh`);
    expect((refreshCall[1] as RequestInit).method).toBe('POST');
    expect((refreshCall[1] as RequestInit).credentials).toBe('include');

    expect(getAccessToken()).toBe('fresh-token');

    const retryCall = fetchMock.mock.calls[2];
    expect((retryCall[1]!.headers as Headers).get('Authorization')).toBe('Bearer fresh-token');
  });

  it('does not refresh more than once (no infinite loop)', async () => {
    setAccessToken('expired-token');
    const assign = vi.fn();
    stubLocation(assign);
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse({}, 401))
      .mockResolvedValueOnce(jsonResponse({ access_token: 'fresh-token', user: USER }))
      .mockResolvedValueOnce(jsonResponse({}, 401));

    await expect(api.get('/api/websites')).rejects.toThrow();

    expect(fetchMock).toHaveBeenCalledTimes(3);
    const refreshPaths = fetchMock.mock.calls.filter(
      (call) => call[0] === `${BASE}/api/auth/refresh`,
    );
    expect(refreshPaths).toHaveLength(1);
  });

  it('clears the session and redirects to /login when the refresh fails', async () => {
    setAccessToken('expired-token');
    const assign = vi.fn();
    stubLocation(assign);
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ error: { code: 'token_expired' } }, 401))
      .mockResolvedValueOnce(jsonResponse({}, 401));

    await expect(api.get('/api/websites')).rejects.toThrow(ApiError);

    expect(getAccessToken()).toBeNull();
    expect(getCsrfToken()).toBeNull();
    expect(assign).toHaveBeenCalledWith('/login?redirect=%2Fwebsites');
  });

  it('sends the CSRF header from memory for protected endpoints', async () => {
    setAccessToken('access-1');
    setCsrfToken('csrf-memory');
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ message: 'Logged out.' }));

    await api.post('/api/auth/logout');

    const [, init] = vi.mocked(fetch).mock.calls[0];
    expect((init!.headers as Headers).get('X-CSRF-Token')).toBe('csrf-memory');
  });

  it('falls back to the csrf_token cookie when no token is in memory', async () => {
    document.cookie = 'csrf_token=cookie-csrf; path=/';
    setAccessToken('access-1');
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ message: 'Logged out.' }));

    await api.post('/api/auth/logout');

    const [, init] = vi.mocked(fetch).mock.calls[0];
    expect((init!.headers as Headers).get('X-CSRF-Token')).toBe('cookie-csrf');
  });

  it('does not send the CSRF header to non-protected endpoints', async () => {
    setAccessToken('access-1');
    setCsrfToken('csrf-memory');
    vi.mocked(fetch).mockResolvedValue(jsonResponse([]));

    await api.get('/api/websites');

    const [, init] = vi.mocked(fetch).mock.calls[0];
    expect((init!.headers as Headers).get('X-CSRF-Token')).toBeNull();
  });

  it('never persists tokens to browser storage', async () => {
    setAccessToken('access-1');
    setCsrfToken('csrf-1');
    vi.mocked(fetch).mockResolvedValue(jsonResponse([]));

    await api.get('/api/websites');

    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it('surfaces structured backend errors as ApiError', async () => {
    setAccessToken('access-1');
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ error: { code: 'duplicate_website', message: 'URL already exists.' } }, 409),
    );

    await expect(
      api.post('/api/websites', { name: 'Acme', url: 'https://acme.com' }),
    ).rejects.toThrow(
      expect.objectContaining({
        status: 409,
        code: 'duplicate_website',
        message: 'URL already exists.',
      }),
    );
  });
});
