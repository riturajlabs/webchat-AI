"""Configuration validation tests (production fail-fast security checks)."""

import pytest
from backend.core.config import Settings


def test_production_rejects_short_jwt_secret() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(environment="production", jwt_secret="too-short")


def test_production_rejects_missing_jwt_secret() -> None:
    # An empty/unset JWT_SECRET must never pass in production, even now that
    # the development default is strong. Skip the dotenv file so a developer's
    # local .env cannot leak a secret into this assertion.
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(_env_file=None, environment="production", jwt_secret="")


def test_production_accepts_32_byte_jwt_secret() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        jwt_secret="a" * 32,
        gemini_api_key="test-key",
        enable_docs=False,
        widget_script_url="https://cdn.example.com/webchat-widget.iife.min.js",
        payment_provider="stripe",
        stripe_secret_key="sk_test",
        stripe_webhook_secret="whsec_test",
        cors_origins=["https://app.example.com"],
        allowed_hosts=["app.example.com"],
        mongo_username="test-user",
        mongo_password="test-pass",
        redis_password="test-pass",
    )
    assert len(settings.jwt_secret.encode("utf-8")) >= 32


@pytest.mark.parametrize(
    "secret",
    [
        "dev-only-jwt-secret-change-me-please",
        "CHANGE_ME-change_me-change_me",
        "a" * 20 + "-your-secret-" + "b" * 4,
    ],
)
def test_production_rejects_placeholder_jwt_secret(secret: str) -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(**_prod(jwt_secret=secret))


def test_local_production_test_rejects_placeholder_jwt_secret() -> None:
    # Even under the local-production-test flag a placeholder signing key is
    # unsafe, and the flag must never mask it (Phase 14.9.5).
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(**_local_prod(jwt_secret="dev-only-jwt-secret-change-me-please"))


def test_production_accepts_real_hex_jwt_secret() -> None:
    settings = Settings(**_prod(jwt_secret="5f" * 32))
    assert len(settings.jwt_secret.encode("utf-8")) == 64


def test_development_allows_example_jwt_secret() -> None:
    settings = Settings(environment="development", jwt_secret="change-me-in-production")
    assert settings.jwt_secret


def test_default_jwt_secret_is_at_least_32_bytes() -> None:
    # The development/test fallback must never regress below 32 bytes, or
    # PyJWT's InsecureKeyLengthWarning (RFC 7518 §3.2) fires in every dev/test
    # stack that relies on the default.
    settings = Settings(_env_file=None)
    assert len(settings.jwt_secret.encode("utf-8")) >= 32


def test_production_rejects_class_default_jwt_secret() -> None:
    # A production deploy that omits JWT_SECRET falls back to the dev default
    # `dev-only-jwt-secret-change-me-please`; startup must fail (SEC-7 / S-03).
    # Build a valid prod config with every other required field but leave the
    # secret unset so only the default-secret rejection can fire.
    base = dict(_PRODUCTION_BASE)
    del base["jwt_secret"]
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(**base)


def test_trust_proxy_defaults_to_false() -> None:
    assert Settings(_env_file=None).trust_proxy is False


# --- Redis URL validation ---


@pytest.mark.parametrize(
    "url",
    [
        "redis://redis:6379",
        "rediss://default:secret@renewed-cricket.example.com:6379",
        "unix:///tmp/redis.sock",
    ],
)
def test_valid_redis_url_schemes_accepted(url: str) -> None:
    assert Settings(_env_file=None, redis_url=url).redis_url == url


@pytest.mark.parametrize(
    "url",
    [
        "REDIS_URL=rediss://default:secret@host:6379",
        "http://redis:6379",
        "mongodb://localhost:27017",
        "foo://bar",
        "",
        "   ",
    ],
)
def test_invalid_redis_url_schemes_rejected(url: str) -> None:
    with pytest.raises(ValueError, match="REDIS_URL"):
        Settings(_env_file=None, redis_url=url)


# --- Phase 9 (ADR-009): provider order & fallback configuration ---


def test_provider_order_defaults_to_gemini() -> None:
    settings = Settings(_env_file=None)
    assert settings.generation_provider_order == ["gemini"]
    assert settings.embedding_provider_order == ["gemini"]


