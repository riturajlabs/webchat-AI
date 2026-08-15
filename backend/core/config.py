"""Application configuration loaded from environment variables (see .env.example)."""

import json
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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

    # Reverse-proxy trust. When True, `X-Forwarded-For` is honored for client
    # IP extraction (rate limiting); must only be enabled behind a trusted proxy.
    trust_proxy: bool = False

    # Trusted Host header values (Phase 16). The API rejects requests whose
    # `Host` header is not listed here (TrustedHostMiddleware). Accepts a
    # comma-separated string or a JSON array from the environment. Loopback
    # hosts are always allowed on top of this list (container health checks),
    # and production validation requires at least one public hostname.
    allowed_hosts: Annotated[list[str], NoDecode] = [
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        "testserver",
    ]

    # Auth cookies (ADR-003)
    refresh_cookie_name: str = "refresh_token"
    csrf_cookie_name: str = "csrf_token"
    cookie_secure: bool = True
    email_verify_token_expire_minutes: int = 60 * 24
    password_reset_token_expire_minutes: int = 30

    # Rate limiting
    rate_limit_enabled: bool = True

    # MongoDB (Motor)
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "webchat_ai"
    mongodb_min_pool_size: int = 10
    mongodb_max_pool_size: int = 100
    mongodb_server_selection_timeout_ms: int = 30000

    # Redis
    redis_url: str = "redis://localhost:6379"
    redis_prefix: str = "webchat_ai"

    # CORS / public URLs. Local dev sites commonly serve the widget embed from
    # Live Server (port 5500); production origins are set via CORS_ORIGINS.
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
    ]
    public_base_url: str = "http://localhost:3000"
    # Where the built widget SDK bundle is served from (embed-script generation).
    widget_script_url: str = "http://localhost:8080/webchat-widget.iife.min.js"
    # Public origin of the widget API, e.g. `https://api.example.com`. When set,
    # the generated embed script carries `data-api-base-url` so the widget talks
    # to the SaaS API even if the served bundle was built for an older origin
    # (or a stale cached bundle). Empty = rely on the build-time
    # `VITE_WIDGET_API_BASE_URL` / same-origin default baked into the bundle.
    widget_api_base_url: str = ""

    # Public widget API (Phase 8, ADR-004 §widget).
    widget_session_token_minutes: int = 15
    widget_session_validity_hours: int = 24
    widget_config_cache_seconds: int = 300
    widget_per_widget_limit: int = 60
    widget_per_visitor_limit: int = 20
    widget_session_issue_limit: int = 30
    # Per-visitor feedback submissions per minute (Phase 12.4). Feedback is
    # write-once per message, so a modest budget bounds abuse without getting
    # in the way of legitimate ratings.
    widget_feedback_limit: int = 30
    # Per-IP budget per widget endpoint / minute (production hardening). The
    # entity-keyed limits (widget/visitor) can be rotated by a hostile client -
    # `visitor_id` is client-supplied - so an IP-shaped budget that a bot farm
    # cannot trivially rotate backs them up.
    widget_ip_limit: int = 120
    widget_max_messages_per_session: int = 50
    # Master switch for the widget rate limits; `None` inherits the global
    # `rate_limit_enabled` (resolved in the validator below).
    widget_rate_limit_enabled: bool | None = None

    # Per-API-key requests per minute (Sprint 2). Programmatic `wc_*` keys get
    # their own sliding window keyed by key id, independent of the per-IP
    # budgets applied to the same endpoints.
    api_key_rate_limit_per_minute: int = 300

    # Email (Phase 2 - ADR-001)
    resend_api_key: str | None = None
    email_from: str = "WebChat AI <no-reply@webchatai.example>"
    mailpit_api_url: str = "http://localhost:8025"

    # AI (Phase 4-6)
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    embedding_model: str = "gemini-embedding-001"

    # AI provider abstraction (Phase 9, ADR-009). Ordered fallback chains:
    # providers are tried in the order listed; a provider whose required API
    # key is missing is skipped and the next provider is attempted. Unknown
    # names are a configuration error and fail fast.
    generation_provider_order: list[str] = ["gemini"]
    embedding_provider_order: list[str] = ["gemini"]

    # Fallback generation providers (OpenAI-compatible chat completions API).
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    openrouter_api_key: str | None = None
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct"

    # Local embedding fallback (self-hosted, no API key; ADR-009).
    # CAUTION: only use an embedding fallback whose vector dimension matches
    # the primary provider, or vector search on a mixed corpus breaks.
    embedding_dimensions: int = 3072
    # Shared HTTP timeout for non-Gemini providers (Groq/OpenRouter/Ollama).
    ai_provider_timeout_seconds: float = 60.0

    # Ollama (local embedding fallback, ADR-009).
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "nomic-embed-text"
    ollama_embedding_dimensions: int = 768

    # Knowledge processing (Phase 5, docs/06 implementation plan).
    # Approximate-token chunk sizing (docs/02-TRD.md §6: 500-800 tokens/chunk,
    # 100-token overlap).
    knowledge_chunk_size_tokens: int = 700
    knowledge_chunk_overlap_tokens: int = 100
    # Embedding client (Google gemini-embedding-001 via the Gemini API, ADR-008).
    # The API key is never logged and never exposed through any API (00 rules §12).
    embedding_batch_size: int = 32
    embedding_max_retries: int = 5
    embedding_retry_base_delay_ms: int = 500
    # Fail a document's embedding pass when a single batch error exceeds this.
    embedding_request_timeout_seconds: float = 60.0
    # Document-level embedding retries (production hardening): a temporary
    # embedding outage must not permanently fail every queued document in one
    # crawl fan-out. A failed attempt re-enqueues the document with a growing
    # delay; only permanent failures (missing API key, insufficient content,
    # retries exhausted) land in the dashboard's failed list.
    knowledge_max_document_retries: int = 3
    # First retry waits this long (seconds); each subsequent retry multiplies
    # by the factor => 5s, 30s, 180s for the default 3-retry budget.
    knowledge_retry_base_delay_seconds: float = 5.0
    knowledge_retry_backoff_factor: float = 6.0
    # Cleaned page text below this length is too thin to embed usefully; such
    # pages are marked failed with "Insufficient content" instead of silently
    # skipped or embedded into near-empty chunks.
    knowledge_min_content_chars: int = 100

    # Ingestion engine (Phase 4, docs/06 implementation plan).
    crawl_max_pages: int = 50
    crawl_max_depth: int = 3
    crawl_navigation_timeout_ms: int = 30000
    # Cap on a single page's rendered HTML (response size limit); the browser
    # truncates at this ceiling and the crawler skips anything still over it.
    crawl_max_html_bytes: int = 5_000_000
    # Cap on the cleaned text stored per page (docs/05, Phase 5 chunking input).
    crawl_max_content_bytes: int = 200_000
    crawl_max_concurrent: int = 2
    crawl_browser_user_agent: str = "WebChatAI-Crawler/1.0"
    # Chrome's sandbox needs a non-root runtime; the dev/worker image runs as
    # root so `--no-sandbox` is the default. Keep `false` behind a non-root
    # production image (00-AI-Development-Rules §11).
    crawl_no_sandbox: bool = True

    # RAG pipeline (Phase 6, docs/02-TRD.md §8 + ADR-008).
    # Versioned answer prompt selected from backend/prompts/rag.py.
    rag_prompt_version: int = 1
    # Retrieval depth: tenant-filtered Top-5 vector search (ADR-008 Phase 6).
    chat_top_k: int = 5
    # Conversation turns fed to the model as memory (most recent N).
    chat_memory_turns: int = 8
    # Character cap per retrieved chunk when building the model context.
    chat_context_chunk_chars: int = 4000
    # Question sanitization cap (prompt-injection defense, TRD §8).
    chat_question_max_chars: int = 2000
    # Generation settings for the Gemini answer stream.
    chat_max_output_tokens: int = 1024
    chat_temperature: float = 0.2
    generation_timeout_seconds: float = 60.0
    # Conversation/session retention (ADR-005 §5.7; TTL safety net is 90 days).
    chat_retention_days: int = 90
    # Daily usage rollup retention (ADR-005 §5.7: 3 years).
    usage_retention_days: int = 365 * 3

    # Analytics (Phase 11.3, docs/02-TRD.md §11): estimated-cost list prices,
    # expressed per million tokens in USD. These are *estimates* for the
    # dashboard - billing reconciles against provider invoices.
    cost_per_million_input_tokens: float = 0.30
    cost_per_million_output_tokens: float = 1.50

    # Platform operations (Phase 15): emails granted the `super_admin` role,
    # the only role allowed on the `/api/admin/*` surface (backend/core/rbac.py).
    # Comma-separated, case-insensitive. Empty = no super admins configured
    # (every admin API call returns 403).
    super_admin_emails: list[str] = []

    # Payments (Phase 14, SaaS subscriptions). `payment_provider` selects the
    # abstraction implementation: "stripe", "razorpay" or "mock" (dev/tests).
    # In production only stripe/razorpay pass validation, with the provider's
    # keys required. `payment_currency` is the ISO 4217 code billed via
    # checkout (plan prices in `backend/models/plan.py` are its minor units).
    payment_provider: str = "mock"
    payment_currency: str = "USD"
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_webhook_secret: str | None = None

    # Performance instrumentation (Phase 12.1; opt-in, disabled by default).
    # When true, per-request HTTP timing, AI provider timings (TTFT/total) and
    # worker job durations are logged as structured records. Never enabled in
    # production - it is a load-testing/observability aid.
    perf_timing_log_enabled: bool = False
    # Log MongoDB commands slower than this threshold (ms); 0 disables.
    mongodb_slow_query_threshold_ms: int = 0

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def _parse_allowed_hosts(cls, value: object) -> object:
        """Accept a comma-separated string or a JSON array for ALLOWED_HOSTS.

        `NoDecode` on the field skips pydantic-settings' automatic JSON decode
        of complex fields, so the raw environment value reaches this validator.
        """
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                try:
                    return json.loads(stripped)
                except json.JSONDecodeError:
                    raise ValueError(
                        "ALLOWED_HOSTS must be a JSON array or comma-separated "
                        f"list, got: {value!r}"
                    ) from None
            return [host.strip() for host in value.split(",") if host.strip()]
        return value

    def effective_allowed_hosts(self) -> list[str]:
        """Host header values the API accepts.

        Loopback hosts are always appended: the API's own container health
        checks target `localhost`, and a hosted database/queue never appears as
        the request Host. The configured public hostnames gate real traffic.
        """
        hosts = set(self.allowed_hosts)
        hosts.update({"localhost", "127.0.0.1", "0.0.0.0", "::1"})
        return sorted(hosts)

    @model_validator(mode="after")
    def _validate_production_security(self) -> "Settings":
        """Fail fast on weak production secrets (00-AI-Development-Rules §20)."""
        if self.environment.lower() == "production":
            if len(self.jwt_secret.encode("utf-8")) < 32:
                raise ValueError("JWT_SECRET must be at least 32 bytes in production.")
            # At least one provider per capability must be configured (ADR-009).
            generation_keys = bool(
                self.gemini_api_key or self.groq_api_key or self.openrouter_api_key
            )
            if not generation_keys:
                raise ValueError(
                    "At least one generation provider key is required in production "
                    "(GEMINI_API_KEY, GROQ_API_KEY or OPENROUTER_API_KEY)."
                )
            if not self.embedding_provider_order:
                raise ValueError("EMBEDDING_PROVIDER_ORDER must not be empty in production.")
            if not self.embedding_provider_order or self.embedding_dimensions <= 0:
                raise ValueError("EMBEDDING_DIMENSIONS must be a positive integer in production.")
            # The embed script URL is baked into the dashboard embed code and
            # into customer pages; a localhost default would break every embed.
            if any(
                marker in self.widget_script_url.lower()
                for marker in ("localhost", "127.0.0.1", "0.0.0.0", "::1")
            ):
                raise ValueError(
                    "WIDGET_SCRIPT_URL must point at a real CDN/host in production "
                    "(got a localhost value)."
                )
            # The widget API base is embedded into customer pages via
            # `data-api-base-url`; a localhost value would break every embed.
            if self.widget_api_base_url and any(
                marker in self.widget_api_base_url.lower()
                for marker in ("localhost", "127.0.0.1", "0.0.0.0", "::1")
            ):
                raise ValueError(
                    "WIDGET_API_BASE_URL must point at a real API origin in production "
                    "(got a localhost value)."
                )
            # Payments fail closed: a real gateway + its keys are mandatory.
            if self.payment_provider.lower() not in ("stripe", "razorpay"):
                raise ValueError(
                    "PAYMENT_PROVIDER must be 'stripe' or 'razorpay' in production "
                    "(got a mock/unset value)."
                )
            if self.payment_provider.lower() == "stripe" and (
                not self.stripe_secret_key or not self.stripe_webhook_secret
            ):
                raise ValueError(
                    "STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET are required in production."
                )
            if self.payment_provider.lower() == "razorpay" and (
                not self.razorpay_key_id
                or not self.razorpay_key_secret
                or not self.razorpay_webhook_secret
            ):
                raise ValueError(
                    "RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET and RAZORPAY_WEBHOOK_SECRET "
                    "are required in production."
                )
            # CORS (Phase 16): the dashboard surface sends credentials, so a
            # wildcard/loopback origin would either leak cookies to any site or
            # silently break every browser request. Fail fast at boot.
            if not self.cors_origins:
                raise ValueError("CORS_ORIGINS must not be empty in production.")
            for origin in self.cors_origins:
                lowered = origin.lower()
                if "*" in lowered:
                    raise ValueError(
                        f"CORS_ORIGINS must not contain wildcard origins in production ({origin})."
                    )
                if any(
                    marker in lowered
                    for marker in ("localhost", "127.0.0.1", "0.0.0.0", "::1")
                ):
                    raise ValueError(
                        f"CORS_ORIGINS must not contain loopback origins in production ({origin})."
                    )
                if not lowered.startswith("https://"):
                    raise ValueError(
                        f"CORS_ORIGINS entries must be HTTPS origins in production ({origin})."
                    )
            # Trusted hosts (Phase 16): without an explicit allowlist, host-header
            # poisoning could route requests anywhere. Require at least one real
            # public hostname (loopback-only lists are a misconfiguration).
            if not self.allowed_hosts:
                raise ValueError("ALLOWED_HOSTS must not be empty in production.")
            if "*" in self.allowed_hosts:
                raise ValueError(
                    "ALLOWED_HOSTS must not contain wildcard entries in production."
                )
            loopback_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "testserver"}
            if not any(host not in loopback_hosts for host in self.allowed_hosts):
                raise ValueError(
                    "ALLOWED_HOSTS must include the public hostname(s) in production."
                )
            # Rate limiting (Phase 16): every route-level limiter gates on
            # `rate_limit_enabled`; silently disabling it in production would
            # expose the API to abuse.
            if not self.rate_limit_enabled:
                raise ValueError("RATE_LIMIT_ENABLED must be true in production.")
        if self.widget_rate_limit_enabled is None:
            self.widget_rate_limit_enabled = self.rate_limit_enabled
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings singleton."""
    return Settings()
