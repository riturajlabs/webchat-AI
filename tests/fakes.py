"""In-memory fakes for repositories and mail delivery used in auth tests."""

from datetime import datetime

from backend.ai.gemini import GenerationUsage
from backend.core.security import utcnow
from backend.models.api_key import API_KEY_STATUS_ACTIVE, API_KEY_STATUS_REVOKED, ApiKey
from backend.models.audit_log import AuditLog
from backend.models.chat_message import CHAT_ROLE_ASSISTANT, ChatMessage
from backend.models.chat_session import CHAT_SESSION_STATUS_DELETED, ChatSession
from backend.models.crawl_job import (
    CRAWL_ACTIVE_STATUSES,
    CrawlJob,
)
from backend.models.document import Document
from backend.models.knowledge_chunk import KnowledgeChunk
from backend.models.member import Member
from backend.models.refresh_token import RefreshToken
from backend.models.tenant import Tenant
from backend.models.usage_record import UsageRecord
from backend.models.user import User
from backend.models.website import WEBSITE_STATUS_DELETED, Website
from backend.models.widget import Widget
from backend.repositories.analytics_repository import (
    AnalyticsSummaryRow,
    ResponseMetricsRow,
    TimeseriesRow,
    TopWebsiteRow,
)
from backend.repositories.chat_message_repository import MessageSummary
from backend.repositories.vector.base import VectorSearchResult
from backend.services.mail.base import EmailMessage


