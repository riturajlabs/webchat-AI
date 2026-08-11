"""Pydantic v2 request/response schemas for the API keys API."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# Uploaded field limits (00-AI-Development-Rules: validate all requests).
MAX_API_KEY_NAME_LENGTH = 100
MIN_API_KEY_NAME_LENGTH = 2


class CreateApiKeyRequest(BaseModel):
    name: str = Field(min_length=MIN_API_KEY_NAME_LENGTH, max_length=MAX_API_KEY_NAME_LENGTH)


class ApiKeyOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    key_prefix: str
    status: str
    last_used_at: datetime | None
    created_at: datetime

    @classmethod
    def from_api_key(cls, key: Any) -> "ApiKeyOut":
        return cls(
            id=key.id,
            tenant_id=key.tenant_id,
            name=key.name,
            key_prefix=key.key_prefix,
            status=key.status,
            last_used_at=key.last_used_at,
            created_at=key.created_at,
        )


class CreateApiKeyResponse(BaseModel):
    # The full raw secret; shown exactly once and never persisted (ADR-004).
    api_key: str
    key: ApiKeyOut


__all__ = [
    "ApiKeyOut",
    "CreateApiKeyRequest",
    "CreateApiKeyResponse",
    "MAX_API_KEY_NAME_LENGTH",
    "MIN_API_KEY_NAME_LENGTH",
]
