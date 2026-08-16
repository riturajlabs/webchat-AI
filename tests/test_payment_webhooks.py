"""End-to-end HTTP tests for the Phase 14 payment webhook surface.

`POST /api/webhooks/payment` is the only unauthenticated billing endpoint:
authentication is the provider signature verified by `parse_webhook`. These
tests drive the real route with a `FakePaymentProvider` so we cover the happy
path (a `paid` event activates a subscription), the fail-closed path (bad
signature -> 400, no state change), non-payment events (no-op), and the
idempotency contract on webhook replay. Signature crypto itself is covered in
`test_payment_providers.py`.
"""

import pytest
from backend.api.deps import get_payment_provider, get_subscription_service
from backend.core.config import get_settings
from backend.main import create_app
from backend.services.billing import PAYMENT_STATUS_FAILED
from fastapi.testclient import TestClient

from tests.auth_helpers import build_auth_env
from tests.billing_helpers import build_payment_env

_ACCOUNT_SEQ = 0


@pytest.fixture
def client(monkeypatch):
    """A TestClient whose subscription + payment provider are backed by fakes."""
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    auth_env = build_auth_env()
    payment_env = build_payment_env(auth_env.tenants)
    app = create_app()
    app.dependency_overrides[get_subscription_service] = lambda: payment_env.service
    app.dependency_overrides[get_payment_provider] = lambda: payment_env.provider
    with TestClient(app) as test_client:
        yield test_client, payment_env
    get_settings.cache_clear()


async def test_paid_webhook_activates_subscription(client) -> None:
    test_client, payment_env = client
    payment_env.provider.tenant_id = "tenant-web-1"

    response = test_client.post("/api/webhooks/payment", content=b'{"event": "payment.captured"}')

    assert response.status_code == 200
    assert response.json() == {"ok": "true", "event": "payment.captured"}
    subscriptions = payment_env.subscriptions.subscriptions
    assert len(subscriptions) == 1
    assert subscriptions[0].tenant_id == "tenant-web-1"
    assert subscriptions[0].plan_id == "pro"
    assert subscriptions[0].status == "active"


async def test_webhook_does_not_require_bearer_token(client) -> None:
    test_client, _ = client
    response = test_client.post("/api/webhooks/payment", content=b'{"event": "payment.captured"}')
    assert response.status_code == 200


async def test_webhook_with_bad_signature_is_rejected(client) -> None:
    test_client, payment_env = client
    payment_env.provider.signature_ok = False

    response = test_client.post("/api/webhooks/payment", content=b'{"event": "payment.captured"}')

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PAYMENT_SIGNATURE"
    assert payment_env.subscriptions.subscriptions == []


async def test_failed_payment_webhook_is_a_noop(client) -> None:
    test_client, payment_env = client
    payment_env.provider.webhook_status = PAYMENT_STATUS_FAILED

    response = test_client.post("/api/webhooks/payment", content=b'{"event": "payment.failed"}')

    assert response.status_code == 200
    assert payment_env.subscriptions.subscriptions == []


async def test_webhook_replay_is_idempotent(client) -> None:
    test_client, payment_env = client
    payload = b'{"event": "payment.captured"}'

    first = test_client.post("/api/webhooks/payment", content=payload)
    replay = test_client.post("/api/webhooks/payment", content=payload)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert len(payment_env.subscriptions.subscriptions) == 1
