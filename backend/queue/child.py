"""Child-enqueue backend routing (Phase 17B).

A job that is executing on one queue must enqueue its children onto that same
queue. Before this module existed, the three worker modules each built a private
``_arq_redis()`` from ``settings.redis_url`` and called ``ArqRedis.enqueue_job``
directly, so a parent executed by :class:`MongoWorkerLoop` silently enqueued its
children into Redis:

    Mongo queue parent -> crawl_website -> enqueue_process_website_documents
                                            -> Redis/ARQ child   (split brain)

The fix is deliberately narrow - no service locator, no global registry, no
rewritten job signatures. The executing loop hands the live :class:`WorkerQueue`
it already owns to the job context, and these helpers read it back out:

    WorkerQueue -> parent -> resolve_child_queue(ctx) -> WorkerQueue.enqueue

Resolution rules, in order:

1. ``ctx[CTX_QUEUE_KEY]`` holds a :class:`WorkerQueue` -> use that exact adapter.
   This is the same object the parent is executing on, so children inherit its
   backend, connection pool and configuration.
2. Anything else - an ARQ worker context (ARQ injects only ``job_id``,
   ``job_try``, ``enqueue_time`` and ``score``), the API process, or a direct
   call in a test - resolves to :class:`ArqQueueAdapter`.

Rule 2 is what makes this safe to land: production runs on ARQ today, and an ARQ
context carries no queue handle, so **every production call site resolves
exactly as it did before**. The Mongo path is only reachable when a Mongo loop
put its own adapter in the context.

A malformed or poisoned ``queue`` value cannot hijack routing: the handle is
checked with ``isinstance`` against the runtime-checkable ``WorkerQueue``
protocol, so anything that is not a queue falls back to ARQ rather than being
called.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.queue.arq_adapter import ArqQueueAdapter
from backend.queue.protocol import WorkerQueue

#: Context key under which an executing loop publishes its own adapter.
#: Deliberately not a queue *name* string: a name would have to be parsed and
#: compared, and a forged name could route children onto the wrong backend. The
#: live adapter cannot be forged into existence by a job payload.
CTX_QUEUE_KEY = "queue"

#: Context key carrying the executing job's *queue row* tenant.
#:
#: This is attributability metadata for the CHILD queue row only, never the
#: child's authority: a queued job still derives its real tenant from the
#: authoritative domain row at execution time (``process_document`` loads the
#: document, ``crawl_website`` loads the crawl job). The Mongo adapter requires a
#: non-empty tenant on every row so a queue row is always attributable, while the
#: ARQ adapter ignores the field because ARQ's job arguments are fixed positional
#: values. Inheriting it from the parent row is therefore safe, and it is the
#: same tenant the parent's own row already carries.
CTX_QUEUE_TENANT_KEY = "queue_tenant_id"


def resolve_child_queue(ctx: Mapping[str, Any] | None) -> WorkerQueue:
    """Return the queue a running job must use to enqueue its children.

    Falls back to :class:`ArqQueueAdapter`, preserving today's production
    behaviour for ARQ workers and for the API process.
    """
    candidate = (ctx or {}).get(CTX_QUEUE_KEY)
    if isinstance(candidate, WorkerQueue):
        return candidate
    return ArqQueueAdapter()


def resolve_child_tenant(ctx: Mapping[str, Any] | None, *, fallback: str = "") -> str:
    """Tenant to stamp on a child queue row (attributability, not authority).

    Empty under ARQ, where the adapter ignores it - exactly today's behaviour,
    since today's ARQ child jobs carry no tenant either.
    """
    return str((ctx or {}).get(CTX_QUEUE_TENANT_KEY) or fallback or "")


__all__ = [
    "CTX_QUEUE_KEY",
    "CTX_QUEUE_TENANT_KEY",
    "resolve_child_queue",
    "resolve_child_tenant",
]
