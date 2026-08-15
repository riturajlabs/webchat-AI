"""Razorpay payment provider (Phase 14).

Talks to the Razorpay REST API over `httpx` (no heavy SDK dependency):

    create_checkout    POST /v1/orders - one order for the plan's
                       `amount_cents` in the configured currency. The tenant
                       and plan ride in `notes`, which Razorpay echoes on the
                       payment webhook so the event can be attributed.
                       Returns the hosted payment page URL
                       (`https://pay.razorpay.com/order/{id}`).
    parse_webhook      verifies the `X-Razorpay-Signature` header (HMAC-SHA256
                       over the raw body with the webhook secret) and
                       normalizes `payment.captured` into a paid `WebhookEvent`.

Key id/secret and webhook secret come from settings and are never logged.
Signature verification is constant-time and rejects a missing/invalid
signature before the payload is trusted.
"""

import hashlib
import hmac
import json
from collections.abc import Mapping

import httpx

from backend.core.errors import (
    PaymentProviderError,
    PaymentSignatureError,
)
from backend.services.billing.payments.base import (
    PAYMENT_STATUS_FAILED,
    PAYMENT_STATUS_PAID,
    PAYMENT_STATUS_PENDING,
    PaymentCheckout,
    PaymentVerification,
    WebhookEvent,
)

_RAZORPAY_API = "https://api.razorpay.com/v1"
_RAZORPAY_PAY_PAGE = "https://pay.razorpay.com/order"
_TIMEOUT = httpx.Timeout(30.0)


class RazorpayPaymentProvider:
    """Razorpay order + webhook implementation."""

    name = "razorpay"

    def __init__(
        self,
        *,
        key_id: str | None,
        key_secret: str | None,
        webhook_secret: str | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._key_id = key_id
        self._key_secret = key_secret
        self._webhook_secret = webhook_secret
        self._client = client

    async def create_checkout(
        self,
        *,
        tenant_id: str,
        plan_id: str,
        amount_cents: int,
        currency: str,
        success_url: str,
        cancel_url: str,
    ) -> PaymentCheckout:
        if not self._key_id or not self._key_secret:
            raise PaymentProviderError(
                "Razorpay is not configured (missing RAZORPAY_KEY_ID/KEY_SECRET)."
            )
        body = {
            "amount": amount_cents,
            "currency": currency.upper(),
            "notes": {"tenant_id": tenant_id, "plan_id": plan_id},
        }
        async with self._client or httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                f"{_RAZORPAY_API}/orders",
                auth=(self._key_id, self._key_secret),
                json=body,
            )
        if response.status_code >= 400:
            raise PaymentProviderError(
                f"Razorpay checkout failed: {_razorpay_error(response)}"
            )
        order = response.json()
        order_id = order.get("id")
        if not order_id:
            raise PaymentProviderError("Razorpay order created without an id.")
        return PaymentCheckout(
            checkout_id=str(order_id),
            url=f"{_RAZORPAY_PAY_PAGE}/{order_id}",
        )

    async def verify_payment(self, payment_id: str) -> PaymentVerification:
        if not self._key_id or not self._key_secret:
            raise PaymentProviderError(
                "Razorpay is not configured (missing RAZORPAY_KEY_ID/KEY_SECRET)."
            )
        async with self._client or httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                f"{_RAZORPAY_API}/payments/{payment_id}",
                auth=(self._key_id, self._key_secret),
            )
        if response.status_code >= 400:
            raise PaymentProviderError(
                f"Razorpay verification failed: {_razorpay_error(response)}"
            )
        payment = response.json()
        notes = payment.get("notes") or {}
        return PaymentVerification(
            payment_id=payment_id,
            status=(
                PAYMENT_STATUS_PAID
                if payment.get("status") == "captured"
                else PAYMENT_STATUS_PENDING
            ),
            tenant_id=notes.get("tenant_id"),
            plan_id=notes.get("plan_id"),
            amount_cents=payment.get("amount"),
        )

    def parse_webhook(
        self, payload: bytes, headers: Mapping[str, str]
    ) -> WebhookEvent:
        if not self._webhook_secret:
            raise PaymentProviderError(
                "Razorpay webhooks are not configured (missing RAZORPAY_WEBHOOK_SECRET)."
            )
        signature = headers.get("x-razorpay-signature")
        if not signature:
            raise PaymentSignatureError("Payment webhook is missing its signature.")
        expected = hmac.new(
            self._webhook_secret.encode("utf-8"), payload, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise PaymentSignatureError("Payment webhook signature is invalid.")
        try:
            body = json.loads(payload)
        except ValueError as exc:
            raise PaymentSignatureError("Payment webhook payload is not valid JSON.") from exc
        event = str(body.get("event") or "")
        entity = (body.get("payload") or {}).get("payment", {}).get("entity") or {}
        notes = entity.get("notes") or {}
        if event == "payment.captured":
            status = PAYMENT_STATUS_PAID
        elif event == "payment.failed":
            status = PAYMENT_STATUS_FAILED
        else:
            status = PAYMENT_STATUS_PENDING
        return WebhookEvent(
            event_type=event,
            status=status,
            payment_id=str(entity.get("id") or ""),
            tenant_id=notes.get("tenant_id"),
            plan_id=notes.get("plan_id"),
            amount_cents=entity.get("amount"),
        )


def _razorpay_error(response: httpx.Response) -> str:
    try:
        body = response.json()
        error = body.get("error") or {}
        message = error.get("description") or error.get("message")
        if message:
            return str(message)
    except ValueError:
        pass
    return f"HTTP {response.status_code}"


__all__ = ["RazorpayPaymentProvider"]
