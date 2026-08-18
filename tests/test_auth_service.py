"""Unit tests for AuthService business logic (register/login/tokens/reset/RBAC)."""

import asyncio
from datetime import timedelta

import pytest
from backend.core.config import Settings
from backend.core.errors import (
    AccountSuspendedError,
    DuplicateEmailError,
    InvalidCredentialsError,
    InvalidTokenError,
    TokenReuseError,
)
from backend.core.security import (
    create_access_token,
    create_password_reset_token,
    hash_refresh_token,
    utcnow,
)
from backend.models.audit_log import (
    AUDIT_EMAIL_VERIFIED,
    AUDIT_FORGOT_PASSWORD,
    AUDIT_LOGIN,
    AUDIT_LOGIN_FAILED,
    AUDIT_LOGOUT,
    AUDIT_PASSWORD_RESET,
    AUDIT_REFRESH_REUSE_DETECTED,
    AUDIT_REGISTER,
    AUDIT_TOKEN_REFRESHED,
    AUDIT_VERIFICATION_RESENT,
)
from backend.models.user import User
from backend.services.auth.auth_service import AuthResult

from tests.auth_helpers import (
    VALID_PASSWORD,
    build_auth_env,
    token_from_url,
    verify_registered_user,
)
from tests.fakes import FakeBrokenCacheStore, FakeCacheStore, FakeUserRepository


async def test_register_creates_tenant_user_member_audit_and_email() -> None:
    env = build_auth_env()
    result = await env.service.register(
        name="Alice",
        email="ALICE@Example.com",
        password=VALID_PASSWORD,
        ip_address="1.2.3.4",
        user_agent="pytest",
    )

    assert result.user.email == "alice@example.com"
    assert result.user.email_verified is False
    assert result.role == "owner"
    assert len(env.tenants.tenants) == 1
    assert len(env.members.members) == 1
    member = env.members.members[next(iter(env.members.members))]
    assert member.role == "owner"
    assert member.user_id == result.user.id
    assert [log.action for log in env.audit.logs] == [AUDIT_REGISTER]

    assert len(env.mail.sent) == 1
    assert env.mail.sent[0].subject == "Verify your email address"
    assert env.mail.sent[0].to == "alice@example.com"


async def test_register_duplicate_email_rejected() -> None:
    env = build_auth_env()
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    with pytest.raises(DuplicateEmailError):
        await env.service.register(
            name="Bob",
            email="alice@example.com",
            password=VALID_PASSWORD,
            ip_address=None,
            user_agent=None,
        )


