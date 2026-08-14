"""Domain errors shared across services.

Routes and the FastAPI exception handler translate these into HTTP responses.
Keeping services free of FastAPI imports preserves the layering rules in
00-AI-Development-Rules.md (routes -> services -> repositories).
"""

from typing import Any


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


class UserNotFoundError(AppError):
    """User does not exist for the admin operation (Phase 12.5)."""

    status_code = 404
    code = "USER_NOT_FOUND"
