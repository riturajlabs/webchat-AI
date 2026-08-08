"""Document models for Mongo collections (docs/05 + ADR-005)."""

from backend.models.audit_log import (
    AUDIT_EMAIL_VERIFIED,
    AUDIT_FORGOT_PASSWORD,
    AUDIT_LOGIN,
    AUDIT_LOGIN_FAILED,
    AUDIT_LOGOUT,
    AUDIT_PASSWORD_RESET,
    AUDIT_REFRESH_REUSE_DETECTED,
    AUDIT_REGISTER,
    AUDIT_TOKEN_REFRESHED,
    AUDIT_WEBSITE_CREATED,
    AUDIT_WEBSITE_DELETED,
    AUDIT_WEBSITE_UPDATED,
    AuditLog,
)
from backend.models.crawl_job import (
    CRAWL_ACTIVE_STATUSES,
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_FAILED,
    CRAWL_STATUS_PENDING,
    CRAWL_STATUS_PROCESSING,
    CRAWL_STATUS_RUNNING,
    CRAWL_STATUSES,
    CrawlJob,
    CrawlJobError,
)
from backend.models.document import (
    DOCUMENT_STATUS_READY,
    DOCUMENT_STATUSES,
    Document,
)
from backend.models.member import Member
from backend.models.refresh_token import RefreshToken
from backend.models.tenant import Tenant
from backend.models.user import User
from backend.models.website import (
    WEBSITE_STATUS_CRAWLING,
    WEBSITE_STATUS_FAILED,
    WEBSITE_STATUS_PENDING,
    WEBSITE_STATUS_PROCESSING,
    WEBSITE_STATUS_READY,
    WEBSITE_STATUSES,
    Website,
)
from backend.models.widget import (
    WIDGET_FONT_SIZES,
    WIDGET_POSITIONS,
    WIDGET_THEMES,
    Widget,
)

__all__ = [
    "AUDIT_EMAIL_VERIFIED",
    "AUDIT_FORGOT_PASSWORD",
    "AUDIT_LOGIN",
    "AUDIT_LOGIN_FAILED",
    "AUDIT_LOGOUT",
    "AUDIT_PASSWORD_RESET",
    "AUDIT_REFRESH_REUSE_DETECTED",
    "AUDIT_REGISTER",
    "AUDIT_TOKEN_REFRESHED",
    "AUDIT_WEBSITE_CREATED",
    "AUDIT_WEBSITE_DELETED",
    "AUDIT_WEBSITE_UPDATED",
    "AUDIT_CRAWL_STARTED",
    "AUDIT_CRAWL_COMPLETED",
    "AUDIT_CRAWL_FAILED",
    "AuditLog",
    "CRAWL_ACTIVE_STATUSES",
    "CRAWL_STATUS_COMPLETED",
    "CRAWL_STATUS_FAILED",
    "CRAWL_STATUS_PENDING",
    "CRAWL_STATUS_PROCESSING",
    "CRAWL_STATUS_RUNNING",
    "CRAWL_STATUSES",
    "CrawlJob",
    "CrawlJobError",
    "DOCUMENT_STATUS_READY",
    "DOCUMENT_STATUSES",
    "Document",
    "Member",
    "RefreshToken",
    "Tenant",
    "User",
    "WEBSITE_STATUSES",
    "WEBSITE_STATUS_CRAWLING",
    "WEBSITE_STATUS_FAILED",
    "WEBSITE_STATUS_PENDING",
    "WEBSITE_STATUS_PROCESSING",
    "WEBSITE_STATUS_READY",
    "WIDGET_FONT_SIZES",
    "WIDGET_POSITIONS",
    "WIDGET_THEMES",
    "Website",
    "Widget",
]
