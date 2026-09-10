"""Account lifecycle business logic (self-service account deletion).

Routes validate and translate; this service owns the irreversible workflow of
deleting an account. A user's account is backed by a private tenant of which
they are the sole owner (signup creates a 1-member tenant), so deleting the
account means purging the whole tenant and every piece of data it owns
(websites, widgets, documents, knowledge chunks, conversations, messages,
feedback, API keys, subscriptions, usage and audit records — MongoDB has no
foreign-key CASCADE, so this is done as one application-level purge).

Security: the account is always resolved from the authenticated `Principal`,
never from a client-supplied identifier, so no caller can delete another
user's or tenant's data.
"""

import logging
from dataclasses import dataclass

from backend.core.errors import InvalidCredentialsError
from backend.core.security import verify_password
from backend.models.audit_log import AUDIT_ACCOUNT_DELETED, AuditLog
from backend.repositories import (
    AuditLogRepository,
    TenantPurgeRepository,
    UserRepository,
)
from backend.services.auth import Principal

logger = logging.getLogger("webchat_ai")


@dataclass(frozen=True)
class AccountDeleteResult:
    """Outcome of an account deletion request."""

    email: str


class AccountService:
    """Encapsulates self-service account lifecycle workflows."""

    def __init__(
        self,
        *,
        users: UserRepository,
        audit: AuditLogRepository,
        purge: TenantPurgeRepository,
    ) -> None:
        self._users = users
        self._audit = audit
        self._purge = purge

    async def delete_account(
        self,
        *,
        principal: Principal,
        ip_address: str | None,
        user_agent: str | None,
        password: str,
    ) -> AccountDeleteResult:
        """Irreversibly delete the authenticated user's account and tenant.

        The user is resolved from the (server-verified) principal so the
        deletion always targets the caller's own tenant. The account password
        must be presented so the caller proves ownership of the account (an
        email-address gate cannot tell a real owner from an attacker who
        registered with someone else's address, while the password can). The
        account is marked deleted only after every tenant-scoped resource has
        been purged. After this returns, the user's session is invalid (refresh
        tokens are gone) and re-authentication is impossible (the user + tenant
        no longer exist).
        """
        user = await self._users.find_by_id(principal.user_id)
        if user is None:
            raise InvalidCredentialsError("Invalid or expired session.")
        if user.tenant_id != principal.tenant_id:
            # Defense in depth: never purge a tenant the principal does not own.
            raise InvalidCredentialsError("Invalid or expired session.")

        # SEC-L02: destructive account writes require the account password.
        # A missing hash is treated as an invalid credential (never an account-
        # probing signal), and the failure happens before anything is purged.
        if not user.password_hash or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError("Incorrect password.")

        await self._purge.purge_user_sessions(user.id)
        await self._purge.purge_tenant(user.tenant_id)

        # Record a platform-level audit trail after the tenant purge: the
        # tenant- scoped audit documents are gone, so this is written as an
        # admin/global audit entry that survives the deletion for review.
        await self._audit.create(
            AuditLog.new(
                action=AUDIT_ACCOUNT_DELETED,
                tenant_id=user.tenant_id,
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        logger.info(
            "Account deleted: user_id=%s tenant_id=%s email=%s",
            user.id,
            user.tenant_id,
            user.email,
        )
        return AccountDeleteResult(email=user.email)


__all__ = ["AccountDeleteResult", "AccountService"]
