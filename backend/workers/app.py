"""ARQ worker configuration.

Run with:  python -m backend.workers   (ADR-002 entrypoint)
Direct:    arq backend.workers.app.WorkerSettings

Job functions are registered in `backend.workers.tasks` and land in Phase 2
(email), Phase 4/5 (crawler) and Phase 5 (knowledge processing). See
docs/07-Architecture-Decisions.md ADR-002.
"""

from typing import Any

from arq.connections import RedisSettings

from backend.core.config import get_settings
from backend.services.ingestion.browser import close_browser
from backend.services.knowledge.embedding import GoogleEmbeddingClient
from backend.workers import tasks

_settings = get_settings()


async def startup(ctx: dict[str, Any]) -> None:
    """Runs once when the worker starts."""
    ctx["app_name"] = _settings.app_name
    # Shared embedding client for all knowledge jobs in this process. Building
    # it never touches the network (the Google SDK client is created lazily).
    ctx["embedding_client"] = GoogleEmbeddingClient()


async def shutdown(ctx: dict[str, Any]) -> None:
    """Runs once when the worker stops."""
    _ = ctx
    await close_browser()


class WorkerSettings:
    """ARQ worker settings consumed via `arq backend.workers.app.WorkerSettings`."""

    functions = tasks.TASKS
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
    on_startup = startup
    on_shutdown = shutdown
    max_tries = 3
    job_timeout = 600
    keep_result = 3600
    max_jobs = 10
