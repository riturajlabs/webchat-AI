"""Task registry for the ARQ worker.

`ping` is a worker health-check task: ops and the dashboard use it to confirm
the worker is alive and processing jobs. Future task modules (each with their
own file under `backend/workers/jobs/`) will be added as their phases land:

- Phase 2: `send_email` (transactional email, see ADR-001)
- Phase 4: `crawl_website`, `finalize_crawl` (ingestion engine)
- Phase 5: `reindex_website` (knowledge processing)
"""

import time
from typing import Any


async def ping(ctx: dict[str, Any]) -> dict[str, str]:
    """Health-check task: returns worker identity and current time."""
    return {
        "app": str(ctx.get("app_name", "webchat-ai")),
        "ts": str(time.time()),
    }
