"""Embedding generation for the knowledge base (Phase 5, ADR-008).

`GoogleEmbeddingClient` calls `gemini-embedding-001` through the Google GenAI
async SDK (`client.aio.models.embed_content`). Texts are sent in configurable
batches, each batch retried with exponential backoff and jitter, and every
successful batch reports usage through an optional hook. Application code
depends on the `EmbeddingClient` Protocol only - the worker receives a client
via its container (`ctx["embedding_client"]`), keeping the Google SDK out of
the processor core. The API key comes from settings (env) and is never logged
or returned (00-AI-Development-Rules §12, §20).
"""

import asyncio
import hashlib
import logging
import random
import re
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from backend.core.config import get_settings
from backend.core.embedding_identity import EmbeddingIdentity, ensure_embedding_compatibility
from backend.core.errors import (
    EmbeddingError,
    EmbeddingRateLimitedError,
    EmbeddingUnavailableError,
)
from backend.services.knowledge.chunker import count_tokens

logger = logging.getLogger("webchat_ai")

# Audit R-09: in-process memo of successfully embedded texts (text hash ->
# vector). Purely in-memory on the client instance - no storage architecture
# change - bounded so long-running workers cannot grow it without limit.
_MEMO_MAX_ENTRIES = 1024

# HTTP / GenAI status codes used to classify embedding failures as retryable
# (temporary provider throttling/availability) vs permanent (client error).
_HTTP_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
_HTTP_PERMANENT_STATUSES = frozenset({400, 401, 403, 404})

# Providers encode a retry hint in the error message when no Retry-After header
# is present (Google GenAI: `Please retry in 23.11s` / `RetryInfo.retryDelay`).
# ING-02: honor those hints so retries wait for the provider instead of
# hammering an already-throttled quota window (which tripped the shared
# provider circuit breakers during the live E2E).
_RETRY_IN_MSG = re.compile(r"please\s+retry\s+in\s+(\d+(?:[.,]\d+)?)\s*s", re.IGNORECASE)
_RETRY_DELAY_MSG = re.compile(
    r"retry\s*delay\s*['\"]?\s*[:=]\s*['\"]?(\d+(?:[.,]\d+)?)\s*s['\"]?", re.IGNORECASE
)
# Upper bound on a message-hint wait: any provider asking for more is capped so
# a single document retry cannot stall the whole ingestion pipeline for minutes.
_MAX_RETRY_HINT_SECONDS = 300.0


class _EmbeddingPacer:
    """Process-wide concurrency ceiling on embedding batch requests (ING-02).

    ARQ may run several `process_document` jobs concurrently (`max_jobs=10`);
    without a shared gate they can all open embedding requests at once and
    exhaust the provider's per-minute embed quota (the observed 429 storm).
    This pacer is module-level and lazily built, so every `GoogleEmbeddingClient`
    in a worker process (production and test) contends on the same bounded
    gate. It only caps how many batches are *in flight*; it does not serialize
    the whole ingestion pipeline (each document still runs independently and
    batches inside a document still pipeline).
    """

    def __init__(self, limit: int) -> None:
        self._limit = max(1, limit)
        # Async primitives bind to the running event loop at creation. Tests run
        # each case on a fresh loop, so (re)build the semaphore lazily, once per
        # loop, keeping concurrency bounded within whatever loop is active.
        self._sem: asyncio.Semaphore | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def __aenter__(self) -> "_EmbeddingPacer":
        loop = asyncio.get_running_loop()
        if self._sem is None or self._loop is not loop:
            self._sem = asyncio.Semaphore(self._limit)
            self._loop = loop
        await self._sem.acquire()
        return self

    async def __aexit__(self, *exc: object) -> None:
        assert self._sem is not None
        self._sem.release()


_pacer: _EmbeddingPacer | None = None


def _get_pacer() -> _EmbeddingPacer:
    global _pacer
    if _pacer is None:
        _pacer = _EmbeddingPacer(get_settings().embedding_max_concurrent_batches)
    return _pacer


