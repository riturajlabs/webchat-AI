"""Stripe payment provider (Phase 14).

Talks to the Stripe REST API over `httpx` (no heavy SDK dependency):

    create_checkout    POST /v1/checkout/sessions - a one-time `payment` mode
                       checkout for the plan's `amount_cents`. The tenant is
                       passed as `client_reference_id` and the plan as
                       `metadata.plan_id` so the webhook can attribute the
                       payment back to the tenant (Stripe cannot be relied on
                       to echo arbitrary notes on every event otherwise).
    parse_webhook      verifies the `Stripe-Signature` header (HMAC-SHA256 over
                       `<t>.<payload>` with the `whsec_` secret, plus a 5-minute
                       tolerance) and normalizes `checkout.session.completed`
                       into a paid `WebhookEvent`.

API key and webhook secret come from settings and are never logged. Signature
verification uses constant-time comparison and rejects missing/expired
signatures before any parsing is trusted.
"""

import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import UTC, datetime

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

_STRIPE_API = "https://api.stripe.com/v1"
# Stripe signatures embed a 5-minute clock tolerance; reject anything older so
# a captured payload cannot be replayed.
_SIGNATURE_TOLERANCE_SECONDS = 300
_TIMEOUT = httpx.Timeout(30.0)


def _verify_stripe_signature(
    payload: bytes, signature: str, webhook_secret: str
) -> tuple[int, str]:
    """Verify `Stripe-Signature`; return (timestamp, hex signature)."""
    parts: dict[str, str] = {}
    for pair in signature.split(","):
        if "=" not in pair:
            continue
        key, _, value = pair.partition("=")
        parts[key.strip()] = value.strip()
    timestamp = parts.get("t")
    signature_hex = parts.get("v1")
    if not timestamp or not signature_hex:
        raise PaymentSignatureError("Payment webhook signature is malformed.")
    try:
        timestamp_int = int(timestamp)
    except ValueError as exc:
        raise PaymentSignatureError("Payment webhook signature is malformed.") from exc
    now = datetime.now(UTC).timestamp()
    if abs(now - timestamp_int) > _SIGNATURE_TOLERANCE_SECONDS:
        raise PaymentSignatureError("Payment webhook signature has expired.")
    signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
    expected = hmac.new(
        webhook_secret.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature_hex):
        raise PaymentSignatureError("Payment webhook signature is invalid.")
    return timestamp_int, signature_hex


class StripePaymentProvider:
    """Stripe checkout + webhook implementation."""

    name = "stripe"

    def __init__(
        self,
        *,
        secret_key: str | None,
        webhook_secret: str | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._secret_key = secret_key
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
        if not self._secret_key:
            raise PaymentProviderError("Stripe is not configured (missing STRIPE_SECRET_KEY).")
        form: dict[str, str] = {
            "mode": "payment",
            "client_reference_id": tenant_id,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata[plan_id]": plan_id,
            "line_items[0][price_data][currency]": currency.lower(),
            "line_items[0][price_data][unit_amount]": str(amount_cents),
            "line_items[0][price_data][product_data][name]": f"WebChat AI {plan_id} plan",
            "line_items[0][quantity]": "1",
        }
        async with self._client or httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                f"{_STRIPE_API}/checkout/sessions",
                auth=(self._secret_key, ""),
                data=form,
            )
        if response.status_code >= 400:
            raise PaymentProviderError(f"Stripe checkout failed: {_stripe_error(response)}")
        body = response.json()
        checkout_id = body.get("id")
        url = body.get("url")
        if not checkout_id or not url:
            raise PaymentProviderError("Stripe checkout returned no session URL.")
        return PaymentCheckout(checkout_id=str(checkout_id), url=str(url))

    async def verify_payment(self, payment_id: str) -> PaymentVerification:
        if not self._secret_key:
            raise PaymentProviderError("Stripe is not configured (missing STRIPE_SECRET_KEY).")
        async with self._client or httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                f"{_STRIPE_API}/checkout/sessions/{payment_id}",
                auth=(self._secret_key, ""),
            )
        if response.status_code >= 400:
            raise PaymentProviderError(f"Stripe verification failed: {_stripe_error(response)}")
        session = response.json()
        metadata = session.get("metadata") or {}
        return PaymentVerification(
            payment_id=payment_id,
            status=(
                PAYMENT_STATUS_PAID
                if session.get("payment_status") == "paid"
                else PAYMENT_STATUS_PENDING
            ),
            tenant_id=session.get("client_reference_id"),
            plan_id=metadata.get("plan_id"),
            amount_cents=session.get("amount_total"),
        )

    def parse_webhook(self, payload: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        if not self._webhook_secret:
            raise PaymentProviderError(
                "Stripe webhooks are not configured (missing STRIPE_WEBHOOK_SECRET)."
            )
        signature = headers.get("stripe-signature")
        if not signature:
            raise PaymentSignatureError("Payment webhook is missing its signature.")
        _verify_stripe_signature(payload, signature, self._webhook_secret)
        try:
            event = json.loads(payload)
        except ValueError as exc:
            raise PaymentSignatureError("Payment webhook payload is not valid JSON.") from exc
        event_type = str(event.get("type") or "")
        if event_type == "checkout.session.completed":
            session = event.get("data", {}).get("object") or {}
            metadata = session.get("metadata") or {}
            return WebhookEvent(
                event_type=event_type,
                status=PAYMENT_STATUS_PAID,
                payment_id=str(session.get("id") or ""),
                tenant_id=session.get("client_reference_id"),
                plan_id=metadata.get("plan_id"),
                amount_cents=session.get("amount_total"),
            )
        if event_type in ("checkout.session.async_payment_failed", "invoice.payment_failed"):
            return WebhookEvent(
                event_type=event_type,
                status=PAYMENT_STATUS_FAILED,
                payment_id=str(event.get("data", {}).get("object", {}).get("id") or ""),
            )
        return WebhookEvent(
            event_type=event_type,
            status=PAYMENT_STATUS_PENDING,
            payment_id="",
        )


def _stripe_error(response: httpx.Response) -> str:
    try:
        body = response.json()
        error = body.get("error") or {}
        message = error.get("message")
        if message:
            return str(message)
    except ValueError:
        pass
    return f"HTTP {response.status_code}"


__all__ = ["StripePaymentProvider"]
