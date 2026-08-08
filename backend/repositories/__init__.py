"""Repository interfaces and MongoDB implementations.

Layering (00-AI-Development-Rules.md §6): routes -> services -> repositories.
Application code depends on the Protocol interfaces only, which keeps the data
layer swappable and testable.
"""

from backend.repositories.audit_log_repository import (
    AuditLogRepository,
    MongoAuditLogRepository,
)
from backend.repositories.crawl_job_repository import (
    CrawlJobRepository,
    MongoCrawlJobRepository,
)
from backend.repositories.document_repository import (
    DocumentRepository,
    MongoDocumentRepository,
)
from backend.repositories.member_repository import MemberRepository, MongoMemberRepository
from backend.repositories.refresh_token_repository import (
    MongoRefreshTokenRepository,
    RefreshTokenRepository,
)
from backend.repositories.tenant_repository import MongoTenantRepository, TenantRepository
from backend.repositories.user_repository import MongoUserRepository, UserRepository
from backend.repositories.website_repository import (
    MongoWebsiteRepository,
    WebsiteRepository,
    WebsiteSortField,
    WebsiteSortOrder,
)
from backend.repositories.widget_repository import MongoWidgetRepository, WidgetRepository

__all__ = [
    "AuditLogRepository",
    "CrawlJobRepository",
    "DocumentRepository",
    "MongoAuditLogRepository",
    "MongoCrawlJobRepository",
    "MongoDocumentRepository",
    "MongoMemberRepository",
    "MongoRefreshTokenRepository",
    "MongoTenantRepository",
    "MongoUserRepository",
    "MongoWebsiteRepository",
    "MongoWidgetRepository",
    "MemberRepository",
    "RefreshTokenRepository",
    "TenantRepository",
    "UserRepository",
    "WebsiteRepository",
    "WebsiteSortField",
    "WebsiteSortOrder",
    "WidgetRepository",
]