class _RateLimitReason(Enum):
    NONE = "none"
    RETRY_AFTER = "retry_after"
    BACKOFF = "backoff"
    PERMANENT = "permanent"


def _extract_status(exc: Exception) -> int | None:
    """Best-effort HTTP/Gemini status code from an embedding exception.

    `google.genai.errors.ClientError`/`ServerError` carry an `httpx.Response`
    (or `requests.Response`); the GenAI SDK may also expose a `.status`. A plain
    `httpx.HTTPStatusError` is handled too. Returns None when no status is
    available (e.g. a timeout/transport error).
    """
    status = getattr(exc, "status", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    if response is not None:
        code = getattr(response, "status_code", None)
        if isinstance(code, int):
            return code
        status_code = getattr(response, "status", None)
        if isinstance(status_code, int):
            return status_code
    return None


def _extract_retry_after(exc: Exception) -> float | None:
    """Seconds until the provider will accept requests again (Retry-After).

    Prefers the HTTP `Retry-After` header from any exception carrying a
    response; falls back to a numeric `Retry-After`/`X-RateLimit-Reset`-style
    hint on the exception itself; finally scans the message text for a provider
    retry hint ("Please retry in 23s", `retryDelay: '23s'` — Google GenAI does
    not emit a Retry-After header). Returns None when the provider gave no
    retry-after information.
    """
    response = getattr(exc, "response", None)
    if response is not None:
        headers = getattr(response, "headers", None)
        if headers is not None:
            try:
                value = headers.get("Retry-After") or headers.get("retry-after")
                if value is not None:
                    return max(0.0, float(value))
            except (TypeError, ValueError):
                pass
    for attr in ("retry_after", "Retry-After", "X-RateLimit-Reset"):
        value = getattr(exc, attr, None)
        if value is not None:
            try:
                return max(0.0, float(value))
            except (TypeError, ValueError):
                pass
    message = f"{type(exc).__name__}: {exc}"
    for pattern in (_RETRY_IN_MSG, _RETRY_DELAY_MSG):
        match = pattern.search(message)
        if match is None:
            continue
        try:
            value = max(0.0, float(match.group(1).replace(",", ".")))
        except ValueError:
            continue
        return min(value, _MAX_RETRY_HINT_SECONDS)
    return None


def _rate_limit_reason(exc: Exception) -> _RateLimitReason:
    """Classify an embedding exception into a retry/backoff decision."""
    status = _extract_status(exc)
    if status is not None:
        if status in _HTTP_PERMANENT_STATUSES:
            # 400/401/403/404: invalid request / auth / not-found. Retrying
            # cannot fix it — fail fast (normal failure handling, PART D).
            return _RateLimitReason.PERMANENT
        if status in _HTTP_RETRYABLE_STATUSES:
            return (
                _RateLimitReason.RETRY_AFTER
                if _extract_retry_after(exc) is not None
                else _RateLimitReason.BACKOFF
            )
    # Rate-limit text hints (e.g. "quota" / "RESOURCE_EXHAUSTED" / "429" in a
    # message) with no parseable numeric status still retry with backoff.
    message = f"{type(exc).__name__}: {exc}".lower()
    if any(hint in message for hint in ("429", "resource_exhausted", "rate limit", "quota")):
        return (
            _RateLimitReason.RETRY_AFTER
            if _extract_retry_after(exc) is not None
            else _RateLimitReason.BACKOFF
        )
    # Timeouts / transport / 5xx without a header: transient, retry with backoff.
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return _RateLimitReason.BACKOFF
    return _RateLimitReason.BACKOFF


def _is_rate_limited(exc: Exception) -> bool:
    """True when the failure is a provider quota/rate-limit rejection (429 or a
    quota text hint with no numeric status). Used to lift the failure into
    `EmbeddingRateLimitedError` so ingestion can record the document as
    temporarily rate-limited (Part E/ING-02).
    """
    status = _extract_status(exc)
    if status == 429:
        return True
    if status in _HTTP_RETRYABLE_STATUSES or status in _HTTP_PERMANENT_STATUSES:
        # Any other concrete HTTP status (5xx timeout-ish, 4xx bad request) is
        # NOT a quota rejection: retry with backoff or fail as permanent.
        return False
    message = f"{type(exc).__name__}: {exc}".lower()
    return any(hint in message for hint in ("429", "resource_exhausted", "rate limit", "quota"))


def _cap_backoff(base_delay_ms: int, attempt: int) -> int:
    """Exponential cap with full jitter: base * 2^attempt * [0,1)."""
    cap = base_delay_ms * (2**attempt)
    return int(random.uniform(0, cap)) if cap > 0 else 0


def ensure_vector_dimensions(
    provider_name: str,
    vectors: list[list[float]],
    expected_dimensions: int,
) -> None:
    """Reject vectors whose length differs from the configured index dimension.

    MongoDB `$vectorSearch` indexes a fixed vector length; silently inserting
    vectors of another length (e.g. after an embedding-provider fallback)
    corrupts retrieval. Raises a clear `EmbeddingError` before any vector is
    committed (ADR-009, docs/EMBEDDING_PROVIDERS.md).
    """
    if not vectors:
        return
    mismatches = {len(vector) for vector in vectors if len(vector) != expected_dimensions}
    if mismatches:
        raise EmbeddingError(
            f"Embedding dimension mismatch: {provider_name} returned dimensions "
            f"{sorted(mismatches)}, configured index expects {expected_dimensions}."
        )


@dataclass(frozen=True)
class EmbeddingUsage:
    """Aggregate embedding-API usage so far (hooks, ADR-008 token capture)."""

    calls: int = 0
    characters: int = 0
    estimated_tokens: int = 0
    failures: int = 0


class EmbeddingClient(Protocol):
    """Async embedding interface. Never raises raw SDK errors."""

    @property
    def usage(self) -> EmbeddingUsage:
        """Aggregate usage so far (Phase 9 fallback reads the serving provider)."""
        ...

    @property
    def embedding_identity(self) -> EmbeddingIdentity:
        """Identity of the provider/model used for the most recent embedding."""
        ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def health(self) -> bool:
        """Cheap readiness probe: configured and believed usable. Never raises
        and never makes a paid embedding request (a live probe during a fan-out
        would burn the very quota a 429 is throttling)."""
        ...


class GoogleEmbeddingClient:
    """`gemini-embedding-001` via the Google GenAI async SDK."""

    name = "gemini"

    def __init__(
        self,
        *,
        model: str | None = None,
        batch_size: int | None = None,
        max_retries: int | None = None,
        base_delay_ms: int | None = None,
        timeout_seconds: float | None = None,
        dimensions: int | None = None,
        on_usage: Callable[[EmbeddingUsage], None] | None = None,
        genai_client: Any | None = None,
        pacer: "_EmbeddingPacer | None" = None,
    ) -> None:
        settings = get_settings()
        self._model = model or settings.embedding_model
        self._batch_size = batch_size or settings.embedding_batch_size
        self._max_retries = (
            max_retries if max_retries is not None else settings.embedding_max_retries
        )
        self._base_delay_ms = base_delay_ms or settings.embedding_retry_base_delay_ms
        self._pacer_override = pacer
        self._timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.embedding_request_timeout_seconds
        )
        self._dimensions = (
            dimensions if dimensions is not None else settings.gemini_embedding_dimensions
        )
        self._on_usage = on_usage
        self._genai_client = genai_client
        self._usage = EmbeddingUsage()
        # Audit R-09: texts embedded successfully by THIS client instance.
        # When a later batch of the same document fails and the processor
        # schedules a document-level retry, already-embedded batches are
        # served from this memo instead of being re-embedded (and re-billed).
        self._memo: OrderedDict[str, list[float]] = OrderedDict()

    def _memo_key(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _memo_put(self, text: str, vector: list[float]) -> None:
        key = self._memo_key(text)
        self._memo[key] = vector
        self._memo.move_to_end(key)
        while len(self._memo) > _MEMO_MAX_ENTRIES:
            self._memo.popitem(last=False)

    @property
    def usage(self) -> EmbeddingUsage:
        return self._usage

    @property
    def dimensions(self) -> int:
        """Embedding vector length (Phase 9 dimension-compatibility check)."""
        return self._dimensions

    @property
    def embedding_identity(self) -> EmbeddingIdentity:
        return EmbeddingIdentity(
            provider=self.name,
            model=self._model,
            dimensions=self._dimensions,
            version=getattr(get_settings(), "embedding_version", "1"),
        )

    async def health(self) -> bool:
        """Cheap readiness probe: the required API key is configured. We avoid
        a live embed (it would consume the free-tier quota a 429 is throttling);
        the key-presence check matches how `build_embedding_chain` gates the
        provider at selection time."""
        return bool(get_settings().gemini_api_key)

    def _client(self) -> Any:
        """Lazily build the SDK client (never touches network until first call)."""
        if self._genai_client is None:
            api_key = get_settings().gemini_api_key
            if not api_key:
                raise EmbeddingUnavailableError(
                    "GEMINI_API_KEY is not configured; cannot generate embeddings."
                )
            from google.genai import Client

            self._genai_client = Client(api_key=api_key)
        return self._genai_client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed `texts` in batches, retrying each batch with backoff.

        Returns one vector per input text, in order. Raises `EmbeddingError`
        when a batch exhausts its retries or the client is misconfigured.

        Audit R-09: texts this client instance already embedded successfully
        are served from the in-memory memo, so a document-level retry after a
        mid-document batch failure only re-embeds the batches that never
        succeeded. The retry policy itself (per-batch backoff + document-level
        deferred retries) is unchanged.
        """
        if not texts:
            return []
        slots: list[list[float] | None] = [None] * len(texts)
        pending: list[str] = []
        queued: set[str] = set()
        for i, text in enumerate(texts):
            key = self._memo_key(text)
            cached = self._memo.get(key)
            if cached is not None:
                self._memo.move_to_end(key)
                slots[i] = cached
            elif text not in queued:
                # Duplicate uncached texts are embedded once and shared.
                pending.append(text)
                queued.add(text)
        for start in range(0, len(pending), self._batch_size):
            batch = pending[start : start + self._batch_size]
            embedded = await self._embed_batch(batch)
            for text, vector in zip(batch, embedded, strict=True):
                self._memo_put(text, vector)
        final: list[list[float]] = []
        for i, text in enumerate(texts):
            slot = slots[i]
            vector = slot if slot is not None else self._memo[self._memo_key(text)]
            if vector is None:  # pragma: no cover - every slot is filled above
                raise EmbeddingError("Embedding assembly failed for a batch text.")
            final.append(vector)
        return final

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        last_error: Exception | None = None
        batch_characters = sum(len(text) for text in batch)
        batch_tokens = sum(count_tokens(text) for text in batch)
        # ING-02: bound concurrent embedding across the whole worker process
        # before opening the request, so a fan-out cannot saturate the provider.
        async with self._pacer():
            for attempt in range(self._max_retries):
                try:
                    # Truncate Gemini's output to EMBEDDING_DIMENSIONS so every
                    # provider in the fallback chain emits the same vector length
                    # (the MongoDB index dimension). gemini-embedding-001 supports
                    # 1..3072 dimensions; the default 3072 is sent only implicitly
                    # (omitted) so existing 3072-index deployments see no change.
                    config: dict[str, int] | None = None
                    if self._dimensions and self._dimensions != 3072:
                        config = {"output_dimensionality": self._dimensions}
                    vectors = await asyncio.wait_for(
                        self._client().aio.models.embed_content(
                            model=self._model, contents=batch, config=config
                        ),
                        timeout=self._timeout_seconds,
                    )
                    parsed = self._parse_response(vectors, len(batch))
                    self._record_usage(1, batch_characters, batch_tokens)
                    return parsed
                except EmbeddingUnavailableError:
                    # Configuration error (e.g. missing API key): fail fast, no
                    # retries or backoff - retrying cannot fix a bad config.
                    raise
                except Exception as exc:  # noqa: BLE001 - normalized below
                    last_error = exc
                    reason = _rate_limit_reason(exc)
                    if reason == _RateLimitReason.PERMANENT:
                        # 400/404 etc: the request can never succeed; give up
                        # immediately (no backoff budget burned on a bad request).
                        raise EmbeddingUnavailableError(
                            f"Embedding request rejected (permanent provider error): {exc}"
                        ) from exc
                    if attempt < self._max_retries - 1:
                        delay = self._backoff_delay(exc, attempt)
                        pace = (
                            " (Respect Retry-After)"
                            if reason == _RateLimitReason.RETRY_AFTER
                            else ""
                        )
                        logger.warning(
                            "embedding batch failed (attempt %s/%s): %s; retrying in %.2fs%s",
                            attempt + 1,
                            self._max_retries,
                            exc,
                            delay,
                            pace,
                        )
                        await asyncio.sleep(delay)
        self._record_usage(0, 0, 0, failures=1)
        if last_error is not None and _is_rate_limited(last_error):
            raise EmbeddingRateLimitedError(
                f"Embedding request rate-limited after {self._max_retries} attempts: {last_error}"
            ) from last_error
        raise EmbeddingError(
            f"Embedding request failed after {self._max_retries} attempts: {last_error}"
        )

    def _parse_response(self, response: Any, expected: int) -> list[list[float]]:
        embeddings = getattr(response, "embeddings", None)
        if not embeddings:
            raise EmbeddingError("Embedding response contained no embeddings.")
        values: list[list[float]] = []
        for item in embeddings:
            vector = getattr(item, "values", None)
            if vector is None:
                raise EmbeddingError("Embedding response item had no values.")
            values.append([float(v) for v in vector])
        if len(values) != expected:
            raise EmbeddingError(
                f"Embedding response returned {len(values)} vectors for {expected} texts."
            )
        ensure_vector_dimensions("gemini", values, self._dimensions)
        return values

    def _record_usage(
        self,
        calls: int,
        characters: int,
        estimated_tokens: int,
        *,
        failures: int = 0,
    ) -> None:
        self._usage = EmbeddingUsage(
            calls=self._usage.calls + calls,
            characters=self._usage.characters + characters,
            estimated_tokens=self._usage.estimated_tokens + estimated_tokens,
            failures=self._usage.failures + failures,
        )
        if self._on_usage is not None:
            self._on_usage(self._usage)

    def _backoff_delay(self, exc: Exception, attempt: int) -> float:
        """Delay before the next retry in seconds.

        If the provider returned Retry-After (header, attribute, or an explicit
        retry hint in the message text), respect it (plus a small jittered
        headroom) instead of guessing. Otherwise use the existing exponential
        backoff with full jitter (`base * 2^attempt * [0,1)`), so a 429 with no
        hint is still paced and a transient timeout uses the same schedule.
        """
        retry_after = _extract_retry_after(exc)
        if retry_after is not None:
            return retry_after + random.uniform(0, self._base_delay_ms / 1000.0)
        return _cap_backoff(self._base_delay_ms, attempt) / 1000.0

    def _pacer(self) -> _EmbeddingPacer:
        """Process-wide bounded concurrency gate; tests may inject an override."""
        return self._pacer_override or _get_pacer()


__all__ = [
    "EmbeddingIdentity",
    "EmbeddingClient",
    "EmbeddingUsage",
    "GoogleEmbeddingClient",
    "ensure_embedding_compatibility",
    "ensure_vector_dimensions",
]
