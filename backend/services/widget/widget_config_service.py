"""Dashboard widget customization workflow (Phase 11.5).

Owns the single write path of the widget builder: apply a validated,
tenant+website-scoped set of config changes, record an audit event, and
invalidate the public Redis cache so the live embed picks up the new
appearance immediately. The RAG pipeline, AI providers, the public widget API
and the SDK runtime are untouched by design.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from backend.core.errors import WebsiteNotFoundError
from backend.models.audit_log import AUDIT_WIDGET_UPDATED, AuditLog
from backend.models.widget import Widget
from backend.repositories import AuditLogRepository, WidgetRepository

logger = logging.getLogger("webchat_ai")


class WidgetConfigService:
    """Encapsulates the dashboard widget-customization workflow.

    Tenancy comes from the caller-provided `tenant_id` (the authenticated
    principal's tenant), never from request input; the repository enforces the
    same scoping at the data layer.
    """

    def __init__(
        self,
        *,
        widgets: WidgetRepository,
        audit: AuditLogRepository,
        invalidate_public_config: Callable[[str], Awaitable[None]],
    ) -> None:
        self._widgets = widgets
        self._audit = audit
        self._invalidate_public_config = invalidate_public_config

    async def update_widget_config(
        self,
        *,
        tenant_id: str,
        website_id: str,
        user_id: str,
        changes: dict[str, Any],
        ip_address: str | None,
        user_agent: str | None,
    ) -> Widget:
        """Apply the requested config changes and return the updated widget.

        Raises `WebsiteNotFoundError` when the website (or its widget) does not
        exist for this tenant, so tenant isolation holds even though the widget
        is addressed by `website_id` only.
        """
        widget = await self._widgets.update_widget_config(tenant_id, website_id, changes)
        if widget is None:
            raise WebsiteNotFoundError("Website not found.")

        await self._audit.create(
            AuditLog.new(
                action=AUDIT_WIDGET_UPDATED,
                tenant_id=tenant_id,
                user_id=user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        # Best-effort: a Redis failure never blocks the save (the stale entry
        # ages out via its TTL). The public chat guard re-checks live state on
        # every request regardless of the cache (Phase 8, ADR-004).
        await self._invalidate_public_config(widget.widget_id)
        return widget


__all__ = ["WidgetConfigService"]
