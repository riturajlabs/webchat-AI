"""Provider-level tests for Phase 14 payment signatures and parsing (no HTTP).

Verify the two real providers fail closed: a missing/malformed/tampered/
expired signature raises `PaymentSignatureError` before any parsing is
trusted, and only `checkout.session.completed` (Stripe) / `payment.captured`
(Razorpay) normalize to a paid `WebhookEvent` carrying the tenant/plan
attribution. HTTP checkout calls are not exercised here (they need a live
gateway); the mock provider's offline contract is covered for dev parity.
"""

import hashlib
import hmac
import json
from datetime import UTC, datetime

import pytest
from backend.core.errors import (
    PaymentProviderError,
    PaymentSignatureError,
)
from backend.services.billing import (
    PAYMENT_STATUS_FAILED,
    PAYMENT_STATUS_PAID,
    PAYMENT_STATUS_PENDING,
    MockPaymentProvider,
    RazorpayPaymentProvider,
    StripePaymentProvider,
)

NOW_TS = int(datetime.now(UTC).timestamp())


# ------------------------------------------------------------------- mock


async def test_mock_checkout_and_verify_are_deterministic() -> None:
    provider = MockPaymentProvider()
    checkout = await provider.create_checkout(
        tenant_id="t1",
        plan_id="pro",
        amount_cents=2_900,
        currency="USD",
        success_url="/ok",
        cancel_url="/no",
    )
    assert checkout.checkout_id.startswith("mock_")
    assert checkout.url == f"https://checkout.example.com/{checkout.checkout_id}"

    verification = await provider.verify_payment("mock_pay_1")
    assert verification.status == PAYMENT_STATUS_PAID


async def test_mock_webhook_fails_closed() -> None:
    provider = MockPaymentProvider()
    with pytest.raises(PaymentSignatureError):
        provider.parse_webhook(b"{}", {})


# ------------------------------------------------------------------ stripe


def _stripe_signature(payload: bytes, secret: str, *, timestamp: int = NOW_TS) -> str:
    signed = f"{timestamp}.{payload.decode('utf-8')}"
    digest = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def _stripe_completed_payload() -> bytes:
    return json.dumps(
        {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_1",
                    "client_reference_id": "tenant-9",
                    "metadata": {"plan_id": "pro"},
                    "amount_total": 2900,
                }
            },
        }
    ).encode()


def test_stripe_webhook_requires_webhook_secret() -> None:
    provider = StripePaymentProvider(secret_key="sk_test", webhook_secret=None)
    with pytest.raises(PaymentProviderError):
        provider.parse_webhook(b"{}", {})


def test_stripe_webhook_requires_signature_header() -> None:
    provider = StripePaymentProvider(secret_key="sk_test", webhook_secret="whsec_test")
    with pytest.raises(PaymentSignatureError):
        provider.parse_webhook(b"{}", {})


def test_stripe_webhook_rejects_malformed_signature() -> None:
    provider = StripePaymentProvider(secret_key="sk_test", webhook_secret="whsec_test")
    with pytest.raises(PaymentSignatureError):
        provider.parse_webhook(b"{}", {"stripe-signature": "garbage"})


def test_stripe_webhook_rejects_expired_signature() -> None:
    provider = StripePaymentProvider(secret_key="sk_test", webhook_secret="whsec_test")
    signature = _stripe_signature(_stripe_completed_payload(), "whsec_test", timestamp=1)
    with pytest.raises(PaymentSignatureError):
        provider.parse_webhook(_stripe_completed_payload(), {"stripe-signature": signature})


def test_stripe_webhook_rejects_tampered_payload() -> None:
    provider = StripePaymentProvider(secret_key="sk_test", webhook_secret="whsec_test")
    signature = _stripe_signature(_stripe_completed_payload(), "whsec_test")
    tampered = b'{"type": "checkout.session.completed"}'
    with pytest.raises(PaymentSignatureError):
        provider.parse_webhook(tampered, {"stripe-signature": signature})


