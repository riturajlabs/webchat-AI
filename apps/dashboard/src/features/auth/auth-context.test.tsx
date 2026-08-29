import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '@/lib/api';
import { getAccessToken, getCsrfToken, setAccessToken } from '@/lib/session';

import { AuthProvider, useAuth } from './auth-context';
import type { AuthResponse, RefreshResponse, UserOut } from './types';

vi.mock('@/lib/api', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    code: string;

    constructor(code: string, message: string) {
      super(message);
      this.code = code;
    }
  },
}));

const mockedGet = vi.mocked(api.get);
const mockedPost = vi.mocked(api.post);

const USER: UserOut = {
  id: 'user-1',
  name: 'Jane Doe',
  email: 'jane@example.com',
  role: 'owner',
  email_verified: true,
  status: 'active',
  tenant_id: 'tenant-1',
  created_at: '2026-08-01T00:00:00Z',
};

function wrapper({ children }: { children: ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}

function setSessionCookie(): void {
  document.cookie = 'csrf_token=session-csrf; path=/';
}

function clearSessionCookie(): void {
  document.cookie = 'csrf_token=; max-age=0; path=/';
}

describe('AuthProvider', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearSessionCookie();
    // By default the initial silent refresh has no session cookie -> skipped.
    mockedPost.mockRejectedValue(new Error('no session cookie'));
    mockedGet.mockRejectedValue(new Error('no token'));
  });

  afterEach(() => {
    vi.clearAllMocks();
    clearSessionCookie();
    // session tokens are module state; reset by importing clearSession in each test
  });

  it('starts unauthenticated without refreshing when there is no session cookie', async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.user).toBeNull();
    expect(mockedPost).not.toHaveBeenCalled();
  });

  it('restores the session via the refresh endpoint when a session cookie exists', async () => {
    setSessionCookie();
    const refreshResponse: RefreshResponse = {
      access_token: 'access-after-refresh',
      token_type: 'bearer',
      expires_in: 3600,
      user: USER,
    };
    mockedPost.mockResolvedValue(refreshResponse);

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.status).toBe('ready'));

    expect(mockedPost).toHaveBeenCalledWith('/api/auth/refresh');
    expect(result.current.user).toEqual(USER);
    expect(result.current.isAuthenticated).toBe(true);
    expect(getAccessToken()).toBe('access-after-refresh');
  });

  it('restores the user from /api/auth/me when an access token is in memory', async () => {
    setAccessToken('existing-access');
    mockedGet.mockResolvedValue(USER);

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.status).toBe('ready'));

    expect(mockedGet).toHaveBeenCalledWith('/api/auth/me');
    expect(mockedPost).not.toHaveBeenCalled();
    expect(result.current.user).toEqual(USER);
    expect(result.current.isAuthenticated).toBe(true);
  });

  it('does not attempt a second refresh when /auth/me fails with an in-memory token (R1)', async () => {
    setAccessToken('expired-access');
    // The API client is responsible for the single internal refresh on a 401;
    // AuthProvider must not call the refresh endpoint again on failure.
    mockedGet.mockRejectedValue(new Error('token expired'));

    const { result } = renderHook(() => useAuth(), { wrapper });

    await waitFor(() => expect(result.current.status).toBe('ready'));

    expect(mockedGet).toHaveBeenCalledWith('/api/auth/me');
    expect(mockedPost).not.toHaveBeenCalled();
    expect(result.current.user).toBeNull();
    expect(result.current.isAuthenticated).toBe(false);
  });

  it('logs in with email/password and stores tokens in memory', async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe('ready'));

    mockedPost.mockResolvedValueOnce({
      access_token: 'access-1',
      token_type: 'bearer',
      expires_in: 3600,
      csrf_token: 'csrf-1',
      user: USER,
    } satisfies AuthResponse);

    await act(async () => {
      await result.current.login('jane@example.com', 'password123');
    });

    expect(mockedPost).toHaveBeenCalledWith('/api/auth/login', {
      email: 'jane@example.com',
      password: 'password123',
    });
    expect(result.current.user).toEqual(USER);
    expect(result.current.isAuthenticated).toBe(true);
    expect(getAccessToken()).toBe('access-1');
    expect(getCsrfToken()).toBe('csrf-1');
  });

  it('clears memory tokens and user on logout', async () => {
    mockedPost
      .mockResolvedValueOnce({
        access_token: 'access-1',
        token_type: 'bearer',
        expires_in: 3600,
        user: USER,
      })
      .mockResolvedValueOnce({ message: 'Logged out.' });

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe('ready'));

    setAccessToken('access-1');

    await act(async () => {
      await result.current.logout();
    });

    expect(mockedPost).toHaveBeenCalledWith('/api/auth/logout');
    expect(result.current.user).toBeNull();
    expect(result.current.isAuthenticated).toBe(false);
    expect(getAccessToken()).toBeNull();
    expect(getCsrfToken()).toBeNull();
  });

  it('clears the session even when the logout API call fails', async () => {
    mockedPost.mockRejectedValueOnce(new Error('logout failed'));

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe('ready'));

    await act(async () => {
      await result.current.logout().catch(() => {
        // logout() re-throws after clearing the session; that is expected.
      });
    });

    expect(result.current.isAuthenticated).toBe(false);
    expect(getAccessToken()).toBeNull();
  });
});
