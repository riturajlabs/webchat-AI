"""AI provider router / fallback chain (Phase 9, ADR-009).

`FallbackGenerationClient` and `FallbackEmbeddingClient` implement the
existing `GenerationClient` (backend/ai/gemini.py) and `EmbeddingClient`
(backend/services/knowledge/embedding.py) Protocols, so the RAG service and
the knowledge worker keep depending on the same interfaces they already use -
the concrete providers just resolve to a fallback chain now.

Fallback semantics
------------------
* Generation is *pre-stream only*: providers are tried in order, but once a
  provider starts emitting deltas the stream is committed to it. A mid-stream
  failure is re-raised (the caller surfaces an SSE `error`) rather than
  restarting the answer, so the client never sees a truncated answer followed
  by a fresh, complete one.
* Embedding is atomic (no streaming), so a failed provider is fully retried on
  the next one.
* A provider that lacks its API key is skipped at registry build time; an
  *empty* chain raises here at call time, preserving the no-key behaviour the
  direct Gemini client already had (error surfaces as an SSE `error` event).
* Phase 4 resilience: every provider also sits behind a per-provider circuit
  breaker (`backend.ai.circuit_breaker`). After repeated consecutive
  failures the provider is skipped without a network call until its cooldown
  elapses; one probe request is then allowed (success closes, failure
  reopens). Skips are logged (`ai_circuit_skipped`) and reported in
  `ProviderLatencyMetrics.skipped_providers` - they are never counted as
  failures by adaptive health tracking.
* `active_provider` reports which provider served the last request
  (observability, ADR-009 §fallback).
"""

import logging
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from backend.ai.circuit_breaker import (
    ROLE_EMBEDDING,
    ROLE_GENERATION,
    allow_provider,
    record_provider_failure,
    record_provider_success,
)
from backend.ai.gemini import GenerationClient, GenerationUsage
from backend.core.config import get_settings
from backend.core.embedding_identity import EmbeddingIdentity
from backend.core.errors import (
    EmbeddingError,
    EmbeddingUnavailableError,
    GenerationError,
    GenerationUnavailableError,
)
from backend.services.knowledge.embedding import (
    EmbeddingClient,
    EmbeddingUsage,
    ensure_vector_dimensions,
)

logger = logging.getLogger("webchat_ai")


def _timing_enabled() -> bool:
    return get_settings().perf_timing_log_enabled


@dataclass
class ProviderLatencyMetrics:
    """Per-request provider latency metrics for observability."""

    provider: str
    first_token_latency_ms: float | None = None
    total_generation_latency_ms: float = 0.0
    fallback_attempts: int = 0
    success: bool = False
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    failed_providers: tuple[str, ...] = ()
    # Providers skipped because their circuit breaker was open (Phase 4).
    # Distinct from `failed_providers`: skipped providers were not attempted,
    # so adaptive health tracking must not count them as failures.
    skipped_providers: tuple[str, ...] = ()


