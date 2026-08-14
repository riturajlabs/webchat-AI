"""Configuration validation tests (production fail-fast security checks)."""

import pytest
from backend.core.config import Settings


def test_production_rejects_short_jwt_secret() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(environment="production", jwt_secret="too-short")


def test_production_rejects_missing_jwt_secret() -> None:
    # No JWT_SECRET provided: the insecure example default must not pass.
    # Skip the dotenv file so a developer's local .env cannot leak a secret
    # into this assertion (tests must be independent of the working env).
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(_env_file=None, environment="production")


def test_production_accepts_32_byte_jwt_secret() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        jwt_secret="a" * 32,
        gemini_api_key="test-key",
        widget_script_url="https://cdn.example.com/webchat-widget.iife.min.js",
    )
    assert len(settings.jwt_secret.encode("utf-8")) >= 32


def test_development_allows_example_jwt_secret() -> None:
    settings = Settings(environment="development", jwt_secret="change-me-in-production")
    assert settings.jwt_secret


def test_trust_proxy_defaults_to_false() -> None:
    assert Settings(_env_file=None).trust_proxy is False


# --- Phase 9 (ADR-009): provider order & fallback configuration ---


def test_provider_order_defaults_to_gemini() -> None:
    settings = Settings(_env_file=None)
    assert settings.generation_provider_order == ["gemini"]
    assert settings.embedding_provider_order == ["gemini"]


def test_production_rejects_settings_with_no_provider_key() -> None:
    with pytest.raises(ValueError, match="generation provider key"):
        Settings(
            _env_file=None,
            environment="production",
            jwt_secret="a" * 32,
            gemini_api_key=None,
            groq_api_key=None,
            openrouter_api_key=None,
        )


def test_production_accepts_groq_as_generation_provider() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        jwt_secret="a" * 32,
        groq_api_key="test-key",
        widget_script_url="https://cdn.example.com/webchat-widget.iife.min.js",
    )
    assert settings.groq_api_key == "test-key"


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8080/webchat-widget.iife.min.js",
        "http://127.0.0.1:8080/webchat-widget.iife.min.js",
        "https://0.0.0.0/webchat-widget.iife.min.js",
    ],
)
def test_production_rejects_localhost_widget_script_url(url: str) -> None:
    # The embed URL is baked into customer pages; a localhost default would
    # break every production embed, so fail fast at boot (audit finding #6).
    with pytest.raises(ValueError, match="WIDGET_SCRIPT_URL"):
        Settings(
            _env_file=None,
            environment="production",
            jwt_secret="a" * 32,
            groq_api_key="test-key",
            widget_script_url=url,
        )


def test_production_accepts_cdn_widget_script_url() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        jwt_secret="a" * 32,
        groq_api_key="test-key",
        widget_script_url="https://assets.example.com/widget.js",
    )
    assert "localhost" not in settings.widget_script_url


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://0.0.0.0:8000",
        "http://[::1]:8000",
    ],
)
def test_production_rejects_localhost_widget_api_base_url(url: str) -> None:
    # The API base is embedded into customer pages via `data-api-base-url`;
    # a localhost value would point every production embed back at the server,
    # so fail fast at boot (audit finding #3).
    with pytest.raises(ValueError, match="WIDGET_API_BASE_URL"):
        Settings(
            _env_file=None,
            environment="production",
            jwt_secret="a" * 32,
            groq_api_key="test-key",
            widget_script_url="https://assets.example.com/widget.js",
            widget_api_base_url=url,
        )


def test_production_accepts_public_widget_api_base_url() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        jwt_secret="a" * 32,
        groq_api_key="test-key",
        widget_script_url="https://assets.example.com/widget.js",
        widget_api_base_url="https://api.example.com",
    )
    assert settings.widget_api_base_url == "https://api.example.com"


def test_production_rejects_empty_embedding_order() -> None:
    with pytest.raises(ValueError, match="EMBEDDING_PROVIDER_ORDER"):
        Settings(
            _env_file=None,
            environment="production",
            jwt_secret="a" * 32,
            gemini_api_key="test-key",
            embedding_provider_order=[],
        )


def test_provider_order_parses_from_json_list() -> None:
    settings = Settings(
        _env_file=None,
        generation_provider_order=["gemini", "openrouter"],
        embedding_provider_order=["ollama"],
    )
    assert settings.generation_provider_order == ["gemini", "openrouter"]
    assert settings.embedding_provider_order == ["ollama"]
    assert settings.ai_provider_timeout_seconds == 60.0
