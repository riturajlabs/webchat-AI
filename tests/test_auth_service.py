"""Unit tests for AuthService business logic (register/login/tokens/reset/RBAC)."""

from datetime import timedelta

import pytest
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

from tests.auth_helpers import (
    VALID_PASSWORD,
    build_auth_env,
    token_from_url,
    verify_registered_user,
)
from tests.fakes import FakeUserRepository


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


async def test_logout_revokes_all_and_audits() -> None:
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

    assert all(t.is_revoked for t in env.refresh_tokens.tokens.values())
    assert env.audit.logs[-1].action == AUDIT_LOGOUT
    # A token revoked by logout triggers reuse detection if presented again.
    with pytest.raises(TokenReuseError):
        await env.service.refresh(
            raw_refresh_token=login.refresh_token, ip_address=None, user_agent=None
        )


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
