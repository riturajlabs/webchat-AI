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
