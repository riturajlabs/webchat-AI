"""Tests for the websites repository query construction (soft-delete URL reuse).

Regression: `find_by_url` previously matched soft-deleted documents (and the
full-unique `(tenant_id, url)` index permanently reserved deleted URLs), so a
deleted website could never be re-registered. The duplicate check must only
consider active records.
"""

from backend.models.website import WEBSITE_STATUS_DELETED
from backend.repositories.website_repository import find_by_url_filter


def test_find_by_url_filter_is_tenant_scoped_and_excludes_soft_deleted() -> None:
    query = find_by_url_filter("tenant-a", "https://indirauniversity.edu.in/")

    assert query["tenant_id"] == "tenant-a"
    assert query["url"] == "https://indirauniversity.edu.in/"
    assert query["status"] == {"$ne": WEBSITE_STATUS_DELETED}


def test_find_by_url_filter_carries_exact_url() -> None:
    query = find_by_url_filter("tenant-a", "https://example.com/")
    assert query["url"] == "https://example.com/"
