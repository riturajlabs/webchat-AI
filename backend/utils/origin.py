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
  * the literal `*` entry allows every origin
"""

from urllib.parse import urlsplit

# Upper bound on a single hostname entry (DNS FQDN + wildcard prefix).
_MAX_HOST_LENGTH = 253

_INVALID_HOST_CHARS = set(" /\\?#@:")


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
    scheme, port) or that exceed the DNS hostname length.
    """
    value = (entry or "").strip().lower().rstrip(".")
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
    return f"*.{value}" if wildcard else value


def normalize_allowed_domains(allowed_domains: list[str]) -> list[str]:
    """Validate and normalize an allowlist, dropping invalid entries."""
    return [
        entry
        for value in allowed_domains
        if (entry := _normalize_entry(value)) is not None
    ]


def origin_allowed(origin: str | None, allowed_domains: list[str]) -> bool:
    """Return True when the request origin is allowed to embed the widget.

    `None` (no `Origin` header) is not a browser embed and is allowed; it is
    guarded by the caller's own policy. An empty allowlist permits any origin
    (backward compatible default). A `null`/unparsable origin is rejected as
    soon as the allowlist is non-empty.
    """
    if origin is None:
        return True
    normalized = normalize_allowed_domains(allowed_domains)
    if not normalized:
        return True
    if "*" in normalized:
        return True
    host = origin_hostname(origin)
    if host is None:
        return False
    for entry in normalized:
        if entry == host:
            return True
        if entry.startswith("*.") and (
            host == entry[2:] or host.endswith(f".{entry[2:]}")
        ):
            return True
    return False
