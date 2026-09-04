"""WidgetService unit tests (Phase 8): config cache, sessions, chat guards.

Uses in-memory fakes for the widget/tenant/website repositories and the Redis
store, mirroring the API-test pattern in tests/chat_helpers.py.
"""

import pytest
from backend.core.errors import (
    MessageLimitReachedError,
    ServiceUnavailableError,
    SessionNotFoundError,
    WebsiteNotReadyError,
    WidgetDisabledError,
    WidgetNotFoundError,
)
from backend.models.chat_session import ChatSession
from backend.models.tenant import Tenant
from backend.models.website import (
    WEBSITE_STATUS_PENDING,
    WEBSITE_STATUS_READY,
    Website,
)
from backend.models.widget import Widget
from backend.schemas.widget import WidgetPublicConfig
from backend.services.widget.widget_service import WidgetService

from tests.fakes import (
    FakeChatSessionRepository,
    FakeTenantRepository,
    FakeWebsiteRepository,
    FakeWidgetRepository,
    FakeWidgetStore,
)


def _widget_env(**kwargs):
    widgets = FakeWidgetRepository()
    tenants = FakeTenantRepository()
    websites = FakeWebsiteRepository()
    store = FakeWidgetStore()
    service = WidgetService(
        widgets=widgets,
        tenants=tenants,
        websites=websites,
        store=store,
        settings=None,
        # P0-2 visitor binding lookup; tests seed via `service._sessions`.
        sessions=FakeChatSessionRepository(),
    )
    return widgets, tenants, websites, store, service


def _seed_widget(
    widgets: FakeWidgetRepository,
    tenants: FakeTenantRepository,
    *,
    widget_id: str = "widget-1",
    tenant_id: str = "tenant-a",
    website_id: str = "web-1",
    enabled: bool = True,
    tenant_status: str = "active",
) -> Widget:
    widget = Widget.new(tenant_id=tenant_id, website_id=website_id)
    widget.widget_id = widget_id
    widget.enabled = enabled
    widgets.widgets[widget.id] = widget
    tenant = Tenant.new(company_name="Acme")
    tenant.id = tenant_id
    tenant.status = tenant_status
    tenants.tenants[tenant_id] = tenant
    return widget


def _seed_website(
    websites: FakeWebsiteRepository,
    *,
    tenant_id: str = "tenant-a",
    website_id: str = "web-1",
    status: str = WEBSITE_STATUS_READY,
) -> Website:
    website = Website.new(tenant_id=tenant_id, name="Acme", url="https://acme.example")
    website.id = website_id
    website.status = status
    websites.websites[website_id] = website
    return website


async def test_get_public_config_serves_and_caches() -> None:
    widgets, tenants, _, store, service = _widget_env()
    _seed_widget(widgets, tenants)

    config = await service.get_public_config("widget-1")
    assert isinstance(config, WidgetPublicConfig)
    assert config.widget_id == "widget-1"
    assert config.enabled is True
    assert config.welcome_message == "Hi! How can I help you?"
    assert "wk:config:widget-1" in store.data


async def test_get_public_config_misses_cache_on_second_widget() -> None:
    widgets, tenants, _, store, service = _widget_env()
    _seed_widget(widgets, tenants, widget_id="widget-1")
    _seed_widget(widgets, tenants, widget_id="widget-2")

    await service.get_public_config("widget-1")
    await service.get_public_config("widget-2")
    assert "wk:config:widget-1" in store.data
    assert "wk:config:widget-2" in store.data


async def test_get_public_config_not_found() -> None:
    _, _, _, _, service = _widget_env()
    with pytest.raises(WidgetNotFoundError):
        await service.get_public_config("nope")


async def test_get_public_config_suspended_tenant_disabled() -> None:
    widgets, tenants, _, _, service = _widget_env()
    _seed_widget(widgets, tenants, tenant_status="suspended")
    config = await service.get_public_config("widget-1")
    assert config.enabled is False