async def test_register_concurrent_duplicate_returns_409_code() -> None:
    """Simulates the unique-index race: the pre-check misses the email, but the
    insert collides with an already-committed registration (DuplicateKeyError).
    The service must surface a 409 `EMAIL_ALREADY_EXISTS`, not a 500, and must
    not leave orphaned tenant/member records behind.
    """
    env = build_auth_env()
    existing = await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )

    class RacingUsers(FakeUserRepository):
        async def find_by_email(self, email: str) -> User | None:
            return None  # the concurrent pre-check does not see the commit

        async def create(self, user: User) -> None:
            if user.email == existing.user.email:
                raise DuplicateEmailError("An account with this email already exists.")
            await super().create(user)

    env.users = RacingUsers()
    env.service._users = env.users

    with pytest.raises(DuplicateEmailError) as exc_info:
        await env.service.register(
            name="Bob",
            email="alice@example.com",
            password=VALID_PASSWORD,
            ip_address=None,
            user_agent=None,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "EMAIL_ALREADY_EXISTS"
    # The losing registration must not persist a tenant or member (user is
    # inserted first, so the race aborts before any related record is written).
    assert len(env.tenants.tenants) == 1
    assert len(env.members.members) == 1


async def test_register_weak_password_rejected() -> None:
    env = build_auth_env()
    with pytest.raises(ValueError):
        await env.service.register(
            name="Alice",
            email="alice@example.com",
            password="short",
            ip_address=None,
            user_agent=None,
        )


async def test_login_success_updates_last_login_and_audits() -> None:
    env = build_auth_env()
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    await verify_registered_user(env)
    result = await env.service.login(
        email="alice@example.com", password=VALID_PASSWORD, ip_address="9.9.9.9", user_agent="ua"
    )

    assert result.user.email == "alice@example.com"
    assert result.role == "owner"
    assert result.user.last_login is not None
    assert env.audit.logs[-1].action == AUDIT_LOGIN
    assert env.audit.logs[-1].ip_address == "9.9.9.9"


async def test_login_wrong_password_rejected_with_generic_error() -> None:
    env = build_auth_env()
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    with pytest.raises(InvalidCredentialsError) as exc:
        await env.service.login(
            email="alice@example.com", password="WrongPass1!", ip_address=None, user_agent=None
        )
    assert "email or password" in str(exc.value.message)
    assert env.audit.logs[-1].action == AUDIT_LOGIN_FAILED


async def test_login_unknown_email_rejected_with_same_error() -> None:
    env = build_auth_env()
    with pytest.raises(InvalidCredentialsError):
        await env.service.login(
            email="ghost@example.com", password="Whatever1!", ip_address=None, user_agent=None
        )
    assert env.audit.logs[-1].action == AUDIT_LOGIN_FAILED
    assert env.audit.logs[-1].user_id is None


async def test_login_suspended_user_rejected() -> None:
    env = build_auth_env()
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    user = env.users.users[next(iter(env.users.users))]
    user.status = "suspended"
    with pytest.raises(AccountSuspendedError):
        await env.service.login(
            email="alice@example.com", password=VALID_PASSWORD, ip_address=None, user_agent=None
        )


async def test_login_suspended_tenant_rejected() -> None:
    env = build_auth_env()
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    tenant = env.tenants.tenants[next(iter(env.tenants.tenants))]
    tenant.status = "suspended"
    with pytest.raises(AccountSuspendedError):
        await env.service.login(
            email="alice@example.com", password=VALID_PASSWORD, ip_address=None, user_agent=None
        )


async def test_verify_email_marks_user_verified_and_audits() -> None:
    env = build_auth_env()
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    token = token_from_url(env.mail.sent[0])

    user = await env.service.verify_email(token=token, ip_address="1.1.1.1", user_agent="ua")

    assert user.email_verified is True
    assert env.audit.logs[-1].action == AUDIT_EMAIL_VERIFIED


async def test_verify_email_invalid_token_rejected() -> None:
    env = build_auth_env()
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    with pytest.raises(InvalidTokenError):
        await env.service.verify_email(token="garbage-token", ip_address=None, user_agent=None)


async def test_refresh_rotates_token_and_revokes_previous() -> None:
    env = build_auth_env()
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    await verify_registered_user(env)
    login = await env.service.login(
        email="alice@example.com", password=VALID_PASSWORD, ip_address=None, user_agent=None
    )

    result = await env.service.refresh(
        raw_refresh_token=login.refresh_token, ip_address=None, user_agent=None
    )

    assert result.refresh_token != login.refresh_token
    assert env.audit.logs[-1].action == AUDIT_TOKEN_REFRESHED
    presented = next(
        t
        for t in env.refresh_tokens.tokens.values()
        if t.token_hash == hash_refresh_token(login.refresh_token)
    )
    assert presented.is_revoked
    assert presented.replaced_by is not None
    assert any(
        t.token_hash == hash_refresh_token(result.refresh_token)
        for t in env.refresh_tokens.tokens.values()
    )


async def test_refresh_reuse_detection_revokes_all_and_alerts() -> None:
    env = build_auth_env()
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    await verify_registered_user(env)
    login = await env.service.login(
        email="alice@example.com", password=VALID_PASSWORD, ip_address=None, user_agent=None
    )
    first = await env.service.refresh(
        raw_refresh_token=login.refresh_token, ip_address=None, user_agent=None
    )

    with pytest.raises(TokenReuseError):
        await env.service.refresh(
            raw_refresh_token=login.refresh_token, ip_address=None, user_agent=None
        )

    assert env.audit.logs[-1].action == AUDIT_REFRESH_REUSE_DETECTED
    # The rotated token from the legit refresh is now revoked too.
    with pytest.raises(TokenReuseError):
        await env.service.refresh(
            raw_refresh_token=first.refresh_token, ip_address=None, user_agent=None
        )
    assert any(m.subject.startswith("Security alert") for m in env.mail.sent)


async def test_concurrent_refresh_only_one_succeeds() -> None:
    """Two simultaneous refresh requests for the same token: one must win, one must lose.

    Regression test for the token-rotation race condition (AUDIT-REPORT §CRITICAL-1).
    The old flow was: find → check → create → revoke (non-atomic).  Two concurrent
    requests could both pass the ``is_revoked`` check.  The new flow uses
    ``find_and_consume`` (``findOneAndUpdate`` with ``revoked_at: None`` guard) so
    that exactly one request wins the atomic consumption.
    """
    env = build_auth_env()
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    await verify_registered_user(env)
    login = await env.service.login(
        email="alice@example.com", password=VALID_PASSWORD, ip_address=None, user_agent=None
    )
    raw_token = login.refresh_token

    # Fire two concurrent refresh requests for the *same* raw token.
    results = await asyncio.gather(
        env.service.refresh(raw_refresh_token=raw_token, ip_address=None, user_agent=None),
        env.service.refresh(raw_refresh_token=raw_token, ip_address=None, user_agent=None),
        return_exceptions=True,
    )

    successes = [r for r in results if isinstance(r, AuthResult)]
    failures = [r for r in results if isinstance(r, Exception)]

    # Exactly one must succeed; the other must fail.
    assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}"
    assert len(failures) == 1, f"Expected exactly 1 failure, got {len(failures)}"
    assert isinstance(failures[0], TokenReuseError)

    # The successful rotation must have produced a new token different from the original.
    replacement_raw = successes[0].refresh_token
    assert replacement_raw != raw_token

    # The old token is now revoked (consumed by winner + reused by loser).
    assert all(t.is_revoked for t in env.refresh_tokens.tokens.values())


