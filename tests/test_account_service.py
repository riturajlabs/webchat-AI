"""Unit tests for AccountService account-deletion cascade logic (SEC-L02 gate)."""

import pytest
from backend.core.errors import EmailNotVerifiedError, InvalidCredentialsError
from backend.core.security import utcnow
from backend.models.audit_log import AUDIT_ACCOUNT_DELETED
from backend.models.user import User
from backend.services.account import AccountService
from backend.services.auth import Principal

from tests.auth_helpers import VALID_PASSWORD, build_auth_env
from tests.fakes import FakeTenantPurgeRepository


def _principal(user: User, role: str = "owner") -> Principal:
    return Principal(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=role,
        name=user.name,
        email=user.email,
        email_verified=user.email_verified,
        status=user.status,
        created_at=user.created_at,
        avatar_url=user.avatar_url,
    )


def _build_service(env, purge: FakeTenantPurgeRepository) -> AccountService:
    return AccountService(
        users=env.users,
        audit=env.audit,
        purge=purge,
    )


async def _register(env) -> User:
    result = await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address="1.2.3.4",
        user_agent="pytest",
    )
    await env.users.set_email_verified(result.user.id, utcnow())
    user = await env.users.find_by_id(result.user.id)
    assert user is not None
    return user


async def _register_unverified(env) -> User:
    result = await env.service.register(
        name="Eve",
        email="eve@example.com",
        password=VALID_PASSWORD,
        ip_address="1.2.3.4",
        user_agent="pytest",
    )
    assert result.user.email_verified is False
    return result.user


async def test_delete_account_purges_tenant_and_sessions_and_audits() -> None:
    env = build_auth_env()
    purge = FakeTenantPurgeRepository()
    service = _build_service(env, purge)
    user = await _register(env)

    result = await service.delete_account(
        principal=_principal(user),
        ip_address="1.2.3.4",
        user_agent="pytest",
    )

    assert result.email == user.email
    assert purge.purged_tenants == [user.tenant_id]
    assert purge.purged_user_sessions == [user.id]
    # An ACCOUNT_DELETED audit entry survives for review after the tenant purge.
    assert len(env.audit.logs) == 2  # REGISTER + ACCOUNT_DELETED
    assert env.audit.logs[-1].action == AUDIT_ACCOUNT_DELETED


async def test_delete_account_unknown_user_raises_and_does_not_purge() -> None:
    env = build_auth_env()
    purge = FakeTenantPurgeRepository()
    service = _build_service(env, purge)
    user = await _register(env)

    # Simulate the user no longer existing (already removed by a previous op).
    env.users.users.pop(user.id)
    with pytest.raises(InvalidCredentialsError):
        await service.delete_account(
            principal=_principal(user),
            ip_address=None,
            user_agent=None,
        )
    assert purge.purged_tenants == []
    assert purge.purged_user_sessions == []


async def test_delete_account_rejects_tenant_mismatch() -> None:
    env = build_auth_env()
    purge = FakeTenantPurgeRepository()
    service = _build_service(env, purge)
    user = await _register(env)

    # A forged principal pointing at a different tenant must be rejected.
    forged = Principal(
        user_id=user.id,
        tenant_id="some-other-tenant",
        role="owner",
        name=user.name,
        email=user.email,
        email_verified=True,
        status="active",
        created_at=user.created_at,
    )
    with pytest.raises(InvalidCredentialsError):
        await service.delete_account(
            principal=forged,
            ip_address=None,
            user_agent=None,
        )
    assert purge.purged_tenants == []
    assert purge.purged_user_sessions == []


async def test_delete_account_rejects_unverified_email() -> None:
    # SEC-L02: destroying an account is a sensitive write and requires a
    # verified email (an attacker using someone else's address cannot purge).
    env = build_auth_env()
    purge = FakeTenantPurgeRepository()
    service = _build_service(env, purge)
    user = await _register_unverified(env)

    with pytest.raises(EmailNotVerifiedError):
        await service.delete_account(
            principal=_principal(user),
            ip_address="1.2.3.4",
            user_agent="pytest",
        )
    assert purge.purged_tenants == []
    assert purge.purged_user_sessions == []
