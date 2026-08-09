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
 */
let accessToken: string | null = null;
let csrfToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
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
}
