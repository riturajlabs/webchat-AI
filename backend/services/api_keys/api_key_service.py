"""API key management business logic (docs/05 §12, ADR-004).

Routes validate and translate; this service owns every workflow: create (the
raw secret is returned exactly once - only a SHA-256 hash is persisted), list,
revoke (soft delete: the record is kept for audit but hidden from
tenant-facing reads), and authenticate (`wc_*` bearer tokens resolve to a
tenant-owned principal, Sprint 2). All database access is tenant-scoped by the
caller-provided `tenant_id`, never by request input.
"""

from dataclasses import dataclass
from datetime import datetime

from backend.core.errors import (
    AccountSuspendedError,
    ApiKeyNotFoundError,
    InvalidCredentialsError,
)
from backend.core.security import (
    API_KEY_PREFIX,
    generate_api_key,
    hash_api_key,
    utcnow,
)
from backend.models.api_key import API_KEY_STATUS_ACTIVE, ApiKey
from backend.models.audit_log import (
    AUDIT_API_KEY_AUTHENTICATED,
    AUDIT_API_KEY_CREATED,
    AUDIT_API_KEY_REJECTED,
    AUDIT_API_KEY_REVOKED,
    AuditLog,
)
from backend.repositories import ApiKeyRepository, AuditLogRepository, TenantRepository
from backend.services.auth import Principal


@dataclass(frozen=True)
class CreateApiKeyResult:
    """Create response: the persisted key plus its one-time raw secret."""

    api_key: ApiKey
    raw_secret: str


@dataclass(frozen=True)
class ApiKeyPrincipal:
    """Authenticated identity for a programmatic `wc_*` API key (Sprint 2).

    Duck-types the surface of `Principal` that tenant routes consume
    (`tenant_id`, `role`, `user_id`, `name`). API keys always authenticate as
    `owner` for their owning tenant; `user_id` is always `None` because a key
    is not a user session.
    """

    key_id: str
    tenant_id: str
    role: str = "owner"
    user_id: str | None = None
    name: str = ""


class ApiKeyService:
    """Encapsulates every API-key management workflow."""

    def __init__(
        self,
        *,
        keys: ApiKeyRepository,
        audit: AuditLogRepository,
        tenants: TenantRepository,
    ) -> None:
        self._keys = keys
        self._audit = audit
        self._tenants = tenants

    async def create_api_key(
        self,
        *,
        principal: Principal,
        name: str,
        ip_address: str | None,
        user_agent: str | None,
        expires_at: datetime | None = None,
    ) -> CreateApiKeyResult:
        raw_secret = generate_api_key()
        key = ApiKey.new(
            tenant_id=principal.tenant_id,
            name=name.strip(),
            hashed_secret=hash_api_key(raw_secret),
            expires_at=expires_at,
        )
        await self._keys.create(key)
        await self._audit.create(
            AuditLog.new(
                action=AUDIT_API_KEY_CREATED,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        return CreateApiKeyResult(api_key=key, raw_secret=raw_secret)

    async def list_api_keys(self, tenant_id: str) -> list[ApiKey]:
        return await self._keys.list_by_tenant(tenant_id)

    async def revoke_api_key(
        self,
        *,
        principal: Principal,
        key_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        key = await self._keys.find_by_id(principal.tenant_id, key_id)
        if key is None:
            raise ApiKeyNotFoundError("API key not found.")
        await self._keys.revoke(principal.tenant_id, key_id)
        await self._audit.create(
            AuditLog.new(
                action=AUDIT_API_KEY_REVOKED,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

    async def authenticate_api_key(
        self,
        *,
        raw_secret: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> ApiKeyPrincipal:
        """Resolve a `wc_*` bearer secret to a tenant principal, or raise 401.

        Failure order: prefix -> unknown hash -> revoked -> expired -> tenant
        suspended. Every rejection is audited (`API_KEY_REJECTED`); a success
        touches `last_used_at` and is audited (`API_KEY_AUTHENTICATED`).
        """
        if not raw_secret.startswith(API_KEY_PREFIX):
            raise InvalidCredentialsError("Invalid API key.")
        key = await self._keys.find_by_hash(hash_api_key(raw_secret))
        if key is None:
            await self._audit_reject(tenant_id=None, ip_address=ip_address, user_agent=user_agent)
            raise InvalidCredentialsError("Invalid API key.")
        if key.status != API_KEY_STATUS_ACTIVE:
            await self._audit_reject(
                tenant_id=key.tenant_id, ip_address=ip_address, user_agent=user_agent
            )
            raise InvalidCredentialsError("Invalid API key.")
        if key.expires_at is not None and utcnow() > key.expires_at:
            await self._audit_reject(
                tenant_id=key.tenant_id, ip_address=ip_address, user_agent=user_agent
            )
            raise InvalidCredentialsError("Invalid API key.")
        tenant = await self._tenants.find_by_id(key.tenant_id)
        if tenant is None or tenant.status != "active":
            await self._audit_reject(
                tenant_id=key.tenant_id, ip_address=ip_address, user_agent=user_agent
            )
            raise AccountSuspendedError("This workspace is suspended.")
        await self._keys.touch_last_used(key.id, utcnow())
        await self._audit.create(
            AuditLog.new(
                action=AUDIT_API_KEY_AUTHENTICATED,
                tenant_id=key.tenant_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        return ApiKeyPrincipal(key_id=key.id, tenant_id=key.tenant_id, name=key.name)

    async def _audit_reject(
        self,
        *,
        tenant_id: str | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        await self._audit.create(
            AuditLog.new(
                action=AUDIT_API_KEY_REJECTED,
                tenant_id=tenant_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )


__all__ = ["ApiKeyPrincipal", "ApiKeyService", "CreateApiKeyResult"]
