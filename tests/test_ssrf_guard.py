"""Unit tests for the crawl-time SSRF guard (Phase 4, ADR-008).

DNS is resolved through the guard's cache so tests can inject both safe and
private resolutions without touching the network.
"""

import pytest
from backend.core.errors import InvalidUrlError
from backend.services.ingestion import SsrFGuard

_PUBLIC_IPS = ["93.184.216.34"]


def _guard_with_resolution(monkeypatch, ips: list[str]) -> SsrFGuard:
    guard = SsrFGuard()
    monkeypatch.setattr(guard, "resolve", lambda host: ips)
    return guard


def test_accepts_public_url(monkeypatch) -> None:
    guard = _guard_with_resolution(monkeypatch, _PUBLIC_IPS)
    assert guard.validate("https://example.com/about") == "https://example.com/about"


def test_accepts_http_and_https(monkeypatch) -> None:
    guard = _guard_with_resolution(monkeypatch, _PUBLIC_IPS)
    assert guard.validate("http://example.com/") == "http://example.com/"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://x.example/f", "javascript:1"])
def test_rejects_non_http_schemes(url: str, monkeypatch) -> None:
    guard = _guard_with_resolution(monkeypatch, _PUBLIC_IPS)
    with pytest.raises(InvalidUrlError):
        guard.validate(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/",
        "https://10.0.0.5/",
        "https://172.16.9.9/",
        "https://192.168.1.10/",
        "https://169.254.169.254/latest/meta-data",
        "https://localhost/",
        "https://intra.corp.internal/",
    ],
)
def test_rejects_literal_private_and_internal_targets(url: str, monkeypatch) -> None:
    guard = _guard_with_resolution(monkeypatch, _PUBLIC_IPS)
    with pytest.raises(InvalidUrlError):
        guard.validate(url)


@pytest.mark.parametrize(
    "ips",
    [
        ["10.0.0.1"],
        ["93.184.216.34", "192.168.0.1"],  # any single private record blocks the host
        ["127.0.0.1"],
        ["169.254.169.254"],
        ["::ffff:192.168.1.1"],  # IPv4-mapped IPv6 must be unmapped before the check
        ["fe80::1"],
    ],
)
def test_rejects_host_resolving_to_private_ip(ips: list[str], monkeypatch) -> None:
    guard = _guard_with_resolution(monkeypatch, ips)
    with pytest.raises(InvalidUrlError):
        guard.validate("https://example.com/")


def test_rejects_unresolvable_host(monkeypatch) -> None:
    guard = SsrFGuard()

    def boom(host: str) -> list[str]:
        raise InvalidUrlError(f"Could not resolve hostname {host}.")

    monkeypatch.setattr(guard, "resolve", boom)
    with pytest.raises(InvalidUrlError):
        guard.validate("https://no-such-host.invalid/")


def test_resolution_is_cached_per_job(monkeypatch) -> None:
    """A host resolved once keeps its answer for the job (rebinding guard)."""
    guard = SsrFGuard()
    calls: list[str] = []

    def fake_resolve(host: str) -> list[str]:
        calls.append(host)
        guard._resolved[host] = _PUBLIC_IPS
        return _PUBLIC_IPS

    monkeypatch.setattr(guard, "_resolve_sync", fake_resolve)
    guard.validate("https://example.com/")
    guard.validate("https://example.com/page")
    assert calls == ["example.com"]


def test_async_validate_blocks_private_dns(monkeypatch) -> None:
    async def run() -> None:
        guard = SsrFGuard()

        async def fake_resolve(host: str) -> list[str]:
            return ["10.0.0.1"]

        monkeypatch.setattr(guard, "resolve_async", fake_resolve)
        with pytest.raises(InvalidUrlError):
            await guard.validate_async("https://example.com/")

    import asyncio

    asyncio.run(run())


def test_async_resolution_is_fresh_each_call_not_cached(monkeypatch) -> None:
    """Every async validation re-resolves DNS (DNS rebinding guard).

    A previously-safe resolution is never trusted: even a poisoned cache entry
    must be ignored and the hostname resolved again before the browser fetches.
    """
    import asyncio
    import socket

    class _Loop:
        def __init__(self) -> None:
            self.calls = 0

        async def getaddrinfo(self, host: str, port, **kwargs):
            self.calls += 1
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80))
                for ip in _PUBLIC_IPS
            ]

    loop = _Loop()
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: loop)
    guard = SsrFGuard()
    # A private result cached by the sync/test path must not short-circuit the
    # fresh async lookup.
    guard._resolved["example.com"] = ["10.0.0.1"]

    async def run() -> None:
        await guard.validate_async("https://example.com/")
        await guard.validate_async("https://example.com/page")

    asyncio.run(run())
    assert loop.calls == 2
