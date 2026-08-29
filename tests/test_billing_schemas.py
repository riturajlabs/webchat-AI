"""Tests for billing schema input validation (open redirect prevention)."""

import pytest
from backend.schemas.billing import CheckoutRequest, UsageMetricOut
from pydantic import ValidationError


class TestCheckoutRequestUrlValidation:
    def test_default_urls_accepted(self) -> None:
        req = CheckoutRequest(plan_id="plan_123")
        assert "localhost" in req.success_url

    def test_rejects_javascript_scheme(self) -> None:
        with pytest.raises(ValueError, match="http"):
            CheckoutRequest(
                plan_id="plan_123",
                success_url="javascript:alert(1)",
            )

    def test_rejects_data_scheme(self) -> None:
        with pytest.raises(ValueError, match="http"):
            CheckoutRequest(
                plan_id="plan_123",
                cancel_url="data:text/html,<script>alert(1)</script>",
            )

    def test_rejects_ftp_scheme(self) -> None:
        with pytest.raises(ValueError, match="http"):
            CheckoutRequest(
                plan_id="plan_123",
                success_url="ftp://evil.com/steal",
            )

    def test_rejects_empty_url(self) -> None:
        with pytest.raises(ValueError, match="URL is required"):
            CheckoutRequest(
                plan_id="plan_123",
                success_url="",
            )

    def test_rejects_url_without_hostname(self) -> None:
        with pytest.raises(ValueError, match="hostname"):
            CheckoutRequest(
                plan_id="plan_123",
                success_url="https://",
            )

    def test_accepts_valid_https_url(self) -> None:
        req = CheckoutRequest(
            plan_id="plan_123",
            success_url="https://app.example.com/billing?status=success",
        )
        assert req.success_url == "https://app.example.com/billing?status=success"

    def test_accepts_valid_http_url(self) -> None:
        req = CheckoutRequest(
            plan_id="plan_123",
            cancel_url="http://localhost:3000/billing?status=cancelled",
        )
        assert "localhost" in req.cancel_url

    def test_rejects_oversized_url(self) -> None:
        long_url = "https://example.com/" + "a" * 3000
        with pytest.raises(ValueError, match="too long"):
            CheckoutRequest(
                plan_id="plan_123",
                success_url=long_url,
            )

    def test_rejects_url_with_only_whitespace(self) -> None:
        with pytest.raises(ValueError, match="URL is required"):
            CheckoutRequest(
                plan_id="plan_123",
                success_url="   ",
            )


class TestUsageMetricOutMetricField:
    def test_valid_metric_name(self) -> None:
        m = UsageMetricOut(metric="messages_sent", used=10)
        assert m.metric == "messages_sent"

    def test_rejects_oversized_metric_name(self) -> None:
        with pytest.raises(ValidationError):
            UsageMetricOut(metric="a" * 51, used=10)
