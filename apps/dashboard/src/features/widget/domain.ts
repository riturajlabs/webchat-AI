/**
 * Embed-origin allowlist helpers for the widget builder.
 *
 * Mirrors the backend rules in `backend/utils/origin.py` so the dashboard
 * shows the tenant the exact value that will be stored (hostnames only,
 * `*.`-wildcards allowed, no scheme/port/path).
 */

/** Upper bound on a single hostname entry (DNS FQDN + wildcard prefix). */
export const MAX_DOMAIN_LENGTH = 253;

/** Maximum number of entries in the allowlist (backend `MAX_ALLOWED_DOMAINS`). */
export const MAX_ALLOWED_DOMAINS = 50;

const INVALID_CHARS = /[ /\\?#@:]/;

/**
 * Validate and normalize a single allowlist entry.
 *
 * Returns the normalized hostname (`*.` prefix preserved) or `null` when the
 * entry cannot be a hostname: empty, too long, contains a scheme/port/path
 * character, or has a malformed label (empty, leading/trailing dash).
 */
export function normalizeDomain(entry: string): string | null {
  const value = entry.trim().toLowerCase().replace(/\.+$/, '');
  const wildcard = value.startsWith('*.');
  const bare = wildcard ? value.slice(2) : value;

  if (!bare) {
    return null;
  }
  if (bare.length > MAX_DOMAIN_LENGTH) {
    return null;
  }
  if (INVALID_CHARS.test(bare)) {
    return null;
  }
  for (const part of bare.split('.')) {
    if (!part || part.startsWith('-') || part.endsWith('-')) {
      return null;
    }
  }
  return wildcard ? `*.${bare}` : bare;
}
