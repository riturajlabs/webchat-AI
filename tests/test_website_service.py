"""Unit tests for the WebsiteService business logic (Phase 3)."""

import pytest
from backend.core.config import get_settings
from backend.core.errors import (
    DuplicateWebsiteError,
    InvalidUrlError,
    WebsiteNotFoundError,
)
from backend.models.audit_log import (
    AUDIT_WEBSITE_CREATED,
    AUDIT_WEBSITE_DELETED,
    AUDIT_WEBSITE_UPDATED,
)
from backend.models.website import WEBSITE_STATUS_DELETED, WEBSITE_STATUS_PENDING
from backend.utils.url_validator import normalize_url

from tests.website_helpers import build_website_env, make_principal


async def test_create_website_creates_website_and_widget() -> None:
    env = build_website_env()
    principal = make_principal()

    result = await env.service.create_website(
        principal=principal,
        name="Example",
        url="https://example.com",
        ip_address="1.2.3.4",
        user_agent="pytest",
    )

    assert result.website.tenant_id == principal.tenant_id
    assert result.website.url == "https://example.com/"
    assert result.website.status == WEBSITE_STATUS_PENDING
    assert len(env.websites.websites) == 1
    assert len(env.widgets.widgets) == 1
    widget = next(iter(env.widgets.widgets.values()))
    assert widget.website_id == result.website.id
    assert widget.tenant_id == principal.tenant_id
    # No long-lived widget secret is ever generated: widget requests are
    # authenticated solely by the short-lived session JWTs (Phase 8).
    assert not hasattr(widget, "widget_secret_hash")


async def test_create_website_returns_embed_script_without_secret() -> None:
    env = build_website_env()
    result = await env.service.create_website(
        principal=make_principal(),
        name="Example",
        url="https://example.com",
        ip_address=None,
        user_agent=None,
    )

    assert not hasattr(result, "widget_secret")
    assert result.widget.widget_id
    assert result.widget.widget_id in result.embed_script


async def test_create_website_seeds_allowed_domains_from_url_host() -> None:
    env = build_website_env()
    await env.service.create_website(
        principal=make_principal(),
        name="Example",
        url="https://store.example.com:8443",
        ip_address=None,
        user_agent=None,
    )
    widget = next(iter(env.widgets.widgets.values()))
    # Scheme + port stripped; the hostname is the seeded embed allowlist entry.
    assert widget.allowed_domains == ["store.example.com"]


async def test_create_website_duplicate_url_raises() -> None:
    env = build_website_env()
    principal = make_principal()
    await env.service.create_website(
        principal=principal, name="A", url="https://example.com", ip_address=None, user_agent=None
    )

    with pytest.raises(DuplicateWebsiteError):
        await env.service.create_website(
            principal=principal,
            name="B",
            url="https://example.com",
            ip_address=None,
            user_agent=None,
        )


async def test_create_website_invalid_url_raises() -> None:
    env = build_website_env()
    with pytest.raises(InvalidUrlError):
        await env.service.create_website(
            principal=make_principal(),
            name="Bad",
            url="http://localhost",
            ip_address=None,
            user_agent=None,
        )


async def test_create_website_audits_event() -> None:
    env = build_website_env()
    principal = make_principal()
    await env.service.create_website(
        principal=principal,
        name="Example",
        url="https://example.com",
        ip_address="1.2.3.4",
        user_agent="pytest",
    )

    assert env.audit.logs[-1].action == AUDIT_WEBSITE_CREATED
    assert env.audit.logs[-1].tenant_id == principal.tenant_id
    assert env.audit.logs[-1].user_id == principal.user_id
    assert env.audit.logs[-1].ip_address == "1.2.3.4"


async def test_list_websites_returns_widget_ids() -> None:
    env = build_website_env()
    principal = make_principal()
    first = await env.service.create_website(
        principal=principal, name="A", url="https://a.example", ip_address=None, user_agent=None
    )
    await env.service.create_website(
        principal=principal, name="B", url="https://b.example", ip_address=None, user_agent=None
    )

    items, total = await env.service.list_websites(principal.tenant_id)

    assert total == 2
    assert len(items) == 2
    by_id = {item.website.id: item for item in items}
    assert by_id[first.website.id].widget_id == first.widget.widget_id


async def test_list_websites_isolation_between_tenants() -> None:
    env = build_website_env()
    await env.service.create_website(
        principal=make_principal(tenant_id="tenant-a"),
        name="A",
        url="https://a.example",
        ip_address=None,
        user_agent=None,
    )
    await env.service.create_website(
        principal=make_principal(tenant_id="tenant-b"),
        name="B",
        url="https://b.example",
        ip_address=None,
        user_agent=None,
    )

    items_a, total_a = await env.service.list_websites("tenant-a")
    items_b, total_b = await env.service.list_websites("tenant-b")
    assert len(items_a) == 1 and total_a == 1
    assert len(items_b) == 1 and total_b == 1


