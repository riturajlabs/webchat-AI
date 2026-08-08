"""In-memory fakes for repositories and mail delivery used in auth tests."""

from datetime import datetime

from backend.core.security import utcnow
from backend.models.audit_log import AuditLog
from backend.models.crawl_job import (
    CRAWL_ACTIVE_STATUSES,
    CrawlJob,
)
from backend.models.document import Document
from backend.models.member import Member
from backend.models.refresh_token import RefreshToken
from backend.models.tenant import Tenant
from backend.models.user import User
from backend.models.website import WEBSITE_STATUS_DELETED, Website
from backend.models.widget import Widget
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
