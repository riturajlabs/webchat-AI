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
    settings = Settings(environment="production", jwt_secret="a" * 32)
    assert len(settings.jwt_secret.encode("utf-8")) >= 32


def test_development_allows_example_jwt_secret() -> None:
    settings = Settings(environment="development", jwt_secret="change-me-in-production")
    assert settings.jwt_secret


def test_trust_proxy_defaults_to_false() -> None:
    assert Settings(_env_file=None).trust_proxy is False
