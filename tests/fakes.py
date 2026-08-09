"""In-memory fakes for repositories and mail delivery used in auth tests."""

from datetime import datetime

from backend.ai.gemini import GenerationUsage
from backend.core.security import utcnow
from backend.models.audit_log import AuditLog
from backend.models.chat_message import ChatMessage
from backend.models.chat_session import ChatSession
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
        return next(
            (
                website
                for website in self._websites.values()
                if website.tenant_id == tenant_id and website.url == url
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
            if website.tenant_id == tenant_id and website.status != WEBSITE_STATUS_DELETED
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


class RecordingMailDispatcher:
    """Async callable that records delivered emails for assertions."""

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    async def __call__(self, message: EmailMessage) -> None:
        self.sent.append(message)


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

    async def find_active_for_website(
        self, tenant_id: str, website_id: str
    ) -> CrawlJob | None:
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
        return {
            text: self._vector(text)
            for batch in self.calls
            for text in batch
        }

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
        if session is not None and session.tenant_id == tenant_id:
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
                if session.tenant_id == tenant_id and session.website_id == website_id
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
                if session.tenant_id == tenant_id and session.website_id == website_id
            ]
        )


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
