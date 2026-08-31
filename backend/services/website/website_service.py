"""Website management business logic (Phase 3, ADR-008).

Routes validate and translate; this service owns every workflow: create
(website + widget + embed script), list/get, update (URL changes reset
crawl state), and delete (cascades to widgets, documents and vector
chunks). All database access is tenant-scoped by the caller-provided
`tenant_id`, never by request input.
"""

from dataclasses import dataclass
from urllib.parse import urlparse

from backend.core.config import Settings, get_settings
from backend.core.errors import (
    DuplicateWebsiteError,
    WebsiteNotFoundError,
)
from backend.core.security import utcnow
from backend.models.audit_log import (
    AUDIT_WEBSITE_CREATED,
    AUDIT_WEBSITE_DELETED,
    AUDIT_WEBSITE_UPDATED,
    AuditLog,
)
from backend.models.website import WEBSITE_STATUS_PENDING, Website
from backend.models.widget import Widget
from backend.repositories import (
    AuditLogRepository,
    ChatMessageRepository,
    ChatSessionRepository,
    CrawlJobRepository,
    DocumentRepository,
    FeedbackRepository,
    UsageRecordRepository,
    WebsiteRepository,
    WebsiteSortField,
    WebsiteSortOrder,
    WidgetRepository,
)
from backend.repositories.vector.base import VectorRepository
from backend.services.auth import Principal
from backend.services.billing import UsageService
from backend.utils.url_validator import normalize_url


@dataclass(frozen=True)
class WebsiteListItem:
    """A website paired with its public widget id for listing responses."""

    website: Website
    widget_id: str


@dataclass(frozen=True)
class CreateWebsiteResult:
    """Create response: the persisted website and widget plus embed script."""

    website: Website
    widget: Widget
    embed_script: str