async def test_config_cache_falls_back_to_db_on_store_error() -> None:
    widgets, tenants, _, _, service = _widget_env()
    _seed_widget(widgets, tenants)

    class _Boom:
        async def get(self, key: str) -> str | None:
            raise RuntimeError("redis down")

        async def setex(self, key: str, seconds: int, value: str) -> None:
            raise RuntimeError("redis down")

        async def incr(self, key: str) -> int:
            raise RuntimeError("redis down")

        async def expire(self, key: str, seconds: int) -> None:
            raise RuntimeError("redis down")

        async def delete(self, key: str) -> None:
            raise RuntimeError("redis down")

    service._store = _Boom()
    config = await service.get_public_config("widget-1")
    assert config.widget_id == "widget-1"


async def test_invalidate_public_config_drops_cached_entry() -> None:
    widgets, tenants, _, store, service = _widget_env()
    _seed_widget(widgets, tenants)
    await service.get_public_config("widget-1")
    assert "wk:config:widget-1" in store.data

    await service.invalidate_public_config("widget-1")
    assert "wk:config:widget-1" not in store.data


async def test_invalidate_public_config_survives_store_failure() -> None:
    widgets, tenants, _, _, service = _widget_env()
    _seed_widget(widgets, tenants)

    class _Boom:
        async def get(self, key: str) -> str | None:
            raise RuntimeError("redis down")

        async def setex(self, key: str, seconds: int, value: str) -> None:
            raise RuntimeError("redis down")

        async def incr(self, key: str) -> int:
            raise RuntimeError("redis down")

        async def expire(self, key: str, seconds: int) -> None:
            raise RuntimeError("redis down")

        async def delete(self, key: str) -> None:
            raise RuntimeError("redis down")

    service._store = _Boom()
    # Best-effort invalidation: never raises.
    await service.invalidate_public_config("widget-1")


async def test_create_session_mints_scoped_token() -> None:
    widgets, tenants, _, _, service = _widget_env()
    _seed_widget(widgets, tenants)

    token, expires_at = await service.create_session(widget_id="widget-1", visitor_id="visitor-9")
    assert token
    assert expires_at is not None
    assert "ws:session:widget-1:visitor-9" in service._store._data


async def test_create_session_rejects_disabled_widget() -> None:
    widgets, tenants, _, _, service = _widget_env()
    _seed_widget(widgets, tenants, enabled=False)
    with pytest.raises(WidgetDisabledError):
        await service.create_session(widget_id="widget-1", visitor_id="v1")


async def test_create_session_rejects_suspended_tenant() -> None:
    widgets, tenants, _, _, service = _widget_env()
    _seed_widget(widgets, tenants, tenant_status="suspended")
    with pytest.raises(WidgetDisabledError):
        await service.create_session(widget_id="widget-1", visitor_id="v1")


async def test_create_session_rejects_unknown_widget() -> None:
    _, _, _, _, service = _widget_env()
    with pytest.raises(WidgetNotFoundError):
        await service.create_session(widget_id="nope", visitor_id="v1")


async def test_validate_chat_accepts_ready_widget() -> None:
    widgets, tenants, websites, _, service = _widget_env()
    _seed_widget(widgets, tenants)
    _seed_website(websites)

    await service.validate_chat(widget_id="widget-1", tenant_id="tenant-a", website_id="web-1")


async def test_validate_chat_rejects_foreign_widget() -> None:
    widgets, tenants, websites, _, service = _widget_env()
    _seed_widget(widgets, tenants)
    _seed_website(websites)
    with pytest.raises(WidgetNotFoundError):
        await service.validate_chat(
            widget_id="widget-1", tenant_id="other-tenant", website_id="web-1"
        )


async def test_validate_chat_rejects_disabled_widget() -> None:
    widgets, tenants, websites, _, service = _widget_env()
    _seed_widget(widgets, tenants, enabled=False)
    _seed_website(websites)
    with pytest.raises(WidgetDisabledError):
        await service.validate_chat(widget_id="widget-1", tenant_id="tenant-a", website_id="web-1")


