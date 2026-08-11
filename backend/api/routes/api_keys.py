"""API key management endpoints (docs/05 §12).

All routes require a valid bearer access token with tenant role `owner` or
`admin`. Tenant scoping comes from the authenticated principal - the request
body can never select another tenant's keys (00-AI-Development-Rules §7).

    POST   /api/api-keys       create a key (raw secret shown exactly once)
    GET    /api/api-keys       list active keys
    DELETE /api/api-keys/{id}  revoke a key (soft delete)
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from backend.api.deps import (
    api_keys_limiter,
    client_ip,
    current_user,
    get_api_key_service,
    require_role,
)
from backend.schemas.api_keys import ApiKeyOut, CreateApiKeyRequest, CreateApiKeyResponse
from backend.services.api_keys import ApiKeyService
from backend.services.auth import Principal

router = APIRouter(
    prefix="/api-keys",
    tags=["api-keys"],
    dependencies=[Depends(require_role("owner", "admin"))],
)


@router.post("", response_model=CreateApiKeyResponse, status_code=201)
async def create_api_key(
    body: CreateApiKeyRequest,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[ApiKeyService, Depends(get_api_key_service)],
    _: Annotated[None, Depends(api_keys_limiter)],
) -> CreateApiKeyResponse:
    result = await service.create_api_key(
        principal=principal,
        name=body.name,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    response.headers["Location"] = f"/api/api-keys/{result.api_key.id}"
    return CreateApiKeyResponse(
        api_key=result.raw_secret,
        key=ApiKeyOut.from_api_key(result.api_key),
    )


@router.get("", response_model=list[ApiKeyOut])
async def list_api_keys(
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[ApiKeyService, Depends(get_api_key_service)],
    _: Annotated[None, Depends(api_keys_limiter)],
) -> list[ApiKeyOut]:
    keys = await service.list_api_keys(principal.tenant_id)
    return [ApiKeyOut.from_api_key(key) for key in keys]


@router.delete("/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[ApiKeyService, Depends(get_api_key_service)],
    _: Annotated[None, Depends(api_keys_limiter)],
) -> None:
    await service.revoke_api_key(
        principal=principal,
        key_id=key_id,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


__all__ = ["router"]
