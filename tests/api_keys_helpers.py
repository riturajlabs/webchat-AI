"""Shared helpers for building a fake-backed ApiKeyService test environment."""

from dataclasses import dataclass

from backend.services.api_keys import ApiKeyService

from tests.fakes import FakeApiKeyRepository, FakeAuditLogRepository
from tests.website_helpers import make_principal

__all__ = ["ApiKeysEnv", "build_api_keys_env", "make_principal"]


@dataclass
class ApiKeysEnv:
    keys: FakeApiKeyRepository
    audit: FakeAuditLogRepository
    service: ApiKeyService


def build_api_keys_env() -> ApiKeysEnv:
    keys = FakeApiKeyRepository()
    audit = FakeAuditLogRepository()
    service = ApiKeyService(
        keys=keys,
        audit=audit,
    )
    return ApiKeysEnv(keys=keys, audit=audit, service=service)