async def test_validate_chat_rejects_suspended_tenant() -> None:
    widgets, tenants, websites, _, service = _widget_env()
    _seed_widget(widgets, tenants, tenant_status="suspended")
    _seed_website(websites)
    with pytest.raises(WidgetDisabledError):
        await service.validate_chat(widget_id="widget-1", tenant_id="tenant-a", website_id="web-1")


async def test_validate_chat_rejects_not_ready_website() -> None:
    widgets, tenants, websites, _, service = _widget_env()
    _seed_widget(widgets, tenants)
    _seed_website(websites, status=WEBSITE_STATUS_PENDING)
    with pytest.raises(WebsiteNotReadyError):
        await service.validate_chat(widget_id="widget-1", tenant_id="tenant-a", website_id="web-1")


async def test_message_cap_reached_after_limit() -> None:
    widgets, tenants, _, store, service = _widget_env()
    _seed_widget(widgets, tenants)

    # Seed the counter right at the cap using a directly-owned session counter.
    for _ in range(service._settings.widget_max_messages_per_session):
        await service.check_message_cap(
            widget_id="widget-1", visitor_id="v1", session_id="session-1"
        )
    assert "ws:msgs:session-1" in store.data
    with pytest.raises(MessageLimitReachedError):
        await service.check_message_cap(
            widget_id="widget-1", visitor_id="v1", session_id="session-1"
        )


async def test_message_cap_fails_open_on_store_error() -> None:
    widgets, tenants, _, _, service = _widget_env()
    _seed_widget(widgets, tenants)

    class _Boom:
        async def get(self, key: str) -> str | None:
            raise RuntimeError("redis down")

        async def setex(self, key: str, seconds: int, value: str) -> None:
            raise RuntimeError("redis down")

        async def incr(self, key: str) -> int:
            raise RuntimeError("redis down")

        async def expire(self, key: str, seconds: int) -> None:
            raise RuntimeError("redis down")

        async def delete(self, key: str) -> None:
            raise RuntimeError("redis down")

    service._store = _Boom()
    await service.check_message_cap(widget_id="widget-1", visitor_id="v1", session_id="session-1")


# --------------------------------------------- visitor binding (P0-2)


def _seed_session(
    sessions: FakeChatSessionRepository,
    *,
    tenant_id: str = "tenant-a",
    website_id: str = "web-1",
    session_id: str = "session-1",
    visitor_id: str | None = "visitor-a",
) -> ChatSession:
    session = ChatSession.new(
        tenant_id=tenant_id,
        website_id=website_id,
        session_id=session_id,
        visitor_id=visitor_id,
        user_id=None,
    )
    return sessions.sessions.setdefault(session.session_id, session)


async def test_session_access_allows_owner() -> None:
    _, _, _, _, service = _widget_env()
    _seed_session(service._sessions)  # noqa: SLF001

    await service.validate_session_access(
        tenant_id="tenant-a",
        website_id="web-1",
        visitor_id="visitor-a",
        session_id="session-1",
    )


async def test_session_access_rejects_foreign_visitor() -> None:
    """P0-2 core case: same tenant+website, different visitor -> denied."""
    _, _, _, _, service = _widget_env()
    _seed_session(service._sessions)  # noqa: SLF001

    with pytest.raises(SessionNotFoundError):
        await service.validate_session_access(
            tenant_id="tenant-a",
            website_id="web-1",
            visitor_id="visitor-b",
            session_id="session-1",
        )


# ------------------------------------------------------------ P0-1 fail-closed


class _RedisBoomStore:
    """WidgetStore whose `setex` raises like a Redis outage/timeout."""

    def __init__(self, *, exc: Exception) -> None:
        self._exc = exc

    async def get(self, key: str) -> str | None:
        return None

    async def setex(self, key: str, seconds: int, value: str) -> None:
        raise self._exc

    async def incr(self, key: str) -> int:
        raise self._exc

    async def expire(self, key: str, seconds: int) -> None:
        raise self._exc

    async def delete(self, key: str) -> None:
        raise self._exc


