"""Payment provider resolution (Phase 14).

Selects the `PaymentProvider` implementation from `Settings.payment_provider`
at request time so tests and deployments can swap gateways without touching
route code. Unknown names are a configuration error and fail fast
(`ProviderConfigurationError`); "mock" is the offline dev/test implementation.
"""

from backend.core.config import Settings
from backend.core.errors import ProviderConfigurationError
from backend.services.billing.payments.base import (
    MockPaymentProvider,
    PaymentProvider,
)
from backend.services.billing.payments.razorpay_provider import RazorpayPaymentProvider
from backend.services.billing.payments.stripe_provider import StripePaymentProvider


def build_payment_provider(settings: Settings) -> PaymentProvider:
    """Return the provider named by `settings.payment_provider`.

    Providers are built lazily from settings (env) and never hold a logged
    secret. Construction has no side effects and performs no network I/O.
    """
    name = (settings.payment_provider or "mock").strip().lower()
    if name == "mock" or not name:
        return MockPaymentProvider()
    if name == "stripe":
        return StripePaymentProvider(
            secret_key=settings.stripe_secret_key,
            webhook_secret=settings.stripe_webhook_secret,
        )
    if name == "razorpay":
        return RazorpayPaymentProvider(
            key_id=settings.razorpay_key_id,
            key_secret=settings.razorpay_key_secret,
            webhook_secret=settings.razorpay_webhook_secret,
        )
    raise ProviderConfigurationError(
        f"Unknown payment provider: {name}. Expected 'stripe', 'razorpay' or 'mock'."
    )


__all__ = ["build_payment_provider"]
