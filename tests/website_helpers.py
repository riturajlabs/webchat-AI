"""Shared helpers for building a fake-backed WebsiteService test environment."""

from dataclasses import dataclass
from datetime import UTC, datetime

from backend.services.auth import Principal
from backend.services.website import WebsiteService

from tests.fakes import FakeAuditLogRepository, FakeWebsiteRepository, FakeWidgetRepository


@dataclass
class WebsiteEnv:
    websites: FakeWebsiteRepository
    widgets: FakeWidgetRepository
    audit: FakeAuditLogRepository
    service: WebsiteService


def build_website_env(usage=None) -> WebsiteEnv:
    websites = FakeWebsiteRepository()
    widgets = FakeWidgetRepository()
    audit = FakeAuditLogRepository()
    service = WebsiteService(
        websites=websites,
        widgets=widgets,
        audit=audit,
        usage=usage,
    )
    return WebsiteEnv(websites=websites, widgets=widgets, audit=audit, service=service)


def make_principal(
    *, tenant_id: str = "tenant-a", user_id: str = "user-a", role: str = "owner"
) -> Principal:
    """A principal whose tenant/user id can be reused across fake repositories."""
    return Principal(
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        name="Alice",
        email="alice@example.com",
        email_verified=True,
        status="active",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
