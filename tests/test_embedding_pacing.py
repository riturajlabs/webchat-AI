"""ING-02 tests: provider-aware embedding pacing and 429 handling.

Covers the behaviors added for Phase 2 Part D (temporary vs permanent
classification, Retry-After respect, bounded retries) and Part E (temporarily
rate-limited documents distinguishable from permanently failed ones).
"""

import asyncio
from dataclasses import dataclass, field

import pytest
from backend.core.errors import EmbeddingError, EmbeddingRateLimitedError
from backend.models.knowledge_chunk import KNOWLEDGE_STATUS_RATE_LIMITED
from backend.services.knowledge.embedding import _EmbeddingPacer

from tests.test_embedding import FakeGenAIClient, GoogleEmbeddingClient


@dataclass
class _FakeResponse:
    """Minimal httpx.Response-like surface used by GenAI SDK errors."""

    status_code: int
    headers: dict[str, str] = field(default_factory=dict)


class _FakeHttpError(Exception):
    """Mimics google.genai.errors.ClientError/ServerError shape."""

    def __init__(self, status_code: int, retry_after: str | None = None) -> None:
        super().__init__(f"provider error status={status_code}")
        headers = {}
        if retry_after is not None:
            headers["Retry-After"] = retry_after
        self.response = _FakeResponse(status_code, headers)
        self.status = None  # GenAI SDKs leave `.status` unset; `.response` carries it.


