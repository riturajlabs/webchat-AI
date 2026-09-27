"""Task registry for the ARQ worker.

`ping` is a worker health-check task: ops and the dashboard use it to confirm
the worker is alive and processing jobs. Future task modules (each with their
own file under `backend/workers/jobs/`) will be added as their phases land:

- Phase 2: `send_email` (transactional email, see ADR-001)
- Phase 4: `crawl_website`, `finalize_crawl` (ingestion engine)
- Phase 5: `process_document`, `process_website_documents` (knowledge processing)
"""

import time
from typing import Any

from arq.worker import func

from backend.core.config import get_settings
from backend.workers.jobs.crawl import crawl_website
from backend.workers.jobs.email import send_email
from backend.workers.jobs.knowledge import process_document, process_website_documents
from backend.workers.timing import timed_job


async def ping(ctx: dict[str, Any]) -> dict[str, str]:
    """Health-check task: returns worker identity and current time."""
    return {
        "app": str(ctx.get("app_name", "webchat-ai")),
        "ts": str(time.time()),
    }


# Tasks registered in the ARQ worker (ADR-002 task registry). The timed_* wrap
# measures queue wait + execution duration (Phase 12.1 instrumentation; only
# logs when PERF_TIMING_LOG_ENABLED=true).
#
# Each wrapped coroutine is bound to a module-level name so the task registry is
# addressable by name, not only by position in `TASKS`. `backend.queue.registry`
# resolves the queue backend's logical function names to *these exact objects*,
# so a Mongo-backend worker keeps the same `timed_job` instrumentation and
# dispatches to the same coroutine the ARQ worker does. The names ARQ keys
# dispatch on are unchanged: `timed_job`'s `functools.wraps` (timing.py)
# preserves the coroutine `__qualname__`.
REGISTERED_PING = ping
REGISTERED_SEND_EMAIL = timed_job(send_email)
REGISTERED_PROCESS_DOCUMENT = timed_job(process_document)
REGISTERED_PROCESS_WEBSITE_DOCUMENTS = timed_job(process_website_documents)

# FIND-08: `crawl_website` is the one task whose honest duration can exceed
# ARQ's global `job_timeout` (600 s; a 50-page crawl at the per-page bounds can
# take an hour or more), so it is registered as an ARQ `Function` with its own
# finite timeout (`crawl_job_timeout_seconds`). Every other task keeps the
# global 600 s as stuck-job protection.
CRAWL_FUNCTION = func(
    timed_job(crawl_website),
    timeout=get_settings().crawl_job_timeout_seconds,
)

#: The wrapped coroutine ARQ actually runs for `crawl_website`, exported so the
#: queue registry resolves the same callable (the timeout lives on the ARQ
#: `Function`, which the Mongo backend reads via `arq_job_timeouts`).
REGISTERED_CRAWL_WEBSITE = CRAWL_FUNCTION.coroutine

TASKS = [
    REGISTERED_PING,
    REGISTERED_SEND_EMAIL,
    CRAWL_FUNCTION,
    REGISTERED_PROCESS_DOCUMENT,
    REGISTERED_PROCESS_WEBSITE_DOCUMENTS,
]
