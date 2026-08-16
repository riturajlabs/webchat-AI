"""Payment provider abstraction (Phase 14, SaaS subscriptions).

`PaymentProvider` is the single seam between the subscription service and the
payment gateways (Stripe / Razorpay). It owns three responsibilities that are
inherently provider-specific:

    create_checkout    start a hosted checkout for a plan purchase and return
                       the redirect URL (drives `POST /api/billing/checkout`)
    verify_payment     server-side confirmation that a payment actually
                       succeeded (not used on the webhook path, kept for
                       manual reconciliation)
    parse_webhook      authenticate a webhook via HMAC signature and normalize
                       the provider payload into a `WebhookEvent` that the
                       subscription service can trust

All providers fail closed: missing keys or a bad signature raise domain errors
(`PaymentProviderError` / `PaymentSignatureError`) instead of fabricating
state. The `MockPaymentProvider` keeps development usable without gateway
credentials; it rejects webhooks outright so a real webhook can never be
misattributed in mock mode.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from backend.core.errors import PaymentSignatureError
from backend.core.security import new_id

PAYMENT_STATUS_PAID = "paid"
PAYMENT_STATUS_FAILED = "failed"
PAYMENT_STATUS_PENDING = "pending"

PAYMENT_STATUSES = frozenset({PAYMENT_STATUS_PAID, PAYMENT_STATUS_FAILED, PAYMENT_STATUS_PENDING})


@dataclass(frozen=True)
class PaymentCheckout:
    """A hosted checkout session: provider session id + redirect URL."""

    checkout_id: str
    url: str


@dataclass(frozen=True)
class PaymentVerification:
    """Server-side payment status for manual reconciliation."""

    payment_id: str
    status: str
    tenant_id: str | None = None
    plan_id: str | None = None
    amount_cents: int | None = None


@dataclass(frozen=True)
class WebhookEvent:
    """A signature-verified payment event normalized across providers.

    `status` is one of `PAYMENT_STATUS_*`. Only `paid` events activate a
    subscription; everything else (failed, pending, non-payment events) is a
    no-op for the subscription service.
    """

    event_type: str
    payment_id: str
    status: str
    tenant_id: str | None = None
    plan_id: str | None = None
    amount_cents: int | None = None


class PaymentProvider(Protocol):
    """The payment gateway contract used by `SubscriptionService`."""

    name: str

    async def create_checkout(
        self,
        *,
        tenant_id: str,
        plan_id: str,
        amount_cents: int,
        currency: str,
        success_url: str,
        cancel_url: str,
    ) -> PaymentCheckout: ...

    async def verify_payment(self, payment_id: str) -> PaymentVerification: ...

    def parse_webhook(self, payload: bytes, headers: Mapping[str, str]) -> WebhookEvent: ...


class MockPaymentProvider:
    """Offline provider for development and tests.

    Checkout returns a deterministic fake redirect URL; webhooks are rejected
    outright so real gateway traffic cannot be silently accepted in mock mode
    (fail closed).
    """

    name = "mock"

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
        checkout_id = f"mock_{new_id()}"
        return PaymentCheckout(
            checkout_id=checkout_id,
            url=f"https://checkout.example.com/{checkout_id}",
        )

    async def verify_payment(self, payment_id: str) -> PaymentVerification:
        return PaymentVerification(payment_id=payment_id, status=PAYMENT_STATUS_PAID)

    def parse_webhook(self, payload: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        raise PaymentSignatureError(
            "Payment webhooks are not processed while the mock provider is configured."
        )


__all__ = [
    "MockPaymentProvider",
    "PAYMENT_STATUSES",
    "PAYMENT_STATUS_FAILED",
    "PAYMENT_STATUS_PAID",
    "PAYMENT_STATUS_PENDING",
    "PaymentCheckout",
    "PaymentProvider",
    "PaymentVerification",
    "WebhookEvent",
]