async def test_create_session_fails_closed_on_redis_connection_error() -> None:
    widgets, tenants, _, _, service = _widget_env()
    _seed_widget(widgets, tenants)
    service._store = _RedisBoomStore(exc=ConnectionError("redis unavailable"))

    with pytest.raises(ServiceUnavailableError):
        await service.create_session(widget_id="widget-1", visitor_id="visitor-9")


async def test_create_session_fails_closed_on_redis_timeout() -> None:
    widgets, tenants, _, _, service = _widget_env()
    _seed_widget(widgets, tenants)
    service._store = _RedisBoomStore(exc=TimeoutError("redis timed out"))

    with pytest.raises(ServiceUnavailableError):
        await service.create_session(widget_id="widget-1", visitor_id="visitor-9")


async def test_create_session_fails_closed_on_unexpected_redis_exception() -> None:
    widgets, tenants, _, _, service = _widget_env()
    _seed_widget(widgets, tenants)
    service._store = _RedisBoomStore(exc=RuntimeError("some unexpected failure"))

    with pytest.raises(ServiceUnavailableError):
        await service.create_session(widget_id="widget-1", visitor_id="visitor-9")


async def test_create_session_redis_failure_does_not_leak_internals(
    caplog,
) -> None:
    # The raised error must carry a generic message only -- no Redis
    # exception detail that could hint at the failure internals.
    widgets, tenants, _, _, service = _widget_env()
    _seed_widget(widgets, tenants)
    service._store = _RedisBoomStore(exc=ConnectionError("redis unavailable"))

    try:
        await service.create_session(widget_id="widget-1", visitor_id="visitor-9")
    except ServiceUnavailableError as exc:
        message = str(exc)
    else:  # pragma: no cover - guard against a regression that mints anyway
        raise AssertionError("expected ServiceUnavailableError")

    assert "redis" not in message.lower()
    assert "unavailable" in message.lower() or "try again" in message.lower()


async def test_session_access_rejects_unknown_and_cross_website() -> None:
    _, _, _, _, service = _widget_env()
    _seed_session(service._sessions)  # noqa: SLF001

    with pytest.raises(SessionNotFoundError):
        await service.validate_session_access(
            tenant_id="tenant-a",
            website_id="web-1",
            visitor_id="visitor-a",
            session_id="missing-session",
        )
    # Same tenant, different website under that tenant.
    _seed_session(
        service._sessions,  # noqa: SLF001
        website_id="web-2",
        session_id="session-web2",
    )
    with pytest.raises(SessionNotFoundError):
        await service.validate_session_access(
            tenant_id="tenant-a",
            website_id="web-other",
            visitor_id="visitor-a",
            session_id="session-web2",
        )


async def test_session_access_rejects_visitorless_dashboard_thread() -> None:
    """A user-created (dashboard) thread has no visitor; a widget token can
    no longer resume it just because it shares the tenant+website."""
    _, _, _, _, service = _widget_env()
    _seed_session(service._sessions, visitor_id=None)  # noqa: SLF001

    with pytest.raises(SessionNotFoundError):
        await service.validate_session_access(
            tenant_id="tenant-a",
            website_id="web-1",
            visitor_id="visitor-a",
            session_id="session-1",
        )


async def test_session_access_new_conversation_needs_no_lookup() -> None:
    """`session_id=None` starts a fresh conversation - always allowed, the
    RAG layer stamps it with this token's visitor id."""
    _, _, _, _, service = _widget_env()

    await service.validate_session_access(
        tenant_id="tenant-a",
        website_id="web-1",
        visitor_id="visitor-a",
        session_id=None,
    )


async def test_session_access_fails_closed_without_lookup() -> None:
    """A mis-wired service (no session repo) must deny, never allow."""
    widgets, tenants, websites, store = (
        FakeWidgetRepository(),
        FakeTenantRepository(),
        FakeWebsiteRepository(),
        FakeWidgetStore(),
    )
    service = WidgetService(widgets=widgets, tenants=tenants, websites=websites, store=store)

    with pytest.raises(SessionNotFoundError):
        await service.validate_session_access(
            tenant_id="tenant-a",
            website_id="web-1",
            visitor_id="visitor-a",
            session_id="session-1",
        )