def test_groq_model_default_is_currently_hosted() -> None:
    """An unset GROQ_MODEL must never fall back to a retired model id.

    Groq shut down `llama-3.3-70b-versatile` on 2026-08-16; requests to it
    return HTTP 404, which silently kills the Groq fallback path. The default
    therefore points at a model verified live on the current Groq API.
    """
    settings = Settings(_env_file=None)
    assert settings.groq_model == "openai/gpt-oss-20b"


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
        enable_docs=False,
        widget_script_url="https://cdn.example.com/webchat-widget.iife.min.js",
        payment_provider="stripe",
        stripe_secret_key="sk_test",
        stripe_webhook_secret="whsec_test",
        cors_origins=["https://app.example.com"],
        allowed_hosts=["app.example.com"],
        mongo_username="test-user",
        mongo_password="test-pass",
        redis_password="test-pass",
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
        enable_docs=False,
        widget_script_url="https://assets.example.com/widget.js",
        payment_provider="stripe",
        stripe_secret_key="sk_test",
        stripe_webhook_secret="whsec_test",
        cors_origins=["https://app.example.com"],
        allowed_hosts=["app.example.com"],
        mongo_username="test-user",
        mongo_password="test-pass",
        redis_password="test-pass",
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
        enable_docs=False,
        widget_script_url="https://assets.example.com/widget.js",
        widget_api_base_url="https://api.example.com",
        payment_provider="stripe",
        stripe_secret_key="sk_test",
        stripe_webhook_secret="whsec_test",
        cors_origins=["https://app.example.com"],
        allowed_hosts=["app.example.com"],
        mongo_username="test-user",
        mongo_password="test-pass",
        redis_password="test-pass",
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
        embedding_provider_order=["jina", "cohere"],
    )
    assert settings.generation_provider_order == ["gemini", "openrouter"]
    assert settings.embedding_provider_order == ["jina", "cohere"]
    assert settings.ai_provider_timeout_seconds == 10.0


def test_latency_settings_are_fail_fast_by_default() -> None:
    """Phase 12.6: provider/LLM timeouts are bounded so a hung upstream fails
    fast into the fallback chain instead of stalling the chat."""
    settings = Settings(_env_file=None)
    assert settings.ai_provider_timeout_seconds == 10.0
    assert settings.generation_timeout_seconds == 30.0
    assert settings.generation_first_token_timeout_seconds == 10.0
    assert settings.embedding_request_timeout_seconds == 10.0
    assert settings.embedding_max_retries == 3
    assert settings.chat_embedding_max_retries == 1
    assert settings.chat_retrieval_cache_ttl_seconds == 900
    assert settings.chat_retrieval_cache_size == 512
    assert settings.chat_context_max_chars == 20000
    assert settings.chat_context_min_score == 0.25


# --- Phase 9: configurable SSE idle timeout ---


def test_sse_idle_timeout_default() -> None:
    """Default SSE idle timeout is 1800 seconds (30 minutes)."""
    settings = Settings(_env_file=None)
    assert settings.sse_idle_timeout == 1800


def test_sse_idle_timeout_configurable() -> None:
    """SSE idle timeout can be overridden via environment variable."""
    settings = Settings(_env_file=None, sse_idle_timeout=600)
    assert settings.sse_idle_timeout == 600


# --- embedding fallback configuration (ADR-009, cloud providers) ---


def test_embedding_default_dimension_matches_cloud_fallback() -> None:
    settings = Settings(_env_file=None)
    assert settings.embedding_dimensions == 1024
    assert settings.jina_embedding_dimensions == 1024
    assert settings.cohere_embedding_dimensions == 1024
    assert settings.jina_embedding_model == "jina-embeddings-v3"
    assert settings.cohere_embedding_model == "embed-multilingual-v3.0"


def test_jina_dimension_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="JINA_EMBEDDING_DIMENSIONS"):
        Settings(
            _env_file=None,
            embedding_provider_order=["gemini", "jina"],
            embedding_dimensions=1024,
            jina_embedding_dimensions=512,
        )


def test_cohere_dimension_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="COHERE_EMBEDDING_DIMENSIONS"):
        Settings(
            _env_file=None,
            embedding_provider_order=["gemini", "cohere"],
            embedding_dimensions=1024,
            cohere_embedding_dimensions=512,
        )