async def test_list_websites_filters_by_status_and_paginates() -> None:
    env = build_website_env()
    principal = make_principal()
    await env.service.create_website(
        principal=principal, name="A", url="https://a.example", ip_address=None, user_agent=None
    )
    await env.service.create_website(
        principal=principal, name="B", url="https://b.example", ip_address=None, user_agent=None
    )

    items, total = await env.service.list_websites(
        principal.tenant_id, status="ready", limit=1, offset=0
    )
    assert items == [] and total == 0

    all_items, all_total = await env.service.list_websites(
        principal.tenant_id, status="pending", limit=1, offset=0
    )
    assert len(all_items) == 1 and all_total == 2
    assert all(item.website.status == "pending" for item in all_items)


async def test_get_website_raises_when_missing() -> None:
    env = build_website_env()
    with pytest.raises(WebsiteNotFoundError):
        await env.service.get_website("tenant-a", "missing")


async def test_get_website_is_tenant_scoped() -> None:
    env = build_website_env()
    result = await env.service.create_website(
        principal=make_principal(tenant_id="tenant-a"),
        name="A",
        url="https://a.example",
        ip_address=None,
        user_agent=None,
    )
    # A different tenant must not read tenant-a's website.
    with pytest.raises(WebsiteNotFoundError):
        await env.service.get_website("tenant-b", result.website.id)


async def test_update_website_renames_and_audits() -> None:
    env = build_website_env()
    principal = make_principal()
    result = await env.service.create_website(
        principal=principal, name="Old", url="https://example.com", ip_address=None, user_agent=None
    )

    updated = await env.service.update_website(
        principal=principal,
        website_id=result.website.id,
        name="New Name",
        url=None,
        ip_address="5.6.7.8",
        user_agent="pytest",
    )

    assert updated.name == "New Name"
    assert updated.url == result.website.url
    assert env.audit.logs[-1].action == AUDIT_WEBSITE_UPDATED


async def test_update_website_url_change_resets_crawl_state() -> None:
    env = build_website_env()
    principal = make_principal()
    result = await env.service.create_website(
        principal=principal, name="A", url="https://a.example", ip_address=None, user_agent=None
    )
    stored = env.websites.websites[result.website.id]
    stored.status = "ready"
    stored.pages_indexed = 42
    stored.last_crawled_at = stored.updated_at
    stored.checksum = "abc123"

    updated = await env.service.update_website(
        principal=principal,
        website_id=result.website.id,
        name=None,
        url="https://b.example",
        ip_address=None,
        user_agent=None,
    )

    assert updated.url == normalize_url("https://b.example")
    assert updated.status == WEBSITE_STATUS_PENDING
    assert updated.pages_indexed == 0
    assert updated.last_crawled_at is None
    assert updated.checksum is None


async def test_update_website_duplicate_url_raises() -> None:
    env = build_website_env()
    principal = make_principal()
    first = await env.service.create_website(
        principal=principal, name="A", url="https://a.example", ip_address=None, user_agent=None
    )
    await env.service.create_website(
        principal=principal, name="B", url="https://b.example", ip_address=None, user_agent=None
    )

    with pytest.raises(DuplicateWebsiteError):
        await env.service.update_website(
            principal=principal,
            website_id=first.website.id,
            name=None,
            url="https://b.example",
            ip_address=None,
            user_agent=None,
        )


async def test_update_website_missing_raises() -> None:
    env = build_website_env()
    with pytest.raises(WebsiteNotFoundError):
        await env.service.update_website(
            principal=make_principal(),
            website_id="missing",
            name="X",
            url=None,
            ip_address=None,
            user_agent=None,
        )


async def test_delete_website_cascades_widget_and_audits() -> None:
    env = build_website_env()
    principal = make_principal()
    result = await env.service.create_website(
        principal=principal, name="A", url="https://a.example", ip_address="1.1.1.1", user_agent="t"
    )

    await env.service.delete_website(
        principal=principal,
        website_id=result.website.id,
        ip_address="1.1.1.1",
        user_agent="t",
    )

    assert len(env.websites.websites) == 1
    remaining = next(iter(env.websites.websites.values()))
    assert remaining.status == WEBSITE_STATUS_DELETED
    assert remaining.deleted is True
    assert len(env.widgets.widgets) == 0
    assert env.audit.logs[-1].action == AUDIT_WEBSITE_DELETED


