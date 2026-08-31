"""Shared helpers for building a fake-backed AuthService test environment."""

import re
from dataclasses import dataclass

from backend.core.cache import CacheStore
from backend.core.config import Settings
from backend.models.user import User
from backend.services.auth import AuthService
from backend.services.mail.base import EmailMessage

from tests.fakes import (
    FakeAuditLogRepository,
    FakeMemberRepository,
    FakeRefreshTokenRepository,
    FakeTenantPurgeRepository,
    FakeTenantRepository,
    FakeUserRepository,
    RecordingMailDispatcher,
)

VALID_PASSWORD = "Str0ng!Pass"

_TOKEN_IN_URL = re.compile(r"token=([^&\"\s]+)")


@dataclass
class AuthEnv:
    users: FakeUserRepository
    tenants: FakeTenantRepository
    members: FakeMemberRepository
    refresh_tokens: FakeRefreshTokenRepository
    audit: FakeAuditLogRepository
    mail: RecordingMailDispatcher
    service: AuthService
    purge: FakeTenantPurgeRepository | None = None


def build_auth_env(
    settings: Settings | None = None,
    *,
    role_cache: CacheStore | None = None,
) -> AuthEnv:
    users = FakeUserRepository()
    tenants = FakeTenantRepository()
    members = FakeMemberRepository()
    refresh_tokens = FakeRefreshTokenRepository()
    audit = FakeAuditLogRepository()
    mail = RecordingMailDispatcher()
    service = AuthService(
        users=users,
        tenants=tenants,
        members=members,
        refresh_tokens=refresh_tokens,
        audit=audit,
        mail_dispatcher=mail,
        settings=settings,
        role_cache=role_cache,
    )
    return AuthEnv(
        users=users,
        tenants=tenants,
        members=members,
        refresh_tokens=refresh_tokens,
        audit=audit,
        mail=mail,
        service=service,
    )


def token_from_url(message: EmailMessage) -> str:
    """Extract the `?token=` value from a rendered email URL."""
    match = _TOKEN_IN_URL.search(message.text)
    assert match is not None, "email does not contain a ?token= URL"
    return match.group(1)


async def verify_registered_user(env: AuthEnv) -> User:
    """Mark the most recently registered user as email-verified.

    Mimics a visitor clicking the link in the last verification email, running
    the real `verify_email` flow (token decode + DB update + audit).
    """
    token = token_from_url(env.mail.sent[-1])
    return await env.service.verify_email(token=token, ip_address=None, user_agent=None)
