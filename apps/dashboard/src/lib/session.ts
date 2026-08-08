/**
 * In-memory access-token holder.
 *
 * ADR-003: access tokens live in JS memory only - never in
 * localStorage/sessionStorage - to avoid XSS token theft. The login flow
 * (Phase 2 frontend) calls `setAccessToken`; a full page reload silently
 * refreshes via the httpOnly cookie before retrying.
 */
let accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}
