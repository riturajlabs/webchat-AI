"""Public widget orchestration (Phase 8, ADR-004 §widget).

Owns the three public workflows:
  * `get_public_config`  - Redis-cached (300 s) theme/branding for the embed;
                            suspended tenant -> `enabled: false` (never 403).
  * `create_session`     - mints the 15-min widget-session JWT and refreshes
                            the 24 h sliding validity window per visitor.
  * `validate_chat`      - re-checks widget enabled + tenant active + website
                            `ready` on every chat request (claims are never
                            trusted alone; ADR-004 tenant validation flow).
  * `check_message_cap`  - 50-message per-conversation counter (ADR-004).

`RagService.stream_answer` is reused verbatim as the chat engine; this module
never duplicates pipeline logic.
"""

import logging
from datetime import datetime, timedelta
from typing import Protocol

from backend.core.config import Settings, get_settings
from backend.core.errors import (
    MessageLimitReachedError,
    WebsiteNotReadyError,
    WidgetDisabledError,
    WidgetNotFoundError,
    WidgetOriginNotAllowedError,
)
from backend.core.security import create_widget_session_token, utcnow
from backend.models.website import WEBSITE_STATUS_READY
from backend.repositories import TenantRepository, WebsiteRepository, WidgetRepository
from backend.schemas.widget import WidgetPublicConfig
from backend.utils.origin import origin_allowed, origin_hostname

logger = logging.getLogger("webchat_ai")

CONFIG_CACHE_PREFIX = "wk:config:"
SESSION_VALIDITY_PREFIX = "ws:session:"
MESSAGE_COUNT_PREFIX = "ws:msgs:"

# Sliding session validity TTL in seconds (config value, hours -> seconds).
_VALIDITY_SECONDS_MULTIPLIER = 3600
# Message-cap counter TTL (24 h; ADR-005 conversation retention is 90 days but
# the counter only needs to bound a single conversation window).
MESSAGE_CAP_TTL_SECONDS = 24 * 3600


class WidgetStore(Protocol):
    """Minimal Redis surface used by `WidgetService` (adapter in deps.py)."""

    async def get(self, key: str) -> str | None: ...

    async def setex(self, key: str, seconds: int, value: str) -> None: ...

    async def incr(self, key: str) -> int: ...

    async def expire(self, key: str, seconds: int) -> None: ...

    async def delete(self, key: str) -> None: ...


