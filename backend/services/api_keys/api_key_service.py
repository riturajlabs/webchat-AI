"""API key management business logic (docs/05 §12, ADR-004).

Routes validate and translate; this service owns every workflow: create (the
raw secret is returned exactly once - only a SHA-256 hash is persisted), list,
and revoke (soft delete: the record is kept for audit but hidden from
tenant-facing reads). All database access is tenant-scoped by the
caller-provided `tenant_id`, never by request input.
"""

from dataclasses import dataclass

from backend.core.errors import ApiKeyNotFoundError
from backend.core.security import generate_api_key, hash_api_key
from backend.models.api_key import ApiKey
from backend.models.audit_log import AUDIT_API_KEY_CREATED, AUDIT_API_KEY_REVOKED, AuditLog
from backend.repositories import ApiKeyRepository, AuditLogRepository
from backend.services.auth import Principal


@dataclass(frozen=True)
class CreateApiKeyResult:
    """Create response: the persisted key plus its one-time raw secret."""

    api_key: ApiKey
    raw_secret: str


class ApiKeyService:
    """Encapsulates every API-key management workflow."""

    def __init__(
        self,
        *,
        keys: ApiKeyRepository,
        audit: AuditLogRepository,
    ) -> None:
        self._keys = keys
        self._audit = audit

    async def create_api_key(
        self,
        *,
        principal: Principal,
        name: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> CreateApiKeyResult:
        raw_secret = generate_api_key()
        key = ApiKey.new(
            tenant_id=principal.tenant_id,
            name=name.strip(),
            hashed_secret=hash_api_key(raw_secret),
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


__all__ = ["ApiKeyService", "CreateApiKeyResult"]