def test_unlisted_provider_dimension_mismatch_is_allowed() -> None:
    # A provider NOT in EMBEDDING_PROVIDER_ORDER is dormant; mismatched dims
    # only matter once it is actually added to the chain.
    settings = Settings(
        _env_file=None,
        embedding_provider_order=["gemini"],
        embedding_dimensions=1024,
        jina_embedding_dimensions=512,
        cohere_embedding_dimensions=768,
    )
    assert settings.jina_embedding_dimensions == 512


def test_embedding_dimensions_positive() -> None:
    with pytest.raises(ValueError, match="EMBEDDING_DIMENSIONS"):
        Settings(_env_file=None, embedding_dimensions=0)


def test_production_allows_keyless_embedding_provider() -> None:
    # jina is the ONLY provider in the order and it has no key. Production
    # must still boot: the registry skips the keyless provider gracefully and
    # the next one (none) is only reached if a call happens (ADR-009). A
    # missing key is a warning, never a startup crash.
    settings = Settings(
        _env_file=None,
        environment="production",
        jwt_secret="a" * 32,
        groq_api_key="test-key",
        enable_docs=False,
        widget_script_url="https://cdn.example.com/webchat-widget.iife.min.js",
        payment_provider="stripe",
        stripe_secret_key="sk_test",
        stripe_webhook_secret="whsec_test",
        cors_origins=["https://app.example.com"],
        allowed_hosts=["app.example.com"],
        mongo_username="test-user",
        mongo_password="test-pass",
        redis_password="test-pass",
        embedding_provider_order=["jina"],
        jina_api_key=None,
    )
    assert settings.embedding_provider_order == ["jina"]


def test_production_allows_partial_missing_fallback_key() -> None:
    # gemini is present, jina is keyless: the registry skips jina gracefully
    # and the chain still serves. Production must NOT crash here.
    settings = Settings(
        _env_file=None,
        environment="production",
        jwt_secret="a" * 32,
        gemini_api_key="test-key",
        enable_docs=False,
        widget_script_url="https://cdn.example.com/webchat-widget.iife.min.js",
        payment_provider="stripe",
        stripe_secret_key="sk_test",
        stripe_webhook_secret="whsec_test",
        cors_origins=["https://app.example.com"],
        allowed_hosts=["app.example.com"],
        mongo_username="test-user",
        mongo_password="test-pass",
        redis_password="test-pass",
        embedding_provider_order=["gemini", "jina"],
        jina_api_key=None,
    )
    assert settings.embedding_provider_order == ["gemini", "jina"]


# --- Phase 16: production CORS / trusted hosts / rate-limit validation ---

