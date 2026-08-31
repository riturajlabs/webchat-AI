"""Authentication service: registration, login, token rotation, reset flows.

Business logic only - routes validate and translate. Implements ADR-003
(stateless access + rotating hashed refresh tokens + CSRF) and ADR-001
(signed email links delivered through the MailService abstraction).
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from backend.core.cache import CacheStore
from backend.core.config import Settings, get_settings
from backend.core.errors import (
    AccountLockedError,
    AccountSuspendedError,
    DuplicateEmailError,
    InvalidCredentialsError,
    InvalidTokenError,
    TokenReuseError,
)
from backend.core.rbac import ROLE_SUPER_ADMIN
from backend.core.security import (
    create_access_token,
    create_email_verification_token,
    create_password_reset_token,
    decode_access_token,
    decode_email_verification_token,
    decode_password_reset_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    utcnow,
    verify_password,
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
    AuditLog,
)
from backend.models.member import Member
from backend.models.refresh_token import RefreshToken
from backend.models.tenant import Tenant
from backend.models.user import User
from backend.repositories import (
    AuditLogRepository,
    MemberRepository,
    RefreshTokenRepository,
    TenantRepository,
    UserRepository,
)
from backend.schemas.auth import validate_password_policy
from backend.services.mail import build_email
from backend.services.mail.base import EmailDispatcher
from backend.workers.timing import chat_stage

logger = logging.getLogger("webchat_ai")

# Sentinel for optional profile fields omitted from a PATCH body.
_UNSET = object()


@dataclass(frozen=True)
class AuthResult:
    """Token bundle returned by register/login/refresh."""

    access_token: str
    expires_in: int
    refresh_token: str
    user: User
    role: str


@dataclass(frozen=True)
class Principal:
    """Authenticated identity resolved from an access token."""

    user_id: str
    tenant_id: str
    role: str
    name: str
    email: str
    email_verified: bool
    status: str
    created_at: datetime
    avatar_url: str | None = None


class AuthService:
    """Encapsulates every authentication workflow."""

    def __init__(
        self,
        *,
        users: UserRepository,
        tenants: TenantRepository,
        members: MemberRepository,
        refresh_tokens: RefreshTokenRepository,
        audit: AuditLogRepository,
        mail_dispatcher: EmailDispatcher,
        settings: Settings | None = None,
        role_cache: CacheStore | None = None,
    ) -> None:
        self._users = users
        self._tenants = tenants
        self._members = members
        self._refresh_tokens = refresh_tokens
        self._audit = audit
        self._mail = mail_dispatcher
        self._settings = settings or get_settings()
        self._role_cache = role_cache

    # ------------------------------------------------------------------ flows

    async def register(
        self,
        *,
        name: str,
        email: str,
        password: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> AuthResult:
        email = email.lower().strip()
        validate_password_policy(password)
        if await self._users.find_by_email(email) is not None:
            raise DuplicateEmailError("An account with this email already exists.")

        tenant = Tenant.new(company_name=name)
        user = User.new(
            tenant_id=tenant.id,
            name=name,
            email=email,
            password_hash=hash_password(password),
        )
        member = Member.new(tenant_id=tenant.id, user_id=user.id, role="owner")

        # Insert the user first: the unique `users.email` index is the source of
        # truth for the concurrent-registration race. If two requests pass the
        # pre-check above, the loser surfaces a 409 DuplicateKeyError here -
        # before any tenant/member record is persisted, so no orphans remain.
        await self._users.create(user)
        await self._tenants.create(tenant)
        await self._members.create(member)
        await self._audit.create(
            AuditLog.new(
                action=AUDIT_REGISTER,
                tenant_id=tenant.id,
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        await self._send_verification_email(user)
        return await self._issue_tokens(user, await self._resolve_role(user))

    async def verify_email(
        self, *, token: str, ip_address: str | None, user_agent: str | None
    ) -> User:
        user_id = decode_email_verification_token(token)
        user = await self._users.find_by_id(user_id)
        if user is None:
            raise InvalidTokenError("Invalid verification token.")
        if not user.email_verified:
            await self._users.set_email_verified(user.id, utcnow())
            await self._audit.create(
                AuditLog.new(
                    action=AUDIT_EMAIL_VERIFIED,
                    tenant_id=user.tenant_id,
                    user_id=user.id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
            )
        return user

    async def resend_verification(
        self, *, email: str, ip_address: str | None, user_agent: str | None
    ) -> None:
        """Send a fresh verification link for an unverified account.

        Silent by design (no response differentiation): unknown emails and
        already-verified accounts get no email, exactly like `forgot_password`,
        so the endpoint cannot be used to enumerate registered addresses.
        """
        user = await self._users.find_by_email(email.lower().strip())
        if user is None or user.email_verified:
            return
        await self._send_verification_email(user)
        await self._audit.create(
            AuditLog.new(
                action=AUDIT_VERIFICATION_RESENT,
                tenant_id=user.tenant_id,
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

    async def update_profile(
        self,
        *,
        user_id: str,
        name: str | None | object = _UNSET,
        avatar_url: str | None | object = _UNSET,
    ) -> User:
        """Update editable profile fields for the signed-in user (name/avatar).

        Omitted fields (default `_UNSET`) are left untouched; pass `name` and
        `avatar_url` explicitly to set them (`avatar_url=None`/`""` clears the
        photo). Returns the refreshed user.
        """
        current = await self._users.find_by_id(user_id)
        if current is None:
            raise InvalidCredentialsError("Invalid or expired session.")
        updates: dict[str, object] = {}
        if name is not _UNSET:
            updates["name"] = name
        if avatar_url is not _UNSET:
            updates["avatar_url"] = avatar_url
        await self._users.update_profile(
            user_id,
            updates=updates,
            at=utcnow(),
        )
        updated = await self._users.find_by_id(user_id)
        if updated is None:
            raise InvalidCredentialsError("Invalid or expired session.")
        return updated

    async def login(
        self,
        *,
        email: str,
        password: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> AuthResult:
        email = email.lower().strip()
        user = await self._users.find_by_email(email)

        # Check account lockout before verifying credentials.
        if user is not None and user.locked_until is not None:
            now = utcnow()
            if user.locked_until > now:
                raise AccountLockedError(
                    "Account is temporarily locked due to too many failed login attempts."
                )
            # Lockout expired — reset counters.
            await self._users.reset_failed_login(user.id, now)
            user = await self._users.find_by_id(user.id)

        if user is None or not verify_password(password, user.password_hash):
            now = utcnow()
            if user is not None:
                await self._users.increment_failed_login(user.id, now)
                user = await self._users.find_by_id(user.id)
                max_attempts = self._settings.login_max_attempts
                if user is not None and user.failed_login_attempts >= max_attempts:
                    lockout_minutes = self._settings.login_lockout_minutes
                    locked_until = now + timedelta(minutes=lockout_minutes)
                    await self._users.lock_account(user.id, locked_until, now)
            await self._audit.create(
                AuditLog.new(
                    action=AUDIT_LOGIN_FAILED,
                    tenant_id=user.tenant_id if user else None,
                    user_id=user.id if user else None,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
            )
            raise InvalidCredentialsError("Invalid email or password.")

        if user.status != "active":
            raise AccountSuspendedError("This account is not active.")
        tenant = await self._tenants.find_by_id(user.tenant_id)
        if tenant is None or tenant.status != "active":
            raise AccountSuspendedError("This account's workspace is suspended.")

        role = await self._resolve_role(user)
        now = utcnow()
        # Reset failed login attempts on successful authentication.
        if user.failed_login_attempts > 0:
            await self._users.reset_failed_login(user.id, now)
        await self._users.update_last_login(user.id, now)
        await self._audit.create(
            AuditLog.new(
                action=AUDIT_LOGIN,
                tenant_id=user.tenant_id,
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        return await self._issue_tokens(user, role)

    async def refresh(
        self, *, raw_refresh_token: str, ip_address: str | None, user_agent: str | None
    ) -> AuthResult:
        # Phase 1: read-only checks before consuming the token.
        token_hash = hash_refresh_token(raw_refresh_token)
        record = await self._refresh_tokens.find_by_hash(token_hash)
        if record is None:
            raise InvalidCredentialsError("Invalid session.")
        if record.is_expired:
            raise InvalidTokenError("Session has expired.")

        # Phase 2: prepare the replacement token.
        user = await self._users.find_by_id(record.user_id)
        if user is None or user.status != "active":
            raise AccountSuspendedError("This account is not active.")
        tenant = await self._tenants.find_by_id(record.tenant_id)
        if tenant is None or tenant.status != "active":
            raise AccountSuspendedError("This account's workspace is suspended.")

        role = await self._resolve_role(user)
        new_raw = generate_refresh_token()
        replacement = RefreshToken.new(
            tenant_id=user.tenant_id,
            user_id=user.id,
            token_hash=hash_refresh_token(new_raw),
        )
        await self._refresh_tokens.create(replacement)

        # Phase 3: atomically consume the old token.  This is the critical
        # section — ``find_and_consume`` uses ``findOneAndUpdate`` with a
        # ``revoked_at: None`` guard so that concurrent refresh requests for
        # the same token will never both succeed: exactly one wins the race.
        now = utcnow()
        consume = await self._refresh_tokens.find_and_consume(
            token_hash, replaced_by=replacement.id, at=now
        )
        if not consume.found:
            raise InvalidCredentialsError("Invalid session.")
        if consume.already_revoked:
            assert consume.token is not None  # already_revoked implies token was found
            await self._on_reuse_detected(consume.token, ip_address, user_agent)
            raise TokenReuseError(
                "Session reuse detected. All sessions for this account were revoked."
            )

        await self._audit.create(
            AuditLog.new(
                action=AUDIT_TOKEN_REFRESHED,
                tenant_id=user.tenant_id,
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        access_token, expires_in = create_access_token(user.id, user.tenant_id, role)
        return AuthResult(
            access_token=access_token,
            expires_in=expires_in,
            refresh_token=new_raw,
            user=user,
            role=role,
        )

    async def logout(
        self, *, raw_refresh_token: str, ip_address: str | None, user_agent: str | None
    ) -> None:
        """Revoke only the current session's refresh token (SEC-4)."""
        token_hash = hash_refresh_token(raw_refresh_token)
        record = await self._refresh_tokens.find_by_hash(token_hash)
        if record is None:
            return
        now = utcnow()
        await self._refresh_tokens.revoke_token(token_hash, now)
        await self._audit.create(
            AuditLog.new(
                action=AUDIT_LOGOUT,
                tenant_id=record.tenant_id,
                user_id=record.user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

    async def logout_all(
        self, *, raw_refresh_token: str, ip_address: str | None, user_agent: str | None
    ) -> None:
        """Revoke every session for the user (opt-in via all_sessions=true)."""
        token_hash = hash_refresh_token(raw_refresh_token)
        record = await self._refresh_tokens.find_by_hash(token_hash)
        if record is None:
            return
        now = utcnow()
        await self._refresh_tokens.revoke_all_for_user(record.user_id, now)
        await self._audit.create(
            AuditLog.new(
                action=AUDIT_LOGOUT,
                tenant_id=record.tenant_id,
                user_id=record.user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

    async def forgot_password(
        self, *, email: str, ip_address: str | None, user_agent: str | None
    ) -> None:
        user = await self._users.find_by_email(email.lower().strip())
        if user is None:
            return  # do not reveal whether the account exists
        token = create_password_reset_token(user.id, user.pwd_token_version)
        reset_url = f"{self._settings.public_base_url}/reset-password?token={token}"
        try:
            await self._mail(
                build_email(
                    user.email,
                    "Reset your password",
                    "reset_password",
                    name=user.name,
                    reset_url=reset_url,
                )
            )
            logger.info(
                "Password reset email dispatched for user %s (to=%s)",
                user.id,
                user.email,
            )
        except Exception as exc:
            logger.exception(
                "Failed to send password reset email for user %s (to=%s): %s",
                user.id,
                user.email,
                exc,
            )
        await self._audit.create(
            AuditLog.new(
                action=AUDIT_FORGOT_PASSWORD,
                tenant_id=user.tenant_id,
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

    async def reset_password(
        self, *, token: str, new_password: str, ip_address: str | None, user_agent: str | None
    ) -> None:
        validate_password_policy(new_password)
        user_id, token_version = decode_password_reset_token(token)
        user = await self._users.find_by_id(user_id)
        if user is None or token_version != user.pwd_token_version:
            raise InvalidTokenError("This reset link is invalid or has already been used.")

        await self._users.update_password(
            user.id, hash_password(new_password), user.pwd_token_version + 1, utcnow()
        )
        await self._refresh_tokens.revoke_all_for_user(user.id, utcnow())
        await self._audit.create(
            AuditLog.new(
                action=AUDIT_PASSWORD_RESET,
                tenant_id=user.tenant_id,
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

    async def authenticate(self, access_token: str) -> Principal:
        """Validate an access JWT and resolve the live user/tenant/member state."""
        async with chat_stage("auth.jwt"):
            claims = decode_access_token(access_token)
        user_id = claims["sub"]
        async with chat_stage("auth.user"):
            user = await self._users.find_by_id(user_id)
        if user is None or user.status != "active":
            raise InvalidCredentialsError("Invalid or expired session.")
        if claims["tenant_id"] != user.tenant_id:
            raise InvalidCredentialsError("Invalid or expired session.")
        async with chat_stage("auth.tenant"):
            tenant = await self._tenants.find_by_id(claims["tenant_id"])
        if tenant is None or tenant.status != "active":
            raise AccountSuspendedError("This account's workspace is suspended.")
        async with chat_stage("auth.member"):
            role = await self._resolve_role(user)
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

    # ------------------------------------------------------------- internals

    async def _resolve_role(self, user: User) -> str:
        """Resolve the effective RBAC role for a user (Phase 15, PERF-1 cached).

        Configured `super_admin_emails` take precedence over the tenant
        membership role: a super admin is a platform-level identity, not a
        tenant membership. Everyone else resolves through the tenant member
        role (falling back to `user.role`, the signup default).

        When a ``role_cache`` is configured, the DB membership lookup is
        cached per-user with a 60-second TTL. Cache misses (or cache
        unavailability) fall through to the database transparently.
        """
        admin_emails = self._super_admin_emails()
        normalized = user.email.strip().casefold()
        if normalized in admin_emails:
            logger.info(
                "Role resolved as super_admin for user %s (email=%s)",
                user.id,
                user.email,
            )
            return ROLE_SUPER_ADMIN

        # Try cache (PERF-1) — skip when not configured.
        if self._role_cache is not None:
            try:
                cached = await self._role_cache.get("auth:role", user.id)
                if cached is not None:
                    logger.debug("Role cache hit for user %s: %s", user.id, cached)
                    return cached
            except Exception:
                logger.warning("Role cache GET failed for user %s", user.id, exc_info=True)

        # Cache miss or unavailable — query database.
        member = await self._members.find_by_user_id(user.id)
        role = member.role if member is not None else user.role

        # Populate cache for next request.
        if self._role_cache is not None:
            try:
                await self._role_cache.set("auth:role", user.id, role, ttl=60)
            except Exception:
                logger.warning("Role cache SET failed for user %s", user.id, exc_info=True)

        logger.debug(
            "Role resolved as %s for user %s (super_admin_count=%d)",
            role,
            user.id,
            len(admin_emails),
        )
        return role

    def _super_admin_emails(self) -> set[str]:
        return {email.strip().casefold() for email in self._settings.super_admin_emails}

    async def _issue_tokens(self, user: User, role: str) -> AuthResult:
        access_token, expires_in = create_access_token(user.id, user.tenant_id, role)
        raw_refresh = generate_refresh_token()
        token = RefreshToken.new(
            tenant_id=user.tenant_id,
            user_id=user.id,
            token_hash=hash_refresh_token(raw_refresh),
        )
        await self._refresh_tokens.create(token)
        return AuthResult(
            access_token=access_token,
            expires_in=expires_in,
            refresh_token=raw_refresh,
            user=user,
            role=role,
        )

    async def _send_verification_email(self, user: User) -> None:
        token = create_email_verification_token(user.id)
        verify_url = f"{self._settings.public_base_url}/verify-email?token={token}"
        logger.info(
            "Sending verification email: recipient=%s, sender=%s, url=%s",
            user.email,
            self._settings.email_from,
            verify_url,
        )
        try:
            await self._mail(
                build_email(
                    user.email,
                    "Verify your email address",
                    "verify_email",
                    name=user.name,
                    verification_url=verify_url,
                )
            )
            logger.info(
                "Verification email dispatched successfully: recipient=%s, user_id=%s",
                user.email,
                user.id,
            )
        except Exception as exc:
            # Verification is no longer required for access, so a mail-infra
            # outage must not block signup/login. Log the provider error so it
            # is visible in API logs; the user can resend from the dashboard.
            logger.exception(
                "Verification email FAILED: recipient=%s, user_id=%s, error=%s",
                user.email,
                user.id,
                exc,
            )

    async def _on_reuse_detected(
        self, record: RefreshToken, ip_address: str | None, user_agent: str | None
    ) -> None:
        await self._refresh_tokens.revoke_all_for_user(record.user_id, utcnow())
        await self._audit.create(
            AuditLog.new(
                action=AUDIT_REFRESH_REUSE_DETECTED,
                tenant_id=record.tenant_id,
                user_id=record.user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        user = await self._users.find_by_id(record.user_id)
        if user is not None:
            await self._mail(
                build_email(
                    user.email,
                    "Security alert: session reuse detected",
                    "security_alert",
                    name=user.name,
                )
            )
