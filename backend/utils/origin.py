"""Widget embed-origin allowlist helpers (production hardening).

A widget's `allowed_domains` is an optional per-widget list of hostnames that
are permitted to embed it. Browsers send the embedding page's origin on every
cross-origin widget request, so the backend can enforce the allowlist
application-level (the public widget surface answers `ACAO: *`, which cannot
express an allowlist). Requests without an `Origin` header (curl, server-to-
server) are not browser embeds and are intentionally not restricted here -
the allowlist guards *embedding*, not API access.

Matching rules:
  * port and scheme are ignored - `https://acme.example:5500` matches `acme.example`
  * hostnames are case-insensitive and trailing dots are normalized away
  * a bare entry matches exactly one hostname
  * `*.acme.example` matches `acme.example` and any subdomain
  * the literal `*` entry allows every origin (explicit opt-in)
  * a bare single-label hostname is only valid for the loopback host
    (`localhost`); typo hosts like `example` are rejected
  * an empty allowlist permits no browser origin - the caller raises
    `WIDGET_DOMAIN_NOT_CONFIGURED` so tenants must configure an allowlist
    (or opt into open embedding with `*`)
"""

from urllib.parse import urlsplit

# Upper bound on a single hostname entry (DNS FQDN + wildcard prefix).
_MAX_HOST_LENGTH = 253

_INVALID_HOST_CHARS = set(" /\\?#@:")

# Loopback host accepted without a suffix (local development).
_LOOPBACK_HOSTS = {"localhost"}


def origin_hostname(origin: str) -> str | None:
    """Extract the normalized lowercase hostname from an `Origin` header.

    Returns `None` for `null` origins (sandboxed iframes, `file://` pages),
    non-http(s) schemes, and malformed origins - none of which are a
    legitimate widget embed.
    """
    candidate = (origin or "").strip()
    if not candidate or candidate.lower() == "null":
        return None
    try:
        parsed = urlsplit(candidate if "://" in candidate else f"https://{candidate}")
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    host = parsed.hostname
    if not host:
        return None
    host = host.lower().rstrip(".")
    if not host:
        return None
    if any(part for part in host.split(".") if not part):
        return None
    if any(char in _INVALID_HOST_CHARS or char.isspace() for char in host):
        return None
    return host


def _normalize_entry(entry: str) -> str | None:
    """Normalize a single allowlist entry (`*.` prefix preserved).

    Rejects entries that contain characters a hostname cannot (path, query,
    scheme, port) or that exceed the DNS hostname length. A bare single-label
    entry is only valid for the loopback host; the literal `*` (open embed)
    and `*.`-prefixed wildcards over a real suffix are the only exceptions.
    """
    value = (entry or "").strip().lower().rstrip(".")
    if not value:
        return None
    if value == "*":
        # Explicit open-embed opt-in.
        return "*"
    wildcard = value.startswith("*.")
    if wildcard:
        value = value[2:]
    if not value:
        return None
    if len(value) > _MAX_HOST_LENGTH:
        return None
    if any(char in _INVALID_HOST_CHARS for char in value):
        return None
    if any(not part or part.startswith("-") or part.endswith("-") for part in value.split(".")):
        return None
    if "." not in value:
        # Single-label hosts: only the loopback host is a legitimate embed
        # origin; anything else is a typo (`example`) or a wildcard over a
        # suffix that cannot exist (`*.localhost`).
        if wildcard or value not in _LOOPBACK_HOSTS:
            return None
    return f"*.{value}" if wildcard else value


def normalize_allowed_domains(allowed_domains: list[str]) -> list[str]:
    """Validate and normalize an allowlist, dropping invalid entries.

    Strict: bare hostnames (plus `*.`-wildcards and the `*` open-embed
    opt-in) only. Use `normalize_domain_entry` when the input may be a full
    URL (dashboard input / data migration).
    """
    return [entry for value in allowed_domains if (entry := _normalize_entry(value)) is not None]


def normalize_domain_entry(entry: str) -> str | None:
    """URL-aware normalization of a single domain input.

    Bare hostnames and `*.`-wildcards are normalized exactly like
    `normalize_allowed_domains`; only inputs carrying a scheme (`http://` /
    `https://`, e.g. `https://www.example.com/path` or
    `http://localhost:3000`) are reduced to their hostname first. Scheme-less
    inputs that are not a bare hostname (`localhost:3000`, `example.com/path`)
    are rejected, matching the dashboard validation.

    Used by the dashboard input layer and `scripts/migrate-allowed-domains.py`
    so legacy entries like `http://localhost:3000` become `localhost` instead
    of being silently dropped.
    """
    cleaned = (entry or "").strip().lower()
    if not cleaned:
        return None
    if "://" in cleaned:
        host = origin_hostname(cleaned)
        return _normalize_entry(host) if host is not None else None
    return _normalize_entry(cleaned)


def origin_allowed(origin: str | None, allowed_domains: list[str]) -> bool:
    """Return True when the request origin is allowed to embed the widget.

    `None` (no `Origin` header) is not a browser embed and is allowed; it is
    guarded by the caller's own policy. An empty allowlist permits no browser
    origin (the caller surfaces `WIDGET_DOMAIN_NOT_CONFIGURED`); the literal
    `*` entry opts into open embedding. A `null`/unparsable origin is always
    rejected once the allowlist is non-empty.
    """
    if origin is None:
        return True
    normalized = normalize_allowed_domains(allowed_domains)
    if "*" in normalized:
        return True
    host = origin_hostname(origin)
    if host is None:
        return False
    if not normalized:
        return False
    for entry in normalized:
        if entry == host:
            return True
        if entry.startswith("*.") and (host == entry[2:] or host.endswith(f".{entry[2:]}")):
            return True
    return False
