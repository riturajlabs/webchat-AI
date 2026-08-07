"""Application configuration loaded from environment variables (see .env.example)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings object. Values come from environment variables or a
    local `.env` file. Never hardcode secrets - see 00-AI-Development-Rules.md.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "webchat-ai"
    environment: str = "development"
    debug: bool = False

    backend_host: str = "0.0.0.0"
    backend_port: int = 8000

    # Security
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30

    # MongoDB (Motor)
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "webchat_ai"
    mongodb_min_pool_size: int = 10
    mongodb_max_pool_size: int = 100

    # Redis
    redis_url: str = "redis://localhost:6379"
    redis_prefix: str = "webchat_ai"

    # CORS / public URLs
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8000"]
    public_base_url: str = "http://localhost:3000"

    # Email (Phase 2 - ADR-001)
    resend_api_key: str | None = None
    email_from: str = "WebChat AI <no-reply@webchatai.example>"

    # AI (Phase 4-6)
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    embedding_model: str = "text-embedding-004"


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings singleton."""
    return Settings()
