"""Unit tests for the legacy allowed-domains migration logic.

The migration script itself talks to a live MongoDB, so these tests exercise
its pure normalization helper (`_normalize_allowlist`) by loading the script
module without connecting to anything.
"""

import importlib.util
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "migrate-allowed-domains.py"


@pytest.fixture(scope="module")
def migration() -> object:
    spec = importlib.util.spec_from_file_location("migrate_allowed_domains", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_normalize_allowlist_converts_legacy_urls_to_hostnames(migration) -> None:
    assert migration._normalize_allowlist(
        ["http://localhost:3000", "HTTPS://WWW.Example.COM", "example.com."]
    ) == ["localhost", "www.example.com", "example.com"]


def test_normalize_allowlist_drops_invalid_entries(migration) -> None:
    assert migration._normalize_allowlist(
        ["example.com/path", "localhost:3000", "example", "*.localhost", "not a hostname"]
    ) == []


def test_normalize_allowlist_preserves_wildcards_and_open_embed(migration) -> None:
    assert migration._normalize_allowlist(["*.Sub.Example", "*"]) == ["*.sub.example", "*"]


def test_normalize_allowlist_deduplicates_and_keeps_order(migration) -> None:
    assert migration._normalize_allowlist(
        ["example.com", "EXAMPLE.com", "localhost", "localhost"]
    ) == ["example.com", "localhost"]


def test_normalize_allowlist_handles_empty_and_missing(migration) -> None:
    assert migration._normalize_allowlist([]) == []
    assert migration._normalize_allowlist(None) == []
