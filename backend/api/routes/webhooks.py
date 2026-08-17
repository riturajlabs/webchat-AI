"""Provider payment webhooks (Phase 14, SaaS subscriptions).

    POST /api/webhooks/payment

The only unauthenticated billing surface: authentication is the provider's
signature, which `PaymentProvider.parse_webhook` verifies with a constant-time
HMAC before the payload is trusted. Invalid signatures are rejected with 400
(`INVALID_PAYMENT_SIGNATURE`) so providers retry instead of silently dropping;
valid `paid` events activate the subscription (idempotent on `payment_id`).

The endpoint is deliberately minimal and must not do heavy work - providers
time out quickly and will retry. Tenant scoping comes from the event itself
(`client_reference_id` / `notes`), which the gateway echoes back; the service
re-validates ids defensively before writing.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from backend.api.deps import (
    get_payment_provider,
    get_subscription_service,
    webhook_limiter,
)
from backend.services.billing import (
    PAYMENT_STATUS_PAID,
    PaymentProvider,
    SubscriptionService,
)

router = APIRouter(prefix="/webhooks", tags=["payment-webhooks"])


@router.post("/payment")
async def payment_webhook(
    request: Request,
    provider: Annotated[PaymentProvider, Depends(get_payment_provider)],
    service: Annotated[SubscriptionService, Depends(get_subscription_service)],
    _: Annotated[None, Depends(webhook_limiter)],
) -> dict[str, str]:
    """Receive and verify a payment gateway webhook, then activate on success."""
    payload = await request.body()
    event = provider.parse_webhook(payload, request.headers)
    if event.status == PAYMENT_STATUS_PAID:
        await service.activate_payment(event)
    return {"ok": True, "event": event.event_type}


__all__ = ["router"]
