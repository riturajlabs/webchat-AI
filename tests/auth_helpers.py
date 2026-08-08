"""Shared helpers for building a fake-backed AuthService test environment."""

import re
from dataclasses import dataclass

from backend.services.auth import AuthService
from backend.services.mail.base import EmailMessage
from tests.fakes import (
    FakeAuditLogRepository,
    FakeMemberRepository,
    FakeRefreshTokenRepository,
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


def build_auth_env() -> AuthEnv:
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
