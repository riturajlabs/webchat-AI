"""SSRF-safe URL validation for tenant-submitted website URLs.

This is the Phase 3 pre-check (ADR-008): scheme whitelist plus syntactic and
literal-IP guards. DNS resolution is intentionally *not* performed here so
request handlers never block on the network; the crawler (Phase 4) re-checks
every resolved IP against the same private-range rules (00-AI-Development-Rules
§11, scraper security).
"""

import ipaddress
import re
from urllib.parse import urljoin, urlparse

from backend.core.errors import InvalidUrlError

ALLOWED_SCHEMES = {"http", "https"}

# Hostnames that are never legitimate crawl targets (loopback/private mDNS).
_BLOCKED_HOSTNAMES = {
    "localhost",
    "ip6-localhost",
    "ip6-loopback",
    "metadata.google.internal",
    "metadata",
}
_BLOCKED_HOSTNAME_SUFFIXES = (".localhost", ".local", ".internal", ".localdomain", ".lan")
_BLOCKED_HOSTNAME_PREFIXES = ("_", "-")

# Literal-IP families that must never be fetched (docs/05 §17, ADR-004).
_PRIVATE_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("64:ff9b:1::/48"),
)

_VALID_HOSTNAME_CHARS = re.compile(r"^[a-z0-9.-]+$")
_MAX_URL_LENGTH = 2048


def _is_blocked_ip(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(address in network for network in _PRIVATE_NETWORKS)


def is_blocked_ip(host: str) -> bool:
    """Public guard used by the Phase 4 crawler SSRF checks (ADR-008)."""
    return _is_blocked_ip(host)


def _reject_bad_hostname(host: str | None) -> None:
    if not host:
        raise InvalidUrlError("The URL must include a hostname.")
    lowered = host.lower()
    if lowered in _BLOCKED_HOSTNAMES:
        raise InvalidUrlError("This hostname is not allowed.")
    if lowered.startswith(_BLOCKED_HOSTNAME_PREFIXES) or lowered.endswith(
        _BLOCKED_HOSTNAME_SUFFIXES
    ):
        raise InvalidUrlError("This hostname is not allowed.")
    if _is_blocked_ip(lowered):
        raise InvalidUrlError("Private and internal IP addresses are not allowed.")


def normalize_url(raw_url: str) -> str:
    """Validate a website URL and return its canonical form.

    Raises `InvalidUrlError` for missing/invalid schemes, unsupported schemes
    (`file://`, `ftp://`, ...), embedded credentials, private/loopback IP
    literals, internal hostnames, and malformed hosts.
    """
    candidate = (raw_url or "").strip()
    if not candidate:
        raise InvalidUrlError("A URL is required.")
    if len(candidate) > _MAX_URL_LENGTH:
        raise InvalidUrlError("The URL is too long.")

    parsed = urlparse(candidate)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise InvalidUrlError("Only http:// and https:// URLs are allowed.")
    if not parsed.netloc:
        raise InvalidUrlError("The URL must include a hostname.")
    if parsed.username or parsed.password:
        raise InvalidUrlError("URLs with embedded credentials are not allowed.")

    hostname = parsed.hostname
    if not hostname:
        raise InvalidUrlError("The URL must include a hostname.")
    _reject_bad_hostname(hostname)

    host = hostname.lower()
    # Reject octet-style IPs with leading zeros that ipaddress cannot parse.
    if not _VALID_HOSTNAME_CHARS.match(host):
        raise InvalidUrlError("The URL hostname contains invalid characters.")
    if _is_blocked_ip(host):
        raise InvalidUrlError("Private and internal IP addresses are not allowed.")

    default_port = {"http": 80, "https": 443}[parsed.scheme]
    try:
        port = parsed.port
    except ValueError:
        raise InvalidUrlError("The URL contains an invalid port.") from None
    if port is not None and port != default_port:
        # Non-default ports are accepted (legit self-hosting), but never
        # the canonical port on private infrastructure, which is already blocked.
        netloc = f"{host}:{parsed.port}"
    else:
        netloc = host

    path = parsed.path or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    return f"{parsed.scheme}://{netloc}{path}{query}{fragment}"


def validate_hostname(hostname: str) -> None:
    """Reject internal/private hostnames (Phase 4 SSRF pre-check, ADR-008).

    The crawler applies this to *every* navigation and redirect target before
    any network I/O; DNS resolution is validated separately in
    `backend.services.ingestion.ssrf_guard`.
    """
    lowered = hostname.lower()
    if not lowered:
        raise InvalidUrlError("The URL must include a hostname.")
    if not _VALID_HOSTNAME_CHARS.match(lowered):
        raise InvalidUrlError("The URL hostname contains invalid characters.")
    _reject_bad_hostname(lowered)
    if is_blocked_ip(lowered):
        raise InvalidUrlError("Private and internal IP addresses are not allowed.")


# Tracking parameters stripped from crawl URLs to avoid duplicate pages that
# differ only in campaign attribution (docs/03 crawl rules, Phase 4).
_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "gclsrc",
    "dclid",
    "msclkid",
    "ref",
    "source",
    "mc_cid",
    "mc_eid",
}


def normalize_crawl_url(raw_url: str, base_url: str) -> str | None:
    """Resolve `raw_url` against `base_url` and return a crawl-safe URL.

    Fragments and tracking parameters are removed (two URLs that differ only by
    those are the same page). Returns `None` when the result is not an http(s)
    URL (mailto:, tel:, javascript:, ...) or carries a non-default scheme.
    """
    joined = urljoin(base_url, (raw_url or "").strip())
    parsed = urlparse(joined)
    if parsed.scheme not in ALLOWED_SCHEMES:
        return None
    if not parsed.hostname:
        return None

    query = "&".join(
        part
        for part in parsed.query.split("&")
        if part and part.split("=", 1)[0].lower() not in _TRACKING_PARAMS
    )
    path = parsed.path or "/"
    url = f"{parsed.scheme}://{parsed.netloc}{path}"
    if query:
        url = f"{url}?{query}"
    return url
