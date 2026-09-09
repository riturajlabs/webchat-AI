"""Tenant repository SQL-free unit tests (Phase 12.5 / SEC-H05)."""

from __future__ import annotations

import pytest
from backend.repositories.tenant_repository import MAX_TENANT_SEARCH_LENGTH, MongoTenantRepository


def test_query_builds_regex_filter_for_search() -> None:
    query = MongoTenantRepository._query(search="Acme", plan=None, status=None)
    assert "$regex" in query["company_name"]
    assert query["company_name"]["$options"] == "i"


def test_query_escapes_regex_metacharacters() -> None:
    query = MongoTenantRepository._query(search="a.c[d]", plan=None, status=None)
    pattern = query["company_name"]["$regex"]
    assert "." not in pattern.replace(r"\.", "").replace(r"\[", "").replace(r"\]", "")
    assert pattern.startswith(r"a\.c\[d\]")


def test_query_rejects_search_over_max_length() -> None:
    with pytest.raises(ValueError, match="Search term exceeds"):
        MongoTenantRepository._query(
            search="x" * (MAX_TENANT_SEARCH_LENGTH + 1), plan=None, status=None
        )


def test_query_accepts_search_at_max_length() -> None:
    query = MongoTenantRepository._query(
        search="x" * MAX_TENANT_SEARCH_LENGTH, plan=None, status=None
    )
    assert "$regex" in query["company_name"]
