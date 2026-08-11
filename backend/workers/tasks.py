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
TASKS = [
    ping,
    timed_job(send_email),
    timed_job(crawl_website),
    timed_job(process_document),
    timed_job(process_website_documents),
]
