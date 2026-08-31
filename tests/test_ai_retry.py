"""Tests for Gemini LLM retry logic (Phase 14.6).

Tests the retry behavior of ``GoogleGeminiClient.stream_generate`` by
mocking ``_stream_generate_once`` — the inner single-attempt method —
so no network or real SDK calls are needed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest
from backend.ai.gemini import GoogleGeminiClient
from backend.core.errors import GenerationError, GenerationUnavailableError


def _make_client(**kwargs) -> GoogleGeminiClient:
    return GoogleGeminiClient(
        model="gemini-2.5-flash",
        max_output_tokens=1024,
        temperature=0.2,
        timeout_seconds=5.0,
        first_token_timeout_seconds=5.0,
        genai_client=object(),  # dummy — _stream_generate_once is mocked
        **kwargs,
    )


async def _collect(gen: AsyncIterator[str]) -> list[str]:
    return [delta async for delta in gen]


def _make_raising_generator(exc: Exception) -> object:
    """Return an async-generator-like object that raises on first iteration.

    Unlike a plain ``async def`` that raises before yielding (which becomes
    a *coroutine*), this returns a proper async iterable.
    """

    async def _gen(**kwargs: object) -> AsyncIterator[str]:  # type: ignore[return]
        if False:
            yield ""  # make it an async generator
        raise exc  # type: ignore[misc]

    return _gen


class TestGeminiRetryTransientFailure:
    """Transient GenerationError retries and recovers on second attempt."""

    async def test_retry_succeeds_on_second_attempt(self) -> None:
        client = _make_client()
        call_count = 0

        async def _fake_once(**kwargs: object) -> AsyncIterator[str]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise GenerationError("transient failure")
            yield "recovered"

        with patch.object(client, "_stream_generate_once", _fake_once):
            deltas = await _collect(client.stream_generate(system="sys", messages=[("user", "q")]))

        assert deltas == ["recovered"]
        assert call_count == 2

    async def test_retry_uses_exponential_backoff(self) -> None:
        client = _make_client()
        sleep_calls: list[float] = []
        call_count = 0

        async def _fake_once(**kwargs: object) -> AsyncIterator[str]:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise GenerationError("transient")
            yield "ok"

        async def _fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        with (
            patch.object(client, "_stream_generate_once", _fake_once),
            patch("backend.ai.gemini.asyncio.sleep", _fake_sleep),
        ):
            deltas = await _collect(client.stream_generate(system="sys", messages=[("user", "q")]))

        assert deltas == ["ok"]
        assert call_count == 3
        assert sleep_calls == [1.0, 2.0]


class TestGeminiRetryExhaustion:
    """All attempts fail — final error propagated, no silent failure."""

    async def test_all_attempts_exhausted(self) -> None:
        client = _make_client()
        call_count = 0

        async def _fake_once(**kwargs: object) -> AsyncIterator[str]:
            nonlocal call_count
            call_count += 1
            if False:
                yield ""  # make it an async generator
            raise GenerationError(f"attempt {call_count} failed")

        with patch.object(client, "_stream_generate_once", _fake_once):
            with pytest.raises(GenerationError, match="attempt 3 failed"):
                async for _ in client.stream_generate(system="sys", messages=[("user", "q")]):
                    pass

        # max_retries=2 → 1 initial + 2 retries = 3 total
        assert call_count == 3


class TestGeminiMidStreamNoRetry:
    """A failure after deltas were already streamed must NOT be retried.

    Retrying a mid-stream GenerationError would append a second, complete
    answer to the already-delivered partial prefix (the caller has already
    consumed and forwarded the deltas), corrupting the response.
    """

    async def test_mid_stream_failure_not_retried(self) -> None:
        client = _make_client()
        call_count = 0

        async def _fake_once(**kwargs: object) -> AsyncIterator[str]:
            nonlocal call_count
            call_count += 1
            yield "partial answer"
            raise GenerationError("stalled mid-stream")

        with patch.object(client, "_stream_generate_once", _fake_once):
            collected: list[str] = []
            with pytest.raises(GenerationError, match="stalled mid-stream"):
                async for delta in client.stream_generate(system="sys", messages=[("user", "q")]):
                    collected.append(delta)

        # Only the partial prefix must be consumed; the failure surfaces as an
        # error instead of triggering a retry that would duplicate output.
        assert collected == ["partial answer"]
        assert call_count == 1

    async def test_mid_stream_failure_not_retried_even_on_first_retry(self) -> None:
        """A pre-delta transient failure retries, but a subsequent mid-stream
        failure after emitted deltas propagates (never a concatenated answer)."""
        client = _make_client()
        call_count = 0

        async def _fake_once(**kwargs: object) -> AsyncIterator[str]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise GenerationError("pre-delta transient")
            yield "final"
            raise GenerationError("stalled after output")

        async def _fake_sleep(delay: float) -> None:
            pass

        with (
            patch.object(client, "_stream_generate_once", _fake_once),
            patch("backend.ai.gemini.asyncio.sleep", _fake_sleep),
        ):
            collected: list[str] = []
            with pytest.raises(GenerationError, match="stalled after output"):
                async for delta in client.stream_generate(system="sys", messages=[("user", "q")]):
                    collected.append(delta)

        assert collected == ["final"]
        assert call_count == 2

    async def test_two_retries_configurable(self) -> None:
        client = _make_client()
        call_count = 0

        async def _fake_once(**kwargs: object) -> AsyncIterator[str]:
            nonlocal call_count
            call_count += 1
            if False:
                yield ""
            raise GenerationError("always fails")

        with (
            patch("backend.ai.gemini.get_settings") as mock_settings,
            patch.object(client, "_stream_generate_once", _fake_once),
        ):
            settings = mock_settings.return_value
            settings.llm_max_retries = 0
            settings.llm_retry_base_delay = 1.0
            with pytest.raises(GenerationError, match="always fails"):
                async for _ in client.stream_generate(system="sys", messages=[("user", "q")]):
                    pass

        # 0 retries → only 1 attempt
        assert call_count == 1


class TestGeminiFirstTokenTimeoutNoRetry:
    """First-token timeout propagates immediately — no retry."""

    async def test_unavailable_error_not_retried(self) -> None:
        client = _make_client()
        call_count = 0

        async def _fake_once(**kwargs: object) -> AsyncIterator[str]:
            nonlocal call_count
            call_count += 1
            if False:
                yield ""
            raise GenerationUnavailableError("first token timeout")

        with patch.object(client, "_stream_generate_once", _fake_once):
            with pytest.raises(GenerationUnavailableError, match="first token timeout"):
                async for _ in client.stream_generate(system="sys", messages=[("user", "q")]):
                    pass

        # GenerationUnavailableError should NOT be retried
        assert call_count == 1
