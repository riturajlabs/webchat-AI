"""Mock domain jobs and providers for the safety scenarios (Phase 15).

These simulate the crawl/document/email side effects WITHOUT touching real
websites, real embeddings, or a real mail provider. They exist to answer the
two things the investigation must keep separate:

- queue correctness  (ownership, leases, fencing, at-least-once delivery)
- side-effect correctness (idempotent webhooks/web pages/email delivery)

``job deduplication != side-effect idempotency``: the queue deduplicates
*submissions* (dedup_key); it can never make an at-least-once *side effect*
exactly-once. Only the provider/business layer can do that.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.prototypes.mongo_queue.ids import utcnow
from backend.prototypes.mongo_queue.worker import JobContext


@dataclass(frozen=True)
class SendResult:
    message_id: str
    duplicated: bool


@dataclass
class SentEmail:
    to: str
    subject: str
    message_id: str
    idempotency_key: str | None
    created_at: datetime


class MockMailProvider:
    """In-memory SMTP-like provider with optional idempotency-key support.

    Without an idempotency key every ``send`` is a NEW delivery. With one,
    the first delivery wins and repeats return the original ``message_id``
    with ``duplicated=True`` - exactly the "provider idempotency" the real
    Resend/SES API offers but the production worker does not currently use
    for send_email scope (report §14).
    """

    def __init__(self, honors_idempotency: bool = True) -> None:
        self._sent: dict[str, SentEmail] = {}
        self._by_key: dict[str, str] = {}
        self.honors_idempotency = honors_idempotency

    @property
    def sent_emails(self) -> tuple[SentEmail, ...]:
        return tuple(self._sent.values())

    @property
    def sent_count(self) -> int:
        return len(self._sent)

    @property
    def email_received(self) -> bool:
        return self.sent_count > 0

    async def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        idempotency_key: str | None = None,
    ) -> SendResult:
        await asyncio.sleep(0)  # simulate an awaited network round-trip
        if (
            self.honors_idempotency
            and idempotency_key is not None
            and idempotency_key in self._by_key
        ):
            return SendResult(self._by_key[idempotency_key], duplicated=True)
        message_id = f"msg-{len(self._sent) + 1:06d}"
        record = SentEmail(
            to=to,
            subject=subject,
            message_id=message_id,
            idempotency_key=idempotency_key,
            created_at=utcnow(),
        )
        self._sent[message_id] = record
        if idempotency_key is not None:
            self._by_key[idempotency_key] = message_id
        return SendResult(message_id, duplicated=False)


async def send_email_handler(
    payload: dict[str, Any],
    ctx: JobContext,
    *,
    provider: MockMailProvider,
    require_idempotency: bool = False,
) -> dict[str, Any]:
    """Mock equivalent of the production ``send_email`` worker job."""
    idempotency_key = payload.get("idempotency_key")
    if require_idempotency and idempotency_key is None:
        raise RuntimeError("idempotency_key required but absent")
    result = await provider.send(
        to=str(payload["to"]),
        subject=str(payload["subject"]),
        body=str(payload["body"]),
        idempotency_key=idempotency_key,
    )
    return {
        "message_id": result.message_id,
        "duplicated": result.duplicated,
        "tenant_id": ctx.tenant_id,
    }


# ---------------------------------------------------------------------------
# Document processing: checksum idempotency (mirrors the production
# `processor.py` checksum-skip path in miniature).
# ---------------------------------------------------------------------------


class DocumentChecksumStore:
    """Tracks per-document checksum -> embedded; appends side-effect events."""

    def __init__(self) -> None:
        self._checksums: dict[str, str] = {}
        self.events: list[str] = []

    def set_checksum(self, document_id: str, checksum: str) -> None:
        self._checksums[document_id] = checksum

    def checksum(self, document_id: str) -> str | None:
        return self._checksums.get(document_id)

    def already_embedded(self, document_id: str) -> bool:
        return self._events_for(document_id) > 0

    def _events_for(self, document_id: str) -> int:
        return sum(1 for e in self.events if e.startswith(f"embedded:{document_id}"))


async def process_document_handler(
    payload: dict[str, Any],
    ctx: JobContext,
    *,
    store: DocumentChecksumStore,
) -> dict[str, Any]:
    """Mock of the embedding job: checksum-skip makes re-runs idempotent."""
    document_id = str(payload["document_id"])
    checksum = str(payload["checksum"])
    stored = store.checksum(document_id)
    if stored is not None and stored == checksum and store._events_for(document_id) > 0:
        return {"document_id": document_id, "skipped": True, "tenant_id": ctx.tenant_id}
    await asyncio.sleep(0)
    store.events.append(f"embedded:{document_id}")
    store.set_checksum(document_id, checksum)
    return {"document_id": document_id, "embedded": True, "tenant_id": ctx.tenant_id}


# ---------------------------------------------------------------------------
# Crawl: single-terminator fence (miniature of `finish_if_active`).
# ---------------------------------------------------------------------------


class CrawlFence:
    """Atomic single-terminator: only one execution may WIN the terminal state.

    Mirrors ``MongoCrawlJobRepository.finish_if_active``: matched only while
    the job is still active; exactly one caller gets ``True`` and owns the
    terminal side effects (audit, usage, website write, knowledge enqueue).
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._state: dict[str, bool] = {}
        self.events: list[str] = []

    async def mark_active(self, crawl_job_id: str) -> None:
        self._state[crawl_job_id] = True

    async def finish_if_active(self, crawl_job_id: str) -> bool:
        async with self._lock:
            if self._state.get(crawl_job_id, False):
                self._state[crawl_job_id] = False
                return True
            return False

    def is_active(self, crawl_job_id: str) -> bool:
        return self._state.get(crawl_job_id, False)

    async def crawl_side_effect(self, crawl_job_id: str, page: str) -> None:
        self.events.append(f"page:{crawl_job_id}:{page}")


async def crawl_handler(
    payload: dict[str, Any],
    ctx: JobContext,
    *,
    fence: CrawlFence,
) -> dict[str, Any]:
    """Mock of the crawl job: partial side effects + fenced terminal step."""
    crawl_job_id = str(payload["crawl_job_id"])
    await fence.crawl_side_effect(crawl_job_id, "home")
    await asyncio.sleep(0)
    winner = await fence.finish_if_active(crawl_job_id)
    if winner:
        fence.events.append(f"completed:{crawl_job_id}")
        return {"crawl_job_id": crawl_job_id, "winner": True, "tenant_id": ctx.tenant_id}
    return {"crawl_job_id": crawl_job_id, "winner": False, "tenant_id": ctx.tenant_id}


# ---------------------------------------------------------------------------
# Generic flaky handler for retry/max-tries tests.
# ---------------------------------------------------------------------------


async def flaky_handler(payload: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
    """Succeeds on ``succeed_on_try`` attempt, raises otherwise."""
    if ctx.job_try < int(payload["succeed_on_try"]):
        raise RuntimeError(f"flaky attempt {ctx.job_try}")
    return {"ok": ctx.job_try}
