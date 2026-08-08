"""Crawl-time SSRF protection (ADR-008, docs/05 §17, 00-AI-Development-Rules §11).

Phase 3's `url_validator` blocks literal private IPs and internal hostnames at
registration time. Phase 4 adds the network-level guard the crawler actually
needs: every navigation and redirect target is re-validated here, including a
DNS resolution check that rejects hosts whose *any* A/AAAA record resolves to a
private/loopback/link-local/metadata range.

DNS rebinding mitigation: the crawler calls `validate_async` before every
navigation, redirect hop and page request, and each call re-resolves the
hostname *fresh* (never cached) so an attacker flipping DNS to a private
address mid-crawl is caught before the browser connects. The sync `resolve`
cache exists only for offline tests, which never run network I/O.
"""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse

from backend.core.errors import InvalidUrlError
from backend.utils.url_validator import ALLOWED_SCHEMES, is_blocked_ip, validate_hostname


@dataclass
class SsrFGuard:
    """Validates every URL the crawler touches before network I/O happens."""

    #: host -> validated public IP strings, cached for the *sync/test* path
    #: only. The async crawler path deliberately bypasses this (see module doc).
    _resolved: dict[str, list[str]] = field(default_factory=dict, init=False)

    def validate(self, raw_url: str) -> str:
        """Validate `raw_url` and return its canonical http(s) form.

        Raises `InvalidUrlError` for non-http(s) schemes, internal hostnames,
        literal private IPs, or hosts whose DNS resolves (even partly) into a
        blocked range.
        """
        parsed = urlparse(raw_url)
        if parsed.scheme not in ALLOWED_SCHEMES:
            raise InvalidUrlError("Only http:// and https:// URLs can be crawled.")
        hostname = parsed.hostname
        if not hostname:
            raise InvalidUrlError("The URL must include a hostname.")
        validate_hostname(hostname)
        host = hostname.lower()
        for ip_string in self.resolve(host):
            if self._is_safe_ip(ip_string):
                continue
            raise InvalidUrlError(
                f"{host} resolves to a private or internal address and is not allowed."
            )
        return raw_url

    async def validate_async(self, raw_url: str) -> str:
        """Async variant: performs a live DNS check for `validate`."""
        parsed = urlparse(raw_url)
        if parsed.scheme not in ALLOWED_SCHEMES:
            raise InvalidUrlError("Only http:// and https:// URLs can be crawled.")
        hostname = parsed.hostname
        if not hostname:
            raise InvalidUrlError("The URL must include a hostname.")
        validate_hostname(hostname)
        host = hostname.lower()
        for ip_string in await self.resolve_async(host):
            if self._is_safe_ip(ip_string):
                continue
            raise InvalidUrlError(
                f"{host} resolves to a private or internal address and is not allowed."
            )
        return raw_url

    # ----------------------------------------------------------- resolution

    def resolve(self, host: str) -> list[str]:
        """Return (cached) validated public IPs for `host` (sync/test path).

        Callers inside an event loop should use `resolve_async`; this sync
        variant exists so the SSRF rules can be tested without a loop and is
        never used by the crawler itself. The per-host cache keeps offline
        tests fast and is never trusted for real crawl decisions.
        """
        cached = self._resolved.get(host)
        if cached is not None:
            return cached
        return self._resolve_sync(host)

    async def resolve_async(self, host: str) -> list[str]:
        """Resolve `host` to public IPs using the running event loop.

        Deliberately uncached: the crawler validates every navigation, redirect
        hop and page request, so a fresh lookup here means a hostname that
        begins resolving to a private address mid-crawl is rejected before the
        browser connects (DNS rebinding). Repeated lookups are cheap because
        the OS resolver caches DNS between calls.
        """
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(
                host,
                None,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise InvalidUrlError(f"Could not resolve hostname {host}.") from exc
        ip_strings = list({str(info[4][0]) for info in infos})
        if not ip_strings:
            raise InvalidUrlError(f"Could not resolve hostname {host}.")
        return ip_strings

    def _resolve_sync(self, host: str) -> list[str]:
        try:
            infos = socket.getaddrinfo(host, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise InvalidUrlError(f"Could not resolve hostname {host}.") from exc
        ip_strings = list({str(info[4][0]) for info in infos})
        if not ip_strings:
            raise InvalidUrlError(f"Could not resolve hostname {host}.")
        self._resolved[host] = ip_strings
        return ip_strings

    @staticmethod
    def _is_safe_ip(ip_string: str) -> bool:
        try:
            address = ipaddress.ip_address(ip_string)
        except ValueError:
            return False
        # Unmap IPv4-mapped IPv6 (::ffff:192.168.0.1) before range checks.
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return not is_blocked_ip(str(address))
