"""Unit tests for the SSRF-safe URL validator (Phase 3, backend/utils)."""

import pytest
from backend.core.errors import InvalidUrlError
from backend.utils.url_validator import (
    normalize_crawl_url,
    normalize_url,
    validate_hostname,
)


def test_accepts_public_https_url() -> None:
    assert normalize_url("https://example.com") == "https://example.com/"


def test_accepts_public_http_url() -> None:
    assert normalize_url("http://example.com") == "http://example.com/"


def test_accepts_subdomain_and_path() -> None:
    assert (
        normalize_url("  https://www.example.com/about?q=1  ")
        == "https://www.example.com/about?q=1"
    )


def test_normalizes_default_port_away() -> None:
    assert normalize_url("https://example.com:443/") == "https://example.com/"
    assert normalize_url("http://example.com:80/") == "http://example.com/"


def test_keeps_custom_port() -> None:
    assert normalize_url("https://example.com:8443/") == "https://example.com:8443/"


def test_rejects_empty_url() -> None:
    with pytest.raises(InvalidUrlError):
        normalize_url("   ")


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/file",
        "javascript:alert(1)",
        "example.com",
        "www.example.com",
    ],
)
def test_rejects_invalid_schemes(url: str) -> None:
    with pytest.raises(InvalidUrlError):
        normalize_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost",
        "http://localhost:8080/",
        "http://127.0.0.1",
        "http://127.0.0.1:8000/admin",
        "http://10.0.0.5",
        "http://172.16.0.1",
        "http://192.168.1.10",
        "http://169.254.169.254/latest/meta-data",
        "http://0.0.0.0",
        "http://[::1]",
        "http://[fc00::1]",
        "http://[fe80::1]",
    ],
)
def test_rejects_private_and_loopback_targets(url: str) -> None:
    with pytest.raises(InvalidUrlError):
        normalize_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://user:pass@example.com",
        "http://user@example.com",
    ],
)
def test_rejects_embedded_credentials(url: str) -> None:
    with pytest.raises(InvalidUrlError):
        normalize_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://mysite.local",
        "http://mysite.localhost",
        "http://internal-service.internal",
        "http://printer.lan",
    ],
)
def test_rejects_internal_hostnames(url: str) -> None:
    with pytest.raises(InvalidUrlError):
        normalize_url(url)


def test_rejects_url_without_hostname() -> None:
    with pytest.raises(InvalidUrlError):
        normalize_url("https:///path-only")


def test_accepts_public_ip_literal() -> None:
    assert normalize_url("http://8.8.8.8") == "http://8.8.8.8/"


# ------------------------------------------------------------ Phase 4 helpers


def test_validate_hostname_accepts_public() -> None:
    validate_hostname("example.com")


@pytest.mark.parametrize(
    "hostname",
    ["localhost", "127.0.0.1", "10.1.2.3", "192.168.0.5", "intra.local", "bad_underscore"],
)
def test_validate_hostname_rejects_internal(hostname: str) -> None:
    with pytest.raises(InvalidUrlError):
        validate_hostname(hostname)


def test_normalize_crawl_url_strips_fragment_and_tracking() -> None:
    assert (
        normalize_crawl_url(
            "https://acme.example/about?utm_source=ads&b=2&fbclid=x#team",
            "https://acme.example/",
        )
        == "https://acme.example/about?b=2"
    )


def test_normalize_crawl_url_resolves_relative_links() -> None:
    assert (
        normalize_crawl_url("/about", "https://acme.example/") == "https://acme.example/about"
    )
    assert (
        normalize_crawl_url("about", "https://acme.example/docs/")
        == "https://acme.example/docs/about"
    )


def test_normalize_crawl_url_drops_non_http_schemes() -> None:
    assert normalize_crawl_url("mailto:hi@acme.example", "https://acme.example/") is None
    assert normalize_crawl_url("javascript:void(0)", "https://acme.example/") is None
    assert normalize_crawl_url("tel:+15551234", "https://acme.example/") is None
    assert normalize_crawl_url("ftp://acme.example/file", "https://acme.example/") is None


def test_normalize_crawl_url_keeps_public_query_params() -> None:
    assert (
        normalize_crawl_url("https://acme.example/search?q=cats&page=2", "https://acme.example/")
        == "https://acme.example/search?q=cats&page=2"
    )