async def test_delete_website_hides_it_from_list_and_get() -> None:
    env = build_website_env()
    principal = make_principal()
    result = await env.service.create_website(
        principal=principal, name="A", url="https://a.example", ip_address=None, user_agent=None
    )

    await env.service.delete_website(
        principal=principal, website_id=result.website.id, ip_address=None, user_agent=None
    )

    # The record persists (soft delete) but is no longer tenant-visible.
    assert len(env.websites.websites) == 1
    items, total = await env.service.list_websites(principal.tenant_id)
    assert items == [] and total == 0
    with pytest.raises(WebsiteNotFoundError):
        await env.service.get_website(principal.tenant_id, result.website.id)


async def test_delete_website_missing_raises() -> None:
    env = build_website_env()
    with pytest.raises(WebsiteNotFoundError):
        await env.service.delete_website(
            principal=make_principal(),
            website_id="missing",
            ip_address=None,
            user_agent=None,
        )


async def test_create_website_allows_url_reuse_after_soft_delete() -> None:
    env = build_website_env()
    principal = make_principal()
    first = await env.service.create_website(
        principal=principal,
        name="Indira",
        url="https://indirauniversity.edu.in",
        ip_address=None,
        user_agent=None,
    )
    await env.service.delete_website(
        principal=principal, website_id=first.website.id, ip_address=None, user_agent=None
    )
    with pytest.raises(WebsiteNotFoundError):
        await env.service.get_website(principal.tenant_id, first.website.id)

    # Regression: a soft-deleted website must not block re-registering its URL.
    second = await env.service.create_website(
        principal=principal,
        name="Indira Again",
        url="https://indirauniversity.edu.in",
        ip_address=None,
        user_agent=None,
    )

    assert second.website.id != first.website.id
    assert second.website.url == "https://indirauniversity.edu.in/"
    assert second.website.status == WEBSITE_STATUS_PENDING
    # The soft-deleted record persists for audit/recovery alongside the new one.
    assert len(env.websites.websites) == 2


async def test_build_embed_script_includes_widget_api_base_url(monkeypatch) -> None:
    monkeypatch.setenv("WIDGET_API_BASE_URL", "https://api.example.com")
    monkeypatch.setenv(
        "WIDGET_SCRIPT_URL", "https://cdn.example.com/webchat-widget.iife.min.js"
    )
    get_settings.cache_clear()
    try:
        env = build_website_env()
        script = env.service.build_embed_script("widget-123")
    finally:
        get_settings.cache_clear()

    assert 'src="https://cdn.example.com/webchat-widget.iife.min.js"' in script
    assert 'data-widget-id="widget-123"' in script
    assert 'data-api-base-url="https://api.example.com"' in script


async def test_build_embed_script_development_fallback_api_base(monkeypatch) -> None:
    # Unset WIDGET_API_BASE_URL in development → the embed pins the local API
    # (http://localhost:8000) so a dev page never resolves the widget API to its
    # own origin.
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("WIDGET_API_BASE_URL", "")
    get_settings.cache_clear()
    try:
        env = build_website_env()
        script = env.service.build_embed_script("widget-123")
    finally:
        get_settings.cache_clear()
    assert 'data-api-base-url="http://localhost:8000"' in script


async def test_build_embed_script_omits_api_base_when_unset_in_production(
    monkeypatch,
) -> None:
    # In production an unset WIDGET_API_BASE_URL is a deployment gap: the
    # attribute is omitted (no localhost fallback) and the build-time bundle
    # default applies until a real public API origin is configured.
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("EMBEDDING_PROVIDER_ORDER", '["gemini"]')
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "768")
    monkeypatch.setenv(
        "WIDGET_SCRIPT_URL", "https://cdn.example.com/webchat-widget.iife.min.js"
    )
    monkeypatch.setenv("WIDGET_API_BASE_URL", "")
    get_settings.cache_clear()
    try:
        env = build_website_env()
        script = env.service.build_embed_script("widget-123")
    finally:
        get_settings.cache_clear()
    assert "data-api-base-url" not in script


async def test_get_widget_returns_tenant_widget() -> None:
    env = build_website_env()
    result = await env.service.create_website(
        principal=make_principal(tenant_id="tenant-a"),
        name="A",
        url="https://a.example",
        ip_address=None,
        user_agent=None,
    )
    widget = await env.service.get_widget("tenant-a", result.website.id)
    assert widget.widget_id == result.widget.widget_id

    with pytest.raises(WebsiteNotFoundError):
        await env.service.get_widget("tenant-b", result.website.id)