class WebsiteService:
    """Encapsulates every website-management workflow."""

    def __init__(
        self,
        *,
        websites: WebsiteRepository,
        widgets: WidgetRepository,
        audit: AuditLogRepository,
        settings: Settings | None = None,
        usage: UsageService | None = None,
        documents: DocumentRepository | None = None,
        vector: VectorRepository | None = None,
        chat_sessions: ChatSessionRepository | None = None,
        chat_messages: ChatMessageRepository | None = None,
        feedback: FeedbackRepository | None = None,
        crawl_jobs: CrawlJobRepository | None = None,
        usage_records: UsageRecordRepository | None = None,
    ) -> None:
        self._websites = websites
        self._widgets = widgets
        self._audit = audit
        self._settings = settings or get_settings()
        # Phase 13 billing: raises `LimitReachedError` before the tenant can
        # exceed `max_websites`. Optional so pre-existing call sites/tests keep
        # working without a usage service.
        self._usage = usage
        # Audit R-02/A-06: deletion cascades to the crawled pages and their
        # embedded chunks. Optional so pre-existing call sites keep working.
        self._documents = documents
        self._vector = vector
        # Cascade deletion to tenant-owned conversation/message/feedback/crawl/
        # usage data on website deletion. Optional for backward compatibility.
        self._chat_sessions = chat_sessions
        self._chat_messages = chat_messages
        self._feedback = feedback
        self._crawl_jobs = crawl_jobs
        self._usage_records = usage_records

    # ------------------------------------------------------------------ flows

    async def create_website(
        self,
        *,
        principal: Principal,
        name: str,
        url: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> CreateWebsiteResult:
        normalized_url = normalize_url(url)
        if await self._websites.find_by_url(principal.tenant_id, normalized_url) is not None:
            raise DuplicateWebsiteError("A website with this URL already exists.")
        if self._usage is not None:
            # Phase 13 billing: reject before persisting anything.
            await self._usage.check_limit(principal.tenant_id, event_type="websites")

        website = Website.new(
            tenant_id=principal.tenant_id,
            name=name.strip(),
            url=normalized_url,
        )
        await self._websites.create(website)

        widget = Widget.new(
            tenant_id=principal.tenant_id,
            website_id=website.id,
        )
        # Seed the embed-origin allowlist from the registered website host so
        # new widgets are protected-by-default against embedding elsewhere;
        # tenants extend it from the dashboard widget builder.
        seed_domain = self._embed_domain(normalized_url)
        if seed_domain:
            widget.allowed_domains = [seed_domain]
        try:
            await self._widgets.create(widget)
        except Exception:
            # Do not leave an orphan website behind if widget creation fails.
            await self._websites.delete(principal.tenant_id, website.id)
            raise

        await self._audit.create(
            AuditLog.new(
                action=AUDIT_WEBSITE_CREATED,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        return CreateWebsiteResult(
            website=website,
            widget=widget,
            embed_script=self.build_embed_script(widget.widget_id),
        )

    async def list_websites(
        self,
        tenant_id: str,
        *,
        status: str | None = None,
        sort: WebsiteSortField = "created_at",
        order: WebsiteSortOrder = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[WebsiteListItem], int]:
        """Return (page items, total matching count) for the tenant.

        Soft-deleted websites are always excluded; `status` narrows to one
        remaining status. Pagination/sorting are delegated to the repository.
        """
        websites = await self._websites.list_by_tenant(
            tenant_id,
            status=status,
            sort=sort,
            order=order,
            limit=limit,
            offset=offset,
        )
        total = await self._websites.count_by_tenant(tenant_id, status=status)
        if not websites:
            return [], total
        widgets = await self._widgets.list_by_website_ids(
            tenant_id, [website.id for website in websites]
        )
        widget_by_website = {widget.website_id: widget.widget_id for widget in widgets}
        items = [
            WebsiteListItem(
                website=website,
                widget_id=widget_by_website.get(website.id, ""),
            )
            for website in websites
        ]
        return items, total

    async def get_website(self, tenant_id: str, website_id: str) -> Website:
        website = await self._websites.find_by_id(tenant_id, website_id)
        if website is None:
            raise WebsiteNotFoundError("Website not found.")
        return website

    async def get_widget(self, tenant_id: str, website_id: str) -> Widget:
        widget = await self._widgets.find_by_website_id(tenant_id, website_id)
        if widget is None:
            raise WebsiteNotFoundError("Website not found.")
        return widget

    async def update_website(
        self,
        *,
        principal: Principal,
        website_id: str,
        name: str | None,
        url: str | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> Website:
        website = await self._websites.find_by_id(principal.tenant_id, website_id)
        if website is None:
            raise WebsiteNotFoundError("Website not found.")

        if name is not None:
            website.name = name.strip()
        if url is not None:
            normalized_url = normalize_url(url)
            if normalized_url != website.url:
                existing = await self._websites.find_by_url(principal.tenant_id, normalized_url)
                if existing is not None and existing.id != website.id:
                    raise DuplicateWebsiteError("A website with this URL already exists.")
                website.url = normalized_url
                # Content changed: reset crawl state until the next index run.
                website.status = WEBSITE_STATUS_PENDING
                website.pages_indexed = 0
                website.last_crawled_at = None
                website.checksum = None
        website.updated_at = utcnow()
        await self._websites.update(website)
        await self._audit.create(
            AuditLog.new(
                action=AUDIT_WEBSITE_UPDATED,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        return website

    async def delete_website(
        self,
        *,
        principal: Principal,
        website_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        website = await self._websites.find_by_id(principal.tenant_id, website_id)
        if website is None:
            raise WebsiteNotFoundError("Website not found.")
        await self._widgets.delete_by_website_id(principal.tenant_id, website_id)
        # Audit R-02/A-06: without this purge the crawled documents and their
        # embedded chunks outlive the website indefinitely (storage growth and
        # retention exposure).
        if self._documents is not None:
            await self._documents.delete_by_website(principal.tenant_id, website_id)
        if self._vector is not None:
            await self._vector.delete_by_website(principal.tenant_id, website_id)
        # Cascade deletion to tenant-owned conversation/feedback/crawl/usage
        # data so no content or rollups outlive the website (retention/compliance).
        if self._chat_sessions is not None:
            await self._chat_sessions.delete_by_website(principal.tenant_id, website_id)
        if self._chat_messages is not None:
            await self._chat_messages.delete_by_website(principal.tenant_id, website_id)
        if self._feedback is not None:
            await self._feedback.delete_by_website(principal.tenant_id, website_id)
        if self._crawl_jobs is not None:
            await self._crawl_jobs.delete_by_website(principal.tenant_id, website_id)
        if self._usage_records is not None:
            await self._usage_records.delete_by_website(principal.tenant_id, website_id)
        await self._websites.delete(principal.tenant_id, website_id)
        await self._audit.create(
            AuditLog.new(
                action=AUDIT_WEBSITE_DELETED,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

    # ------------------------------------------------------------- internals

    @staticmethod
    def _embed_domain(url: str) -> str | None:
        """Hostname of the registered website URL, or None when unusable."""
        try:
            parsed = urlparse(url)
        except ValueError:
            return None
        host = parsed.hostname
        if not host:
            return None
        return host.lower().rstrip(".")

    def build_embed_script(self, widget_id: str) -> str:
        """One-line embed snippet for a widget.

        `data-api-base-url` is included so the SDK resolves the API origin from
        the embed tag (the highest-precedence source) regardless of which build
        the served bundle was produced with. The SDK appends `/api/widget/v1`
        when needed.

        Development: falls back to the local API (`http://localhost:8000`)
        when `WIDGET_API_BASE_URL` is unset so a local embed never resolves to
        the page's own origin. Production requires `WIDGET_API_BASE_URL` (or
        omits the attribute so the build-time bundle default applies).
        """
        api_base = self._widget_api_base()
        api_attr = f' data-api-base-url="{api_base}"' if api_base else ""
        return (
            f'<script src="{self._settings.widget_script_url}" '
            f'data-widget-id="{widget_id}"{api_attr} defer></script>'
        )

    def _widget_api_base(self) -> str:
        """Public API origin for the embed tag (empty = omit the attribute)."""
        if self._settings.widget_api_base_url:
            return self._settings.widget_api_base_url.rstrip("/")
        if self._settings.environment.lower() == "production":
            return ""
        return "http://localhost:8000"


__all__ = [
    "CreateWebsiteResult",
    "WebsiteListItem",
    "WebsiteService",
]
