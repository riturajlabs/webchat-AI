/**
 * Embed-origin allowlist helpers for the widget builder.
 *
 * Mirrors the backend rules in `backend/utils/origin.py` so the dashboard
 * shows the tenant the exact value that will be stored (hostnames only,
 * `*.`-wildcards allowed, no scheme/port/path).
 *
 * The dashboard additionally accepts full http(s) URLs and reduces them to
 * their hostname, so `https://www.example.com/dashboard` is saved as
 * `www.example.com` - the backend PATCH endpoint only accepts the normalized
 * bare hostname.
 */

/** Upper bound on a single hostname entry (DNS FQDN + wildcard prefix). */
export const MAX_DOMAIN_LENGTH = 253;

/** Maximum number of entries in the allowlist (backend `MAX_ALLOWED_DOMAINS`). */
export const MAX_ALLOWED_DOMAINS = 50;

/** The single label host that is never a typo. */
export const LOOPBACK_HOSTS = ['localhost', '127.0.0.1'];

const INVALID_CHARS = /[ /\\?#@:]/;

/**
 * Strict hostname check shared by all input shapes. Accepts `localhost` as the
 * only single-label hostname (a bare `example` is a typo), loopback IPs, and
 * dotted FQDNs. Rejects schemes, ports, paths and malformed labels.
 */
function strictHostname(host: string): string | null {
  const value = host.trim().toLowerCase().replace(/\.+$/, '');
  if (!value) {
    return null;
  }
  if (value.length > MAX_DOMAIN_LENGTH) {
    return null;
  }
  if (INVALID_CHARS.test(value)) {
    return null;
  }
  const parts = value.split('.');
  if (parts.length === 1 && value !== 'localhost') {
    return null;
  }
  for (const part of parts) {
    if (!part || part.startsWith('-') || part.endsWith('-')) {
      return null;
    }
  }
  return value;
}

/**
 * Validate and normalize a single allowlist entry.
 *
 * Returns the normalized hostname (`*.` prefix preserved) or `null` when the
 * entry cannot be saved. Accepts:
 *   * bare hostnames: `example.com`, `www.example.com`, `localhost`,
 *     `127.0.0.1` (a bare single-label hostname other than `localhost` is
 *     rejected as a typo);
 *   * wildcards: `*.example.com` (requires at least one label, so
 *     `*.localhost` is rejected);
 *   * the literal `*` (open embedding opt-in) and the legacy `*.`;
 *   * full http(s) URLs, which are reduced to their hostname.
 */
export function normalizeDomain(entry: string): string | null {
  const value = entry.trim().toLowerCase().replace(/\.+$/, '');
  if (!value) {
    return null;
  }
  if (value === '*') {
    return '*';
  }
  if (value.startsWith('*.')) {
    const rest = value.slice(2);
    if (!rest) {
      // Legacy wildcard shorthand → open embedding.
      return '*';
    }
    const host = strictHostname(rest);
    if (host === null || host.split('.').length === 1) {
      return null;
    }
    return `*.${host}`;
  }
  if (value.includes('://')) {
    let url: URL;
    try {
      url = new URL(value);
    } catch {
      return null;
    }
    if (url.protocol !== 'http:' && url.protocol !== 'https:') {
      return null;
    }
    return strictHostname(url.hostname);
  }
  return strictHostname(value);
}
