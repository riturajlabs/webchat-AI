"""Application configuration loaded from environment variables (see .env.example)."""

import json
from functools import lru_cache
from typing import Annotated
from urllib.parse import urlparse

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_RESEND_SANDBOX_SENDERS = frozenset(
    {
        "onboarding@resend.dev",
        "no-reply@resend.dev",
        "notifications@resend.dev",
    }
)

_RAZORPAY_WEBHOOK_URL_MARKERS = frozenset(
    {
        "https://",
        "http://",
        "dashboard.razorpay.com",
    }
)


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

    # Explicit local-production-testing mode. When True, `environment` stays
    # "production" (so all production code paths - JSON logs, Resend mail, real
    # payment gateways, rate limiting - are exercised) but loopback
    # (localhost / 127.0.0.1 / 0.0.0.0 / ::1) URLs and HTTP CORS origins are
    # accepted so the stack can run on a local machine over plain HTTP.
    #
    # This flag is STRICTLY opt-in and must NEVER be set in a real deployment
    # (Railway etc.): a deployed production install must use public HTTPS URLs,
    # secure cookies and a trusted proxy. It only relaxes the URL/host
    # validators; every other production security check still applies.
    # See .env.example ("LOCAL_PRODUCTION_TEST").
    local_production_test: bool = False

    backend_host: str = "0.0.0.0"
    backend_port: int = 8000

    # Security
    # Development/test fallback only. Strong enough (>= 32 bytes) that PyJWT's
    # InsecureKeyLengthWarning (RFC 7518 §3.2) never fires in dev/test stacks;
    # production enforces its own minimum and rejects weak values at boot.
    jwt_secret: str = "dev-only-jwt-secret-change-me-please"
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

    # Account lockout (SEC-3)
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15

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
    # Dedicated per-IP burst budgets (P0-4) for the two most expensive widget
    # endpoints. Anonymous token minting (`/sessions`) and SSE generation
    # (`/chat`) previously shared the generic `widget_ip_limit` bucket, so an
    # attacker rotating both visitor_id and target widget_id kept fresh entity
    # budgets while blending into that 120/min pool. These tighter IP-shaped
    # windows fire regardless of rotation; both stay configurable and honor
    # the `WIDGET_RATE_LIMIT_ENABLED` master switch (localhost dev unaffected).
    widget_session_issue_ip_limit: int = 30
    widget_chat_ip_limit: int = 60
    widget_max_messages_per_session: int = 50
    # Master switch for the widget rate limits; `None` inherits the global
    # `rate_limit_enabled` (resolved in the validator below).
    widget_rate_limit_enabled: bool | None = None

    # Per-API-key requests per minute (Sprint 2). Programmatic `wc_*` keys get
    # their own sliding window keyed by key id, independent of the per-IP
    # budgets applied to the same endpoints.
    api_key_rate_limit_per_minute: int = 300

    # Per-session-token refresh limit (SEC-7): bounds refresh attempts on a
    # stolen token+CSRF pair.  Keyed by the token hash so each rotated token
    # gets a fresh window while an attacker with one token is throttled.
    refresh_rate_limit_per_minute: int = 30

    # Email (Phase 2 - ADR-001)
    resend_api_key: str | None = None
    email_from: str = "WebChat AI <no-reply@webchatai.example>"
    mailpit_api_url: str = "http://localhost:8025"

    # AI (Phase 4-6)
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    embedding_model: str = "gemini-embedding-001"
    # Increment when preprocessing or embedding semantics change; existing
    # chunks must be re-indexed before the new version can retrieve them.
    embedding_version: str = "1"

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

    # Vector length the MongoDB `$vectorSearch` index expects. All providers in
    # `EMBEDDING_PROVIDER_ORDER` must produce this dimension or vector search
    # on a mixed corpus breaks: Gemini is truncated to it via
    # `outputDimensionality`, and Jina/Cohere must declare a matching
    # dimension (validated at boot). Default 1024 matches the cloud fallback
    # providers (jina-embeddings-v3 / embed-multilingual-v3.0).
    embedding_dimensions: int = 1024
    # Shared HTTP timeout for non-Gemini providers (Groq/OpenRouter/Jina/Cohere).
    # Bounded at 10s so a hung provider fails fast and the fallback chain moves
    # on instead of stalling the chat for a minute (Phase 12.6 latency work).
    ai_provider_timeout_seconds: float = 10.0

    # Cloud embedding fallbacks (ADR-009). Keys are optional: a provider in
    # `EMBEDDING_PROVIDER_ORDER` whose key is missing is skipped gracefully at
    # registry build time (the next provider is tried). `embedding_dimensions`
    # must match for every provider in the order (see `_validate_embedding_config`).
    jina_api_key: str | None = None
    jina_embedding_model: str = "jina-embeddings-v3"
    jina_embedding_dimensions: int = 1024
    cohere_api_key: str | None = None
    cohere_embedding_model: str = "embed-multilingual-v3.0"
    cohere_embedding_dimensions: int = 1024
    # Gemini-specific embedding dimensions. gemini-embedding-001 supports
    # 1..3072; the native default is 3072. When Gemini is the primary provider,
    # this value is sent as `outputDimensionality` to truncate/extend the
    # output. Must match `EMBEDDING_DIMENSIONS` when Gemini is in the fallback
    # chain (validated at boot). Separated so Gemini can run at full 3072 when
    # Jina/Cohere are not in the chain.
    gemini_embedding_dimensions: int = 1024

    # Knowledge processing (Phase 5, docs/06 implementation plan).
    # Approximate-token chunk sizing (docs/02-TRD.md §6: 500-800 tokens/chunk,
    # 100-token overlap).
    knowledge_chunk_size_tokens: int = 700
    knowledge_chunk_overlap_tokens: int = 100
    # Embedding client (Google gemini-embedding-001 via the Gemini API, ADR-008).
    # The API key is never logged and never exposed through any API (00 rules §12).
    embedding_batch_size: int = 32
    # Per-provider retries/timeout for embedding. Reduced for the Phase 12.6
    # latency work: a hung provider now costs ~10s per attempt instead of 60s,
    # and the chat path retries only once (see `chat_embedding_max_retries`) so
    # it fails fast into the next fallback provider.
    embedding_max_retries: int = 3
    embedding_retry_base_delay_ms: int = 300
    # Fail a document's embedding pass when a single batch error exceeds this.
    embedding_request_timeout_seconds: float = 10.0
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
    chat_top_k: int = 8
    # Conversation turns fed to the model as memory (most recent N).
    chat_memory_turns: int = 12
    # Character cap per retrieved chunk when building the model context.
    chat_context_chunk_chars: int = 4000
    # Total character budget for the retrieved context (all chunks combined).
    # Keeps the prompt small so the first token arrives fast (Phase 12.6).
    chat_context_max_chars: int = 20000
    # Relevance floor for retrieved chunks (cosine similarity). 0 disables the
    # filter; raise it to drop low-signal chunks before they reach the prompt.
    chat_context_min_score: float = 0.25
    # Question sanitization cap (prompt-injection defense, TRD §8).
    chat_question_max_chars: int = 2000
    # Generation settings for the Gemini answer stream.
    chat_max_output_tokens: int = 4096
    chat_temperature: float = 0.2
    # Per-chunk stream timeout (guards a stalled answer mid-stream).
    # Recommendation: 30s is appropriate for most use cases. Reduce only if
    # measurements show consistent faster completion. Monitor p99 latency
    # before adjusting.
    generation_timeout_seconds: float = 30.0
    # Hard bound on the wait for the FIRST token: a provider that takes longer
    # is treated as unavailable so the fallback chain can switch providers
    # instead of leaving the user staring at a spinner.
    # Recommendation: 10s is a good balance. For Gemini, typical TTFT is 1-3s.
    # For fallback providers (Groq, OpenRouter), TTFT can be 2-5s. Values
    # below 5s may cause premature fallbacks on slow networks.
    generation_first_token_timeout_seconds: float = 10.0
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

    # Hybrid search (opt-in, off by default). When enabled, retrieval combines
    # vector similarity ranking with keyword-based ranking via Reciprocal Rank
    # Fusion (RRF) to improve source accuracy.  The existing vector-only path
    # remains the default fallback — no production behavior changes unless this
    # flag is explicitly set to True.
    enable_hybrid_search: bool = True
    # RRF constant for hybrid fusion (higher reduces top-rank impact).
    hybrid_rrf_k: int = 60
    # Maximum candidate chunks loaded for keyword scoring in hybrid search.
    # Bounded loading prevents O(n) memory/CPU growth with large knowledge bases.
    # Set 0 to disable the limit (loads all chunks — legacy behavior).
    hybrid_search_candidate_limit: int = 50

    # Adaptive retrieval (opt-in, off by default). When enabled, retrieval
    # parameters (top_k, rerank candidates, context budget) are adjusted per
    # query based on lightweight complexity classification.  Simple queries
    # use smaller budgets for lower latency; complex queries retrieve more
    # context for better accuracy.  Disabled by default — existing retrieval
    # behavior is preserved unless explicitly turned on.
    enable_adaptive_retrieval: bool = False
    # Adaptive retrieval parameter overrides.  When adaptive retrieval is
    # enabled, these values replace the defaults for each complexity level.
    adaptive_simple_top_k: int = 4
    adaptive_simple_rerank_top_k: int = 3
    adaptive_simple_max_context_chars: int = 8000
    adaptive_complex_top_k: int = 12
    adaptive_complex_rerank_top_k: int = 8
    adaptive_complex_max_context_chars: int = 30000

    # Reranking (post-retrieval). When enabled, retrieved chunks are re-scored
    # using the embedding model's query-chunk similarity before context
    # construction.  Improves ranking quality at the cost of one extra embed
    # call per query (embeds query + top_k chunk texts in a single batch).
    enable_reranking: bool = True
    # Number of top results after reranking fed into context.  Must be <=
    # chat_top_k.  When 0, reranking is effectively disabled even if the flag
    # is on.
    rerank_top_k: int = 5

    # Answer faithfulness (post-generation). When enabled, each answer is
    # checked for unsupported claims by verifying that every sentence in the
    # answer is grounded in the retrieved context chunks.  A low faithfulness
    # score is logged as a warning (never blocks the response).
    enable_faithfulness_check: bool = True
    # Minimum faithfulness score (0.0-1.0) before a warning is emitted.
    faithfulness_warning_threshold: float = 0.6

    # RAG confidence check (pre-generation). When enabled, retrieved context
    # is scored for relevance *before* the LLM is called.  Low-confidence
    # queries receive the safe fallback response instead of a generated answer,
    # preventing hallucinations when the knowledge base lacks relevant content.
    enable_rag_confidence_check: bool = True
    # Minimum confidence score (0.0–1.0) required to proceed with generation.
    # Scores below this threshold trigger the fallback response.
    rag_confidence_threshold: float = 0.3

    # Context optimization (opt-in, disabled by default). When enabled,
    # near-duplicate chunks are removed and context text is compressed
    # (redundant sentences stripped) before prompt construction.  This
    # reduces unnecessary tokens while preserving answer quality.
    enable_context_optimization: bool = False

    # Performance instrumentation (Phase 12.1; opt-in, disabled by default).
    # When true, per-request HTTP timing, AI provider timings (TTFT/total) and
    # worker job durations are logged as structured records. Never enabled in
    # production - it is a load-testing/observability aid.
    perf_timing_log_enabled: bool = False
    # Log MongoDB commands slower than this threshold (ms); 0 disables.
    mongodb_slow_query_threshold_ms: int = 0
    # Cross-process Redis cache of question embeddings. Repeated questions
    # reuse the cached vector and skip the embedding API call, cutting
    # perceived latency and provider usage on high-repeat traffic. TTL
    # prevents unbounded Redis growth; set 0 to disable.
    # Recommendation: 256 entries is sufficient for most workloads. Monitor
    # hit rate to adjust. A hit rate > 30% indicates good value.
    embedding_cache_size: int = 256
    embedding_cache_ttl_seconds: int = 3600
    # Retrieval cache (cross-process via Redis): repeat questions - same
    # website, same normalized text - reuse the embedding AND the vector-search
    # results for `chat_retrieval_cache_ttl_seconds`, skipping both the
    # embedding provider and the search query. Answers are NEVER cached:
    # generation still runs so every turn is a fresh answer. Set size 0 or
    # TTL 0 to disable.
    # Recommendation: 512 entries with 15-minute TTL balances hit rate vs.
    # freshness. Monitor hit rate to adjust.
    chat_retrieval_cache_ttl_seconds: int = 900
    chat_retrieval_cache_size: int = 512
    # Chat-path embedding retries per provider. The chat must fail fast: a
    # single hung embedding request (up to `embedding_request_timeout_seconds`)
    # then the next provider. Ingestion keeps `embedding_max_retries` because
    # a crawl has no interactive user waiting on it.
    chat_embedding_max_retries: int = 1
    # SSE delta coalescing window (ms). Small `message` deltas are buffered and
    # flushed as a single SSE frame every `sse_buffer_ms` milliseconds, reducing
    # the number of frames and network round-trips without changing the
    # client-visible streaming semantics. 0 disables buffering (raw per-token
    # frames). Default 50ms balances latency vs. frame count.
    sse_buffer_ms: float = 50.0

    # Adaptive provider routing (Phase 12.6). When "adaptive", the router
    # queries Redis for per-provider health and reorders the fallback chain
    # per-request to prefer healthy low-latency providers and skip those in
    # cooldown. "static" preserves the original fixed order (zero health
    # lookups, zero Redis reads on the chat path).
    ai_provider_routing_mode: str = "static"
    # Seconds to suppress a provider after a failure before retesting it.
    ai_provider_cooldown_seconds: int = 60
    # Staleness threshold (seconds): health data older than this is treated
    # as obsolete and the provider is treated as recoverable.
    ai_provider_health_check_interval: int = 300
    # After a provider recovers from cooldown, it stays below healthy
    # providers for this many seconds before regaining normal priority.
    ai_provider_recovery_window_seconds: int = 120

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

    @field_validator("redis_url")
    @classmethod
    def _validate_redis_url(cls, value: object) -> object:
        """Fail fast on a malformed REDIS_URL.

        Both the API rate limiter and the ARQ worker parse this URL on every
        startup / first use; an invalid scheme previously surfaced as an
        opaque 500 (`ValueError: Redis URL must specify...`) or a worker crash
        at runtime instead of a clear boot-time configuration error.
        """
        if not isinstance(value, str) or not value.strip():
            raise ValueError("REDIS_URL must not be empty.")
        scheme = urlparse(value.strip()).scheme.lower()
        if scheme not in {"redis", "rediss", "unix"}:
            raise ValueError(
                f"REDIS_URL must use a redis://, rediss:// or unix:// scheme (got: {value!r})."
            )
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

    @staticmethod
    def _loopback_markers() -> tuple[str, ...]:
        return ("localhost", "127.0.0.1", "0.0.0.0", "::1")

    def _has_loopback_host(self, value: str) -> bool:
        """True when a URL/string contains a loopback host marker."""
        lowered = value.lower()
        return any(marker in lowered for marker in self._loopback_markers())

    def _is_loopback_host(self, host: str) -> bool:
        return host.strip().lower() in {
            "localhost",
            "127.0.0.1",
            "0.0.0.0",
            "::1",
            "testserver",
        }

    @model_validator(mode="after")
    def _validate_embedding_config(self) -> "Settings":
        """Fail fast on an incoherent embedding configuration (ADR-009).

        Every fallback provider listed in `EMBEDDING_PROVIDER_ORDER` must agree
        on a single vector dimension: the MongoDB index is built for
        `EMBEDDING_DIMENSIONS`, so a fallback provider returning a different
        length would silently corrupt `$vectorSearch`. Missing API keys are NOT
        an error here - the registry skips a keyless provider gracefully and
        the next one is tried. Only the dimension contract is enforced.

        Gemini's `outputDimensionality` is set from `GEMINI_EMBEDDING_DIMENSIONS`
        and the runtime `ensure_vector_dimensions` gate in
        `GoogleEmbeddingClient._parse_response` catches any mismatch.
        """
        if self.embedding_dimensions <= 0:
            raise ValueError("EMBEDDING_DIMENSIONS must be a positive integer.")
        if self.gemini_embedding_dimensions <= 0:
            raise ValueError("GEMINI_EMBEDDING_DIMENSIONS must be a positive integer.")
        for provider in self.embedding_provider_order:
            if provider == "jina" and self.jina_embedding_dimensions != self.embedding_dimensions:
                raise ValueError(
                    "JINA_EMBEDDING_DIMENSIONS must match EMBEDDING_DIMENSIONS "
                    f"({self.embedding_dimensions}); "
                    f"got {self.jina_embedding_dimensions}. "
                    "A mismatched fallback provider corrupts $vectorSearch."
                )
            if (
                provider == "cohere"
                and self.cohere_embedding_dimensions != self.embedding_dimensions
            ):
                raise ValueError(
                    "COHERE_EMBEDDING_DIMENSIONS must match EMBEDDING_DIMENSIONS "
                    f"({self.embedding_dimensions}); "
                    f"got {self.cohere_embedding_dimensions}. "
                    "A mismatched fallback provider corrupts $vectorSearch."
                )
        return self

    @model_validator(mode="after")
    def _validate_confidence_config(self) -> "Settings":
        """Keep confidence controls within their documented range."""
        if not 0.0 <= self.rag_confidence_threshold <= 1.0:
            raise ValueError("RAG_CONFIDENCE_THRESHOLD must be between 0 and 1.")
        if not 0.0 <= self.chat_context_min_score <= 1.0:
            raise ValueError("CHAT_CONTEXT_MIN_SCORE must be between 0 and 1.")
        return self

    @model_validator(mode="after")
    def _validate_production_security(self) -> "Settings":
        """Fail fast on weak production secrets (00-AI-Development-Rules §20).

        `LOCAL_PRODUCTION_TEST=true` relaxes ONLY the URL/host validators so
        the production code paths can run on a local machine over plain HTTP.
        All other production checks (JWT length, provider keys, real payment
        gateway, rate limiting, wildcard rejection) always apply.
        """
        if self.environment.lower() == "production":
            if len(self.jwt_secret.encode("utf-8")) < 32:
                raise ValueError("JWT_SECRET must be at least 32 characters in production.")
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
            # Embedding API keys are intentionally NOT required at boot: a
            # keyless provider is skipped gracefully by the registry (with a
            # warning) and the next provider in the order is tried, so a missing
            # key must never crash the application (ADR-009).
            # The embed script URL is baked into the dashboard embed code and
            # into customer pages; a localhost default would break every embed.
            # Allowed only under the explicit local-production-test flag.
            if self._has_loopback_host(self.widget_script_url) and not self.local_production_test:
                raise ValueError(
                    "WIDGET_SCRIPT_URL must point at a real CDN/host in production "
                    "(got a localhost value)."
                )
            # The widget API base is embedded into customer pages via
            # `data-api-base-url`; a localhost value would break every embed.
            # Allowed only under the explicit local-production-test flag.
            if (
                self.widget_api_base_url
                and self._has_loopback_host(self.widget_api_base_url)
                and not self.local_production_test
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
            if self.payment_provider.lower() == "razorpay" and self.razorpay_webhook_secret:
                secret_lower = self.razorpay_webhook_secret.strip().lower()
                if any(marker in secret_lower for marker in _RAZORPAY_WEBHOOK_URL_MARKERS):
                    if not self.local_production_test:
                        raise ValueError(
                            "RAZORPAY_WEBHOOK_SECRET appears to contain a URL "
                            "instead of the actual webhook secret string. "
                            "Use the secret from the Razorpay Dashboard."
                        )
            sender_email = self.email_from.split("<")[-1].strip().rstrip(">").strip().lower()
            if sender_email in _RESEND_SANDBOX_SENDERS:
                if not self.local_production_test:
                    raise ValueError(
                        "EMAIL_FROM must not use a Resend sandbox sender "
                        "(onboarding@resend.dev) in production. "
                        "Configure a verified custom domain sender."
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
                if self._has_loopback_host(lowered):
                    # Loopback (plain-HTTP) origins are allowed only under the
                    # explicit local-production-test flag; they never are in a
                    # real deployment.
                    if not self.local_production_test:
                        raise ValueError(
                            "CORS_ORIGINS must not contain loopback origins in "
                            f"production ({origin})."
                        )
                    continue
                if not lowered.startswith("https://"):
                    raise ValueError(
                        f"CORS_ORIGINS entries must be HTTPS origins in production ({origin})."
                    )
            # Trusted hosts (Phase 16): without an explicit allowlist, host-header
            # poisoning could route requests anywhere. Require at least one real
            # public hostname (loopback-only lists are a misconfiguration),
            # except under the explicit local-production-test flag.
            if not self.allowed_hosts:
                raise ValueError("ALLOWED_HOSTS must not be empty in production.")
            if "*" in self.allowed_hosts:
                raise ValueError("ALLOWED_HOSTS must not contain wildcard entries in production.")
            if not self.local_production_test and not any(
                not self._is_loopback_host(host) for host in self.allowed_hosts
            ):
                raise ValueError("ALLOWED_HOSTS must include the public hostname(s) in production.")
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