class FallbackGenerationClient:
    """`GenerationClient` that tries providers in order (pre-stream fallback)."""

    def __init__(self, providers: Sequence[GenerationClient]) -> None:
        self._providers = list(providers)
        self._usage = GenerationUsage()
        self._active_provider: str | None = None
        self._active_model: str | None = None
        self._fallback_count = 0
        self._last_latency_metrics: ProviderLatencyMetrics | None = None

    @property
    def usage(self) -> GenerationUsage:
        return self._usage

    @property
    def active_provider(self) -> str | None:
        """Name of the provider that served the most recent request."""
        return self._active_provider

    @property
    def active_model(self) -> str | None:
        """Model id of the provider that served the most recent request.

        Resolved via the serving client's ``model_name`` property (Phase 1
        cost tracking rate-card key); ``None`` when the provider does not
        expose one or no request has completed yet.
        """
        return self._active_model

    @property
    def last_latency_metrics(self) -> ProviderLatencyMetrics | None:
        """Latency metrics from the most recent request."""
        return self._last_latency_metrics

    async def stream_generate(
        self,
        *,
        system: str,
        messages: list[tuple[str, str]],
    ) -> AsyncIterator[str]:
        if not self._providers:
            self._last_latency_metrics = ProviderLatencyMetrics(
                provider="none",
                first_token_latency_ms=None,
                total_generation_latency_ms=0.0,
                fallback_attempts=0,
                success=False,
                error="No generation providers are configured.",
            )
            raise GenerationUnavailableError("No generation providers are configured.")
        last_error: Exception | None = None
        started = time.perf_counter()
        ttft_ms: float | None = None
        successful_provider: str | None = None
        failed_names: list[str] = []
        skipped_names: list[str] = []
        for provider in self._providers:
            name = getattr(provider, "name", type(provider).__name__)
            if not allow_provider(ROLE_GENERATION, name):
                # Circuit open (Phase 4): skip without touching the network.
                skipped_names.append(name)
                logger.warning(
                    "ai_circuit_skipped role=%s provider=%s state=open; trying next provider",
                    ROLE_GENERATION,
                    name,
                )
                continue
            started_streaming = False
            try:
                async for delta in provider.stream_generate(system=system, messages=messages):
                    if not started_streaming:
                        started_streaming = True
                        ttft_ms = (time.perf_counter() - started) * 1000.0
                        self._active_provider = name
                        model_name = getattr(provider, "model_name", None)
                        self._active_model = (
                            model_name if isinstance(model_name, str) and model_name else None
                        )
                        successful_provider = name
                    yield delta
                self._usage = provider.usage
                total_ms = (time.perf_counter() - started) * 1000.0
                record_provider_success(ROLE_GENERATION, name)
                self._last_latency_metrics = ProviderLatencyMetrics(
                    provider=name,
                    first_token_latency_ms=round(ttft_ms, 2) if ttft_ms is not None else None,
                    total_generation_latency_ms=round(total_ms, 2),
                    fallback_attempts=self._fallback_count,
                    success=True,
                    input_tokens=provider.usage.input_tokens,
                    output_tokens=provider.usage.output_tokens,
                    failed_providers=tuple(failed_names),
                    skipped_providers=tuple(skipped_names),
                )
                if _timing_enabled():
                    logger.info(
                        "ai_generation_request",
                        extra=self._timing_extra(
                            provider=name,
                            ttft_ms=ttft_ms,
                            total_ms=total_ms,
                            ok=True,
                        ),
                    )
                return
            except GenerationError as exc:
                if started_streaming:
                    record_provider_failure(ROLE_GENERATION, name)
                    raise
                last_error = exc
                failed_names.append(name)
                record_provider_failure(ROLE_GENERATION, name)
                if _timing_enabled():
                    logger.info(
                        "ai_generation_request",
                        extra=self._timing_extra(
                            provider=name,
                            ttft_ms=None,
                            total_ms=(time.perf_counter() - started) * 1000.0,
                            ok=False,
                            error=str(exc),
                        ),
                    )
                self._fallback_count += 1
                logger.warning(
                    "generation provider %r failed before producing output (%s); trying next",
                    name,
                    exc,
                )
        if last_error is not None:
            self._last_latency_metrics = ProviderLatencyMetrics(
                provider=successful_provider or "unknown",
                first_token_latency_ms=None,
                total_generation_latency_ms=round((time.perf_counter() - started) * 1000.0, 2),
                fallback_attempts=self._fallback_count,
                success=False,
                error=str(last_error),
                failed_providers=tuple(failed_names),
                skipped_providers=tuple(skipped_names),
            )
            raise last_error
        if successful_provider is None and skipped_names:
            # Every provider was circuit-skipped: fail fast with the reason.
            error = "All generation providers are unavailable (circuits open)."
            self._last_latency_metrics = ProviderLatencyMetrics(
                provider="unknown",
                first_token_latency_ms=None,
                total_generation_latency_ms=round((time.perf_counter() - started) * 1000.0, 2),
                fallback_attempts=self._fallback_count,
                success=False,
                error=error,
                skipped_providers=tuple(skipped_names),
            )
            raise GenerationUnavailableError(error)
        self._last_latency_metrics = ProviderLatencyMetrics(
            provider="unknown",
            first_token_latency_ms=None,
            total_generation_latency_ms=round((time.perf_counter() - started) * 1000.0, 2),
            fallback_attempts=self._fallback_count,
            success=False,
            error="All providers failed",
        )
        raise GenerationUnavailableError("All generation providers failed before producing output.")

    def _timing_extra(
        self,
        *,
        provider: str,
        ttft_ms: float | None,
        total_ms: float,
        ok: bool,
        error: str | None = None,
    ) -> dict[str, object]:
        extra: dict[str, object] = {
            "provider": provider,
            "ttft_ms": round(ttft_ms, 2) if ttft_ms is not None else None,
            "total_ms": round(total_ms, 2),
            "fallback_count": self._fallback_count,
            "ok": ok,
        }
        if error is not None:
            extra["error"] = error
        return extra


