"""Shared helpers for building a fake-backed ApiKeyService test environment."""

from dataclasses import dataclass

from backend.services.api_keys import ApiKeyService

from tests.fakes import (
    FakeApiKeyRepository,
    FakeAuditLogRepository,
    FakeTenantRepository,
)
from tests.website_helpers import make_principal

__all__ = ["ApiKeysEnv", "build_api_keys_env", "make_principal"]


@dataclass
class ApiKeysEnv:
    keys: FakeApiKeyRepository
    audit: FakeAuditLogRepository
    tenants: FakeTenantRepository
    service: ApiKeyService


def build_api_keys_env() -> ApiKeysEnv:
    keys = FakeApiKeyRepository()
    audit = FakeAuditLogRepository()
    tenants = FakeTenantRepository()
    service = ApiKeyService(
        keys=keys,
        audit=audit,
        tenants=tenants,
    )
    return ApiKeysEnv(keys=keys, audit=audit, tenants=tenants, service=service)