async def test_refresh_unknown_token_rejected() -> None:
    env = build_auth_env()
    with pytest.raises(InvalidCredentialsError):
        await env.service.refresh(
            raw_refresh_token="not-a-real-token", ip_address=None, user_agent=None
        )


async def test_refresh_expired_token_rejected() -> None:
    env = build_auth_env()
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    await verify_registered_user(env)
    login = await env.service.login(
        email="alice@example.com", password=VALID_PASSWORD, ip_address=None, user_agent=None
    )
    record = next(
        t
        for t in env.refresh_tokens.tokens.values()
        if t.token_hash == hash_refresh_token(login.refresh_token)
    )
    record.expires_at = utcnow() - timedelta(minutes=1)

    with pytest.raises(InvalidTokenError):
        await env.service.refresh(
            raw_refresh_token=login.refresh_token, ip_address=None, user_agent=None
        )


async def test_logout_revokes_current_session_and_audits() -> None:
    env = build_auth_env()
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    await verify_registered_user(env)
    login = await env.service.login(
        email="alice@example.com", password=VALID_PASSWORD, ip_address=None, user_agent=None
    )

    await env.service.logout(
        raw_refresh_token=login.refresh_token, ip_address=None, user_agent=None
    )

    # Only the presented token is revoked; registration token is still valid.
    token_hash = hash_refresh_token(login.refresh_token)
    revoked = [t for t in env.refresh_tokens.tokens.values() if t.is_revoked]
    active = [t for t in env.refresh_tokens.tokens.values() if not t.is_revoked]
    assert len(revoked) == 1
    assert revoked[0].token_hash == token_hash
    assert len(active) == 1  # the registration session token is untouched
    assert env.audit.logs[-1].action == AUDIT_LOGOUT
    # A token revoked by logout triggers reuse detection if presented again.
    with pytest.raises(TokenReuseError):
        await env.service.refresh(
            raw_refresh_token=login.refresh_token, ip_address=None, user_agent=None
        )


async def test_logout_current_device_keeps_other_sessions_active() -> None:
    """Logging out from one device must not invalidate another device's session."""
    env = build_auth_env()
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    await verify_registered_user(env)
    # Simulate two independent login sessions (two devices).
    device_a = await env.service.login(
        email="alice@example.com", password=VALID_PASSWORD, ip_address=None, user_agent="device-a"
    )
    device_b = await env.service.login(
        email="alice@example.com", password=VALID_PASSWORD, ip_address=None, user_agent="device-b"
    )

    # Logout from device A only.
    await env.service.logout(
        raw_refresh_token=device_a.refresh_token, ip_address=None, user_agent="device-a"
    )

    # Device A's token is revoked.
    assert hash_refresh_token(device_a.refresh_token) in {
        t.token_hash for t in env.refresh_tokens.tokens.values() if t.is_revoked
    }
    # Device B's token is still valid — can refresh without error.
    refreshed = await env.service.refresh(
        raw_refresh_token=device_b.refresh_token, ip_address=None, user_agent="device-b"
    )
    assert refreshed.access_token
    assert refreshed.user.email == "alice@example.com"