class FallbackEmbeddingClient:
    """`EmbeddingClient` that tries providers in order (atomic retry)."""

    def __init__(self, providers: Sequence[EmbeddingClient]) -> None:
        self._providers = list(providers)
        self._usage = EmbeddingUsage()
        self._active_provider: str | None = None
        self._fallback_count = 0

    @property
    def usage(self) -> EmbeddingUsage:
        return self._usage

    @property
    def active_provider(self) -> str | None:
        """Name of the provider that served the most recent request."""
        return self._active_provider

    @property
    def embedding_identity(self) -> EmbeddingIdentity:
        """Identity of the provider that served the most recent request."""
        if self._active_provider is None:
            raise EmbeddingUnavailableError("No embedding identity is available before embedding.")
        for provider in self._providers:
            if getattr(provider, "name", type(provider).__name__) == self._active_provider:
                return provider.embedding_identity
        raise EmbeddingUnavailableError("The active embedding provider is unavailable.")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self._providers:
            raise EmbeddingUnavailableError("No embedding providers are configured.")
        expected_dimensions = get_settings().embedding_dimensions
        last_error: Exception | None = None
        started = time.perf_counter()
        skipped_names: list[str] = []
        for index, provider in enumerate(self._providers):
            name = getattr(provider, "name", type(provider).__name__)
            if not allow_provider(ROLE_EMBEDDING, name):
                # Circuit open (Phase 4): skip without touching the network.
                skipped_names.append(name)
                logger.warning(
                    "ai_circuit_skipped role=%s provider=%s state=open; trying next provider",
                    ROLE_EMBEDDING,
                    name,
                )
                continue
            try:
                vectors = await provider.embed(texts)
            except EmbeddingError as exc:
                last_error = exc
                record_provider_failure(ROLE_EMBEDDING, name)
                if _timing_enabled():
                    logger.info(
                        "ai_embedding_request",
                        extra={
                            "provider": name,
                            "total_ms": round((time.perf_counter() - started) * 1000.0, 2),
                            "fallback_count": self._fallback_count,
                            "texts": len(texts),
                            "ok": False,
                            "error": str(exc),
                        },
                    )
                self._fallback_count += 1
                next_name = (
                    getattr(self._providers[index + 1], "name", "?")
                    if index + 1 < len(self._providers)
                    else None
                )
                if next_name is not None:
                    logger.warning(
                        "%s embedding failed (%s); switching to %s",
                        name,
                        exc,
                        next_name,
                    )
                else:
                    logger.warning("%s embedding failed (%s); no providers left", name, exc)
                continue
            # Gate before any vector is committed: the MongoDB index is built
            # for EMBEDDING_DIMENSIONS, so a provider that returns a different
            # length would silently corrupt $vectorSearch. A mismatch is a
            # configuration error, not a transient failure: it is raised
            # (clear error, no fallback) instead of trying more providers.
            ensure_vector_dimensions(name, vectors, expected_dimensions)
            self._usage = provider.usage
            self._active_provider = name
            record_provider_success(ROLE_EMBEDDING, name)
            if _timing_enabled():
                logger.info(
                    "ai_embedding_request",
                    extra={
                        "provider": name,
                        "total_ms": round((time.perf_counter() - started) * 1000.0, 2),
                        "fallback_count": self._fallback_count,
                        "texts": len(texts),
                        "ok": True,
                    },
                )
            logger.info("Embedding provider selected: %s", name)
            return vectors
        if last_error is not None:
            logger.error("All embedding providers failed (%s)", last_error)
            raise EmbeddingUnavailableError(
                f"All embedding providers failed: {last_error}"
            ) from last_error
        if skipped_names:
            # Every provider was circuit-skipped (no attempt produced an error).
            logger.error(
                "All embedding providers skipped by open circuits (%s)",
                ", ".join(skipped_names),
            )
            raise EmbeddingUnavailableError(
                "All embedding providers are unavailable (circuits open)."
            )
        logger.error("All embedding providers failed.")
        raise EmbeddingUnavailableError("All embedding providers failed.")


__all__ = ["FallbackEmbeddingClient", "FallbackGenerationClient"]
