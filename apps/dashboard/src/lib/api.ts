/**
 * Typed API client for the WebChat AI backend.
 *
 * The dashboard calls the backend directly from the browser (CORS is enabled
 * for the dashboard origin). `NEXT_PUBLIC_API_URL` overrides the default
 * `http://localhost:8000` for deployed environments.
 *
 * Authentication handling (ADR-003, Phase 7):
 * - Bearer access token is attached from memory only.
 * - CSRF-protected endpoints (/auth/refresh, /auth/logout) send the
 *   X-CSRF-Token double-submit header from memory, falling back to the
 *   non-httpOnly csrf_token cookie.
 * - A 401 on an authenticated request triggers a single silent refresh via
 *   the httpOnly refresh cookie, then retries the original request once.
 *   If the refresh fails the session is cleared and the user is redirected
 *   to /login. The retry flag prevents infinite refresh loops.
 */

import {
  clearSession,
  getAccessToken,
  getCsrfToken,
  setAccessToken,
  setCsrfToken,
} from '@/lib/session';

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

const CSRF_COOKIE_NAME = 'csrf_token';

const CSRF_PROTECTED_PATHS = new Set(['/api/auth/refresh', '/api/auth/logout']);

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;

  constructor(status: number, code: string | undefined, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

interface ApiErrorPayload {
  error?: { code?: string; message?: string };
}

function readCsrfCookie(): string | null {
  if (typeof document === 'undefined') {
    return null;
  }
  const prefix = `${CSRF_COOKIE_NAME}=`;
  for (const part of document.cookie.split('; ')) {
    if (part.startsWith(prefix)) {
      return part.slice(prefix.length) || null;
    }
  }
  return null;
}

function redirectToLogin(): void {
  if (typeof window === 'undefined') {
    return;
  }
  const current = window.location.pathname + window.location.search;
  if (window.location.pathname === '/login') {
    return;
  }
  const redirect = encodeURIComponent(current);
  window.location.assign(`/login?redirect=${redirect}`);
}

async function refreshSession(): Promise<boolean> {
  const csrf = getCsrfToken() ?? readCsrfCookie();
  const headers = new Headers();
  if (csrf) {
    headers.set('X-CSRF-Token', csrf);
  }
  try {
    const response = await fetch(`${API_BASE_URL}/api/auth/refresh`, {
      method: 'POST',
      headers,
      credentials: 'include',
    });
    if (!response.ok) {
      return false;
    }
    const payload = (await response.json()) as {
      access_token?: string;
      csrf_token?: string;
    };
    if (typeof payload.access_token !== 'string') {
      return false;
    }
    setAccessToken(payload.access_token);
    setCsrfToken(payload.csrf_token ?? readCsrfCookie());
    return true;
  } catch {
    return false;
  }
}

interface RequestOptions {
  retry?: boolean;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  { retry = true }: RequestOptions = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getAccessToken();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (CSRF_PROTECTED_PATHS.has(path)) {
    const csrf = getCsrfToken() ?? readCsrfCookie();
    if (csrf) {
      headers.set('X-CSRF-Token', csrf);
    }
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
    credentials: 'include',
  });

  if (response.status === 401 && token && retry) {
    const refreshed = await refreshSession();
    if (refreshed) {
      return request<T>(path, init, { retry: false });
    }
    clearSession();
    redirectToLogin();
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const error = (payload as ApiErrorPayload | null)?.error;
    throw new ApiError(
      response.status,
      error?.code,
      error?.message ?? `Request failed (${response.status})`,
    );
  }
  return payload as T;
}

export const api = {
  get<T>(path: string): Promise<T> {
    return request<T>(path);
  },
  post<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, {
      method: 'POST',
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  },
  patch<T>(path: string, body: unknown): Promise<T> {
    return request<T>(path, { method: 'PATCH', body: JSON.stringify(body) });
  },
  delete<T>(path: string): Promise<T> {
    return request<T>(path, { method: 'DELETE' });
  },
};
