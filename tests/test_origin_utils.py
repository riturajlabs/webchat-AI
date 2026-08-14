"""Unit tests for the embed-origin allowlist helpers (production hardening).

The widget surface answers `ACAO: *`, so the allowlist must be enforced
application-level on the `Origin` header hostname. These tests pin the
matching rules: scheme/port-insensitive, case-insensitive, `*.` wildcards,
the literal `*` escape hatch, and strict rejection of `null`/malformed
origins once a allowlist is configured.
"""

import pytest
from backend.utils.origin import (
    normalize_allowed_domains,
    normalize_domain_entry,
    origin_allowed,
    origin_hostname,
)

# -------------------------------------------------------------- hostname


def test_origin_hostname_strips_scheme_port_and_case() -> None:
    assert origin_hostname("https://Acme.Example:443") == "acme.example"
    assert origin_hostname("http://acme.example:5500") == "acme.example"


def test_origin_hostname_handles_bare_host_and_trailing_dot() -> None:
    assert origin_hostname("acme.example") == "acme.example"
    assert origin_hostname("https://acme.example.") == "acme.example"


@pytest.mark.parametrize(
    "origin",
    ["null", "", "   ", "file:///tmp/page.html"],
)
def test_origin_hostname_rejects_unparsable_or_non_http(origin: str) -> None:
    assert origin_hostname(origin) is None


@pytest.mark.parametrize(
    "origin",
    ["javascript:alert(1)", "data:text/html,hi", "not a url at all", "///"],
)
def test_origin_hostname_never_allowed_when_allowlist_set(origin: str) -> None:
    # Weird / hostile `Origin` values never parse into an allowlisted host, so
    # they must never be allowed once a allowlist is configured.
    assert origin_allowed(origin, ["acme.example"]) is False


# ------------------------------------------------------------ normalization


def test_normalize_entries_lowercases_and_drops_invalid() -> None:
    assert normalize_allowed_domains(["Acme.Example", "*.Sub.Example"]) == [
        "acme.example",
        "*.sub.example",
    ]
    assert normalize_allowed_domains(["", "   ", None]) == []
    assert normalize_allowed_domains([".example.com"]) == []
    assert normalize_allowed_domains(["example.com."]) == ["example.com"]
    assert normalize_allowed_domains(["*"]) == ["*"]


def test_normalize_entries_accepts_loopback_hosts() -> None:
    assert normalize_allowed_domains(["localhost", "127.0.0.1", "LOCALHOST."]) == [
        "localhost",
        "127.0.0.1",
        "localhost",
    ]


def test_normalize_entries_rejects_bare_single_label_typos() -> None:
    # A single-label hostname other than the loopback host is a typo.
    assert normalize_allowed_domains(["example"]) == []
    assert normalize_allowed_domains(["*.localhost"]) == []


@pytest.mark.parametrize(
    "entry",
    [
        "https://example.com",
        "example.com:8080",
        "example.com/path",
        "example.com?query=1",
        "example.com#frag",
        "user@example.com",
        "-leading.example.com",
        "trailing-.example.com",
        "empty..example.com",
        "..",
        "." * 254,
    ],
)
def test_normalize_entries_rejects_scheme_port_path_or_oversized(entry: str) -> None:
    assert normalize_allowed_domains([entry]) == []


# ---------------------------------------------------- URL-aware normalization


@pytest.mark.parametrize(
    ("input", "expected"),
    [
        ("https://example.com", "example.com"),
        ("http://localhost:3000", "localhost"),
        ("https://www.example.com/dashboard", "www.example.com"),
        ("https://example.com/path?query=1#hash", "example.com"),
        ("HTTPS://SUBDOMAIN.EXAMPLE.COM", "subdomain.example.com"),
        ("localhost", "localhost"),
        ("127.0.0.1", "127.0.0.1"),
        ("example.com", "example.com"),
        ("*.example.com", "*.example.com"),
        ("  Acme.Example.  ", "acme.example"),
    ],
)
def test_normalize_domain_entry_extracts_hostname_from_urls(
    input: str, expected: str
) -> None:
    assert normalize_domain_entry(input) == expected


@pytest.mark.parametrize(
    "entry",
    [
        "example",
        "localhost:3000",
        "example.com/path",
        "http://",
        "https://",
        "ftp://example.com",
        "file:///tmp/page.html",
        "not a hostname",
        "user@example.com",
        "*.localhost",
        "-example.com",
    ],
)
def test_normalize_domain_entry_rejects_invalid_input(entry: str) -> None:
    assert normalize_domain_entry(entry) is None


# ---------------------------------------------------------------- matching


def test_origin_allowed_no_origin_header_is_permitted() -> None:
    assert origin_allowed(None, ["acme.example"]) is True


def test_origin_allowed_empty_allowlist_denies_browser_origins() -> None:
    # An empty allowlist never means "any origin": browser embeds are blocked
    # (the service surfaces WIDGET_DOMAIN_NOT_CONFIGURED) until domains are
    # configured. Only the literal `*` entry opts into open embedding.
    assert origin_allowed("https://evil.example", []) is False
    assert origin_allowed("https://evil.example", ["*"]) is True


def test_origin_allowed_matches_hostname_only() -> None:
    assert origin_allowed("https://acme.example:5500/any/path", ["acme.example"]) is True
    assert origin_allowed("https://acme.example", ["acme.example"]) is True
    assert origin_allowed("https://other.example", ["acme.example"]) is False
    assert origin_allowed("https://sub.acme.example", ["acme.example"]) is False


def test_origin_allowed_matches_case_insensitively() -> None:
    assert origin_allowed("https://ACME.EXAMPLE", ["acme.example"]) is True
    assert origin_allowed("https://acme.example", ["Acme.Example"]) is True


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        ("https://acme.example", True),
        ("https://www.acme.example", True),
        ("https://deep.sub.acme.example", True),
        ("https://notacme.example", False),
        ("https://acme.example.evil.com", False),
    ],
)
def test_origin_allowed_wildcard_subdomain(origin: str, expected: bool) -> None:
    assert origin_allowed(origin, ["*.acme.example"]) is expected


def test_origin_allowed_literal_star_allows_all() -> None:
    assert origin_allowed("https://anything.example", ["*"]) is True
    assert origin_allowed("https://anything.example", ["acme.example", "*"]) is True


def test_origin_allowed_null_origin_rejected_once_allowlist_set() -> None:
    # `Origin: null` (sandboxed iframe / file://) is never a legitimate embed.
    assert origin_allowed("null", ["acme.example"]) is False
    assert origin_allowed("https://acme.example", ["acme.example"]) is True