class FakeUserRepository:
    def __init__(self) -> None:
        self._users: dict[str, User] = {}

    @property
    def users(self) -> dict[str, User]:
        return self._users

    async def create(self, user: User) -> None:
        self._users[user.id] = user

    async def find_by_email(self, email: str) -> User | None:
        return next((u for u in self._users.values() if u.email == email), None)

    async def find_by_id(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    async def set_email_verified(self, user_id: str, at: datetime) -> None:
        user = self._users[user_id]
        user.email_verified = True
        user.updated_at = at

    async def update_last_login(self, user_id: str, at: datetime) -> None:
        user = self._users[user_id]
        user.last_login = at
        user.updated_at = at

    async def update_password(
        self, user_id: str, password_hash: str, pwd_token_version: int, at: datetime
    ) -> None:
        user = self._users[user_id]
        user.password_hash = password_hash
        user.pwd_token_version = pwd_token_version
        user.updated_at = at


class FakeTenantRepository:
    def __init__(self) -> None:
        self._tenants: dict[str, Tenant] = {}

    @property
    def tenants(self) -> dict[str, Tenant]:
        return self._tenants

    async def create(self, tenant: Tenant) -> None:
        self._tenants[tenant.id] = tenant

    async def find_by_id(self, tenant_id: str) -> Tenant | None:
        return self._tenants.get(tenant_id)


class FakeMemberRepository:
    def __init__(self) -> None:
        self._members: dict[str, Member] = {}

    @property
    def members(self) -> dict[str, Member]:
        return self._members

    async def create(self, member: Member) -> None:
        self._members[member.id] = member

    async def find_by_user_id(self, user_id: str) -> Member | None:
        return next((m for m in self._members.values() if m.user_id == user_id), None)


class FakeRefreshTokenRepository:
    def __init__(self) -> None:
        self._tokens: dict[str, RefreshToken] = {}

    @property
    def tokens(self) -> dict[str, RefreshToken]:
        return self._tokens

    async def create(self, token: RefreshToken) -> None:
        self._tokens[token.id] = token

    async def find_by_hash(self, token_hash: str) -> RefreshToken | None:
        return next((t for t in self._tokens.values() if t.token_hash == token_hash), None)

    async def mark_revoked(self, token_id: str, replaced_by: str | None, at: datetime) -> None:
        token = self._tokens[token_id]
        token.revoked_at = at
        token.replaced_by = replaced_by

    async def revoke_all_for_user(self, user_id: str, at: datetime) -> None:
        for token in self._tokens.values():
            if token.user_id == user_id and token.revoked_at is None:
                token.revoked_at = at


class FakeAuditLogRepository:
    def __init__(self) -> None:
        self._logs: list[AuditLog] = []

    @property
    def logs(self) -> list[AuditLog]:
        return self._logs

    async def create(self, log: AuditLog) -> None:
        self._logs.append(log)


class FakeApiKeyRepository:
    """In-memory API key repository (tenant-scoped like the Mongo impl)."""

    def __init__(self) -> None:
        self._keys: dict[str, ApiKey] = {}

    @property
    def keys(self) -> dict[str, ApiKey]:
        return self._keys

    async def create(self, key: ApiKey) -> None:
        self._keys[key.id] = key

    async def find_by_id(self, tenant_id: str, key_id: str) -> ApiKey | None:
        key = self._keys.get(key_id)
        if key is not None and key.tenant_id == tenant_id and key.status == API_KEY_STATUS_ACTIVE:
            return key
        return None

    async def list_by_tenant(self, tenant_id: str) -> list[ApiKey]:
        return sorted(
            (
                key
                for key in self._keys.values()
                if key.tenant_id == tenant_id and key.status == API_KEY_STATUS_ACTIVE
            ),
            key=lambda key: key.created_at,
            reverse=True,
        )

    async def revoke(self, tenant_id: str, key_id: str) -> None:
        key = self._keys.get(key_id)
        if key is not None and key.tenant_id == tenant_id:
            key.status = API_KEY_STATUS_REVOKED
            key.updated_at = utcnow()


class FakeWebsiteRepository:
    def __init__(self) -> None:
        self._websites: dict[str, Website] = {}

    @property
    def websites(self) -> dict[str, Website]:
        return self._websites

    async def create(self, website: Website) -> None:
        self._websites[website.id] = website

    async def find_by_id(self, tenant_id: str, website_id: str) -> Website | None:
        website = self._websites.get(website_id)
        if (
            website is not None
            and website.tenant_id == tenant_id
            and website.status != WEBSITE_STATUS_DELETED
        ):
            return website
        return None

    async def find_by_url(self, tenant_id: str, url: str) -> Website | None:
        # Mirrors `MongoWebsiteRepository`: soft-deleted documents are excluded
        # so a deleted website's URL can be re-registered.
        return next(
            (
                website
                for website in self._websites.values()
                if website.tenant_id == tenant_id
                and website.url == url
                and website.status != WEBSITE_STATUS_DELETED
            ),
            None,
        )

    async def find_by_id_any(self, website_id: str) -> Website | None:
        return self._websites.get(website_id)

    async def list_by_tenant(
        self,
        tenant_id: str,
        *,
        status: str | None = None,
        sort: str = "created_at",
        order: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> list[Website]:
        candidates = [
            website
            for website in self._websites.values()
            if website.tenant_id == tenant_id
            and website.status != WEBSITE_STATUS_DELETED
            and (status is None or website.status == status)
        ]
        reverse = order == "desc"
        if sort == "name":
            candidates = sorted(candidates, key=lambda w: w.name.lower(), reverse=reverse)
        else:
            candidates = sorted(candidates, key=lambda w: w.created_at, reverse=reverse)
        return candidates[offset : offset + limit]

    async def count_by_tenant(self, tenant_id: str, *, status: str | None = None) -> int:
        return len(
            [
                website
                for website in self._websites.values()
                if website.tenant_id == tenant_id
                and website.status != WEBSITE_STATUS_DELETED
                and (status is None or website.status == status)
            ]
        )

    async def update(self, website: Website) -> None:
        self._websites[website.id] = website

    async def delete(self, tenant_id: str, website_id: str) -> None:
        website = self._websites.get(website_id)
        if website is not None and website.tenant_id == tenant_id:
            website.status = WEBSITE_STATUS_DELETED
            website.deleted = True
            website.updated_at = utcnow()


class FakeWidgetRepository:
    def __init__(self) -> None:
        self._widgets: dict[str, Widget] = {}

    @property
    def widgets(self) -> dict[str, Widget]:
        return self._widgets

    async def create(self, widget: Widget) -> None:
        self._widgets[widget.id] = widget

    async def find_by_website_id(self, tenant_id: str, website_id: str) -> Widget | None:
        return next(
            (
                widget
                for widget in self._widgets.values()
                if widget.tenant_id == tenant_id and widget.website_id == website_id
            ),
            None,
        )

    async def list_by_website_ids(self, tenant_id: str, website_ids: list[str]) -> list[Widget]:
        return [
            widget
            for widget in self._widgets.values()
            if widget.tenant_id == tenant_id and widget.website_id in website_ids
        ]

    async def delete_by_website_id(self, tenant_id: str, website_id: str) -> None:
        for widget_id in list(self._widgets):
            widget = self._widgets[widget_id]
            if widget.tenant_id == tenant_id and widget.website_id == website_id:
                del self._widgets[widget_id]

    async def update_widget_config(
        self, tenant_id: str, website_id: str, updates: dict
    ) -> Widget | None:
        widget = next(
            (
                widget
                for widget in self._widgets.values()
                if widget.tenant_id == tenant_id and widget.website_id == website_id
            ),
            None,
        )
        if widget is None:
            return None
        for key, value in updates.items():
            setattr(widget, key, value)
        widget.updated_at = utcnow()
        return widget

    async def find_by_widget_id(self, widget_id: str) -> Widget | None:
        return next(
            (widget for widget in self._widgets.values() if widget.widget_id == widget_id),
            None,
        )


class RecordingMailDispatcher:
    """Async callable that records delivered emails for assertions."""

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    async def __call__(self, message: EmailMessage) -> None:
        self.sent.append(message)


class FakeWidgetStore:
    """In-memory `WidgetStore` mirroring the Redis surface (Phase 8)."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    @property
    def data(self) -> dict[str, str]:
        return self._data

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def setex(self, key: str, seconds: int, value: str) -> None:
        self._data[key] = value

    async def incr(self, key: str) -> int:
        value = int(self._data.get(key, "0")) + 1
        self._data[key] = str(value)
        return value

    async def expire(self, key: str, seconds: int) -> None:
        pass

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)


class FakeCrawlJobRepository:
    """In-memory crawl job repository (tenant-scoped like the Mongo impl)."""

    def __init__(self) -> None:
        self._jobs: dict[str, CrawlJob] = {}

    @property
    def jobs(self) -> dict[str, CrawlJob]:
        return self._jobs

    async def create(self, job: CrawlJob) -> None:
        self._jobs[job.id] = job

    async def find_by_id(self, tenant_id: str, job_id: str) -> CrawlJob | None:
        job = self._jobs.get(job_id)
        return job if job is not None and job.tenant_id == tenant_id else None

    async def find_by_id_any(self, job_id: str) -> CrawlJob | None:
        return self._jobs.get(job_id)

    async def find_active_for_website(self, tenant_id: str, website_id: str) -> CrawlJob | None:
        return next(
            (
                job
                for job in self._jobs.values()
                if job.tenant_id == tenant_id
                and job.website_id == website_id
                and job.status in CRAWL_ACTIVE_STATUSES
            ),
            None,
        )

    async def update(self, job: CrawlJob) -> None:
        self._jobs[job.id] = job


class FakeDocumentRepository:
    """In-memory document repository with a (tenant, website, url) unique key."""

    def __init__(self) -> None:
        self._documents: dict[str, Document] = {}

    @property
    def documents(self) -> dict[str, Document]:
        return self._documents

    async def upsert(self, document: Document) -> None:
        for existing_id, existing in list(self._documents.items()):
            if (
                existing.tenant_id == document.tenant_id
                and existing.website_id == document.website_id
                and existing.url == document.url
            ):
                del self._documents[existing_id]
                break
        self._documents[document.id] = document

    async def count_by_website(self, tenant_id: str, website_id: str) -> int:
        return len(
            [
                document
                for document in self._documents.values()
                if document.tenant_id == tenant_id and document.website_id == website_id
            ]
        )

    async def all_checksums(self, tenant_id: str, website_id: str) -> list[str]:
        return [
            document.checksum
            for document in self._documents.values()
            if document.tenant_id == tenant_id and document.website_id == website_id
        ]

    async def find_by_id(self, tenant_id: str, document_id: str) -> Document | None:
        document = self._documents.get(document_id)
        if document is not None and document.tenant_id == tenant_id:
            return document
        return None

    async def find_by_id_any(self, document_id: str) -> Document | None:
        return self._documents.get(document_id)

    async def list_by_website(self, tenant_id: str, website_id: str) -> list[Document]:
        return [
            document
            for document in self._documents.values()
            if document.tenant_id == tenant_id and document.website_id == website_id
        ]


class FakeEmbeddingClient:
    """Deterministic embedding client: vector i is derived from text[i]."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    @property
    def embeddings(self) -> dict[str, list[float]]:
        return {text: self._vector(text) for batch in self.calls for text in batch}

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [self._vector(text) for text in texts]

    @staticmethod
    def _vector(text: str) -> list[float]:
        # Stable hash-based 4-d vector so identical text embeds identically.
        return [hash(text) % 1000 / 1000.0, len(text), float(len(text.split())), 1.0]


class FakeVectorRepository:
    """In-memory VectorRepository keyed by (tenant, website, document, index)."""

    def __init__(self) -> None:
        self._chunks: dict[tuple[str, str, str, int], KnowledgeChunk] = {}

    @property
    def chunks(self) -> list[KnowledgeChunk]:
        return list(self._chunks.values())

    def by_document(self, tenant_id: str, document_id: str) -> list[KnowledgeChunk]:
        return [
            chunk
            for chunk in self._chunks.values()
            if chunk.tenant_id == tenant_id and chunk.document_id == document_id
        ]

    async def insert_chunks(self, chunks: list[KnowledgeChunk]) -> int:
        inserted = 0
        for chunk in chunks:
            key = (chunk.tenant_id, chunk.website_id, chunk.document_id, chunk.chunk_index)
            if key not in self._chunks:
                inserted += 1
            self._chunks[key] = chunk
        return inserted

    async def delete_by_document(self, tenant_id: str, document_id: str) -> int:
        deleted = len(self.by_document(tenant_id, document_id))
        for key in list(self._chunks):
            if key[0] == tenant_id and key[2] == document_id:
                del self._chunks[key]
        return deleted

    async def delete_by_website(self, tenant_id: str, website_id: str) -> int:
        deleted = 0
        for key in list(self._chunks):
            if key[0] == tenant_id and key[1] == website_id:
                del self._chunks[key]
                deleted += 1
        return deleted

    async def similarity_search(
        self,
        tenant_id: str,
        website_id: str,
        query_embedding: list[float],
        *,
        top_k: int = 5,
    ) -> list[VectorSearchResult]:
        candidates = [
            chunk
            for chunk in self._chunks.values()
            if chunk.tenant_id == tenant_id and chunk.website_id == website_id
        ]
        results = [
            VectorSearchResult(chunk=chunk, score=0.9 - chunk.chunk_index / 100.0)
            for chunk in candidates
        ]
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]


class FakeKnowledgeChunkRepository:
    """In-memory read-side knowledge chunk statistics.

    In production both `MongoVectorRepository` and `MongoKnowledgeChunkRepository`
    read the same `knowledge_chunks` collection. To mirror that, this fake can be
    constructed around a `FakeVectorRepository` so counts reflect inserted chunks.
    """

    def __init__(self, vector: FakeVectorRepository | None = None) -> None:
        self._chunks: dict[str, KnowledgeChunk] = {}
        self._vector = vector

    def seed(self, chunks: list[KnowledgeChunk]) -> None:
        for chunk in chunks:
            self._chunks[chunk.id] = chunk

    def _all(self) -> list[KnowledgeChunk]:
        return self._vector.chunks if self._vector is not None else list(self._chunks.values())

    async def count_by_website(self, tenant_id: str, website_id: str) -> int:
        return len(
            [
                chunk
                for chunk in self._all()
                if chunk.tenant_id == tenant_id and chunk.website_id == website_id
            ]
        )

    async def count_by_document(self, tenant_id: str, document_id: str) -> int:
        return len(
            [
                chunk
                for chunk in self._all()
                if chunk.tenant_id == tenant_id and chunk.document_id == document_id
            ]
        )

    async def count_documents_by_website(self, tenant_id: str, website_id: str) -> int:
        return len(
            {
                chunk.document_id
                for chunk in self._all()
                if chunk.tenant_id == tenant_id and chunk.website_id == website_id
            }
        )


class FakeChatSessionRepository:
    """In-memory chat session repository (tenant-scoped like the Mongo impl)."""

    def __init__(self) -> None:
        self._sessions: dict[str, ChatSession] = {}

    @property
    def sessions(self) -> dict[str, ChatSession]:
        return self._sessions

    async def create(self, session: ChatSession) -> None:
        self._sessions[session.session_id] = session

    async def find_by_session_id(self, tenant_id: str, session_id: str) -> ChatSession | None:
        session = self._sessions.get(session_id)
        if (
            session is not None
            and session.tenant_id == tenant_id
            and session.status != CHAT_SESSION_STATUS_DELETED
        ):
            return session
        return None

    async def touch(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            session.last_activity = utcnow()

    async def list_by_website(
        self,
        tenant_id: str,
        website_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ChatSession]:
        candidates = sorted(
            (
                session
                for session in self._sessions.values()
                if session.tenant_id == tenant_id
                and session.website_id == website_id
                and session.status != CHAT_SESSION_STATUS_DELETED
            ),
            key=lambda session: session.last_activity,
            reverse=True,
        )
        return candidates[offset : offset + limit]

    async def count_by_website(self, tenant_id: str, website_id: str) -> int:
        return len(
            [
                session
                for session in self._sessions.values()
                if session.tenant_id == tenant_id
                and session.website_id == website_id
                and session.status != CHAT_SESSION_STATUS_DELETED
            ]
        )

    async def list_by_tenant(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        session_ids: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ChatSession]:
        candidates = sorted(
            (
                session
                for session in self._sessions.values()
                if session.tenant_id == tenant_id
                and session.status != CHAT_SESSION_STATUS_DELETED
                and (website_id is None or session.website_id == website_id)
                and (session_ids is None or session.session_id in session_ids)
            ),
            key=lambda session: session.last_activity,
            reverse=True,
        )
        return candidates[offset : offset + limit]

    async def count_by_tenant(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        session_ids: list[str] | None = None,
    ) -> int:
        return len(
            [
                session
                for session in self._sessions.values()
                if session.tenant_id == tenant_id
                and session.status != CHAT_SESSION_STATUS_DELETED
                and (website_id is None or session.website_id == website_id)
                and (session_ids is None or session.session_id in session_ids)
            ]
        )

    async def delete(self, tenant_id: str, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if (
            session is not None
            and session.tenant_id == tenant_id
            and session.status != CHAT_SESSION_STATUS_DELETED
        ):
            session.status = CHAT_SESSION_STATUS_DELETED
            return True
        return False


class FakeChatMessageRepository:
    """In-memory chat message repository (tenant-scoped like the Mongo impl)."""

    def __init__(self) -> None:
        self._messages: list[ChatMessage] = []

    @property
    def messages(self) -> list[ChatMessage]:
        return self._messages

    async def create(self, message: ChatMessage) -> None:
        self._messages.append(message)

    async def list_recent(
        self,
        tenant_id: str,
        session_id: str,
        *,
        limit: int = 20,
    ) -> list[ChatMessage]:
        recent = [
            message
            for message in self._messages
            if message.tenant_id == tenant_id and message.session_id == session_id
        ]
        return recent[-limit:]

    async def count_by_session(self, tenant_id: str, session_id: str) -> int:
        return len(
            [
                message
                for message in self._messages
                if message.tenant_id == tenant_id and message.session_id == session_id
            ]
        )

    async def list_by_session(self, tenant_id: str, session_id: str) -> list[ChatMessage]:
        return sorted(
            (
                message
                for message in self._messages
                if message.tenant_id == tenant_id and message.session_id == session_id
            ),
            key=lambda message: message.created_at,
        )

    async def summarize_sessions(
        self, tenant_id: str, session_ids: list[str]
    ) -> dict[str, MessageSummary]:
        summaries: dict[str, MessageSummary] = {}
        for session_id in session_ids:
            messages = [
                message
                for message in self._messages
                if message.tenant_id == tenant_id and message.session_id == session_id
            ]
            if not messages:
                continue
            ordered = sorted(messages, key=lambda message: message.created_at)
            summaries[session_id] = MessageSummary(
                message_count=len(ordered),
                first_content=ordered[0].content,
                last_content=ordered[-1].content,
                last_role=ordered[-1].role,
                last_created_at=ordered[-1].created_at,
                total_input_tokens=sum(message.input_tokens for message in ordered),
                total_output_tokens=sum(message.output_tokens for message in ordered),
                max_response_time=max(
                    (
                        message.response_time
                        for message in ordered
                        if message.response_time is not None
                    ),
                    default=None,
                ),
            )
        return summaries

    async def search_session_ids(
        self,
        tenant_id: str,
        *,
        query: str,
        website_id: str | None = None,
        limit: int = 500,
    ) -> list[str]:
        needle = query.casefold()
        matches: list[str] = []
        for message in self._messages:
            if message.tenant_id != tenant_id:
                continue
            if website_id is not None and message.website_id != website_id:
                continue
            if needle in message.content.casefold():
                if message.session_id not in matches:
                    matches.append(message.session_id)
        return matches[:limit]

    async def delete_by_session(self, tenant_id: str, session_id: str) -> int:
        remaining = [
            message
            for message in self._messages
            if not (message.tenant_id == tenant_id and message.session_id == session_id)
        ]
        deleted = len(self._messages) - len(remaining)
        self._messages = remaining
        return deleted


class FakeUsageRecordRepository:
    """In-memory usage rollup repository (ADR-005 §5.5)."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str, str], UsageRecord] = {}

    @property
    def records(self) -> list[UsageRecord]:
        return list(self._records.values())

    def get_record(self, tenant_id: str, website_id: str, date: str) -> UsageRecord | None:
        return self._records.get((tenant_id, website_id, date))

    async def increment(
        self,
        *,
        tenant_id: str,
        website_id: str,
        date: str,
        counters: dict[str, int],
    ) -> None:
        key = (tenant_id, website_id, date)
        record = self._records.get(key)
        if record is None:
            record = UsageRecord.new(tenant_id=tenant_id, website_id=website_id, date=date)
            self._records[key] = record
        for name, value in counters.items():
            record.counters[name] = record.counters.get(name, 0) + value
        record.updated_at = utcnow()

    async def get(self, tenant_id: str, website_id: str, date: str) -> UsageRecord | None:
        return self._records.get((tenant_id, website_id, date))


class FakeAnalyticsRepository:
    """In-memory read-only analytics repository over the other fakes (Phase 11.3).

    Aggregates the same way `MongoAnalyticsRepository` does, so the service and
    routes are exercised without a database (layering rules §6): conversations
    come from non-deleted `chat_sessions`, AI response counts and response
    times from `assistant` messages, message/token totals from the daily
    `usage_records` rollup, and website names from `websites`.
    """

    def __init__(
        self,
        *,
        sessions: FakeChatSessionRepository,
        messages: FakeChatMessageRepository,
        usage: FakeUsageRecordRepository,
        websites: FakeWebsiteRepository,
    ) -> None:
        self._sessions = sessions
        self._messages = messages
        self._usage = usage
        self._websites = websites

    async def summary(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        since: datetime,
    ) -> AnalyticsSummaryRow:
        conversations = self._conversations(tenant_id, website_id=website_id, since=since)
        responses = [
            msg
            for msg in self._messages.messages
            if msg.tenant_id == tenant_id
            and msg.role == CHAT_ROLE_ASSISTANT
            and msg.created_at >= since
            and (website_id is None or msg.website_id == website_id)
        ]
        response_times = [m.response_time for m in responses if m.response_time is not None]
        records = self._usage_records(tenant_id, website_id=website_id, since=since)
        return AnalyticsSummaryRow(
            total_conversations=conversations,
            total_messages=sum(r.counters.get("messages", 0) for r in records),
            total_ai_responses=len(responses),
            total_input_tokens=sum(r.counters.get("input_tokens", 0) for r in records),
            total_output_tokens=sum(r.counters.get("output_tokens", 0) for r in records),
            avg_response_time=(
                round(sum(response_times) / len(response_times), 3) if response_times else None
            ),
        )

    async def timeseries(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        since: datetime,
    ) -> list[TimeseriesRow]:
        return [
            TimeseriesRow(
                date=date,
                conversations=sum(r.counters.get("chats", 0) for r in rows),
                messages=sum(r.counters.get("messages", 0) for r in rows),
                tokens=sum(
                    r.counters.get("input_tokens", 0) + r.counters.get("output_tokens", 0)
                    for r in rows
                ),
                input_tokens=sum(r.counters.get("input_tokens", 0) for r in rows),
                output_tokens=sum(r.counters.get("output_tokens", 0) for r in rows),
            )
            for date, rows in sorted(
                self._usage_grouped(tenant_id, website_id=website_id, since=since).items()
            )
        ]

    async def top_websites(
        self,
        tenant_id: str,
        *,
        since: datetime,
        limit: int,
    ) -> list[TopWebsiteRow]:
        groups: dict[str, tuple[int, int]] = {}
        for record in self._usage.records:
            if record.tenant_id != tenant_id or record.date < since.date().isoformat():
                continue
            chats, messages = groups.get(record.website_id, (0, 0))
            groups[record.website_id] = (
                chats + record.counters.get("chats", 0),
                messages + record.counters.get("messages", 0),
            )
        ranked = sorted(groups.items(), key=lambda item: (-item[1][0], -item[1][1], item[0]))[
            :limit
        ]
        names = self._website_names(tenant_id)
        return [
            TopWebsiteRow(
                website_id=website_id,
                website_name=names.get(website_id, "Unknown website"),
                conversations=conversations,
                messages=messages,
            )
            for website_id, (conversations, messages) in ranked
        ]

    async def response_metrics(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        since: datetime,
    ) -> ResponseMetricsRow:
        response_times = [
            m.response_time
            for m in self._messages.messages
            if m.tenant_id == tenant_id
            and m.role == CHAT_ROLE_ASSISTANT
            and m.response_time is not None
            and m.created_at >= since
            and (website_id is None or m.website_id == website_id)
        ]
        if not response_times:
            return ResponseMetricsRow(None, None, None)
        return ResponseMetricsRow(
            avg_response_time=round(sum(response_times) / len(response_times), 3),
            fastest_response_time=round(min(response_times), 3),
            slowest_response_time=round(max(response_times), 3),
        )

    # ------------------------------------------------------------- internals

    def _conversations(self, tenant_id: str, *, website_id: str | None, since: datetime) -> int:
        return sum(
            1
            for session in self._sessions.sessions.values()
            if session.tenant_id == tenant_id
            and session.status != CHAT_SESSION_STATUS_DELETED
            and session.started_at >= since
            and (website_id is None or session.website_id == website_id)
        )

    def _usage_records(
        self, tenant_id: str, *, website_id: str | None, since: datetime
    ) -> list[UsageRecord]:
        return [
            record
            for record in self._usage.records
            if record.tenant_id == tenant_id
            and record.date >= since.date().isoformat()
            and (website_id is None or record.website_id == website_id)
        ]

    def _usage_grouped(
        self, tenant_id: str, *, website_id: str | None, since: datetime
    ) -> dict[str, list[UsageRecord]]:
        grouped: dict[str, list[UsageRecord]] = {}
        for record in self._usage_records(tenant_id, website_id=website_id, since=since):
            grouped.setdefault(record.date, []).append(record)
        return grouped

    def _website_names(self, tenant_id: str) -> dict[str, str]:
        return {
            website.id: website.name
            for website in self._websites.websites.values()
            if website.tenant_id == tenant_id and website.status != WEBSITE_STATUS_DELETED
        }


class FakeGenerationClient:
    """Fake `GenerationClient`: records the prompt and streams canned deltas.

    `usage` defaults to 10/20 tokens but can be configured; `failures` lets
    tests exercise the error path.
    """

    def __init__(self, deltas: list[str] | None = None) -> None:
        self.calls: list[dict] = []
        self.deltas = deltas if deltas is not None else ["Hello", " world!"]
        self.failures: list[Exception] = []
        self.input_tokens = 10
        self.output_tokens = 20

    @property
    def usage(self) -> GenerationUsage:
        return GenerationUsage(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )

    def stream_generate(
        self,
        *,
        system: str,
        messages: list[tuple[str, str]],
    ):
        self.calls.append({"system": system, "messages": messages})
        if self.failures:
            raise self.failures.pop(0)

        async def _stream():
            for delta in self.deltas:
                yield delta

        return _stream()
