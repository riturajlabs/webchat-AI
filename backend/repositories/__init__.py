"""Repository interfaces and MongoDB implementations.

Layering (00-AI-Development-Rules.md §6): routes -> services -> repositories.
Application code depends on the Protocol interfaces only, which keeps the data
layer swappable and testable.
"""

from backend.repositories.analytics_repository import (
    AnalyticsRepository,
    AnalyticsSummaryRow,
    MongoAnalyticsRepository,
    ResponseMetricsRow,
    TimeseriesRow,
    TopWebsiteRow,
)
from backend.repositories.audit_log_repository import (
    AuditLogRepository,
    MongoAuditLogRepository,
)
from backend.repositories.chat_message_repository import (
    ChatMessageRepository,
    MongoChatMessageRepository,
)
from backend.repositories.chat_session_repository import (
    ChatSessionRepository,
    MongoChatSessionRepository,
)
from backend.repositories.crawl_job_repository import (
    CrawlJobRepository,
    MongoCrawlJobRepository,
)
from backend.repositories.document_repository import (
    DocumentRepository,
    MongoDocumentRepository,
)
from backend.repositories.knowledge_chunk_repository import (
    KnowledgeChunkRepository,
    MongoKnowledgeChunkRepository,
)
from backend.repositories.member_repository import MemberRepository, MongoMemberRepository
from backend.repositories.refresh_token_repository import (
    MongoRefreshTokenRepository,
    RefreshTokenRepository,
)
from backend.repositories.tenant_repository import MongoTenantRepository, TenantRepository
from backend.repositories.usage_record_repository import (
    MongoUsageRecordRepository,
    UsageRecordRepository,
)
from backend.repositories.user_repository import MongoUserRepository, UserRepository
from backend.repositories.vector import (
    MongoVectorRepository,
    VectorRepository,
    VectorSearchResult,
    get_vector_repository,
)
from backend.repositories.website_repository import (
    MongoWebsiteRepository,
    WebsiteRepository,
    WebsiteSortField,
    WebsiteSortOrder,
)
from backend.repositories.widget_repository import MongoWidgetRepository, WidgetRepository

__all__ = [
    "AnalyticsRepository",
    "AnalyticsSummaryRow",
    "AuditLogRepository",
    "ChatMessageRepository",
    "ChatSessionRepository",
    "CrawlJobRepository",
    "DocumentRepository",
    "KnowledgeChunkRepository",
    "MongoAnalyticsRepository",
    "MongoAuditLogRepository",
    "MongoChatMessageRepository",
    "MongoChatSessionRepository",
    "MongoCrawlJobRepository",
    "MongoDocumentRepository",
    "MongoKnowledgeChunkRepository",
    "MongoMemberRepository",
    "MongoRefreshTokenRepository",
    "MongoTenantRepository",
    "MongoUserRepository",
    "MongoUsageRecordRepository",
    "MongoWebsiteRepository",
    "MongoWidgetRepository",
    "MongoVectorRepository",
    "MemberRepository",
    "RefreshTokenRepository",
    "ResponseMetricsRow",
    "TenantRepository",
    "TimeseriesRow",
    "TopWebsiteRow",
    "UserRepository",
    "UsageRecordRepository",
    "VectorRepository",
    "VectorSearchResult",
    "WebsiteRepository",
    "WebsiteSortField",
    "WebsiteSortOrder",
    "WidgetRepository",
    "get_vector_repository",
]
