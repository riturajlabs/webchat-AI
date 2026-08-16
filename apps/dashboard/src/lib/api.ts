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
 * - Every request runs with a client-side timeout (30s default, override via
 *   `timeoutMs`); a hang aborts the request and rejects with a
 *   `RequestTimeoutError` instead of leaving the request pending forever.
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

export const TIMEOUT_MESSAGE = 'Request timed out. Please try again.';

/** Default client-side request timeout in milliseconds. */
export const DEFAULT_TIMEOUT_MS = 30_000;

/**
 * A request that exceeded the client-side timeout. Distinct from backend
 * `ApiError`s (no HTTP response was ever received) and `NetworkError`s (the
 * connection failed before the timeout fired).
 */
export class RequestTimeoutError extends Error {
  readonly status = 408;
  readonly code = 'timeout';

  constructor() {
    super(TIMEOUT_MESSAGE);
    this.name = 'RequestTimeoutError';
  }
}

/** A request that failed at the network layer (DNS, CORS, dropped connection). */
export class NetworkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'NetworkError';
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

/** `RequestInit` extended with a client-side timeout override (ms). */
export interface ApiRequestInit extends RequestInit {
  timeoutMs?: number;
}

const NETWORK_ERROR_MESSAGE = 'Network request failed. Please try again.';

/**
 * `fetch` wrapped with a client-side timeout. The internal timeout signal is
 * merged with any caller-provided `signal` — whichever fires first wins. The
 * timer is always cleared once the request settles (no leaked timers) and
 * failures are classified as `RequestTimeoutError` (timeout), `NetworkError`
 * (connection failure), or rethrown unchanged (caller cancellation).
 */
async function fetchWithTimeout(url: string, init: ApiRequestInit): Promise<Response> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, signal: callerSignal, ...fetchInit } = init;
  const controller = new AbortController();
  let timedOut = false;
  let callerAborted = false;

  const onCallerAbort = (): void => {
    callerAborted = true;
    controller.abort();
  };
  if (callerSignal) {
    if (callerSignal.aborted) {
      callerAborted = true;
      controller.abort();
    } else {
      callerSignal.addEventListener('abort', onCallerAbort, { once: true });
    }
  }

  let timer: ReturnType<typeof setTimeout> | undefined;
  if (timeoutMs > 0) {
    timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
  }

  try {
    return await fetch(url, { ...fetchInit, signal: controller.signal });
  } catch (error) {
    if (timedOut) {
      throw new RequestTimeoutError();
    }
    if (callerAborted) {
      throw error;
    }
    throw new NetworkError(error instanceof Error ? error.message : NETWORK_ERROR_MESSAGE);
  } finally {
    if (timer !== undefined) {
      clearTimeout(timer);
    }
    if (callerSignal) {
      callerSignal.removeEventListener('abort', onCallerAbort);
    }
  }
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
    const response = await fetchWithTimeout(`${API_BASE_URL}/api/auth/refresh`, {
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

export async function request<T>(
  path: string,
  init: ApiRequestInit = {},
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

  const response = await fetchWithTimeout(`${API_BASE_URL}${path}`, {
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