async def test_logout_all_revokes_every_session() -> None:
    """logout_all must revoke every active session for the user."""
    env = build_auth_env()
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    await verify_registered_user(env)
    device_a = await env.service.login(
        email="alice@example.com", password=VALID_PASSWORD, ip_address=None, user_agent="device-a"
    )
    device_b = await env.service.login(
        email="alice@example.com", password=VALID_PASSWORD, ip_address=None, user_agent="device-b"
    )

    await env.service.logout_all(
        raw_refresh_token=device_a.refresh_token, ip_address=None, user_agent="device-a"
    )

    assert all(t.is_revoked for t in env.refresh_tokens.tokens.values())
    # Both devices' tokens are now unusable.
    with pytest.raises(TokenReuseError):
        await env.service.refresh(
            raw_refresh_token=device_a.refresh_token, ip_address=None, user_agent="device-a"
        )
    with pytest.raises(TokenReuseError):
        await env.service.refresh(
            raw_refresh_token=device_b.refresh_token, ip_address=None, user_agent="device-b"
        )


async def test_logout_invalid_token_is_silent() -> None:
    """Logout with a non-existent token must succeed silently (no error, no-op)."""
    env = build_auth_env()
    await env.service.logout(
        raw_refresh_token="not-a-real-token", ip_address=None, user_agent=None
    )
    # No audit log should be created for a non-existent token.
    assert env.audit.logs == []


async def test_forgot_password_unknown_email_is_silent() -> None:
    env = build_auth_env()
    await env.service.forgot_password(email="ghost@example.com", ip_address=None, user_agent=None)
    assert env.mail.sent == []
    assert env.audit.logs == []


async def test_forgot_password_sends_versioned_reset_link() -> None:
    env = build_auth_env()
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )

    await env.service.forgot_password(email="alice@example.com", ip_address=None, user_agent=None)

    assert env.audit.logs[-1].action == AUDIT_FORGOT_PASSWORD
    assert len(env.mail.sent) == 2
    assert env.mail.sent[-1].subject == "Reset your password"
    user = env.users.users[next(iter(env.users.users))]
    assert user.pwd_token_version == 0  # unchanged until actually reset
    token = token_from_url(env.mail.sent[-1])
    assert token != ""


async def test_reset_password_updates_hash_increments_version_and_revokes_sessions() -> None:
    env = build_auth_env()
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    await verify_registered_user(env)
    # Establish a session; the reset must revoke it.
    await env.service.login(
        email="alice@example.com", password=VALID_PASSWORD, ip_address=None, user_agent=None
    )
    user = env.users.users[next(iter(env.users.users))]
    token = create_password_reset_token(user.id, user.pwd_token_version)

    await env.service.reset_password(
        token=token, new_password="NewStr0ng!Pass", ip_address=None, user_agent=None
    )

    assert env.audit.logs[-1].action == AUDIT_PASSWORD_RESET
    assert user.pwd_token_version == 1
    assert all(t.is_revoked for t in env.refresh_tokens.tokens.values())
    # Old password fails, new password works.
    with pytest.raises(InvalidCredentialsError):
        await env.service.login(
            email="alice@example.com", password=VALID_PASSWORD, ip_address=None, user_agent=None
        )
    result = await env.service.login(
        email="alice@example.com", password="NewStr0ng!Pass", ip_address=None, user_agent=None
    )
    assert result.user.email == "alice@example.com"


async def test_reset_password_reused_link_rejected() -> None:
    env = build_auth_env()
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    user = env.users.users[next(iter(env.users.users))]
    token = create_password_reset_token(user.id, user.pwd_token_version)

    await env.service.reset_password(
        token=token, new_password="NewStr0ng!Pass", ip_address=None, user_agent=None
    )
    with pytest.raises(InvalidTokenError):
        await env.service.reset_password(
            token=token, new_password="AnotherStr0ng!", ip_address=None, user_agent=None
        )


async def test_rbac_role_resolved_from_membership() -> None:
    env = build_auth_env()
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    await verify_registered_user(env)
    user = env.users.users[next(iter(env.users.users))]
    member = env.members.members[next(iter(env.members.members))]
    member.role = "viewer"

    result = await env.service.login(
        email="alice@example.com", password=VALID_PASSWORD, ip_address=None, user_agent=None
    )
    assert result.role == "viewer"

    principal = await env.service.authenticate(result.access_token)
    assert principal.role == "viewer"
    assert principal.user_id == user.id
    assert principal.email == "alice@example.com"