class WidgetService:
    """Public-facing widget business logic (config, sessions, chat guards)."""

    def __init__(
        self,
        *,
        widgets: WidgetRepository,
        tenants: TenantRepository,
        websites: WebsiteRepository,
        store: WidgetStore,
        settings: Settings | None = None,
    ) -> None:
        self._widgets = widgets
        self._tenants = tenants
        self._websites = websites
        self._store = store
        self._settings = settings or get_settings()

    # ------------------------------------------------------------ config

    async def validate_origin(self, widget_id: str, origin: str | None) -> None:
        """Reject browser embeds from domains outside the widget allowlist.

        Policy (production hardening):
          * no `Origin` header → allowed (non-browser clients; curl/SSE are
            not an embed and cannot be validated anyway);
          * widget has an empty allowlist → allowed (legacy permissive mode);
          * otherwise the `Origin` hostname must be in the allowlist, or be a
            configured dashboard origin (widget-builder previews are always
            permitted). `Origin: null` (sandboxed iframe) is never allowed
            once a allowlist is configured.
        """
        if origin is None:
            return
        widget = await self._widgets.find_by_widget_id(widget_id)
        if widget is None:
            raise WidgetNotFoundError("Widget not found.")
        allowed = list(widget.allowed_domains or [])
        if not allowed:
            return
        # Dashboard origins (widget-builder preview, local dev) are always
        # permitted so the tenant can preview without editing the allowlist.
        allowed.extend(self._dashboard_origins())
        if not origin_allowed(origin, allowed):
            raise WidgetOriginNotAllowedError(
                "This domain is not allowed to embed this widget."
            )

    def _dashboard_origins(self) -> list[str]:
        return [
            host
            for origin in self._settings.cors_origins
            if (host := origin_hostname(str(origin))) is not None
        ]

    async def get_public_config(self, widget_id: str) -> WidgetPublicConfig:
        """Return the public config, serving from Redis when available.

        Fails closed to the database on cache errors: the embed must never be
        blocked (or served stale `enabled` state) by a Redis outage.
        """
        cache_key = f"{CONFIG_CACHE_PREFIX}{widget_id}"
        cached = await self._cache_get(cache_key)
        if cached is not None:
            return cached

        widget = await self._widgets.find_by_widget_id(widget_id)
        if widget is None:
            raise WidgetNotFoundError("Widget not found.")

        tenant = await self._tenants.find_by_id(widget.tenant_id)
        suspended = tenant is None or tenant.status != "active"
        config = WidgetPublicConfig.from_widget(widget)
        if suspended:
            # Suspended tenant: never answer, but do not reveal anything via a
            # 403 to an anonymous visitor (ADR-005 §suspension semantics).
            config.enabled = False
        await self._cache_set(cache_key, config)
        return config

    async def invalidate_public_config(self, widget_id: str) -> None:
        """Drop the cached public config so dashboard edits apply immediately.

        Best-effort: a Redis failure must never block a config save (the stale
        entry simply ages out via its TTL).
        """
        try:
            await self._store.delete(f"{CONFIG_CACHE_PREFIX}{widget_id}")
        except Exception:
            logger.warning("widget config cache invalidation failed for %s", widget_id)

    async def _cache_get(self, key: str) -> WidgetPublicConfig | None:
        try:
            raw = await self._store.get(key)
        except Exception:
            logger.warning("widget config cache read failed; falling back to DB")
            return None
        if raw is None:
            return None
        try:
            return WidgetPublicConfig.model_validate_json(raw)
        except Exception:
            logger.warning("stale/invalid widget config cache entry; ignoring")
            return None

    async def _cache_set(self, key: str, config: WidgetPublicConfig) -> None:
        try:
            await self._store.setex(
                key, self._settings.widget_config_cache_seconds, config.model_dump_json()
            )
        except Exception:
            logger.warning("widget config cache write failed; DB is authoritative")

    # ----------------------------------------------------------- sessions

    async def create_session(
        self, *, widget_id: str, visitor_id: str | None
    ) -> tuple[str, datetime]:
        """Mint a 15-min widget-session token after validating the widget.

        Returns `(token, expires_at)`. Refreshes the per-visitor 24 h sliding
        validity window (a hard ceiling per conversation window, refreshed by
        activity - plan §3.2).
        """
        widget = await self._widgets.find_by_widget_id(widget_id)
        if widget is None:
            raise WidgetNotFoundError("Widget not found.")
        tenant = await self._tenants.find_by_id(widget.tenant_id)
        if not widget.enabled or tenant is None or tenant.status != "active":
            raise WidgetDisabledError("Widget is not available.")

        validity_key = f"{SESSION_VALIDITY_PREFIX}{widget_id}:{visitor_id or 'anon'}"
        try:
            await self._store.setex(
                validity_key,
                self._settings.widget_session_validity_hours * _VALIDITY_SECONDS_MULTIPLIER,
                "1",
            )
        except Exception:
            # Validity window is a soft ceiling; a Redis hiccup must not block
            # legitimate visitors from minting a token.
            logger.warning("widget session validity window refresh failed")

        token, ttl_s = create_widget_session_token(
            widget_id=widget.widget_id,
            tenant_id=widget.tenant_id,
            website_id=widget.website_id,
            visitor_id=visitor_id,
        )
        return token, utcnow() + timedelta(seconds=ttl_s)

    # -------------------------------------------------------------- chat

    async def validate_chat(self, *, widget_id: str, tenant_id: str, website_id: str) -> None:
        """Re-verify the token claims against live state (never trust claims).

        A token minted for widget A cannot query widget B, even if its claims
        were tampered - the widget record is the source of truth.
        """
        widget = await self._widgets.find_by_widget_id(widget_id)
        if widget is None or widget.tenant_id != tenant_id or widget.website_id != website_id:
            raise WidgetNotFoundError("Widget not found.")
        tenant = await self._tenants.find_by_id(tenant_id)
        if not widget.enabled or tenant is None or tenant.status != "active":
            raise WidgetDisabledError("Widget is not available.")
        website = await self._websites.find_by_id_any(website_id)
        if website is None or website.status != WEBSITE_STATUS_READY:
            raise WebsiteNotReadyError("This website is still being indexed.")

    async def check_message_cap(
        self,
        *,
        widget_id: str,
        visitor_id: str | None,
        session_id: str | None,
    ) -> None:
        """Increment the per-conversation counter and enforce the 50-message cap.

        Fails open on store errors: rate limits (separate, fail-closed) bound
        abuse; this counter only prevents a single conversation from running
        forever. `session_id` is the persisted conversation id; when the first
        message has not created one yet, the (widget, visitor) pair keys the
        counter so the cap still applies.
        """
        identity = session_id or f"{widget_id}:{visitor_id or 'anon'}"
        counter_key = f"{MESSAGE_COUNT_PREFIX}{identity}"
        try:
            count = await self._store.incr(counter_key)
            if count == 1:
                await self._store.expire(counter_key, MESSAGE_CAP_TTL_SECONDS)
        except Exception:
            logger.warning("widget message counter failed; cap not enforced")
            return
        if count > self._settings.widget_max_messages_per_session:
            raise MessageLimitReachedError(
                "You have reached the message limit for this conversation."
            )


__all__ = ["WidgetService", "WidgetStore"]
