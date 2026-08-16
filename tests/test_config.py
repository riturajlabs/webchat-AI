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
        payment_provider="stripe",
        stripe_secret_key="sk_test",
        stripe_webhook_secret="whsec_test",
        cors_origins=["https://app.example.com"],
        allowed_hosts=["app.example.com"],
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
        payment_provider="stripe",
        stripe_secret_key="sk_test",
        stripe_webhook_secret="whsec_test",
        cors_origins=["https://app.example.com"],
        allowed_hosts=["app.example.com"],
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
        payment_provider="stripe",
        stripe_secret_key="sk_test",
        stripe_webhook_secret="whsec_test",
        cors_origins=["https://app.example.com"],
        allowed_hosts=["app.example.com"],
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
        payment_provider="stripe",
        stripe_secret_key="sk_test",
        stripe_webhook_secret="whsec_test",
        cors_origins=["https://app.example.com"],
        allowed_hosts=["app.example.com"],
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


# --- Phase 16: production CORS / trusted hosts / rate-limit validation ---

_PRODUCTION_BASE = dict(
    _env_file=None,
    environment="production",
    jwt_secret="a" * 32,
    gemini_api_key="test-key",
    widget_script_url="https://cdn.example.com/webchat-widget.iife.min.js",
    payment_provider="stripe",
    stripe_secret_key="sk_test",
    stripe_webhook_secret="whsec_test",
    cors_origins=["https://app.example.com"],
    allowed_hosts=["app.example.com"],
)


def _prod(**overrides: object) -> dict[str, object]:
    base = dict(_PRODUCTION_BASE)
    base.update(overrides)
    return base


def test_production_rejects_empty_cors_origins() -> None:
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        Settings(**_prod(cors_origins=[]))


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://*.example.com",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://app.example.com",
    ],
)
def test_production_rejects_unsafe_cors_origins(origin: str) -> None:
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        Settings(**_prod(cors_origins=[origin]))


def test_production_rejects_any_unsafe_cors_origin_in_list() -> None:
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        Settings(**_prod(cors_origins=["https://app.example.com", "https://evil.test/*"]))


def test_allowed_hosts_accepts_comma_separated_string() -> None:
    settings = Settings(_env_file=None, allowed_hosts="app.example.com, api.example.com")
    assert settings.allowed_hosts == ["app.example.com", "api.example.com"]


def test_production_rejects_empty_allowed_hosts() -> None:
    with pytest.raises(ValueError, match="ALLOWED_HOSTS"):
        Settings(**_prod(allowed_hosts=[]))


def test_production_rejects_wildcard_allowed_hosts() -> None:
    with pytest.raises(ValueError, match="ALLOWED_HOSTS"):
        Settings(**_prod(allowed_hosts=["*"]))


def test_production_rejects_loopback_only_allowed_hosts() -> None:
    with pytest.raises(ValueError, match="ALLOWED_HOSTS"):
        Settings(**_prod(allowed_hosts=["localhost"]))


def test_effective_allowed_hosts_always_includes_loopback() -> None:
    settings = Settings(**_prod(allowed_hosts=["app.example.com"]))
    hosts = set(settings.effective_allowed_hosts())
    assert "app.example.com" in hosts
    assert "localhost" in hosts
    assert "127.0.0.1" in hosts


def test_production_rejects_disabled_rate_limiting() -> None:
    with pytest.raises(ValueError, match="RATE_LIMIT_ENABLED"):
        Settings(**_prod(rate_limit_enabled=False))


def test_production_accepts_phase16_validation_passing_settings() -> None:
    settings = Settings(**_prod())
    assert settings.environment == "production"
    assert settings.cors_origins == ["https://app.example.com"]


# --- Local production testing (LOCAL_PRODUCTION_TEST) ---

_LOCAL_PROD_BASE = dict(
    _env_file=None,
    environment="production",
    jwt_secret="a" * 32,
    gemini_api_key="test-key",
    local_production_test=True,
    widget_script_url="http://localhost:8080/webchat-widget.iife.min.js",
    widget_api_base_url="http://localhost:8000",
    payment_provider="stripe",
    stripe_secret_key="sk_test",
    stripe_webhook_secret="whsec_test",
    cors_origins=["http://localhost:3000"],
    allowed_hosts=["localhost", "127.0.0.1", "0.0.0.0", "::1"],
)


def _local_prod(**overrides: object) -> dict[str, object]:
    base = dict(_LOCAL_PROD_BASE)
    base.update(overrides)
    return base


def test_local_production_test_allows_loopback_urls() -> None:
    """The explicit flag accepts localhost URLs so production can run locally."""
    settings = Settings(**_local_prod())
    assert settings.environment == "production"
    assert settings.local_production_test is True
    assert settings.widget_script_url.startswith("http://localhost")
    assert settings.widget_api_base_url.startswith("http://localhost")


def test_local_production_test_flag_defaults_to_false() -> None:
    assert Settings(_env_file=None).local_production_test is False


def test_production_rejects_loopback_without_local_production_test() -> None:
    """Without the flag, production still fails fast on loopback URLs/hosts."""
    with pytest.raises(ValueError, match="WIDGET_SCRIPT_URL"):
        Settings(**_prod(widget_script_url="http://localhost:8080/widget.js"))


def test_local_production_test_still_requires_strong_jwt_secret() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(**_local_prod(jwt_secret="too-short"))


def test_local_production_test_still_requires_generation_provider_key() -> None:
    with pytest.raises(ValueError, match="generation provider key"):
        Settings(**_local_prod(gemini_api_key=None, groq_api_key=None, openrouter_api_key=None))


def test_local_production_test_still_rejects_mock_payments() -> None:
    with pytest.raises(ValueError, match="PAYMENT_PROVIDER"):
        Settings(**_local_prod(payment_provider="mock"))


def test_local_production_test_still_rejects_disabled_rate_limiting() -> None:
    with pytest.raises(ValueError, match="RATE_LIMIT_ENABLED"):
        Settings(**_local_prod(rate_limit_enabled=False))


def test_local_production_test_still_rejects_wildcard_cors() -> None:
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        Settings(**_local_prod(cors_origins=["*", "http://localhost:3000"]))


def test_local_production_test_still_rejects_http_public_cors_origin() -> None:
    """Only loopback origins may be plain HTTP; a public http:// origin stays banned."""
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        Settings(**_local_prod(cors_origins=["http://app.example.com"]))


def test_local_production_test_still_rejects_wildcard_allowed_hosts() -> None:
    with pytest.raises(ValueError, match="ALLOWED_HOSTS"):
        Settings(**_local_prod(allowed_hosts=["*"]))
