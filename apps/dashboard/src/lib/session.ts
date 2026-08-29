/**
 * In-memory session token holder.
 *
 * ADR-003 (Phase 7 corrections): tokens are never persisted to
 * localStorage/sessionStorage. Access and CSRF tokens live only in JS
 * memory to avoid XSS token theft. The refresh token is an httpOnly cookie
 * managed entirely by the browser and is never read from JavaScript.
 *
 * Memory is intentionally lost on a full page reload; AuthProvider performs
 * a silent refresh via the httpOnly cookie to restore the session.
 *
 * The access token is also mirrored to a non-httpOnly cookie
 * (`sse_access_token`) so that SSE connections (which cannot send custom
 * headers) can authenticate via cookies. This cookie is only used as a
 * fallback for SSE and is cleared on logout.
 */
let accessToken: string | null = null;
let csrfToken: string | null = null;

const SSE_ACCESS_COOKIE = 'sse_access_token';

const CSRF_COOKIE_NAME = 'csrf_token';

function setCookie(name: string, value: string, maxAgeSeconds: number): void {
  if (typeof document === 'undefined') return;
  const isSecure = window.location.protocol === 'https:';
  document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=${maxAgeSeconds}; SameSite=Lax${isSecure ? '; Secure' : ''}`;
}

function deleteCookie(name: string): void {
  if (typeof document === 'undefined') return;
  document.cookie = `${name}=; path=/; max-age=0; SameSite=Lax`;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
  if (token) {
    // Mirror to cookie for SSE auth (15 min TTL, matches access token lifetime).
    setCookie(SSE_ACCESS_COOKIE, token, 15 * 60);
  } else {
    deleteCookie(SSE_ACCESS_COOKIE);
  }
}

export function getAccessToken(): string | null {
  return accessToken;
}

/**
 * Whether a session cookie is present in the browser.
 *
 * The backend mirror of the refresh session — the non-httpOnly `csrf_token`
 * double-submit cookie — is set alongside the httpOnly refresh cookie with the
 * same 30-day lifetime, so its presence tells us a (possibly expired) refresh
 * session exists without exposing the actual token to JavaScript. Used to skip
 * the silent-refresh network call entirely for anonymous visitors.
 */
export function hasSessionCookie(): boolean {
  if (typeof document === 'undefined') {
    return false;
  }
  return document.cookie.split(';').some((part) => part.trim().startsWith(`${CSRF_COOKIE_NAME}=`));
}

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function getCsrfToken(): string | null {
  return csrfToken;
}

export function clearSession(): void {
  accessToken = null;
  csrfToken = null;
  deleteCookie(SSE_ACCESS_COOKIE);
}
