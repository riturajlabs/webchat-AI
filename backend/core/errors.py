"""Domain errors shared across services.

Routes and the FastAPI exception handler translate these into HTTP responses.
Keeping services free of FastAPI imports preserves the layering rules in
00-AI-Development-Rules.md (routes -> services -> repositories).
"""

import logging
from typing import Any

logger = logging.getLogger("webchat_ai")


def capture_exception(
    exc: BaseException,
    *,
    context: dict[str, Any] | None = None,
    level: int = logging.ERROR,
) -> None:
    """Log an exception with full context for future Sentry integration.

    Currently emits a structured log record.  When a Sentry SDK is added later,
    this single call-site can be updated to also call ``sentry_sdk.capture_exception``
    without touching every consumer.

    Parameters
    ----------
    exc:
        The exception to record.
    context:
        Optional extra fields merged into the log record (e.g.
        ``tenant_id``, ``job_id``).
    level:
        Logging level (default ``ERROR``).
    """
    extra: dict[str, Any] = {
        "error_type": type(exc).__name__,
        "error_code": getattr(exc, "code", None),
        "error_status": getattr(exc, "status_code", None),
    }
    if context:
        extra.update(context)
    logger.log(
        level,
        "exception_captured: %s",
        exc,
        exc_info=(type(exc), exc, exc.__traceback__),
        extra=extra,
    )


