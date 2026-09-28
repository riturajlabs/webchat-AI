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
import sys
from datetime import UTC, datetime
from typing import Any

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
from backend.services.billing.payments import stripe_provider

# Captured before any patching so the clock stand-in below can build real
# datetimes without recursing into itself.
_REAL_DATETIME = datetime
# An arbitrary fixed instant, chosen once and never derived from the wall clock.
_FROZEN_INSTANT = 1_760_000_000


class _FrozenClock:
    """A ``datetime`` stand-in whose ``now()`` the test chooses outright.

    Installed with ``monkeypatch.setattr(module, "datetime", clock)``, this makes
    every ``datetime.now(...)`` in that module return an exact instant. The
    signature tests depend on differences measured against a clock, so freezing
    it is what lets them assert an exact boundary instead of racing one.
    """

    def __init__(self, instant: int) -> None:
        self.instant = instant

    def now(self, tz: object = None) -> Any:
        return _REAL_DATETIME.fromtimestamp(self.instant, UTC)


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


def _stripe_signature(payload: bytes, secret: str, *, timestamp: int | None = None) -> str:
    """Sign ``payload`` the way Stripe does.

    ``timestamp`` is resolved when the signature is *built*, not at import, so
    every caller that omits it signs at the moment it is about to hand the
    payload to ``parse_webhook``. That is the whole point: a stamp captured once
    at collection time makes each test's validity depend on how long the suite
    took to reach it, which is how these tests stayed green on a fast machine
    and expired in CI against the provider's 300 s tolerance.

    Pass ``timestamp`` explicitly to exercise the tolerance window.
    """
    stamp = timestamp if timestamp is not None else int(datetime.now(UTC).timestamp())
    signed = f"{stamp}.{payload.decode('utf-8')}"
    digest = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
    return f"t={stamp},v1={digest}"


def _stripe_timestamp(signature: str) -> int:
    """Read the ``t=`` value back out of a signature header."""
    for part in signature.split(","):
        key, _, value = part.partition("=")
        if key.strip() == "t":
            return int(value.strip())
    raise AssertionError(f"no t= component in {signature!r}")


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


# ---------------------------------------------- signature clock determinism


def test_a_signature_is_stamped_when_it_is_built(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: the signing timestamp is read when the signature is built.

    The helper used to default to a module-level ``NOW_TS`` captured at import,
    so whether a webhook test passed came down to how long the suite took to
    reach it. The clock is frozen and then advanced here, which pins the
    property exactly - the two signatures below are built a day apart and must
    carry their own instants - with no sleeping and no dependence on where the
    wall clock happens to sit when the module is imported.
    """
    clock = _FrozenClock(_FROZEN_INSTANT)
    monkeypatch.setattr(sys.modules[__name__], "datetime", clock)

    first = _stripe_timestamp(_stripe_signature(_stripe_completed_payload(), "whsec_test"))
    clock.instant += 86_400
    second = _stripe_timestamp(_stripe_signature(_stripe_completed_payload(), "whsec_test"))

    assert first == _FROZEN_INSTANT
    assert second == _FROZEN_INSTANT + 86_400


def test_the_signature_tolerance_is_exactly_five_minutes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the tolerance the provider enforces, so it cannot be widened quietly.

    The provider's clock is frozen, which turns the replay window into an exact
    boundary: a signature 300 s old is still inside it, 301 s old is outside
    it. Asserting the edge both ways is what makes any future change to
    ``_SIGNATURE_TOLERANCE_SECONDS`` fail here instead of quietly making the
    suite green.
    """
    provider = StripePaymentProvider(secret_key="sk_test", webhook_secret="whsec_test")
    payload = _stripe_completed_payload()
    monkeypatch.setattr(stripe_provider, "datetime", _FrozenClock(_FROZEN_INSTANT))

    at_the_limit = _stripe_signature(payload, "whsec_test", timestamp=_FROZEN_INSTANT - 300)
    assert (
        provider.parse_webhook(payload, {"stripe-signature": at_the_limit}).status
        == PAYMENT_STATUS_PAID
    )

    past_the_limit = _stripe_signature(payload, "whsec_test", timestamp=_FROZEN_INSTANT - 301)
    with pytest.raises(PaymentSignatureError, match="expired"):
        provider.parse_webhook(payload, {"stripe-signature": past_the_limit})


def test_fresh_expired_and_forged_signatures_stay_distinguished() -> None:
    """All four outcomes in one place, so a tolerance change cannot make one of
    them quietly pass: a correctly signed fresh payload is accepted and
    normalized, a stale one is refused for staleness, a wrongly signed one is
    refused by the constant-time HMAC comparison rather than by the clock, and
    a header that is not a signature at all is refused before either check.
    """
    provider = StripePaymentProvider(secret_key="sk_test", webhook_secret="whsec_test")
    payload = _stripe_completed_payload()

    event = provider.parse_webhook(
        payload, {"stripe-signature": _stripe_signature(payload, "whsec_test")}
    )
    assert event.status == PAYMENT_STATUS_PAID
    assert event.payment_id == "cs_test_1"

    expired = _stripe_signature(payload, "whsec_test", timestamp=1)
    with pytest.raises(PaymentSignatureError, match="expired"):
        provider.parse_webhook(payload, {"stripe-signature": expired})

    forged = _stripe_signature(payload, "whsec_attacker")
    with pytest.raises(PaymentSignatureError, match="invalid"):
        provider.parse_webhook(payload, {"stripe-signature": forged})

    with pytest.raises(PaymentSignatureError, match="malformed"):
        provider.parse_webhook(payload, {"stripe-signature": "not-a-signature"})


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


def test_razorpay_webhook_warns_on_url_secret(caplog) -> None:
    """RAZORPAY_WEBHOOK_SECRET containing a URL is detected and logged."""
    import logging

    logger_name = "backend.services.billing.payments.razorpay_provider"
    with caplog.at_level(logging.WARNING, logger=logger_name):
        RazorpayPaymentProvider(
            key_id="rzp_test",
            key_secret="secret",
            webhook_secret="https://dashboard.razorpay.com/whsec_test123",
        )
    assert "RAZORPAY_WEBHOOK_SECRET appears to contain a URL" in caplog.text