_PRODUCTION_BASE = dict(
    _env_file=None,
    environment="production",
    jwt_secret="a" * 32,
    gemini_api_key="test-key",
    enable_docs=False,
    widget_script_url="https://cdn.example.com/webchat-widget.iife.min.js",
    payment_provider="stripe",
    stripe_secret_key="sk_test",
    stripe_webhook_secret="whsec_test",
    cors_origins=["https://app.example.com"],
    allowed_hosts=["app.example.com"],
    mongo_username="test-user",
    mongo_password="test-pass",
    redis_password="test-pass",
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
    enable_docs=False,
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


# --- Phase 17: Resend sender + Razorpay webhook secret validation ---


def test_production_rejects_resend_sandbox_sender() -> None:
    with pytest.raises(ValueError, match="EMAIL_FROM.*Resend sandbox"):
        Settings(**_prod(email_from="WebChat AI <onboarding@resend.dev>"))


def test_production_rejects_resend_sandbox_no_reply_sender() -> None:
    with pytest.raises(ValueError, match="EMAIL_FROM.*Resend sandbox"):
        Settings(**_prod(email_from="WebChat AI <no-reply@resend.dev>"))


def test_production_accepts_verified_custom_domain_sender() -> None:
    settings = Settings(**_prod(email_from="WebChat AI <no-reply@webchatai.example>"))
    assert "webchatai.example" in settings.email_from


def test_production_rejects_razorpay_webhook_secret_url() -> None:
    with pytest.raises(ValueError, match="RAZORPAY_WEBHOOK_SECRET.*URL"):
        Settings(
            **_prod(
                payment_provider="razorpay",
                razorpay_key_id="rzp_test",
                razorpay_key_secret="secret",
                stripe_secret_key=None,
                stripe_webhook_secret=None,
                razorpay_webhook_secret="https://dashboard.razorpay.com/whsec_test",
            )
        )


def test_production_accepts_valid_razorpay_webhook_secret() -> None:
    settings = Settings(
        **_prod(
            payment_provider="razorpay",
            razorpay_key_id="rzp_test",
            razorpay_key_secret="secret",
            stripe_secret_key=None,
            stripe_webhook_secret=None,
            razorpay_webhook_secret="whsec_abc123def456",
        )
    )
    assert settings.razorpay_webhook_secret == "whsec_abc123def456"


def test_local_production_test_allows_resend_sandbox_sender() -> None:
    settings = Settings(**_local_prod(email_from="WebChat AI <onboarding@resend.dev>"))
    assert "onboarding@resend.dev" in settings.email_from


def test_local_production_test_allows_razorpay_webhook_url() -> None:
    settings = Settings(
        **_local_prod(
            payment_provider="razorpay",
            razorpay_key_id="rzp_test",
            razorpay_key_secret="secret",
            stripe_secret_key=None,
            stripe_webhook_secret=None,
            razorpay_webhook_secret="http://localhost:8000/api/webhooks/razorpay",
        )
    )
    assert "localhost" in settings.razorpay_webhook_secret


# --- Phase 14.3: production DEBUG / ENABLE_DOCS / body-limit validation ---


def test_production_rejects_debug_enabled() -> None:
    with pytest.raises(ValueError, match="DEBUG"):
        Settings(**_prod(debug=True))


def test_production_rejects_enable_docs_enabled() -> None:
    with pytest.raises(ValueError, match="ENABLE_DOCS"):
        Settings(**_prod(enable_docs=True))


def test_production_accepts_debug_false_enable_docs_false() -> None:
    settings = Settings(**_prod(debug=False, enable_docs=False))
    assert settings.debug is False
    assert settings.enable_docs is False


def test_development_allows_debug_and_docs() -> None:
    settings = Settings(_env_file=None, debug=True, enable_docs=True)
    assert settings.debug is True
    assert settings.enable_docs is True


def test_local_production_test_still_rejects_debug() -> None:
    with pytest.raises(ValueError, match="DEBUG"):
        Settings(**_local_prod(debug=True))


def test_local_production_test_still_rejects_enable_docs() -> None:
    with pytest.raises(ValueError, match="ENABLE_DOCS"):
        Settings(**_local_prod(enable_docs=True))


def test_request_body_max_bytes_default() -> None:
    settings = Settings(_env_file=None)
    assert settings.request_body_max_bytes == 10 * 1024 * 1024


def test_request_body_max_bytes_too_small() -> None:
    with pytest.raises(ValueError, match="REQUEST_BODY_MAX_BYTES"):
        Settings(_env_file=None, request_body_max_bytes=100)


def test_request_body_max_bytes_configurable() -> None:
    settings = Settings(_env_file=None, request_body_max_bytes=1024)
    assert settings.request_body_max_bytes == 1024


# --- Phase 14.4: production cookie_secure + auth security ---


def test_production_rejects_insecure_cookies() -> None:
    with pytest.raises(ValueError, match="COOKIE_SECURE"):
        Settings(**_prod(cookie_secure=False))


def test_production_accepts_secure_cookies() -> None:
    settings = Settings(**_prod(cookie_secure=True))
    assert settings.cookie_secure is True


def test_development_allows_insecure_cookies() -> None:
    settings = Settings(_env_file=None, cookie_secure=False)
    assert settings.cookie_secure is False


def test_local_production_test_allows_insecure_cookies() -> None:
    # The local harness runs the full stack over plain HTTP on loopback, so
    # the Secure cookie flag must be relaxable under the explicit flag
    # (mirrors .env.production's COOKIE_SECURE=false + LOCAL_PRODUCTION_TEST=true
    # and the loopback URL relaxations). Real production still rejects it.
    settings = Settings(**_local_prod(cookie_secure=False))
    assert settings.cookie_secure is False