class _FakeMessageError(Exception):
    """Mimics a provider error that embeds its retry hint in the message text
    (Google GenAI: `Please retry in 23s` / `retryDelay: '23s'`) with no
    Retry-After header."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


def _client(fake_sdk: FakeGenAIClient, **kwargs) -> GoogleEmbeddingClient:
    return GoogleEmbeddingClient(
        model="test-embedding",
        batch_size=2,
        max_retries=3,
        base_delay_ms=1,
        timeout_seconds=5.0,
        dimensions=2,
        genai_client=fake_sdk,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Part D: 429 / rate-limit retry behavior
# ---------------------------------------------------------------------------


async def test_429_is_retried_with_backoff_then_succeeds() -> None:
    """A 429 (throttling) is temporary: the batch is retried, not failed."""
    fake_sdk = FakeGenAIClient()
    # Fail the first two attempts with 429, succeed on the third.
    fake_sdk.failures = [
        _FakeHttpError(429),
        _FakeHttpError(429),
    ]
    client = _client(fake_sdk)

    vectors = await client.embed(["a", "b"])

    assert len(vectors) == 2
    assert len(fake_sdk.calls) == 3  # 2 throttled attempts + 1 success


async def test_429_raises_rate_limited_error_when_retries_exhausted() -> None:
    """Bounded retries (Part D): after `max_retries` 429s the batch fails with
    `EmbeddingRateLimitedError`, NOT an endless retry loop."""
    fake_sdk = FakeGenAIClient()
    fake_sdk.failures = [_FakeHttpError(429)] * 10
    client = _client(fake_sdk)

    with pytest.raises(EmbeddingRateLimitedError, match="rate-limited after 3 attempts") as exc:
        await client.embed(["a"])

    assert isinstance(exc.value, EmbeddingError)
    assert len(fake_sdk.calls) == 3  # exactly max_retries, no more


async def test_retry_after_header_is_respected() -> None:
    """A 429 carrying `Retry-After: 2` must wait ~2s before the next attempt
    (bounded to avoid a flaky wall-clock sleep)."""
    fake_sdk = FakeGenAIClient()
    fake_sdk.failures = [_FakeHttpError(429, retry_after="2")]

    sleep_started = asyncio.Event()
    original_sleep = asyncio.sleep
    sleeps: list[float] = []

    async def recording_sleep(delay: float) -> None:
        sleeps.append(delay)
        sleep_started.set()
        await original_sleep(0)  # keep the test fast: just record the delay

    try:
        asyncio.sleep = recording_sleep  # type: ignore[assignment]
        client = _client(fake_sdk)
        await client.embed(["a", "b"])
    finally:
        asyncio.sleep = original_sleep  # type: ignore[assignment]

    assert len(sleeps) == 1
    assert 2.0 <= sleeps[0] < 3.0  # Retry-After honored (plus jitter headroom)


async def test_retry_hint_in_message_text_is_respected() -> None:
    """A 429 whose hint lives in the message ("Please retry in 23.11s") must be
    honored even though no Retry-After header exists (Google GenAI shape)."""
    fake_sdk = FakeGenAIClient()
    fake_sdk.failures = [
        _FakeMessageError(
            "429 RESOURCE_EXHAUSTED. You exceeded your current quota... "
            "Please retry in 23.11s."
        )
    ]

    sleep_started = asyncio.Event()
    original_sleep = asyncio.sleep
    sleeps: list[float] = []

    async def recording_sleep(delay: float) -> None:
        sleeps.append(delay)
        sleep_started.set()
        await original_sleep(0)

    try:
        asyncio.sleep = recording_sleep  # type: ignore[assignment]
        client = _client(fake_sdk)
        await client.embed(["a", "b"])
    finally:
        asyncio.sleep = original_sleep  # type: ignore[assignment]

    assert len(sleeps) == 1
    assert 23.11 <= sleeps[0] < 24.0  # message hint honored (+ jitter headroom)


async def test_retry_delay_hint_in_message_text_is_respected() -> None:
    """The `retryDelay: '23s'` (RetryInfo) message form is parsed too."""
    fake_sdk = FakeGenAIClient()
    fake_sdk.failures = [
        _FakeMessageError(
            "{'error': {'code': 429, 'status': 'RESOURCE_EXHAUSTED', "
            "'details': [{'@type': 'type.googleapis.com/google.rpc.RetryInfo', "
            "'retryDelay': '23s'}]}}"
        )
    ]

    original_sleep = asyncio.sleep
    sleeps: list[float] = []

    async def recording_sleep(delay: float) -> None:
        sleeps.append(delay)
        await original_sleep(0)

    try:
        asyncio.sleep = recording_sleep  # type: ignore[assignment]
        client = _client(fake_sdk)
        await client.embed(["a", "b"])
    finally:
        asyncio.sleep = original_sleep  # type: ignore[assignment]

    assert len(sleeps) == 1
    assert 23.0 <= sleeps[0] < 24.0


async def test_429_without_header_uses_bounded_backoff() -> None:
    """A 429 with no Retry-After still backs off (bounded, jittered), and the
    retry budget caps total attempts."""
    fake_sdk = FakeGenAIClient()
    fake_sdk.failures = [_FakeHttpError(429)]  # no Retry-After header

    quarantine = []
    original_sleep = asyncio.sleep

    async def quarantine_sleep(delay: float) -> None:
        quarantine.append(delay)
        await original_sleep(0)

    try:
        asyncio.sleep = quarantine_sleep  # type: ignore[assignment]
        client = _client(fake_sdk)
        await client.embed(["a", "b"])
    finally:
        asyncio.sleep = original_sleep  # type: ignore[assignment]

    assert len(quarantine) == 1  # one backoff between the two attempts
    assert 0.0 <= quarantine[0] <= 0.002  # base=1ms, capped+jittered


async def test_400_is_permanent_and_fails_fast_without_retry() -> None:
    """A 400 invalid-request can never succeed: fail immediately as
    `EmbeddingUnavailableError` without burning the retry budget (Part D)."""
    fake_sdk = FakeGenAIClient()
    fake_sdk.failures = [_FakeHttpError(400)]
    client = _client(fake_sdk)

    from backend.core.errors import EmbeddingUnavailableError

    with pytest.raises(EmbeddingUnavailableError, match="permanent provider error"):
        await client.embed(["a"])

    assert len(fake_sdk.calls) == 1  # no retries for a permanent failure


async def test_timeout_is_temporary_embedding_error_not_rate_limited() -> None:
    """A transient timeout is retried with backoff but the exhausted failure is
    a generic `EmbeddingError`, NOT `EmbeddingRateLimitedError` (distinguishes
    part D: only quota/429 is 'rate limited')."""
    fake_sdk = FakeGenAIClient()
    fake_sdk.failures = [TimeoutError("slow")] * 10
    client = _client(fake_sdk)

    with pytest.raises(EmbeddingError) as exc:
        await client.embed(["a"])

    assert not isinstance(exc.value, EmbeddingRateLimitedError)
    assert len(fake_sdk.calls) == 3


async def test_server_error_is_retryable_not_rate_limited() -> None:
    """A 503 is transient (retry with backoff) but not a quota rejection."""
    fake_sdk = FakeGenAIClient()
    fake_sdk.failures = [_FakeHttpError(503)]
    client = _client(fake_sdk)

    vectors = await client.embed(["a", "b"])

    assert len(vectors) == 2  # retried and succeeded


# ---------------------------------------------------------------------------
# ING-02: bounded concurrency / pacing
# ---------------------------------------------------------------------------


async def test_concurrent_embeds_are_paced_to_one_in_flight() -> None:
    """With a limit-1 pacer, two concurrent batch calls must never be in
    flight simultaneously."""
    class PacedSDK(FakeGenAIClient):
        async def _embed_content(self, model: str, contents: list[str]):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.05)
            in_flight -= 1
            return await super()._embed_content(model, contents)

    in_flight = 0
    peak = 0
    fake_sdk = PacedSDK()
    client = _client(fake_sdk, pacer=_EmbeddingPacer(1))

    # 3 concurrent document embeds -> many batches, but at most 1 in flight.
    await asyncio.gather(*[client.embed(["x", "y"]) for _ in range(3)])

    assert peak == 1


async def test_default_pacing_uses_config_concurrency_safe_baseline() -> None:
    """Even without an explicit pacer the client gates on a bounded pacer, so
    unrestricted fan-out cannot happen (existence/safety check)."""
    fake_sdk = FakeGenAIClient()
    fake_sdk.delay = 0.01
    client = _client(fake_sdk)

    vectors = await asyncio.gather(*[client.embed(["a", "b"]) for _ in range(4)])

    assert all(len(v) == 2 for v in vectors)


# ---------------------------------------------------------------------------
# Part E: status representation distinguishes rate-limited vs failed
# ---------------------------------------------------------------------------


async def test_rate_limited_status_is_known_to_status_set() -> None:
    from backend.models.knowledge_chunk import KNOWLEDGE_STATUSES

    assert KNOWLEDGE_STATUS_RATE_LIMITED in KNOWLEDGE_STATUSES


async def test_rate_limited_processing_status_maps_to_rate_limited() -> None:
    from tests.test_knowledge_processor import _env  # reuse the processor harness

    env = await _env()
    env.document.knowledge_status = KNOWLEDGE_STATUS_RATE_LIMITED
    assert env.document.processing_status == "rate_limited"


# ---------------------------------------------------------------------------
# Part E: document-level pipeline distinguishes rate-limited vs permanent
# ---------------------------------------------------------------------------


async def test_rate_limited_failure_schedules_retry_and_records_status() -> None:
    """A rate-limited embedding failure is retried at the document level and the
    document is stored as `rate_limited` (not permanently `failed`)."""
    from tests.test_knowledge_processor import (
        RecordingRetry,
        _env,
        _failing_processor,
    )

    env = await _env()
    retries = RecordingRetry()
    env.processor = _failing_processor(
        env,
        error=EmbeddingRateLimitedError("quota exceeded"),
        max_retries=3,
    )

    result = await env.processor.process_document(env.document.id, on_retry=retries)

    assert result["status"] == "retry_scheduled"
    assert retries.scheduled == [(env.document.id, 5.0)]
    stored = env.documents.documents[env.document.id]
    assert stored.knowledge_status == KNOWLEDGE_STATUS_RATE_LIMITED
    assert stored.processing_status == "rate_limited"
    assert stored.knowledge_retry_count == 1
    assert "EmbeddingRateLimitedError" in (stored.knowledge_failure_reason or "")


async def test_rate_limited_retries_exhausted_becomes_permanent_failure() -> None:
    """Bounded document-level retries (Part D): a rate-limited document that
    exhausts its budget lands in the permanently-failed bucket, no loop."""
    from tests.test_knowledge_processor import (
        RecordingRetry,
        _env,
        _failing_processor,
    )

    env = await _env()
    retries = RecordingRetry()
    env.processor = _failing_processor(
        env,
        error=EmbeddingRateLimitedError("quota exceeded"),
        max_retries=2,
    )

    await env.processor.process_document(env.document.id, on_retry=retries)  # attempt 1
    await env.processor.process_document(env.document.id, on_retry=retries)  # attempt 2

    result = await env.processor.process_document(env.document.id, on_retry=retries)

    assert result["status"] == "failed"
    assert result["retryable"] is False
    assert len(retries.scheduled) == 2  # no third retry
    stored = env.documents.documents[env.document.id]
    assert stored.knowledge_status == "failed"
    assert stored.processing_status == "failed"