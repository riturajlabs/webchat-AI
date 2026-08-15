"""Tests for the ARQ knowledge worker tasks (Phase 5, ADR-002).

`_run_process_document` and `_run_process_website` are exercised directly with
fake-backed `KnowledgeProcessor` instances (no Redis, no Google SDK).
"""

from dataclasses import dataclass, field

from backend.services.knowledge.processor import KnowledgeProcessor
from backend.workers.jobs.knowledge import _run_process_document, _run_process_website


@dataclass
class FakeProcessor:
    """Stands in for `KnowledgeProcessor`; records what the task would run."""

    document_ids: list[str] = field(default_factory=list)
    website_ids: list[str] = field(default_factory=list)
    enqueues: list[list[str]] = field(default_factory=list)
    on_retries: list[object] = field(default_factory=list)
    processor: KnowledgeProcessor | None = None

    async def process_document(self, document_id: str, on_retry=None) -> dict:
        self.document_ids.append(document_id)
        if on_retry is not None:
            self.on_retries.append(on_retry)
        return {"status": "processed", "chunks": 3}

    async def process_website_documents(self, website_id: str, *, enqueue) -> dict:
        self.website_ids.append(website_id)
        if enqueue is not None:
            self.enqueues.append([enqueue])
        return {"status": "queued", "documents": 2}


async def _retry_callback(document_id: str, delay: float) -> None:  # pragma: no cover
    pass


async def test_run_process_document_calls_processor() -> None:
    fake = FakeProcessor()
    result = await _run_process_document({}, "doc-1", fake)  # type: ignore[arg-type]

    assert result == {"status": "processed", "chunks": 3}
    assert fake.document_ids == ["doc-1"]


async def test_run_process_document_forwards_retry_callback() -> None:
    """The deferred-retry callback bound by the worker task must reach the
    processor so a temporary embedding failure can schedule a backoff re-run."""
    fake = FakeProcessor()
    await _run_process_document({}, "doc-1", fake, on_retry=_retry_callback)  # type: ignore[arg-type]

    assert fake.on_retries == [_retry_callback]


async def test_run_process_website_fans_out_via_enqueue() -> None:
    fake = FakeProcessor()
    result = await _run_process_website({}, "site-1", fake)  # type: ignore[arg-type]

    assert result == {"status": "queued", "documents": 2}
    assert fake.website_ids == ["site-1"]
    # The worker injects `enqueue_process_document`; a real call never happens
    # because the fake's `process_website_documents` records rather than runs it.
    assert len(fake.enqueues) == 1
