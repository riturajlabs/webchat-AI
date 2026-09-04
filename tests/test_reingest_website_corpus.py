from types import SimpleNamespace

import pytest
from scripts.reingest_website_corpus import validate_target


def test_validate_target_requires_exact_tenant_and_website() -> None:
    website = SimpleNamespace(id="site-a", tenant_id="tenant-a", status="ready")

    validate_target(website, tenant_id="tenant-a", website_id="site-a")

    with pytest.raises(RuntimeError, match="requested tenant"):
        validate_target(website, tenant_id="tenant-b", website_id="site-a")
    with pytest.raises(RuntimeError, match="requested tenant"):
        validate_target(website, tenant_id="tenant-a", website_id="site-b")


def test_validate_target_rejects_deleted_or_missing_website() -> None:
    deleted = SimpleNamespace(id="site-a", tenant_id="tenant-a", status="deleted")

    with pytest.raises(RuntimeError, match="deleted"):
        validate_target(deleted, tenant_id="tenant-a", website_id="site-a")
    with pytest.raises(RuntimeError, match="requested tenant"):
        validate_target(None, tenant_id="tenant-a", website_id="site-a")