class AppError(Exception):
    """Base class for all application errors."""

    status_code: int = 400
    code: str = "APP_ERROR"

    def __init__(self, message: str, *, extra: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.extra = extra or {}


class InvalidCredentialsError(AppError):
    status_code = 401
    code = "INVALID_CREDENTIALS"


class AccountSuspendedError(AppError):
    status_code = 403
    code = "ACCOUNT_SUSPENDED"


class AccountLockedError(AppError):
    """Too many failed login attempts; the account is temporarily locked."""

    status_code = 429
    code = "ACCOUNT_LOCKED"


class EmailNotVerifiedError(AppError):
    """The account exists but its email has not been verified yet.

    Raised by login/refresh/authenticate so unverified users are blocked from
    the dashboard until they verify (Sprint 1 P1 remediation). The distinct
    403 code lets the frontend route to the verify-email screen with a resend
    action instead of showing a generic credential error.
    """

    status_code = 403
    code = "EMAIL_NOT_VERIFIED"


class FeatureUnavailableError(AppError):
    """A surface is intentionally disabled (returns HTTP 501).

    Used to clearly disable endpoints whose credentials cannot actually be
    used yet (e.g. API-key minting) rather than silently issuing secrets.
    """

    status_code = 501
    code = "NOT_IMPLEMENTED"


class ForbiddenError(AppError):
    status_code = 403
    code = "FORBIDDEN"


class DuplicateEmailError(AppError):
    status_code = 409
    code = "EMAIL_ALREADY_EXISTS"


class InvalidUrlError(AppError):
    status_code = 400
    code = "INVALID_URL"


class DuplicateWebsiteError(AppError):
    status_code = 409
    code = "WEBSITE_ALREADY_EXISTS"


class WebsiteNotFoundError(AppError):
    status_code = 404
    code = "WEBSITE_NOT_FOUND"


class CrawlJobNotFoundError(AppError):
    status_code = 404
    code = "CRAWL_JOB_NOT_FOUND"


class CrawlConflictError(AppError):
    status_code = 409
    code = "CRAWL_IN_PROGRESS"


class AIQuotaExceededError(AppError):
    """Tenant AI usage limit reached (Phase 14.9.4)."""

    status_code = 429
    code = "AI_QUOTA_EXCEEDED"
    message = "AI usage limit exceeded. Please upgrade your plan."


class InvalidTokenError(AppError):
    status_code = 401
    code = "INVALID_TOKEN"


class TokenExpiredError(InvalidTokenError):
    code = "TOKEN_EXPIRED"


class TokenReuseError(AppError):
    status_code = 401
    code = "TOKEN_REUSE_DETECTED"


class CsrfError(AppError):
    status_code = 403
    code = "CSRF_FAILED"


class RateLimitExceededError(AppError):
    status_code = 429
    code = "RATE_LIMIT_EXCEEDED"


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "SERVICE_UNAVAILABLE"


class EmbeddingError(AppError):
    """Embedding generation failed after retries (Phase 5)."""

    status_code = 502
    code = "EMBEDDING_FAILED"


class EmbeddingUnavailableError(EmbeddingError):
    """Embedding service cannot run (e.g. missing API key)."""

    code = "EMBEDDING_UNAVAILABLE"


class EmbeddingRateLimitedError(EmbeddingError):
    """Embedding request rejected for quota/rate-limit reasons (e.g. a 429).

    Distinguishes "temporarily rate-limited" from a generic transient failure:
    the knowledge pipeline records such documents as `rate_limited` (awaiting a
    deferred retry) instead of permanently `failed`, so the dashboard can render
    them separately.
    """

    code = "EMBEDDING_RATE_LIMITED"


class EmbeddingCompatibilityError(EmbeddingError):
    """Stored and query vectors belong to incompatible embedding spaces."""

    code = "EMBEDDING_INCOMPATIBLE"


class InsufficientContentError(AppError):
    """Cleaned page text is too short to embed usefully (pipeline stage).

    Raised internally by the knowledge pipeline when a document's content falls
    below the minimum-length threshold; it is never returned over HTTP, only
    recorded as the document's permanent failure reason.
    """

    status_code = 422
    code = "INSUFFICIENT_CONTENT"


class DocumentNotFoundError(AppError):
    """Knowledge document does not exist for this tenant (retry/status APIs)."""

    status_code = 404
    code = "DOCUMENT_NOT_FOUND"


class InvalidQuestionError(AppError):
    """Chat question rejected after sanitization (Phase 6)."""

    status_code = 400
    code = "INVALID_QUESTION"


class SessionNotFoundError(AppError):
    """Chat session does not exist for this tenant (Phase 6)."""

    status_code = 404
    code = "SESSION_NOT_FOUND"


class GenerationError(AppError):
    """LLM answer generation failed (Phase 6, ADR-008)."""

    status_code = 502
    code = "GENERATION_FAILED"


class GenerationUnavailableError(GenerationError):
    """Generation service cannot run (e.g. missing API key)."""

    code = "GENERATION_UNAVAILABLE"


class ProviderConfigurationError(AppError):
    """AI provider configuration is invalid (unknown name in an order list).

    Raised by the Phase 9 provider registry so a typo in
    `GENERATION_PROVIDER_ORDER`/`EMBEDDING_PROVIDER_ORDER` fails fast instead
    of silently serving a degraded chain.
    """

    status_code = 500
    code = "PROVIDER_CONFIGURATION"


class WidgetNotFoundError(AppError):
    """Public widget id does not exist (Phase 8, ADR-004)."""

    status_code = 404
    code = "WIDGET_NOT_FOUND"


class WidgetDisabledError(AppError):
    """Widget exists but is disabled by its tenant (Phase 8, ADR-004)."""

    status_code = 403
    code = "WIDGET_DISABLED"


class WidgetOriginNotAllowedError(AppError):
    """The embedding page's origin is not in the widget's allowed_domains.

    Raised when a browser embeds a widget on a domain the tenant has not
    authorized. A `403` keeps the rejection loud while revealing nothing
    about the widget's existence beyond what the tenant configured.
    """

    status_code = 403
    code = "WIDGET_ORIGIN_NOT_ALLOWED"


class WidgetDomainNotConfiguredError(AppError):
    """No embed-origin allowlist has been configured for the widget.

    Raised when a widget has an empty `allowed_domains` and a browser origin
    tries to embed it. Distinct from `WidgetOriginNotAllowedError` so clients
    can tell "this domain is blocked" from "no domains have been configured
    yet" - the fix differs (add a domain vs. configure the allowlist). The
    literal `*` entry is the explicit opt-in for open embedding.
    """

    status_code = 403
    code = "WIDGET_DOMAIN_NOT_CONFIGURED"


class WebsiteNotReadyError(AppError):
    """Website has not finished indexing, so it cannot answer (Phase 8)."""

    status_code = 409
    code = "WEBSITE_NOT_READY"


class MessageLimitReachedError(AppError):
    """Visitor exceeded the per-conversation message cap (Phase 8, ADR-004)."""

    status_code = 429
    code = "MESSAGE_LIMIT_REACHED"


class SpamRejectedError(AppError):
    """Question rejected by the low-cost spam heuristics (Phase 8)."""

    status_code = 400
    code = "SPAM_REJECTED"


class ApiKeyNotFoundError(AppError):
    """API key does not exist or is already revoked (docs/05 §12)."""

    status_code = 404
    code = "API_KEY_NOT_FOUND"


class FeedbackMessageNotFoundError(AppError):
    """No assistant message exists for the feedback target (Phase 12.4)."""

    status_code = 404
    code = "MESSAGE_NOT_FOUND"


class TenantNotFoundError(AppError):
    """Tenant does not exist for the admin operation (Phase 12.5)."""

    status_code = 404
    code = "TENANT_NOT_FOUND"


class PlanNotFoundError(AppError):
    """Plan id is not a purchasable/assignable plan (Phase 15 admin ops)."""

    status_code = 404
    code = "PLAN_NOT_FOUND"


class UserNotFoundError(AppError):
    """User does not exist for the admin operation (Phase 12.5)."""

    status_code = 404
    code = "USER_NOT_FOUND"


class LimitReachedError(AppError):
    """A subscription plan limit is exhausted (Phase 13 billing).

    Raised before an action that would exceed a plan cap (chat message,
    website creation, document crawl). `extra` carries the offending metric,
    the current usage and the plan limit so clients can render a meaningful
    upgrade prompt.
    """

    status_code = 429
    code = "LIMIT_REACHED"


class PaymentProviderError(AppError):
    """The payment gateway rejected or failed a request (Phase 14).

    Raised when creating a checkout session or verifying a payment upstream;
    a gateway outage must not look like a caller mistake, so this surfaces as
    a 502 with the provider's message (never its keys).
    """

    status_code = 502
    code = "PAYMENT_PROVIDER_ERROR"


class PaymentSignatureError(AppError):
    """A payment webhook failed signature verification (Phase 14).

    Raised by `PaymentProvider.parse_webhook` so an unverified webhook is
    rejected (400) *before* any subscription state changes. Providers retry on
    non-2xx, so a bad signature is retried rather than silently accepted.
    """

    status_code = 400
    code = "INVALID_PAYMENT_SIGNATURE"


class PlanNotPurchasableError(AppError):
    """The requested plan cannot be bought via self-serve checkout (Phase 14).

    Free is the trial tier and Enterprise is sold by sales (`price_cents`
    is `None`/`0`); attempting to checkout either is a client error.
    """

    status_code = 400
    code = "PLAN_NOT_PURCHASABLE"
