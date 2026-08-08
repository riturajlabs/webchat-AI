"""Email template rendering tests (ADR-001)."""

from backend.services.mail import build_email, render_email


def test_verify_email_template_renders_context() -> None:
    url = "http://localhost:3000/verify-email?token=abc123"
    text, html = render_email("verify_email", name="Alice", verification_url=url)
    assert "Alice" in text
    assert "abc123" in text
    assert "Alice" in html
    assert "abc123" in html


def test_reset_password_template_renders_context() -> None:
    url = "http://localhost:3000/reset-password?token=xyz789"
    text, html = render_email("reset_password", name="Bob", reset_url=url)
    assert "Bob" in text
    assert "xyz789" in text
    assert "Bob" in html
    assert "xyz789" in html


def test_security_alert_template_renders_context() -> None:
    text, html = render_email("security_alert", name="Carol")
    assert "Carol" in text
    assert "Carol" in html


def test_build_email_wraps_rendered_message() -> None:
    message = build_email(
        "alice@example.com",
        "Verify your email address",
        "verify_email",
        name="Alice",
        verification_url="http://localhost:3000/verify-email?token=abc123",
    )
    assert message.to == "alice@example.com"
    assert message.subject == "Verify your email address"
    assert message.text
    assert message.html
    payload = message.to_payload()
    assert payload["to"] == "alice@example.com"
    assert payload["subject"] == "Verify your email address"