async def test_super_admin_role_granted_from_config_emails() -> None:
    """Phase 15 RBAC: `SUPER_ADMIN_EMAILS` outranks the tenant membership."""
    env = build_auth_env(
        settings=Settings(super_admin_emails=["ops@webchat.example", "root@example.com"])
    )
    await env.service.register(
        name="Ops",
        email="OPS@webchat.example",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    await verify_registered_user(env)

    result = await env.service.login(
        email="ops@webchat.example", password=VALID_PASSWORD, ip_address=None, user_agent=None
    )
    assert result.role == "super_admin"

    principal = await env.service.authenticate(result.access_token)
    assert principal.role == "super_admin"


async def test_super_admin_emails_are_case_insensitive() -> None:
    env = build_auth_env(settings=Settings(super_admin_emails=["OPS@Example.com"]))
    await env.service.register(
        name="Ops",
        email="ops@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    await verify_registered_user(env)

    result = await env.service.login(
        email="ops@example.com", password=VALID_PASSWORD, ip_address=None, user_agent=None
    )
    assert result.role == "super_admin"


async def test_super_admin_emails_are_trimmed() -> None:
    env = build_auth_env(settings=Settings(super_admin_emails=["  ops@Example.com  "]))
    await env.service.register(
        name="Ops",
        email="ops@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    await verify_registered_user(env)

    result = await env.service.login(
        email="ops@example.com", password=VALID_PASSWORD, ip_address=None, user_agent=None
    )
    assert result.role == "super_admin"


async def test_super_admin_email_without_membership_still_gets_role() -> None:
    """The config grant applies to any account, even without a member record."""
    env = build_auth_env(settings=Settings(super_admin_emails=["ops@webchat.example"]))
    await env.service.register(
        name="Ops",
        email="ops@webchat.example",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    await verify_registered_user(env)
    env.members.members.clear()  # drop the tenant membership entirely

    principal = await env.service.authenticate(
        (
            await env.service.login(
                email="ops@webchat.example",
                password=VALID_PASSWORD,
                ip_address=None,
                user_agent=None,
            )
        ).access_token
    )
    assert principal.role == "super_admin"


async def test_authenticate_rejects_wrong_tenant_token() -> None:
    env = build_auth_env()
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    user = env.users.users[next(iter(env.users.users))]
    forged = create_access_token(user.id, "other-tenant-id", "owner")[0]

    with pytest.raises(InvalidCredentialsError):
        await env.service.authenticate(forged)


async def test_authenticate_rejects_unknown_user() -> None:
    env = build_auth_env()
    token = create_access_token("no-such-user", "no-such-tenant", "owner")[0]
    with pytest.raises(InvalidCredentialsError):
        await env.service.authenticate(token)


# ---------------------------------------------------- email-verification gate


async def test_login_unverified_email_allowed() -> None:
    env = build_auth_env()
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    result = await env.service.login(
        email="alice@example.com", password=VALID_PASSWORD, ip_address=None, user_agent=None
    )
    assert result.user.email_verified is False
    assert result.access_token


async def test_authenticate_unverified_token_allowed() -> None:
    env = build_auth_env()
    result = await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    principal = await env.service.authenticate(result.access_token)
    assert principal.email_verified is False
    assert principal.email == "alice@example.com"


async def test_refresh_unverified_session_allowed() -> None:
    env = build_auth_env()
    result = await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    refreshed = await env.service.refresh(
        raw_refresh_token=result.refresh_token, ip_address=None, user_agent=None
    )
    assert refreshed.access_token
    assert refreshed.user.email_verified is False


async def test_resend_verification_sends_link_and_audits() -> None:
    env = build_auth_env()
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    assert len(env.mail.sent) == 1

    await env.service.resend_verification(
        email="ALICE@example.com", ip_address="1.1.1.1", user_agent="ua"
    )

    assert len(env.mail.sent) == 2
    assert env.mail.sent[-1].subject == "Verify your email address"
    assert env.audit.logs[-1].action == AUDIT_VERIFICATION_RESENT
    assert env.audit.logs[-1].ip_address == "1.1.1.1"


async def test_resend_verification_is_silent_for_unknown_email() -> None:
    env = build_auth_env()
    await env.service.resend_verification(
        email="ghost@example.com", ip_address=None, user_agent=None
    )
    assert env.mail.sent == []
    assert env.audit.logs == []


async def test_resend_verification_is_silent_for_verified_account() -> None:
    env = build_auth_env()
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    await verify_registered_user(env)
    assert len(env.mail.sent) == 1

    await env.service.resend_verification(
        email="alice@example.com", ip_address=None, user_agent=None
    )

    assert len(env.mail.sent) == 1
    assert env.audit.logs[-1].action == AUDIT_EMAIL_VERIFIED  # unchanged


# ---------------------------------------------------------------- lockout tests


async def test_login_failed_increments_attempts() -> None:
    """Failed login increments failed_login_attempts on the user record."""
    env = build_auth_env(settings=Settings(login_max_attempts=5))
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    user = env.users.users[next(iter(env.users.users))]
    assert user.failed_login_attempts == 0

    with pytest.raises(InvalidCredentialsError):
        await env.service.login(
            email="alice@example.com", password="WrongPass1!", ip_address=None, user_agent=None
        )
    assert user.failed_login_attempts == 1

    with pytest.raises(InvalidCredentialsError):
        await env.service.login(
            email="alice@example.com", password="WrongPass1!", ip_address=None, user_agent=None
        )
    assert user.failed_login_attempts == 2


async def test_login_locks_account_after_max_attempts() -> None:
    """Account is locked after login_max_attempts consecutive failures."""
    env = build_auth_env(settings=Settings(login_max_attempts=3, login_lockout_minutes=15))
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    user = env.users.users[next(iter(env.users.users))]

    for _ in range(3):
        with pytest.raises(InvalidCredentialsError):
            await env.service.login(
                email="alice@example.com", password="WrongPass1!", ip_address=None, user_agent=None
            )

    assert user.locked_until is not None
    assert user.failed_login_attempts == 3


async def test_login_blocked_during_lockout() -> None:
    """Even correct password is rejected while account is locked."""
    from backend.core.errors import AccountLockedError

    env = build_auth_env(settings=Settings(login_max_attempts=3, login_lockout_minutes=15))
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    user = env.users.users[next(iter(env.users.users))]

    # Exhaust attempts.
    for _ in range(3):
        with pytest.raises(InvalidCredentialsError):
            await env.service.login(
                email="alice@example.com", password="WrongPass1!", ip_address=None, user_agent=None
            )

    assert user.locked_until is not None

    # Correct password still fails during lockout.
    with pytest.raises(AccountLockedError):
        await env.service.login(
            email="alice@example.com", password=VALID_PASSWORD, ip_address=None, user_agent=None
        )


async def test_successful_login_resets_failed_attempts() -> None:
    """A successful login resets the failed_login_attempts counter."""
    env = build_auth_env(settings=Settings(login_max_attempts=5))
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    user = env.users.users[next(iter(env.users.users))]

    # Two failures.
    for _ in range(2):
        with pytest.raises(InvalidCredentialsError):
            await env.service.login(
                email="alice@example.com", password="WrongPass1!", ip_address=None, user_agent=None
            )
    assert user.failed_login_attempts == 2

    # Successful login resets counter.
    await env.service.login(
        email="alice@example.com", password=VALID_PASSWORD, ip_address=None, user_agent=None
    )
    assert user.failed_login_attempts == 0


async def test_lockout_resets_after_expiry() -> None:
    """Lockout is cleared when the lockout window expires."""
    from backend.core.security import utcnow

    env = build_auth_env(settings=Settings(login_max_attempts=2, login_lockout_minutes=15))
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    user = env.users.users[next(iter(env.users.users))]

    # Lock the account.
    for _ in range(2):
        with pytest.raises(InvalidCredentialsError):
            await env.service.login(
                email="alice@example.com", password="WrongPass1!", ip_address=None, user_agent=None
            )
    assert user.locked_until is not None

    # Simulate lockout expiry by manually setting locked_until to the past.
    user.locked_until = utcnow() - timedelta(minutes=1)

    # Next login (even with wrong password) should clear the lockout.
    with pytest.raises(InvalidCredentialsError):
        await env.service.login(
            email="alice@example.com", password="WrongPass1!", ip_address=None, user_agent=None
        )

    assert user.locked_until is None
    assert user.failed_login_attempts == 1  # only the current failed attempt


async def test_unknown_email_does_not_leak_lockout_info() -> None:
    """Login with unknown email always returns InvalidCredentialsError (no lockout)."""
    env = build_auth_env(settings=Settings(login_max_attempts=3))
    with pytest.raises(InvalidCredentialsError):
        await env.service.login(
            email="ghost@example.com", password="Whatever1!", ip_address=None, user_agent=None
        )


async def test_lockout_is_configurable() -> None:
    """Different login_max_attempts settings produce different thresholds."""
    env = build_auth_env(settings=Settings(login_max_attempts=10, login_lockout_minutes=30))
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    user = env.users.users[next(iter(env.users.users))]

    # 5 failures should NOT lock with threshold=10.
    for _ in range(5):
        with pytest.raises(InvalidCredentialsError):
            await env.service.login(
                email="alice@example.com", password="WrongPass1!", ip_address=None, user_agent=None
            )
    assert user.locked_until is None
    assert user.failed_login_attempts == 5


# ------------------------------------------------------------------ PERF-1 cache


async def test_role_cache_hit_avoids_database_query() -> None:
    """A warm cache serves the role without touching the members repository."""
    cache = FakeCacheStore()
    env = build_auth_env(role_cache=cache)
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    await verify_registered_user(env)
    user = env.users.users[next(iter(env.users.users))]
    # Seed the cache directly.
    await cache.set("auth:role", user.id, "owner", ttl=60)

    login_result = await env.service.login(
        email="alice@example.com", password=VALID_PASSWORD, ip_address=None, user_agent=None
    )
    # Reset counter: login called _resolve_role once (cache hit, no DB).
    env.members.find_by_user_id_calls = 0

    principal = await env.service.authenticate(login_result.access_token)

    assert principal.role == "owner"
    # find_by_user_id was never called — cache served the role.
    assert env.members.find_by_user_id_calls == 0


async def test_role_cache_miss_queries_database_and_populates() -> None:
    """On cache miss the DB is queried and the result is cached for next time."""
    cache = FakeCacheStore()
    env = build_auth_env(role_cache=cache)
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    await verify_registered_user(env)
    user = env.users.users[next(iter(env.users.users))]
    member = env.members.members[next(iter(env.members.members))]
    member.role = "viewer"
    # Clear any role cached during register/login so the next resolve is a miss.
    await cache.delete("auth:role", user.id)

    principal = await env.service.authenticate(
        (await env.service.login(
            email="alice@example.com", password=VALID_PASSWORD, ip_address=None, user_agent=None
        )).access_token
    )

    assert principal.role == "viewer"
    # Cache was populated with the DB result.
    cached_role = await cache.get("auth:role", user.id)
    assert cached_role == "viewer"


async def test_role_cache_expiry_triggers_fresh_db_query() -> None:
    """After a cache entry expires (simulated by deletion) the DB is re-queried."""
    cache = FakeCacheStore()
    env = build_auth_env(role_cache=cache)
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    await verify_registered_user(env)
    user = env.users.users[next(iter(env.users.users))]
    member = env.members.members[next(iter(env.members.members))]
    member.role = "viewer"
    # Clear any role cached during register so first resolve is a clean miss.
    await cache.delete("auth:role", user.id)

    # First call: populates cache with "viewer".
    principal1 = await env.service.authenticate(
        (await env.service.login(
            email="alice@example.com", password=VALID_PASSWORD, ip_address=None, user_agent=None
        )).access_token
    )
    assert principal1.role == "viewer"
    assert await cache.get("auth:role", user.id) == "viewer"

    # Admin changes the role in the DB.
    member.role = "admin"
    # Simulate TTL expiry by clearing the cache entry.
    await cache.delete("auth:role", user.id)

    # Second call: cache miss → re-queries DB → gets new role.
    principal2 = await env.service.authenticate(
        (await env.service.login(
            email="alice@example.com", password=VALID_PASSWORD, ip_address=None, user_agent=None
        )).access_token
    )
    assert principal2.role == "admin"


async def test_role_cache_unavailable_falls_back_to_database() -> None:
    """When the cache raises, role resolution falls through to the DB."""
    broken = FakeBrokenCacheStore()
    env = build_auth_env(role_cache=broken)
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    await verify_registered_user(env)
    member = env.members.members[next(iter(env.members.members))]
    member.role = "admin"

    principal = await env.service.authenticate(
        (await env.service.login(
            email="alice@example.com", password=VALID_PASSWORD, ip_address=None, user_agent=None
        )).access_token
    )

    # Falls through to DB despite broken cache.
    assert principal.role == "admin"
