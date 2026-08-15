"""Repository interfaces and MongoDB implementations.

Layering (00-AI-Development-Rules.md §6): routes -> services -> repositories.
Application code depends on the Protocol interfaces only, which keeps the data
layer swappable and testable.
"""

from backend.repositories.admin_repository import (
    AdminRepository,
    MongoAdminRepository,
    PlatformStats,
)
from backend.repositories.analytics_repository import (
    AnalyticsRepository,
    AnalyticsSummaryRow,
    MongoAnalyticsRepository,
    ResponseMetricsRow,
    TimeseriesRow,
    TopWebsiteRow,
)
from backend.repositories.api_key_repository import (
    ApiKeyRepository,
    MongoApiKeyRepository,
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
from backend.repositories.feedback_repository import (
    FeedbackRepository,
    FeedbackSummary,
    MongoFeedbackRepository,
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
from backend.repositories.subscription_repository import (
    MongoSubscriptionRepository,
    SubscriptionRepository,
)
from backend.repositories.tenant_repository import MongoTenantRepository, TenantRepository
from backend.repositories.usage_event_repository import (
    MongoUsageEventRepository,
    UsageEventRepository,
    UsageEventTotals,
)
from backend.repositories.usage_record_repository import (
    MongoUsageRecordRepository,
    TenantUsageSummary,
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
    "AdminRepository",
    "AnalyticsRepository",
    "AnalyticsSummaryRow",
    "ApiKeyRepository",
    "AuditLogRepository",
    "ChatMessageRepository",
    "ChatSessionRepository",
    "CrawlJobRepository",
    "DocumentRepository",
    "FeedbackRepository",
    "FeedbackSummary",
    "KnowledgeChunkRepository",
    "MongoAdminRepository",
    "MongoAnalyticsRepository",
    "MongoAuditLogRepository",
    "MongoApiKeyRepository",
    "MongoChatMessageRepository",
    "MongoChatSessionRepository",
    "MongoCrawlJobRepository",
    "MongoDocumentRepository",
    "MongoFeedbackRepository",
    "MongoKnowledgeChunkRepository",
    "MongoMemberRepository",
    "MongoRefreshTokenRepository",
    "MongoTenantRepository",
    "MongoUserRepository",
    "MongoUsageRecordRepository",
    "MongoUsageEventRepository",
    "MongoWebsiteRepository",
    "MongoWidgetRepository",
    "MongoVectorRepository",
    "MongoSubscriptionRepository",
    "MemberRepository",
    "PlatformStats",
    "RefreshTokenRepository",
    "ResponseMetricsRow",
    "SubscriptionRepository",
    "TenantRepository",
    "TimeseriesRow",
    "TopWebsiteRow",
    "UserRepository",
    "UsageRecordRepository",
    "UsageEventRepository",
    "UsageEventTotals",
    "VectorRepository",
    "VectorSearchResult",
    "WebsiteRepository",
    "WebsiteSortField",
    "WebsiteSortOrder",
    "WidgetRepository",
    "TenantUsageSummary",
    "get_vector_repository",
]
