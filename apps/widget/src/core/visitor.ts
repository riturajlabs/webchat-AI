/**
 * Anonymous visitor identity (plan §5, ADR-004).
 *
 * A first-party cookie `wc_visitor` holds `crypto.randomUUID()`. It is NOT a
 * session cookie and is never sent to the widget API — it only keys per-visitor
 * rate limits and 24-hour session continuity. No PII. When cookies are blocked
 * the id is kept in memory for the page session and we continue (rate limiting
 * then falls back to per-widget/IP keys).
 *
 * Storage posture (ADR-003): cookies only, never `localStorage`/`sessionStorage`.
 */

export const VISITOR_COOKIE_NAME = 'wc_visitor';
export const VISITOR_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 730; // 24 months

export interface CookieAccessor {
  read(name: string): string | null;
  write(name: string, value: string): void;
}

const documentCookieAccessor: CookieAccessor = {
  read(name: string): string | null {
    const prefix = `${name}=`;
    for (const part of document.cookie.split(';')) {
      const trimmed = part.trim();
      if (trimmed.startsWith(prefix)) {
        return decodeURIComponent(trimmed.slice(prefix.length));
      }
    }
    return null;
  },
  write(name: string, value: string): void {
    const secure = window.location.protocol === 'https:' ? '; Secure' : '';
    document.cookie = `${name}=${encodeURIComponent(value)}; Path=/; SameSite=Lax; Max-Age=${VISITOR_COOKIE_MAX_AGE_SECONDS}${secure}`;
  },
};

/** Generate a random id, preferring a real UUID when the platform supports it. */
export function generateVisitorId(): string {
  const cryptoApi = globalThis.crypto;
  if (typeof cryptoApi?.randomUUID === 'function') {
    return cryptoApi.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (char) => {
    const random = (Math.random() * 16) | 0;
    const value = char === 'x' ? random : (random & 0x3) | 0x8;
    return value.toString(16);
  });
}

/**
 * Return the visitor id, creating + persisting it on first use.
 * Falls back to an in-memory id when cookies are unavailable.
 */
export function getVisitorId(accessor: CookieAccessor = documentCookieAccessor): string {
  const existing = accessor.read(VISITOR_COOKIE_NAME);
  if (existing) {
    return existing;
  }
  if (inMemoryVisitorId) {
    return inMemoryVisitorId;
  }
  const id = generateVisitorId();
  try {
    accessor.write(VISITOR_COOKIE_NAME, id);
  } catch {
    // Cookies blocked — the in-memory fallback below still returns an id.
  }
  if (accessor.read(VISITOR_COOKIE_NAME) !== id) {
    inMemoryVisitorId = id;
  }
  return id;
}

let inMemoryVisitorId: string | null = null;