def test_stripe_webhook_normalizes_completed_session_to_paid() -> None:
    provider = StripePaymentProvider(secret_key="sk_test", webhook_secret="whsec_test")
    signature = _stripe_signature(_stripe_completed_payload(), "whsec_test")

    event = provider.parse_webhook(_stripe_completed_payload(), {"stripe-signature": signature})

    assert event.event_type == "checkout.session.completed"
    assert event.status == PAYMENT_STATUS_PAID
    assert event.payment_id == "cs_test_1"
    assert event.tenant_id == "tenant-9"
    assert event.plan_id == "pro"
    assert event.amount_cents == 2900


def test_stripe_webhook_maps_failed_events() -> None:
    provider = StripePaymentProvider(secret_key="sk_test", webhook_secret="whsec_test")
    payload = json.dumps(
        {"type": "invoice.payment_failed", "data": {"object": {"id": "cs_test_2"}}}
    ).encode()
    signature = _stripe_signature(payload, "whsec_test")

    event = provider.parse_webhook(payload, {"stripe-signature": signature})

    assert event.event_type == "invoice.payment_failed"
    assert event.status == PAYMENT_STATUS_FAILED
    assert event.payment_id == "cs_test_2"


def test_stripe_webhook_other_events_are_pending() -> None:
    provider = StripePaymentProvider(secret_key="sk_test", webhook_secret="whsec_test")
    payload = b'{"type": "customer.created", "data": {"object": {}}}'
    signature = _stripe_signature(payload, "whsec_test")

    event = provider.parse_webhook(payload, {"stripe-signature": signature})

    assert event.status == PAYMENT_STATUS_PENDING
    assert event.payment_id == ""


# ----------------------------------------------------------------- razorpay


def _razorpay_signature(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def _razorpay_captured_payload() -> bytes:
    return json.dumps(
        {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_9",
                        "amount": 2900,
                        "notes": {"tenant_id": "tenant-9", "plan_id": "pro"},
                    }
                }
            },
        }
    ).encode()


def test_razorpay_webhook_requires_webhook_secret() -> None:
    provider = RazorpayPaymentProvider(key_id="rzp_test", key_secret="secret", webhook_secret=None)
    with pytest.raises(PaymentProviderError):
        provider.parse_webhook(b"{}", {})


def test_razorpay_webhook_requires_signature_header() -> None:
    provider = RazorpayPaymentProvider(
        key_id="rzp_test", key_secret="secret", webhook_secret="whsec"
    )
    with pytest.raises(PaymentSignatureError):
        provider.parse_webhook(b"{}", {})


def test_razorpay_webhook_rejects_tampered_payload() -> None:
    provider = RazorpayPaymentProvider(
        key_id="rzp_test", key_secret="secret", webhook_secret="whsec"
    )
    signature = _razorpay_signature(_razorpay_captured_payload(), "whsec")
    with pytest.raises(PaymentSignatureError):
        provider.parse_webhook(
            b'{"event": "payment.captured"}', {"x-razorpay-signature": signature}
        )


def test_razorpay_webhook_normalizes_captured_to_paid() -> None:
    provider = RazorpayPaymentProvider(
        key_id="rzp_test", key_secret="secret", webhook_secret="whsec"
    )
    signature = _razorpay_signature(_razorpay_captured_payload(), "whsec")

    event = provider.parse_webhook(
        _razorpay_captured_payload(), {"x-razorpay-signature": signature}
    )

    assert event.event_type == "payment.captured"
    assert event.status == PAYMENT_STATUS_PAID
    assert event.payment_id == "pay_9"
    assert event.tenant_id == "tenant-9"
    assert event.plan_id == "pro"
    assert event.amount_cents == 2900


def test_razorpay_webhook_maps_failed_payment() -> None:
    provider = RazorpayPaymentProvider(
        key_id="rzp_test", key_secret="secret", webhook_secret="whsec"
    )
    payload = json.dumps(
        {"event": "payment.failed", "payload": {"payment": {"entity": {"id": "pay_10"}}}}
    ).encode()
    signature = _razorpay_signature(payload, "whsec")

    event = provider.parse_webhook(payload, {"x-razorpay-signature": signature})

    assert event.status == PAYMENT_STATUS_FAILED
    assert event.payment_id == "pay_10"
