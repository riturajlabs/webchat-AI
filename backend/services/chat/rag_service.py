"""Retrieval-augmented answer generation (Phase 6, ADR-008).

Per question: validate website ownership -> sanitize -> persist the user turn
-> embed the question -> tenant-filtered Top-5 vector search -> build context
-> load conversation memory (overlapping the retrieval) -> stream the Gemini
answer -> persist the answer with sources + tokens + per-stage latency ->
roll up `usage_records` (ADR-005 §5.5/§5.8).

Latency (Phase 12.6): repeated questions hit the bounded retrieval cache
(embedding + search results, TTL-bounded, answers never cached), the context
is capped by total characters, and every assistant message records the
embedding/retrieval/context/history/generation/TTFT/total breakdown for the
performance dashboard.

Hallucination guard (docs/06 Phase 6 rules): the model is never called without
retrieved context. When the knowledge base is empty or search yields no hits,
a fixed fallback (docs/02-TRD.md §8) is returned instead, so the chatbot
cannot fabricate answers. All failures are surfaced as SSE `error` events so
the streaming endpoint stays uniform.
"""

import asyncio
import contextlib
import json
import logging
import re
import time
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from typing import Any

from backend.ai.gemini import GenerationClient, GenerationUsage
from backend.core.cache import CacheStore
from backend.core.config import get_settings
from backend.core.errors import (
    AppError,
    EmbeddingCompatibilityError,
    SessionNotFoundError,
)
from backend.core.logging import get_request_id
from backend.core.metrics import (
    record_chat_failure,
    record_chat_latency,
    record_chat_request,
    record_llm_failure,
    record_llm_latency,
    record_llm_request,
    record_llm_tokens,
    record_rag_empty,
    record_rag_latency,
    record_rag_stage_latency,
)
from backend.core.privacy import content_hash
from backend.core.prompt_guard import InjectionVerdict, validate_response
from backend.core.quota import LLMQuotaService
from backend.core.security import new_id
from backend.models.chat_message import (
    CHAT_ROLE_ASSISTANT,
    CHAT_ROLE_USER,
    ChatMessage,
)
from backend.models.chat_session import ChatSession
from backend.models.knowledge_chunk import KnowledgeChunk
from backend.models.usage_record import usage_date_key
from backend.prompts.rag import (
    UNKNOWN_ANSWER_FALLBACK,
    ContextItem,
    build_user_prompt,
    get_system_prompt,
    sanitize_question,
)
from backend.repositories.chat_message_repository import ChatMessageRepository
from backend.repositories.chat_session_repository import ChatSessionRepository
from backend.repositories.usage_record_repository import UsageRecordRepository
from backend.repositories.vector import VectorRepository, VectorSearchResult
from backend.repositories.vector.hybrid import tokenize
from backend.repositories.vector.reranker import EmbeddingReranker, _strong_lexical_match
from backend.repositories.website_repository import WebsiteRepository
from backend.services.billing.pricing import (
    dollars_to_micros,
    estimate_generation_cost,
    get_model_price,
    load_rate_card,
)
from backend.services.chat.confidence import (
    AnswerabilityMetrics,
    ConfidenceMetrics,
    assess_answerability,
    assess_result_confidence,
    usable,
)
from backend.services.chat.context_optimizer import (
    OptimizationMetrics,
    compress_text,
    remove_near_duplicates,
)
from backend.services.chat.query_classifier import QueryComplexity, classify_query
from backend.services.chat.query_rewrite import (
    DEFAULT_REWRITE_CONTEXT_CHARS,
    build_search_query,
    needs_conversation_context,
)
from backend.services.chat.retrieval_strategy import (
    HybridRetrievalStrategy,
    RetrievalMetricsInfo,
    RetrievalStrategy,
    VectorRetrievalStrategy,
)
from backend.services.knowledge.embedding import (
    EmbeddingClient,
    EmbeddingIdentity,
    ensure_embedding_compatibility,
)
from backend.utils.prompt_security import InjectionTracker
from backend.utils.sanitization import truncate_at_word_boundary
from backend.workers.timing import chat_stage

logger = logging.getLogger("webchat_ai")

# RAG-02: shared process-local abuse tracker. Wired into the RAG entry path
# (`stream_answer`) so every injection verdict recorded by the existing
# `sanitize_question` -> `scan_user_input` pass also feeds repeated-HIGH-attempt
# escalation. Process-local by design and bounded (see InjectionTracker);
# callers that need a deterministic instance (tests) inject their own.
_SHARED_INJECTION_TRACKER = InjectionTracker()


@dataclass(frozen=True)
class RetrievalResult:
    """Structured retrieval-stage output (replaces a 13-element tuple).

    Carries the vector query plus every per-stage timer and diagnostic so
    ``stream_answer`` consumes the stage by name instead of positional
    unpacking (BE-Q10).
    """

    query_vector: list[float]
    results: list[VectorSearchResult]
    embedding_ms: float
    retrieval_ms: float
    embedding_cache_hit: bool
    retrieval_cache_hit: bool
    metrics: RetrievalMetricsInfo
    load_chunks_ms: float
    rerank_ms: float
    rerank_embedding_ms: float
    rerank_input_count: int
    hybrid_candidate_count: int
    adaptive_max_context_chars: int


def _error_event(code: str, message: str) -> dict[str, Any]:
    return {"event": "error", "data": {"code": code, "message": message}}


# RAG-PERF-02: stable serialization for a final retrieval result so the
# retrieval cache can round-trip the post-strategy, post-rerank output
# (schema 2) without recomputing the lexical/RRF/rerank pipeline on a hit.
# All eight VectorSearchResult fields are preserved so downstream consumers
# (context builder, confidence, answerability) see identical evidence on a
# cache hit and a miss.
def _vector_result_payload(result: VectorSearchResult) -> dict[str, Any]:
    payload = {
        "chunk": result.chunk.model_dump(mode="json"),
        "score": result.score,
    }
    if result.lexical_score is not None:
        payload["lexical_score"] = result.lexical_score
    if result.dense_score is not None:
        payload["dense_score"] = result.dense_score
    if result.lexical_exact:
        payload["lexical_exact"] = True
    return payload


def _vector_result_from_payload(payload: dict[str, Any]) -> VectorSearchResult:
    return VectorSearchResult(
        chunk=KnowledgeChunk(**payload["chunk"]),
        score=payload["score"],
        lexical_score=payload.get("lexical_score"),
        dense_score=payload.get("dense_score"),
        lexical_exact=bool(payload.get("lexical_exact", False)),
    )


def _parse_lexical_corpus(raw: str) -> list[VectorSearchResult]:
    """CPU-bound hydration of the compact lexical-corpus Redis payload.

    Pure transformation (JSON parse + ``KnowledgeChunk`` construction +
    ``VectorSearchResult`` wrapping) with NO I/O. Runs inside a worker thread
    via ``asyncio.to_thread`` so it never blocks the asyncio event loop
    (RAG-PERF-03 / F-01). Input order is preserved and raise types mirror the
    legacy inline code (``JSONDecodeError``/``KeyError``/``TypeError``/
    ``ValueError``) so malformed cache values still degrade to the DB path
    exactly as before.
    """
    payload = json.loads(raw)
    return [
        VectorSearchResult(chunk=KnowledgeChunk(**item), score=0.5) for item in payload["chunks"]
    ]


def _now() -> float:
    """Monotonic clock for cache TTL checks (module-level so tests can stub it)."""
    return time.monotonic()


def _round_ms(value: float | None) -> float | None:
    """Round a millisecond duration for persistence (None passes through)."""
    return round(value, 2) if value is not None else None


def _error_code(exc: Exception) -> str:
    """Map an exception to a stable error code (AppError codes pass through)."""
    if isinstance(exc, AppError):
        return exc.code
    return "INTERNAL_ERROR"


def _generation_model_name(generation: Any) -> str:
    """Rate-card key for the model that served the last request.

    Prefers the router's ``active_model`` (the serving provider's id after a
    fallback chain), then a concrete client's ``model_name``. Returns "" when
    neither is available so cost accrues at 0 rather than misattributing.
    """
    for attr in ("active_model", "model_name"):
        value = getattr(generation, attr, None)
        if isinstance(value, str) and value:
            return value
    return ""


class RagService:
    """Orchestrates retrieval -> context -> generation -> persistence."""

    def __init__(
        self,
        *,
        websites: WebsiteRepository,
        vector: VectorRepository,
        embedder: EmbeddingClient,
        generation: GenerationClient,
        sessions: ChatSessionRepository,
        messages: ChatMessageRepository,
        usage: UsageRecordRepository,
        cache: CacheStore | None = None,
        injection_tracker: InjectionTracker | None = None,
        embedding_resolver: Callable[[EmbeddingIdentity], EmbeddingClient] | None = None,
        top_k: int | None = None,
        prompt_version: int | None = None,
        memory_turns: int | None = None,
        retrieval_strategy: RetrievalStrategy | None = None,
        reranker: EmbeddingReranker | None = None,
        allow_reranking: bool = True,
    ) -> None:
        settings = get_settings()
        self._websites = websites
        self._vector = vector
        self._embedder = embedder
        self._embedding_resolver = embedding_resolver
        self._generation = generation
        self._sessions = sessions
        self._messages = messages
        self._usage = usage
        self._cache = cache
        self._injection_tracker = (
            injection_tracker if injection_tracker is not None else _SHARED_INJECTION_TRACKER
        )
        self._top_k = top_k if top_k is not None else settings.chat_top_k
        self._prompt_version = (
            prompt_version if prompt_version is not None else settings.rag_prompt_version
        )
        self._memory_turns = (
            memory_turns if memory_turns is not None else settings.chat_memory_turns
        )
        self._max_chars_per_chunk = settings.chat_context_chunk_chars
        self._max_context_chars = settings.chat_context_max_chars
        self._min_score = settings.chat_context_min_score
        self._timing_enabled = settings.perf_timing_log_enabled
        self._embedding_cache_size = settings.embedding_cache_size
        self._embedding_cache_ttl = settings.embedding_cache_ttl_seconds
        # Phase 3: coalesce identical concurrent cache misses so N identical
        # questions sharing a cold embed cache trigger ONE provider call, not N.
        # Keyed on the normalized question; consumed per retrieval turn.
        self._embed_inflight: dict[str, asyncio.Future[tuple[list[float], EmbeddingIdentity]]] = {}
        # PERF-05: write-behind embedding cache SETs. The cache entry only
        # benefits future callers, so the Redis write runs as a background task
        # off the request critical path. Held here (strong ref) so the loop does
        # not GC a pending task; each task self-removes on completion.
        self._embedding_write_tasks: set[asyncio.Task[None]] = set()
        self._retrieval_cache_size = settings.chat_retrieval_cache_size
        self._retrieval_cache_ttl = settings.chat_retrieval_cache_ttl_seconds
        self._enable_faithfulness_check = settings.enable_faithfulness_check
        self._faithfulness_warning_threshold = settings.faithfulness_warning_threshold
        # RAG confidence check (pre-generation). When enabled, retrieval
        # scores are evaluated before the LLM is called.  Low-confidence
        # queries receive the safe fallback instead of a generated answer.
        self._confidence_check_enabled = settings.enable_rag_confidence_check
        self._confidence_threshold = settings.rag_confidence_threshold
        # Context optimization (opt-in). When enabled, near-duplicate chunks
        # are removed and context text is compressed before prompt construction.
        self._context_optimization_enabled = settings.enable_context_optimization
        self._hybrid_candidate_limit = settings.hybrid_search_candidate_limit
        # Adaptive retrieval (opt-in). When disabled, all queries use the
        # same fixed parameters — zero overhead.
        self._adaptive_enabled = settings.enable_adaptive_retrieval
        self._adaptive_simple_top_k = settings.adaptive_simple_top_k
        self._adaptive_simple_rerank_top_k = settings.adaptive_simple_rerank_top_k
        self._adaptive_simple_max_context_chars = settings.adaptive_simple_max_context_chars
        self._adaptive_complex_top_k = settings.adaptive_complex_top_k
        self._adaptive_complex_rerank_top_k = settings.adaptive_complex_rerank_top_k
        self._adaptive_complex_max_context_chars = settings.adaptive_complex_max_context_chars
        # Conversational query rewriting (multi-turn retrieval accuracy).
        self._query_rewrite_enabled = settings.enable_conversational_query_rewrite
        # Retrieval strategy: explicit override or config-driven default.
        if retrieval_strategy is not None:
            self._retrieval_strategy = retrieval_strategy
        elif settings.enable_hybrid_search:
            self._retrieval_strategy = HybridRetrievalStrategy(
                rrf_k=settings.hybrid_rrf_k,
                keyword_top_k=self._hybrid_candidate_limit,
                # RRF expands past the final top_k into a candidate pool so the
                # reranker can still surface keyword-only results the vector
                # stage missed and that RRF would otherwise truncate away.
                candidate_top_k=self._hybrid_candidate_limit,
            )
        else:
            self._retrieval_strategy = VectorRetrievalStrategy()
        # Reranker: explicit override or config-driven default.
        self._reranker: EmbeddingReranker | None
        if reranker is not None:
            self._reranker = reranker
        elif allow_reranking and settings.enable_reranking and settings.rerank_top_k > 0:
            self._reranker = EmbeddingReranker(
                embedder=embedder,
                top_k=settings.rerank_top_k,
            )
        else:
            self._reranker = None
        # Source diversification for the reranker input pool (max chunks per
        # source URL).  <= 0 disables the filter (reranker input unchanged).
        # getattr with a 0 default keeps behavior unchanged when a settings
        # stub (e.g. in tests) does not expose the new field.
        self._rerank_max_chunks_per_source = getattr(settings, "rerank_max_chunks_per_source", 0)
        # AI cost rate card (Phase 1). Parsed once at construction so a
        # malformed AI_MODEL_PRICING_JSON fails fast instead of silently
        # producing zero-cost traffic. Unpriced models warn once per process.
        self._rate_card = load_rate_card(settings.ai_model_pricing_json)
        self._warned_unpriced_models: set[str] = set()

    @staticmethod
    def _tracking_identity(
        tenant_id: str, visitor_id: str | None, session_id: str | None
    ) -> str | None:
        """Tenant-scoped key for injection tracking, or None when unattributable.

        Skipping anonymous requests (no visitor/session) keeps the tracker
        isolated: attempts can only ever be counted for an identity that
        actually identifies a caller, and the tenant prefix prevents any
        cross-tenant visitor/session id collision.
        """
        raw = visitor_id or session_id
        if not raw:
            return None
        return f"{tenant_id}:{raw}"

    def _injection_hook(
        self, tenant_id: str, visitor_id: str | None, session_id: str | None
    ) -> Callable[[InjectionVerdict], None]:
        """Build the on_verdict hook feeding the injection abuse tracker.

        Consumes the verdict already produced by `sanitize_question`'s single
        `scan_user_input` pass (no re-scan). The tracker records only HIGH
        severity; when it crosses the escalation threshold a warning log fires.
        Tracker failures are caught so security monitoring can never break the
        normal request path (fail-open).
        """
        identity = self._tracking_identity(tenant_id, visitor_id, session_id)

        def hook(verdict: InjectionVerdict) -> None:
            if identity is None:
                return
            try:
                self._injection_tracker.record(identity, verdict.severity)
                if self._injection_tracker.is_escalated(identity):
                    logger.warning(
                        "prompt_security injection_escalated identity=%s severity=%s patterns=%s",
                        identity,
                        verdict.severity,
                        verdict.patterns,
                    )
            except Exception:
                logger.exception("prompt_security tracker_record_failed")

        return hook

    async def _embedded_from_cache(self, key: str) -> tuple[list[float], EmbeddingIdentity] | None:
        """Read and decode a cached question embedding; None on miss/corrupt."""
        if self._cache is None or self._embedding_cache_size <= 0:
            return None
        raw = await self._cache.get("embed", key)
        if raw is None:
            return None
        try:
            entry = json.loads(raw)
            identity_data = entry["embedding_identity"]
            identity = EmbeddingIdentity(
                provider=identity_data["provider"],
                model=identity_data["model"],
                dimensions=identity_data["dimensions"],
                version=identity_data["version"],
            )
            return entry["vector"], identity
        except (json.JSONDecodeError, TypeError, KeyError):
            # Corrupt entry: treated as a miss so the exact text is re-embedded.
            return None

    async def _embed_question(
        self, question: str, *, required_identity: EmbeddingIdentity | None = None
    ) -> tuple[list[float], bool, EmbeddingIdentity]:
        """Embed `question`, caching identical questions across turns.

        Returns `(vector, cache_hit, identity)` so callers can report hit/miss and the
        opt-in timing breakdown. The cache is a bounded per-process LRU keyed on
        the normalized (case-folded) question text; repeated/echoed questions hit
        the cache and skip the provider call. Eviction is size-only so entries
        never go stale.

        Concurrent identical cache misses are coalesced (single-flight): the
        first request calls the provider; identical waiters share that one
        result instead of each embedding the same text (Phase 3 latency audit).
        Waiter callers report `cache_hit=False` — the provider cache itself was
        not hit — which is accurate for analytics.

        Ownership of a key is claimed atomically via `setdefault` (BE-Q01), so
        two concurrent callers can never both embed the same text: exactly one
        registers as owner, every other caller awaits that same future, and an
        owner re-checks the cache after winning the key so a flight that
        completed during the race window is reused instead of re-embedded.

        The cache write-back is off the critical path (PERF-05): the SET only
        benefits future requests, so it runs as a background task and the
        request proceeds once the vector is produced. The single-flight key
        stays claimed until the write settles so a caller arriving mid-write
        shares this resolved future instead of re-embedding (BE-Q01); write
        failures are logged and the cache remains fail-open.
        """
        identity_key = ""
        if required_identity is not None:
            identity_key = ":".join(
                [
                    required_identity.provider,
                    required_identity.model,
                    str(required_identity.dimensions),
                    required_identity.version,
                ]
            )
        key = (
            f"{identity_key}:{question.strip().lower()}"
            if identity_key
            else question.strip().lower()
        )
        cached = await self._embedded_from_cache(key)
        if cached is not None:
            return cached[0], True, cached[1]
        # Single-flight: claim the key atomically. `setdefault` guarantees only
        # the first registrant becomes owner; all other concurrent callers
        # receive the owner's future and await the same result.
        loop = asyncio.get_running_loop()
        my_future: asyncio.Future[tuple[list[float], EmbeddingIdentity]] = loop.create_future()
        owner = self._embed_inflight.setdefault(key, my_future)
        if owner is not my_future:
            # A concurrent owner already claimed this key — share its result.
            vector, identity = await owner
            return vector, False, identity
        write_pending = False
        try:
            # We own the key. Re-check the cache: an owner that completed in
            # the window between our first cache read and this registration
            # already wrote the entry (BE-Q01). Reuse it instead of opening a
            # duplicate provider call for the same text.
            cached = await self._embedded_from_cache(key)
            if cached is not None:
                if not my_future.done():
                    my_future.set_result(cached)
                return cached[0], False, cached[1]
            embedder = (
                self._embedding_resolver(required_identity)
                if required_identity is not None and self._embedding_resolver is not None
                else self._embedder
            )
            vectors = await embedder.embed([question])
            vector = vectors[0]
            identity = embedder.embedding_identity
            if required_identity is not None and identity != required_identity:
                raise EmbeddingCompatibilityError(
                    "Query embedding provider does not match the website corpus identity."
                )
            if self._cache is not None and self._embedding_cache_size > 0:
                ttl = self._embedding_cache_ttl if self._embedding_cache_ttl > 0 else None
                # PERF-05 write-behind: the SET is only read by *future*
                # requests, so it must never block this one. Run it as a
                # background task after producing the vector. The single-flight
                # key stays claimed until the write settles — the done-callback
                # below releases it — so a caller arriving mid-write shares this
                # already-resolved future instead of opening a duplicate provider
                # call for the same text (BE-Q01).
                payload = json.dumps({"vector": vector, "embedding_identity": identity.as_dict()})

                def _release_after_write(task: asyncio.Task[None]) -> None:
                    self._embedding_write_tasks.discard(task)
                    try:
                        task.result()
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        logger.warning(
                            "embedding cache write-behind failed (key=%r)", key, exc_info=True
                        )
                    finally:
                        if self._embed_inflight.get(key) is my_future:
                            self._embed_inflight.pop(key, None)

                write_task = asyncio.create_task(self._cache.set("embed", key, payload, ttl=ttl))
                self._embedding_write_tasks.add(write_task)
                write_task.add_done_callback(_release_after_write)
                write_pending = True
            if not my_future.done():
                my_future.set_result((vector, identity))
            return vector, False, identity
        except BaseException as exc:  # noqa: BLE001 - propagate to owner AND waiters
            if not my_future.done():
                my_future.set_exception(exc)
            try:
                # The owner never awaits its own future, so make it retrieve
                # its exception here: a flight with no waiters must not surface
                # an unobserved Future exception. Waiters (if any) saw the same
                # value; the original exception is re-raised below regardless.
                await my_future
            except BaseException:  # noqa: BLE001 - value was already seen by waiters
                pass
            raise
        finally:
            # Cleanup on every exit (success AND failure) so a later caller can
            # retry. The identity guard never evicts a newer owner of the key.
            # When a write-behind was scheduled the key is released by its
            # done-callback instead (BE-Q01 coalescing across the write window).
            if not write_pending and self._embed_inflight.get(key) is my_future:
                self._embed_inflight.pop(key, None)

    async def _run_retrieval_strategy(
        self,
        *,
        query: str,
        vector_results: list[VectorSearchResult],
        all_chunks: list[VectorSearchResult] | None,
        top_k: int,
    ) -> tuple[list[VectorSearchResult], RetrievalMetricsInfo]:
        """Run the configured retrieval strategy off the event loop (PERF-K01).

        ``HybridRetrievalStrategy`` tokenizes the full lexical corpus — a
        CPU-bound O(n) pass (50-300ms on large websites) — so it is moved to a
        worker thread to keep the event loop responsive during chat requests.
        The vector-only pass-through stays on the loop (it does no work).
        """
        if isinstance(self._retrieval_strategy, HybridRetrievalStrategy):
            return await asyncio.to_thread(
                self._retrieval_strategy.search,
                query=query,
                vector_results=vector_results,
                all_chunks=all_chunks,
                top_k=top_k,
            )
        return self._retrieval_strategy.search(
            query=query,
            vector_results=vector_results,
            all_chunks=all_chunks,
            top_k=top_k,
        )

    @staticmethod
    async def _stop_history_task(history_task: asyncio.Task[Any]) -> None:
        """Cancel the background history read and consume its termination.

        ``Task.cancel()`` only *schedules* cancellation; without awaiting the
        task, the resulting ``CancelledError`` surfaces later as a noisy
        "Task exception was never retrieved" background traceback and the read's
        resources are not released deterministically (BE-Q11).
        """
        history_task.cancel()
        try:
            await history_task
        except (asyncio.CancelledError, Exception):
            pass

    async def _fallback_events(
        self,
        *,
        tenant_id: str,
        website_id: str,
        history_task: asyncio.Task[Any] | None,
        session: ChatSession,
        started: float,
        vector_queries: int,
        reason: str,
        query: str,
        scores: list[float] | None = None,
        confidence_metrics: ConfidenceMetrics | None = None,
    ) -> AsyncGenerator[dict[str, Any]]:
        """Emit the safe-fallback stream and record it (BE-Q09 pipeline stage).

        Stops the background history read (when one is in flight), emits the
        no-context fallback event sequence and records the chat failure.
        Callers forward the yielded events and ``return``.
        """
        if history_task is not None:
            await self._stop_history_task(history_task)
        async for event in self._emit_fallback(
            tenant_id=tenant_id,
            website_id=website_id,
            session=session,
            started=started,
            vector_queries=vector_queries,
            reason=reason,
            query=query,
            scores=scores,
            confidence_metrics=confidence_metrics,
        ):
            yield event
        record_chat_failure(reason=reason)

    async def _retrieve(
        self,
        *,
        tenant_id: str,
        website_id: str,
        question: str,
        embedding_identity: EmbeddingIdentity | None = None,
        lexical_corpus_version: str = "",
        history_task: asyncio.Task[list[tuple[str, str]]] | None = None,
    ) -> RetrievalResult:
        """Embed + search, memoizing repeats within the retrieval TTL.

        Returns a :class:`RetrievalResult` carrying ``(query_vector, results,
        embedding_ms, retrieval_ms, embedding_cache_hit,
        retrieval_cache_hit, retrieval_metrics, load_chunks_ms, rerank_ms,
        rerank_embedding_ms, rerank_input_count, hybrid_candidate_count,
        adaptive_max_context_chars)``.

        When *history_task* is supplied and the question looks
        context-dependent, the most recent user turn is prepended before
        embedding so follow-up questions keep their conversation subject
        (`enable_conversational_query_rewrite`).  Cache keys derive from the
        final search query, so rewrites never collide with standalone asks.
        """
        # Adaptive retrieval: classify query complexity and determine params.
        complexity = classify_query(question)
        effective_top_k = self._top_k
        adaptive_max_context_chars = self._max_context_chars
        if self._adaptive_enabled:
            if complexity == QueryComplexity.SIMPLE:
                effective_top_k = self._adaptive_simple_top_k
                adaptive_max_context_chars = self._adaptive_simple_max_context_chars
            elif complexity == QueryComplexity.COMPLEX:
                effective_top_k = self._adaptive_complex_top_k
                adaptive_max_context_chars = self._adaptive_complex_max_context_chars

        # Conversational query rewrite: retrieval-only contextualization.
        search_query = question
        if (
            self._query_rewrite_enabled
            and history_task is not None
            and needs_conversation_context(question)
        ):
            try:
                history = await history_task
                rewritten = build_search_query(
                    question,
                    history,
                    max_context_chars=DEFAULT_REWRITE_CONTEXT_CHARS,
                )
            except Exception:
                # History load failed: fall back to the raw question.  The
                # later history await still surfaces the error downstream.
                logger.exception(
                    "query rewrite skipped: conversation memory unavailable (tenant=%s website=%s)",
                    tenant_id,
                    website_id,
                )
            else:
                if rewritten != question:
                    search_query = rewritten
                    logger.info(
                        "rag_query_rewritten tenant=%s website=%s "
                        "original_hash=%s search_hash=%s search_length=%d",
                        tenant_id,
                        website_id,
                        content_hash(question),
                        content_hash(search_query),
                        len(search_query),
                    )

        cache = self._cache
        # RAG-07: bind the retrieval cache to the corpus version so a knowledge
        # re-processing (which bumps `website.updated_at`) can never serve stale
        # cached results for the same question within the TTL window.
        corpus_part = f":{lexical_corpus_version}" if lexical_corpus_version else ""
        cache_key = f"{tenant_id}:{website_id}{corpus_part}:{search_query.strip().lower()}"
        now = _now()
        retrieval_enabled = (
            cache is not None and self._retrieval_cache_size > 0 and self._retrieval_cache_ttl > 0
        )
        if retrieval_enabled:
            assert cache is not None  # guaranteed by retrieval_enabled
            raw = await cache.get("retrieval", cache_key)
            if raw is not None:
                try:
                    entry = json.loads(raw)
                    if now - entry["cached_at"] < self._retrieval_cache_ttl:
                        if entry.get("schema") == 2:
                            # RAG-PERF-02: schema-2 entries hold the FINAL
                            # post-strategy, post-rerank retrieval result. A
                            # valid hit returns it directly, skipping the full
                            # lexical-corpus load + keyword/RRF pass + rerank
                            # (deterministic given query vector + stored chunk
                            # embeddings + query tokens + top_k).
                            vector = entry["vector"]
                            identity_data = entry["embedding_identity"]
                            query_identity = EmbeddingIdentity(
                                provider=identity_data["provider"],
                                model=identity_data["model"],
                                dimensions=identity_data["dimensions"],
                                version=identity_data["version"],
                            )
                            results = [_vector_result_from_payload(r) for r in entry["results"]]
                            for result in results:
                                ensure_embedding_compatibility(result.chunk, query_identity)
                            metrics_data = entry.get("metrics") or {}
                            metrics = RetrievalMetricsInfo(
                                retrieval_method=metrics_data.get("retrieval_method", "vector"),
                                vector_result_count=metrics_data.get("vector_result_count", 0),
                                keyword_result_count=metrics_data.get("keyword_result_count", 0),
                                final_result_count=metrics_data.get("final_result_count", 0),
                                hybrid_candidate_count=metrics_data.get(
                                    "hybrid_candidate_count", 0
                                ),
                            )
                            return RetrievalResult(
                                query_vector=vector,
                                results=results,
                                embedding_ms=0.0,
                                retrieval_ms=0.0,
                                embedding_cache_hit=True,
                                retrieval_cache_hit=True,
                                metrics=metrics,
                                load_chunks_ms=0.0,
                                # No lexical load / keyword-RRF / rerank ran on
                                # THIS request: report zero measured stage cost
                                # (percentile histograms observe what actually
                                # executed). The cached result itself is the
                                # same the miss path would have returned.
                                rerank_ms=0.0,
                                rerank_embedding_ms=0.0,
                                rerank_input_count=0,
                                # `hybrid_candidate_count` describes the corpus
                                # that produced the served results (the cache
                                # key is corpus-version-bound, so the cached
                                # value equals what a re-run would report).
                                hybrid_candidate_count=int(
                                    entry.get("hybrid_candidate_count", 0) or 0
                                ),
                                adaptive_max_context_chars=adaptive_max_context_chars,
                            )
                        # schema-1 legacy entries (raw vector results only) are
                        # treated as a cache miss: they lack the final rerank
                        # output and would otherwise short-circuit incorrectly.
                except (json.JSONDecodeError, TypeError, KeyError, ValueError):
                    pass
        t0 = time.perf_counter()
        async with chat_stage("retrieval.embed"):
            query_vector, embedding_cache_hit, query_identity = await self._embed_question(
                search_query, required_identity=embedding_identity
            )
        embedding_ms = (time.perf_counter() - t0) * 1000.0
        t1 = time.perf_counter()
        # RAG-PERF-07: the hybrid lexical corpus load (Redis/DB read of the
        # website's full embedding-free corpus) is independent of the `$vectorSearch`
        # result set — same tenant/website scope, same embedding identity, corpus
        # version bound — so it is started now and overlaps the vector round trip
        # instead of serializing behind it. `_run_retrieval_strategy` still awaits
        # both inputs and runs in the same order, so RRF fusion, ranking and the
        # returned metrics are byte-for-byte identical to the sequential behavior.
        load_chunks_ms = 0.0
        hybrid_candidate_count = 0
        load_task: asyncio.Task[list[VectorSearchResult]] | None = None
        if isinstance(self._retrieval_strategy, HybridRetrievalStrategy):
            t_load = time.perf_counter()
            load_task = asyncio.create_task(
                self._load_all_chunks(
                    tenant_id,
                    website_id,
                    embedding_identity=query_identity,
                    corpus_version=lexical_corpus_version,
                )
            )
        try:
            async with chat_stage("retrieval.vector_search"):
                raw_results = await self._vector.similarity_search(
                    tenant_id,
                    website_id,
                    query_vector,
                    top_k=effective_top_k,
                    embedding_identity=query_identity,
                )
        except BaseException:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                if load_task is not None:
                    load_task.cancel()
                    await load_task
            raise
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "mongodb_vector_search_debug question=%r vector_result_count=%d",
                search_query,
                len(raw_results),
            )
            for result in raw_results:
                metadata = result.chunk.metadata
                logger.debug(
                    "mongodb_vector_search_result chunk_id=%s score=%s title=%s url=%s "
                    "chunk_text_200=%r",
                    result.chunk.id,
                    round(result.score, 4),
                    metadata.get("title"),
                    metadata.get("source_url"),
                    result.chunk.chunk_text[:200],
                )
        retrieval_ms = (time.perf_counter() - t1) * 1000.0
        # Hybrid keyword retrieval is a second source over the website's full
        # corpus (recovering exact-term matches the vector stage missed), so
        # load the corpus for the keyword pass when hybrid is enabled. The read
        # has been running concurrently with the vector search above; only its
        # residual wait (if any) remains.
        if load_task is not None:
            all_chunks = await load_task
            load_chunks_ms = (time.perf_counter() - t_load) * 1000.0
            hybrid_candidate_count = len(all_chunks)
        else:
            all_chunks = None
        results, metrics = await self._run_retrieval_strategy(
            query=search_query,
            vector_results=raw_results,
            all_chunks=all_chunks,
            top_k=effective_top_k,
        )
        # Apply reranking to improve ordering quality.
        rerank_ms = 0.0
        rerank_embedding_ms = 0.0
        rerank_input_count = 0
        if self._reranker is not None and results:
            results = self._diversify_sources(results, search_query)
            results = await self._hydrate_rerank_candidates(tenant_id, website_id, results)
            rerank_input_count = len(results)
            results, rerank_metrics = await self._reranker.rerank(
                search_query, results, query_embedding=query_vector
            )
            rerank_ms = rerank_metrics.rerank_ms
            rerank_embedding_ms = rerank_metrics.rerank_embedding_ms
        results = self._strip_lexical_scores(results) if self._reranker is None else results
        # RAG-PERF-02: cache the FINAL retrieval result (post-strategy, post-
        # rerank) so a warm cache hit can return it directly, skipping the full
        # lexical-corpus load + keyword/RRF pass + reranking. Reranking is
        # deterministic given (query vector, stored chunk embeddings, query
        # tokens, top_k) — all fixed per (search_query, corpus version) — so the
        # cached result is exactly what a repeat of the miss path would compute.
        # Schema 2 marks this enriched format; older schema-1 entries (raw
        # vector results only) are treated as misses by the reader.
        if retrieval_enabled:
            assert cache is not None  # guaranteed by retrieval_enabled
            entry = {
                "schema": 2,
                "vector": query_vector,
                "embedding_identity": query_identity.as_dict(),
                "results": [_vector_result_payload(r) for r in results],
                "metrics": {
                    "retrieval_method": metrics.retrieval_method,
                    "vector_result_count": metrics.vector_result_count,
                    "keyword_result_count": metrics.keyword_result_count,
                    "final_result_count": metrics.final_result_count,
                    "hybrid_candidate_count": metrics.hybrid_candidate_count,
                },
                "rerank_ms": rerank_ms,
                "rerank_embedding_ms": rerank_embedding_ms,
                "rerank_input_count": rerank_input_count,
                "hybrid_candidate_count": hybrid_candidate_count,
                "cached_at": _now(),
            }
            await cache.set(
                "retrieval", cache_key, json.dumps(entry), ttl=self._retrieval_cache_ttl
            )
        return RetrievalResult(
            query_vector=query_vector,
            results=results,
            embedding_ms=embedding_ms,
            retrieval_ms=retrieval_ms,
            embedding_cache_hit=embedding_cache_hit,
            retrieval_cache_hit=False,
            metrics=metrics,
            load_chunks_ms=load_chunks_ms,
            rerank_ms=rerank_ms,
            rerank_embedding_ms=rerank_embedding_ms,
            rerank_input_count=rerank_input_count,
            hybrid_candidate_count=hybrid_candidate_count,
            adaptive_max_context_chars=adaptive_max_context_chars,
        )

    @staticmethod
    def _strip_lexical_scores(
        results: list[VectorSearchResult],
    ) -> list[VectorSearchResult]:
        """Clear lexical evidence when reranking did not run.

        The lexical gate in ``_build_context`` is only meaningful when the
        lexical-aware reranker actually narrowed candidates by strong lexical
        match. When no reranker is present, the raw strategy results carry RRF
        evidence that has not been protected, so it must be neutralized to keep
        the no-reranker path behaving exactly as before (cosine gate only).
        """
        return [
            VectorSearchResult(
                chunk=r.chunk,
                score=r.score,
                dense_score=r.dense_score,
                lexical_exact=r.lexical_exact,
            )
            for r in results
        ]

    def _diversify_sources(
        self,
        results: list[VectorSearchResult],
        query: str,
    ) -> list[VectorSearchResult]:
        """Cap chunks per source URL in the reranker input pool.

        The RRF/hybrid pool can be monopolized by many chunks of a single,
        highly-relevant source (e.g. several near-identical chunks of one
        course page) that then crowd genuinely relevant *other* sources out of
        the reranker's cosine-based ``top_k``.  This filter keeps at most
        ``max_per_url`` unprotected chunks per source URL while iterating in
        the existing pool order, so the final top-k spans more distinct
        sources without changing relevance scoring.

        Strong lexical/protected candidates — the SAME signal the reranker
        protects (every content token of the query present in the chunk) — are
        always exempt from the cap, matching the reranker exactly, so the
        chairperson / dean-of-SOIT lexical protection is never regressed.
        Exempt chunks do not consume a URL's per-source budget.

        All ``VectorSearchResult`` fields (true cosine ``score``,
        ``lexical_score``, chunk metadata/source URL) are preserved verbatim —
        this filter only removes whole candidates, never mutates them.

        Returns a new list to keep the pipeline functional; the original
        ``results`` is not modified.  Bounded to ``max_per_url`` per source.
        When ``rerank_max_chunks_per_source <= 0`` the pool is returned
        unchanged (diversification disabled).

        Note: ``lexical_score``/RRF evidence is a *pool* signal computed before
        reranking and is separate from the reranker's strong-lexical flag; here
        we base the exemption on strong-lexical presence (not on
        ``lexical_score``) to mirror what the reranker will protect.
        """
        max_per_url = self._rerank_max_chunks_per_source
        if max_per_url <= 0:
            return results
        query_tokens = tokenize(query)
        per_url: dict[str, int] = {}
        kept: list[VectorSearchResult] = []
        for result in results:
            is_strong = _strong_lexical_match(query_tokens, result.chunk.chunk_text)
            if is_strong:
                kept.append(result)
                continue
            url = str(result.chunk.metadata.get("source_url") or "")
            count = per_url.get(url, 0)
            if count >= max_per_url:
                continue
            per_url[url] = count + 1
            kept.append(result)
        return kept

    async def _hydrate_rerank_candidates(
        self,
        tenant_id: str,
        website_id: str,
        results: list[VectorSearchResult],
    ) -> list[VectorSearchResult]:
        """Ensure rerank-pool chunks carry embeddings for the cosine reranker.

        The keyword corpus is loaded embedding-free (via ``list_chunks_light``)
        so keyword-only candidates it recovered have empty embeddings.  The
        reranker scores candidates with stored chunk embeddings (and only
        protects strong lexical matches for candidates *with* embeddings), so
        an empty-embedding keyword-only chunk would be scored 0.0 and stripped
        of its lexical evidence — regressing hybrid retrieval.  Hydrate just
        the missing embeddings by chunk id (a small, bounded subset, at most
        the rerank candidate pool), keeping the full-corpus transfer light.
        """
        missing = [r for r in results if not r.chunk.embedding]
        if not missing:
            return results
        hydrated = await self._vector.get_chunks_by_ids(
            tenant_id, website_id, [r.chunk.id for r in missing]
        )
        by_id = {chunk.id: chunk for chunk in hydrated}
        out: list[VectorSearchResult] = []
        for result in results:
            chunk = result.chunk
            if not chunk.embedding and chunk.id in by_id:
                chunk = by_id[chunk.id]
            out.append(
                VectorSearchResult(
                    chunk=chunk,
                    score=result.score,
                    lexical_score=result.lexical_score,
                    dense_score=result.dense_score,
                    lexical_exact=result.lexical_exact,
                )
            )
        return out

    async def stream_answer(
        self,
        *,
        tenant_id: str,
        website_id: str,
        question: str,
        session_id: str | None = None,
        visitor_id: str | None = None,
        user_id: str | None = None,
    ) -> AsyncGenerator[dict[str, Any]]:
        """Answer `question` as a stream of SSE events.

        Events: `sources`, `message` (one per delta), `done`, or `error`.
        """
        started = time.monotonic()
        perf_started = time.perf_counter()
        website_lookup_ms: float = 0.0
        record_chat_request()
        try:
            t_lookup = time.perf_counter()
            async with chat_stage("website.lookup"):
                website = await self._websites.find_by_id(tenant_id, website_id)
            website_lookup_ms = (time.perf_counter() - t_lookup) * 1000.0
            if website is None:
                yield _error_event("WEBSITE_NOT_FOUND", "Website not found.")
                record_chat_failure(reason="website_not_found")
                return
            question = sanitize_question(
                question,
                on_verdict=self._injection_hook(tenant_id, visitor_id, session_id),
            )
            logger.info(
                "chat_request tenant=%s website=%s session=%s knowledge_chunks=%s "
                "query_hash=%s query_length=%d",
                tenant_id,
                website_id,
                session_id,
                website.knowledge_chunks,
                content_hash(question),
                len(question),
            )
            async with chat_stage("session.resolve"):
                t_session = time.perf_counter()
                session = await self._ensure_session(
                    tenant_id=tenant_id,
                    website_id=website_id,
                    session_id=session_id,
                    visitor_id=visitor_id,
                    user_id=user_id,
                )
                session_resolution_ms = (time.perf_counter() - t_session) * 1000.0
        except Exception as exc:
            yield _error_event(_error_code(exc), _safe_message(exc))
            return

        # Persist the user turn up front: a later failure still leaves a
        # complete, searchable conversation log (docs/05 §10).
        user_message = ChatMessage.new(
            tenant_id=tenant_id,
            website_id=website_id,
            session_id=session.session_id,
            role=CHAT_ROLE_USER,
            content=question,
        )
        t_user_persist = time.perf_counter()
        async with chat_stage("persist.user_message"):
            await self._messages.create(user_message)
        user_message_persist_ms = (time.perf_counter() - t_user_persist) * 1000.0

        if website.knowledge_chunks == 0:
            async for event in self._fallback_events(
                tenant_id=tenant_id,
                website_id=website_id,
                history_task=None,
                session=session,
                started=started,
                vector_queries=0,
                reason="knowledge_empty",
                query=question,
            ):
                yield event
            return

        # Start the conversation-memory read up front so the Mongo query
        # overlaps the embedding + vector search (both are usually slower than a
        # recent-messages read).
        history_task = asyncio.create_task(
            self._load_history(
                tenant_id,
                session.session_id,
                exclude_message_id=user_message.id,
            )
        )
        try:
            retrieval = await self._retrieve(
                tenant_id=tenant_id,
                website_id=website_id,
                question=question,
                embedding_identity=website.embedding_identity,
                # A lexical corpus cache is immutable for one website version.
                # `updated_at` changes when knowledge processing refreshes the
                # website, so a new corpus naturally receives a new cache key.
                lexical_corpus_version=website.updated_at.isoformat(),
                history_task=history_task,
            )
            query_vector = retrieval.query_vector
            results = retrieval.results
            embedding_ms = retrieval.embedding_ms
            retrieval_ms = retrieval.retrieval_ms
            embedding_cache_hit = retrieval.embedding_cache_hit
            retrieval_cache_hit = retrieval.retrieval_cache_hit
            retrieval_metrics = retrieval.metrics
            load_chunks_ms = retrieval.load_chunks_ms
            rerank_ms = retrieval.rerank_ms
            rerank_embedding_ms = retrieval.rerank_embedding_ms
            rerank_input_count = retrieval.rerank_input_count
            hybrid_candidate_count = retrieval.hybrid_candidate_count
            adaptive_max_context_chars = retrieval.adaptive_max_context_chars
        except EmbeddingCompatibilityError:
            # Audit fix (embedding identity): a mixed/incompatible corpus must
            # never surface as an error to the visitor. The repositories
            # already refuse to mix embedding spaces; here we degrade to the
            # existing safe fallback instead of an error event.
            logger.warning(
                "rag_embedding_identity_mismatch tenant=%s website=%s session=%s",
                tenant_id,
                website_id,
                session.session_id,
            )
            async for event in self._fallback_events(
                tenant_id=tenant_id,
                website_id=website_id,
                history_task=history_task,
                session=session,
                started=started,
                vector_queries=1,
                reason="embedding_mismatch",
                query=question,
            ):
                yield event
            return
        except Exception as exc:
            await self._stop_history_task(history_task)
            logger.exception("question embedding failed (tenant=%s)", tenant_id)
            yield _error_event(_error_code(exc), _safe_message(exc))
            record_chat_failure(reason="embedding_error")
            return
        logger.info(
            "chat_embedding tenant=%s website=%s provider=%s dims=%s cache=%s",
            tenant_id,
            website_id,
            self._provider_name(self._embedder),
            len(query_vector),
            "hit" if embedding_cache_hit else "miss",
        )
        logger.info(
            "chat_vector_search tenant=%s website=%s top_k=%s hits=%s scores=%s",
            tenant_id,
            website_id,
            self._top_k,
            len(results),
            [round(result.score, 4) for result in results],
        )
        for result in results[:10]:
            metadata = result.chunk.metadata
            logger.info(
                "chat_retrieval_hit tenant=%s website=%s chunk_id=%s document_id=%s "
                "score=%s source_url=%s title=%s",
                tenant_id,
                website_id,
                result.chunk.id,
                result.chunk.document_id,
                round(result.score, 4),
                metadata.get("source_url"),
                metadata.get("title"),
            )

        if not results:
            async for event in self._fallback_events(
                tenant_id=tenant_id,
                website_id=website_id,
                history_task=history_task,
                session=session,
                started=started,
                vector_queries=1,
                reason="retrieval_empty",
                query=question,
            ):
                yield event
            record_rag_empty()
            return

        # Pre-generation confidence check.  When enabled, the retrieval
        # scores are evaluated before the LLM is called.  Low confidence
        # means the knowledge base likely lacks relevant content, so we
        # return the safe fallback instead of risking a hallucinated answer.
        retrieval_scores = [r.score for r in results]
        confidence_score: float | None = None
        confidence_metrics: ConfidenceMetrics | None = None
        answerability_metrics: AnswerabilityMetrics | None = None
        if self._confidence_check_enabled:
            # Base relevance confidence (0.50*mean + 0.30*hit_ratio + 0.20*peak)
            # is kept unchanged and exposed for telemetry.
            confidence_metrics = assess_result_confidence(
                results, min_score=self._min_score, query=question
            )
            confidence_score = confidence_metrics.confidence
            # The strict evidence-aware answerability decision.  For a closed
            # (specific-entity/fact) query, generation is allowed only when the
            # query's required content terms are present in the evidence; this
            # overrides a high cosine that merely reflects generic similarity.
            # Strong entity evidence may also authorise generation when the raw
            # cosine falls below the calibration floor (fixing false fallback).
            # `confidence_score` intentionally stays the raw base confidence so
            # the unchanged confidence metric remains available for telemetry.
            answerability_metrics = assess_answerability(
                question,
                results,
                min_score=self._min_score,
            )
            base_allowed = (
                confidence_score >= self._confidence_threshold
                or answerability_metrics.reason == "strong_entity_evidence"
            )
            generation_allowed = answerability_metrics.allowed and base_allowed
            if not generation_allowed:
                logger.warning(
                    "rag_answerability_blocked base_confidence=%.4f "
                    "answerability=%.4f lexical_coverage=%.4f "
                    "query_type=%s evidence_strength=%s category=%s reason=%s "
                    "tenant=%s website=%s session=%s result_count=%d",
                    confidence_score,
                    answerability_metrics.answerability,
                    answerability_metrics.lexical_coverage,
                    answerability_metrics.query_type.value,
                    answerability_metrics.evidence_strength.value,
                    answerability_metrics.category,
                    answerability_metrics.reason,
                    tenant_id,
                    website_id,
                    session.session_id,
                    len(results),
                )
                async for event in self._fallback_events(
                    tenant_id=tenant_id,
                    website_id=website_id,
                    history_task=history_task,
                    session=session,
                    started=started,
                    vector_queries=1,
                    reason="confidence_low",
                    query=question,
                    scores=retrieval_scores,
                    confidence_metrics=confidence_metrics,
                ):
                    yield event
                return

        t_context = time.perf_counter()
        async with chat_stage("retrieval.context"):
            context_items, sources, opt_metrics = self._build_context(
                results,
                max_context_chars=adaptive_max_context_chars,
                query=question,
            )
        context_ms = (time.perf_counter() - t_context) * 1000.0
        # Context-empty guard: min_score filtering can drop every retrieved
        # chunk even when raw retrieval returned hits (e.g. the confidence
        # gate is disabled, or its threshold sits below ~0.7 * min_score).
        # Calling the model with an empty context block would rely purely on
        # prompt compliance to avoid hallucination, so emit the safe
        # fallback instead — the model is never called without context.
        if not context_items:
            async for event in self._fallback_events(
                tenant_id=tenant_id,
                website_id=website_id,
                history_task=history_task,
                session=session,
                started=started,
                vector_queries=1,
                reason="context_empty",
                query=question,
                scores=retrieval_scores,
                confidence_metrics=confidence_metrics,
            ):
                yield event
            return
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "chat_context_build question=%r context_count=%d",
                question,
                len(context_items),
            )
            for idx, (item, src) in enumerate(zip(context_items, sources, strict=True)):
                logger.debug(
                    "chat_context_chunk idx=%d chunk_id=%s citation=%s "
                    "score=%s url=%s title=%s chunk_text_300=%r",
                    idx,
                    src.get("chunk_id", ""),
                    src.get("citation", ""),
                    src.get("score", ""),
                    item.url,
                    item.title,
                    item.text[:300],
                )
        try:
            t_history = time.perf_counter()
            async with chat_stage("retrieval.history"):
                history = await history_task
            history_ms = (time.perf_counter() - t_history) * 1000.0
        except Exception as exc:
            logger.exception("conversation memory load failed (session=%s)", session.session_id)
            yield _error_event(_error_code(exc), _safe_message(exc))
            return

        yield {"event": "sources", "data": {"sources": sources}}

        t_prompt = time.perf_counter()
        system_prompt = get_system_prompt(self._prompt_version)
        user_prompt = build_user_prompt(
            question=question,
            context=context_items,
            history=history,
            max_chars_per_chunk=self._max_chars_per_chunk,
        )
        prompt_construction_ms = (time.perf_counter() - t_prompt) * 1000.0
        context_chars = sum(len(item.text) for item in context_items)
        logger.info(
            "chat_prompt tenant=%s website=%s prompt_version=%s context_items=%s "
            "context_chars=%s system_chars=%s user_chars=%s",
            tenant_id,
            website_id,
            self._prompt_version,
            len(context_items),
            context_chars,
            len(system_prompt),
            len(user_prompt),
        )
        logger.debug(
            "chat_prompt_full tenant=%s website=%s system_chars=%d user_hash=%s user_length=%d",
            tenant_id,
            website_id,
            len(system_prompt),
            content_hash(user_prompt),
            len(user_prompt),
        )

        estimated_prompt_tokens = (len(system_prompt) + len(user_prompt)) // 4
        logger.info(
            "chat_prompt_size tenant=%s website=%s context_chars=%d "
            "system_chars=%d user_chars=%d estimated_tokens=%d",
            tenant_id,
            website_id,
            context_chars,
            len(system_prompt),
            len(user_prompt),
            estimated_prompt_tokens,
        )

        deltas: list[str] = []
        ttft_ms: float | None = None
        provider_name: str | None = None
        generation_consumed_ms: float = 0.0
        delta_overhead_ms: float = 0.0
        delta_count: int = 0
        try:
            t2 = time.perf_counter()
            async with chat_stage("generation.stream"):
                async for delta in self._generation.stream_generate(
                    system=system_prompt,
                    messages=[(CHAT_ROLE_USER, user_prompt)],
                ):
                    if ttft_ms is None:
                        ttft_ms = (time.perf_counter() - t2) * 1000.0
                        if hasattr(self._generation, "active_provider"):
                            provider_name = self._generation.active_provider
                    t_delta_overhead = time.perf_counter()
                    deltas.append(delta)
                    yield {"event": "message", "data": {"delta": delta}}
                    delta_overhead_ms += (time.perf_counter() - t_delta_overhead) * 1000.0
                    delta_count += 1
            generation_ms = (time.perf_counter() - t2) * 1000.0
            generation_consumed_ms = generation_ms
            if hasattr(self._generation, "active_provider"):
                provider_name = self._generation.active_provider
            elif hasattr(self._generation, "name"):
                provider_name = self._generation.name
        except Exception as exc:
            await self._stop_history_task(history_task)
            logger.exception("answer generation failed (session=%s)", session.session_id)
            yield _error_event(_error_code(exc), _safe_message(exc))
            record_chat_failure(reason="generation_error")
            record_llm_failure(code=_error_code(exc))
            return

        answer = "".join(deltas)
        # Blank-generation guard: a provider can close the stream without
        # emitting anything (no exception). Persisting an empty assistant
        # turn and reporting success would leave the widget with nothing to
        # render, so substitute the canonical fallback instead.
        substituted_fallback = False
        if not answer.strip():
            logger.warning(
                "rag_empty_generation tenant=%s website=%s session=%s delta_count=%d",
                tenant_id,
                website_id,
                session.session_id,
                delta_count,
            )
            answer = UNKNOWN_ANSWER_FALLBACK
            substituted_fallback = True
            yield {"event": "message", "data": {"delta": answer}}
            record_chat_failure(reason="empty_generation")
        # Citation validation (audit fix): the model may emit [N] markers that
        # reference no retrieved source. Strip the invalid ones so the
        # persisted answer and conversation history never carry an
        # unverifiable citation; valid markers and formatting are untouched.
        if not substituted_fallback:
            answer, removed_citations = _strip_invalid_citations(answer, len(sources))
            if removed_citations:
                logger.info(
                    "rag_invalid_citations_removed tenant=%s website=%s session=%s "
                    "removed=%s source_count=%d",
                    tenant_id,
                    website_id,
                    session.session_id,
                    removed_citations,
                    len(sources),
                )
        output_issues = validate_response(answer)
        if output_issues:
            logger.warning(
                "prompt_guard output_issue issues=%s tenant=%s website=%s session=%s",
                output_issues,
                tenant_id,
                website_id,
                session.session_id,
            )
        # Faithfulness check: verify answer is grounded in retrieved context.
        faithfulness_score: float | None = None
        if (
            self._enable_faithfulness_check
            and context_items
            and answer
            and not substituted_fallback
        ):
            faithfulness_score = _check_faithfulness(answer, context_items)
            if faithfulness_score < self._faithfulness_warning_threshold:
                logger.warning(
                    "faithfulness_low score=%.2f threshold=%.2f tenant=%s website=%s session=%s",
                    faithfulness_score,
                    self._faithfulness_warning_threshold,
                    tenant_id,
                    website_id,
                    session.session_id,
                )
        response_time = time.monotonic() - started
        usage = self._generation.usage

        # AI cost estimate (Phase 1 cost tracking). Computed from the serving
        # model's reported token counts and the configured rate card; models
        # without a rate accrue zero cost and warn once. Failed generations
        # never reach this line, so errors stay non-billable by construction.
        model_name = _generation_model_name(self._generation)
        price = get_model_price(self._rate_card, model_name) if model_name else None
        if price is None and model_name:
            if model_name not in self._warned_unpriced_models:
                self._warned_unpriced_models.add(model_name)
                logger.warning(
                    "cost_unpriced_model model=%s tenant=%s website=%s",
                    model_name,
                    tenant_id,
                    website_id,
                )
        estimated_cost = (
            estimate_generation_cost(
                price,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )
            if price is not None
            else 0.0
        )

        assistant = ChatMessage.new(
            tenant_id=tenant_id,
            website_id=website_id,
            session_id=session.session_id,
            role=CHAT_ROLE_ASSISTANT,
            content=answer,
        )
        assistant.sources = sources
        assistant.response_time = response_time
        assistant.input_tokens = usage.input_tokens
        assistant.output_tokens = usage.output_tokens
        assistant.total_tokens = usage.input_tokens + usage.output_tokens
        assistant.estimated_cost = round(estimated_cost, 6)
        assistant.model_name = model_name
        # Persist the per-stage latency breakdown for the performance
        # dashboard (Phase 12.6). Durations only - never content or secrets.
        assistant.latency_embedding_ms = _round_ms(embedding_ms)
        assistant.latency_retrieval_ms = _round_ms(retrieval_ms)
        record_rag_latency(retrieval_ms / 1000.0)
        assistant.latency_context_ms = _round_ms(context_ms)
        assistant.latency_history_ms = _round_ms(history_ms)
        assistant.latency_generation_ms = _round_ms(generation_ms)
        assistant.latency_ttft_ms = _round_ms(ttft_ms)
        assistant.latency_website_lookup_ms = _round_ms(website_lookup_ms)
        assistant.latency_session_resolution_ms = _round_ms(session_resolution_ms)
        assistant.latency_user_message_persist_ms = _round_ms(user_message_persist_ms)
        assistant.latency_prompt_construction_ms = _round_ms(prompt_construction_ms)
        assistant.latency_load_chunks_ms = _round_ms(load_chunks_ms)
        assistant.latency_rerank_ms = _round_ms(rerank_ms)
        assistant.latency_rerank_embedding_ms = _round_ms(rerank_embedding_ms)
        assistant.latency_generation_consumed_ms = _round_ms(generation_consumed_ms)
        assistant.latency_total_ms = round(response_time * 1000.0, 2)
        t_persist = time.perf_counter()
        async with chat_stage("persist.messages"):
            await self._messages.create(assistant)
        await asyncio.gather(
            self._sessions.touch(session.session_id),
            self._usage.increment(
                tenant_id=tenant_id,
                website_id=website_id,
                date=usage_date_key(),
                counters={
                    "chats": 1,
                    "messages": 2,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "estimated_cost_micros": dollars_to_micros(estimated_cost),
                    "vector_queries": 1,
                },
            ),
            return_exceptions=True,
        )
        persist_ms = (time.perf_counter() - t_persist) * 1000.0
        assistant.latency_persist_ms = _round_ms(persist_ms)
        total_ms = (time.perf_counter() - perf_started) * 1000.0

        fallback_attempts = 0
        if hasattr(self._generation, "last_latency_metrics"):
            metrics = self._generation.last_latency_metrics
            if metrics is not None:
                fallback_attempts = metrics.fallback_attempts

        done_data = self._build_done_data(
            assistant=assistant,
            session=session,
            usage=usage,
            model_name=model_name,
            response_time=response_time,
            substituted_fallback=substituted_fallback,
            confidence_score=confidence_score,
            confidence_metrics=confidence_metrics,
            answerability_metrics=answerability_metrics,
            faithfulness_score=faithfulness_score,
        )
        if self._timing_enabled:
            done_data["timing"] = {
                "embedding_ms": round(embedding_ms, 2),
                "retrieval_ms": round(retrieval_ms, 2),
                "load_chunks_ms": round(load_chunks_ms, 2),
                "context_ms": round(context_ms, 2),
                "history_ms": round(history_ms, 2),
                "generation_ms": round(generation_ms, 2),
                "generation_consumed_ms": round(generation_consumed_ms, 2),
                "delta_overhead_ms": round(delta_overhead_ms, 2),
                "delta_count": delta_count,
                "ttft_ms": round(ttft_ms, 2) if ttft_ms is not None else None,
                "persist_ms": round(persist_ms, 2),
                "website_lookup_ms": round(website_lookup_ms, 2),
                "session_resolution_ms": round(session_resolution_ms, 2),
                "user_message_persist_ms": round(user_message_persist_ms, 2),
                "prompt_construction_ms": round(prompt_construction_ms, 2),
                "rerank_ms": round(rerank_ms, 2),
                "rerank_embedding_ms": round(rerank_embedding_ms, 2),
                "rerank_input_count": rerank_input_count,
                "total_ms": round(total_ms, 2),
                "provider": provider_name,
                "model_name": model_name,
                "estimated_cost": assistant.estimated_cost,
                "embedding_cache": "hit" if embedding_cache_hit else "miss",
                "retrieval_cache": "hit" if retrieval_cache_hit else "miss",
                "context_chars": context_chars,
                "estimated_prompt_tokens": estimated_prompt_tokens,
                "fallback_attempts": fallback_attempts,
                # Hybrid retrieval metrics (always present; "vector" when
                # hybrid search is disabled).
                "retrieval_method": retrieval_metrics.retrieval_method,
                "vector_result_count": retrieval_metrics.vector_result_count,
                "keyword_result_count": retrieval_metrics.keyword_result_count,
                "final_result_count": retrieval_metrics.final_result_count,
                "reranked": self._reranker is not None,
                "faithfulness_score": (
                    round(faithfulness_score, 3) if faithfulness_score is not None else None
                ),
                "hybrid_candidate_count": hybrid_candidate_count,
                "adaptive_max_context_chars": adaptive_max_context_chars,
                "confidence_score": (
                    round(confidence_score, 4) if confidence_score is not None else None
                ),
                "confidence_minimum_score": (
                    confidence_metrics.minimum_score if confidence_metrics is not None else None
                ),
                "confidence_average_score": (
                    confidence_metrics.average_score if confidence_metrics is not None else None
                ),
                "confidence_rejected_chunks_count": (
                    confidence_metrics.rejected_chunks_count
                    if confidence_metrics is not None
                    else None
                ),
                "original_context_chars": (
                    opt_metrics.original_chars if opt_metrics is not None else None
                ),
                "optimized_context_chars": (
                    opt_metrics.optimized_chars if opt_metrics is not None else None
                ),
                "removed_chunks_count": (
                    opt_metrics.removed_chunks if opt_metrics is not None else None
                ),
            }
            self._log_rag_timing(
                tenant_id=tenant_id,
                website_id=website_id,
                session=session,
                embedding_ms=embedding_ms,
                retrieval_ms=retrieval_ms,
                load_chunks_ms=load_chunks_ms,
                context_ms=context_ms,
                history_ms=history_ms,
                generation_ms=generation_ms,
                generation_consumed_ms=generation_consumed_ms,
                delta_overhead_ms=delta_overhead_ms,
                delta_count=delta_count,
                ttft_ms=ttft_ms,
                persist_ms=persist_ms,
                website_lookup_ms=website_lookup_ms,
                session_resolution_ms=session_resolution_ms,
                user_message_persist_ms=user_message_persist_ms,
                prompt_construction_ms=prompt_construction_ms,
                rerank_ms=rerank_ms,
                rerank_embedding_ms=rerank_embedding_ms,
                rerank_input_count=rerank_input_count,
                total_ms=total_ms,
                provider_name=provider_name,
                model_name=model_name,
                estimated_cost=assistant.estimated_cost,
                embedding_cache_hit=embedding_cache_hit,
                retrieval_cache_hit=retrieval_cache_hit,
                context_chars=context_chars,
                estimated_prompt_tokens=estimated_prompt_tokens,
                fallback_attempts=fallback_attempts,
                retrieval_metrics=retrieval_metrics,
                hybrid_candidate_count=hybrid_candidate_count,
                adaptive_max_context_chars=adaptive_max_context_chars,
                confidence_score=confidence_score,
                confidence_metrics=confidence_metrics,
                opt_metrics=opt_metrics,
                faithfulness_score=faithfulness_score,
            )
        yield {"event": "done", "data": done_data}

        # Record Prometheus metrics for the completed turn.
        record_chat_latency(time.monotonic() - started)
        # Per-stage RAG pipeline latency (baseline instrumentation) — feeds
        # the percentile histograms. Durations only, never content.
        cache_status = "hit" if embedding_cache_hit else "miss"
        record_rag_stage_latency("embedding", embedding_ms / 1000.0, cache_status=cache_status)
        cache_status = "hit" if retrieval_cache_hit else "miss"
        record_rag_stage_latency("vector_search", retrieval_ms / 1000.0, cache_status=cache_status)
        record_rag_stage_latency("load_chunks", load_chunks_ms / 1000.0)
        record_rag_stage_latency("rerank", rerank_ms / 1000.0)
        record_rag_stage_latency("context", context_ms / 1000.0)
        record_rag_stage_latency("history", history_ms / 1000.0)
        record_rag_stage_latency("generation", generation_ms / 1000.0)
        record_rag_stage_latency("persist", persist_ms / 1000.0)
        record_rag_stage_latency("total", total_ms / 1000.0)
        if provider_name:
            record_llm_request(provider=provider_name)
            record_llm_latency(provider=provider_name, duration_seconds=generation_ms / 1000.0)
            # Cost observability: feed the serving provider's token counts into
            # the `llm_tokens_used` metric so spend is trackable per kind.
            record_llm_tokens(kind="input", count=usage.input_tokens)
            record_llm_tokens(kind="output", count=usage.output_tokens)
            # Per-tenant AI quota accounting (Phase 14.9.4): best-effort
            # increment of the running daily/monthly token totals so the
            # pre-call `check()` enforces budgets across turns.
            try:
                await LLMQuotaService().record(tenant_id, usage.input_tokens, usage.output_tokens)
            except Exception:  # pragma: no cover - best effort
                logger.warning("llm_quota_record_failed tenant=%s", tenant_id)

    async def _ensure_session(
        self,
        *,
        tenant_id: str,
        website_id: str,
        session_id: str | None,
        visitor_id: str | None,
        user_id: str | None,
    ) -> ChatSession:
        """Reuse the tenant's session, or create a new one when absent."""
        if session_id is None:
            session = ChatSession.new(
                tenant_id=tenant_id,
                website_id=website_id,
                session_id=new_id(),
                visitor_id=visitor_id,
                user_id=user_id,
            )
            await self._sessions.create(session)
            return session
        existing = await self._sessions.find_by_session_id(tenant_id, session_id)
        if existing is None or existing.website_id != website_id:
            # Unknown session, or a session bound to a different website:
            # never resume a session that does not belong to this tenant+website.
            raise SessionNotFoundError("Chat session not found.")
        return existing

    async def _load_history(
        self,
        tenant_id: str,
        session_id: str,
        *,
        exclude_message_id: str | None = None,
    ) -> list[tuple[str, str]]:
        """Recent turns (oldest first), excluding the current user message.

        The current turn is persisted before retrieval so failures still
        leave a complete log; excluding it here keeps the prompt free of a
        duplicated question and preserves the full `memory_turns` window for
        genuinely prior context.
        """
        limit = self._memory_turns + 1 if exclude_message_id else self._memory_turns
        recent = await self._messages.list_recent(tenant_id, session_id, limit=limit)
        if exclude_message_id:
            recent = [message for message in recent if message.id != exclude_message_id]
            recent = recent[-self._memory_turns :]
        return [(message.role, message.content) for message in recent]

    async def _load_all_chunks(
        self,
        tenant_id: str,
        website_id: str,
        *,
        embedding_identity: EmbeddingIdentity | None = None,
        corpus_version: str = "",
    ) -> list[VectorSearchResult]:
        """Load the deterministic, embedding-free lexical corpus for one site.

        Keyword retrieval must search the complete tenant/website corpus: a
        ``limit`` here would silently turn it into a natural-order slice and
        make exact entities unrecoverable.  On a cold cache this performs one
        Mongo projection excluding ``embedding``; subsequent requests use a
        compact Redis value containing only text/metadata chunk records.

        The cache key includes tenant, website, corpus version and embedding
        identity.  Knowledge processing both changes the website version and
        explicitly invalidates this namespace, so an old corpus cannot be
        reused after a completed update.  The cached representation is still
        sufficient for RRF, source diversity, lexical protection, hydration,
        citations and context construction; reranking fetches embeddings only
        for its small candidate subset.
        """
        identity_key = "unlocked"
        if embedding_identity is not None:
            identity_key = ":".join(
                (
                    embedding_identity.provider,
                    embedding_identity.model,
                    str(embedding_identity.dimensions),
                    embedding_identity.version,
                )
            )
        key = f"{tenant_id}:{website_id}:{corpus_version or 'unknown'}:{identity_key}"
        cache_enabled = (
            self._cache is not None
            and self._retrieval_cache_size > 0
            and self._retrieval_cache_ttl > 0
        )
        if cache_enabled:
            assert self._cache is not None
            try:
                raw = await self._cache.get("lexical", key)
            except Exception:  # cache is an optimization, never a retrieval dependency
                logger.warning(
                    "lexical_corpus_cache_get_failed tenant=%s website=%s",
                    tenant_id,
                    website_id,
                    exc_info=True,
                )
                raw = None
            if raw is not None:
                # RAG-PERF-03 (F-01): deserializing the corpus (json.loads +
                # KnowledgeChunk construction + VectorSearchResult wrapping) is
                # CPU-bound and was running on the asyncio event loop. Offload
                # it to a worker thread; the Redis read above stays async I/O.
                # Exception types are preserved by `_parse_lexical_corpus`, so
                # a malformed cache value still degrades to the DB path below
                # (same logging, same semantics).
                try:
                    return await asyncio.to_thread(_parse_lexical_corpus, raw)
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    logger.warning(
                        "lexical_corpus_cache_invalid tenant=%s website=%s", tenant_id, website_id
                    )

        # `limit=0` deliberately means the whole scoped corpus.  The repository
        # projection excludes vectors, and Mongo orders records by `_id`, so the
        # lexical input is deterministic without transferring embeddings.
        chunks = await self._vector.list_chunks_light(tenant_id, website_id, limit=0)
        if cache_enabled:
            assert self._cache is not None
            payload = {
                "chunks": [chunk.model_dump(mode="json", exclude={"embedding"}) for chunk in chunks]
            }
            try:
                await self._cache.set(
                    "lexical", key, json.dumps(payload), ttl=self._retrieval_cache_ttl
                )
            except Exception:
                logger.warning(
                    "lexical_corpus_cache_set_failed tenant=%s website=%s",
                    tenant_id,
                    website_id,
                    exc_info=True,
                )
        return [VectorSearchResult(chunk=chunk, score=0.5) for chunk in chunks]

    @staticmethod
    def _provider_name(embedder: Any) -> str:
        """Best-effort provider label for observability (never fails)."""
        return (
            getattr(embedder, "active_provider", None)
            or getattr(embedder, "name", None)
            or type(embedder).__name__
        )

    def _build_context(
        self,
        results: list[VectorSearchResult],
        *,
        max_context_chars: int | None = None,
        query: str | None = None,
    ) -> tuple[
        list[ContextItem],
        list[dict[str, Any]],
        OptimizationMetrics | None,
    ]:
        """Deduplicate hits, optionally optimize, and cap total size.

        When ``enable_context_optimization`` is disabled (default), this
        method behaves identically to the legacy path: exact dedup + budget
        capping.  When enabled, an additional near-duplicate removal and
        sentence-level compression step runs between dedup and budget capping,
        reducing token usage while preserving unique information.
        """
        # `chat_context_max_chars <= 0` means "no total budget" (disabled).
        effective_max = (
            max_context_chars
            if max_context_chars is not None and max_context_chars > 0
            else self._max_context_chars
        )

        # ------------------------------------------------------------------
        # Phase 1: Exact dedup + min-score filter (always runs).
        # Collect candidate items before applying the budget so optimization
        # can operate on the full candidate set.
        #
        # The gate is score-type-aware. `min_score` is a cosine calibration, so
        # it only governs candidates whose evidence IS vector cosine. A chunk
        # that survives reranking as a genuine strong lexical match and carries
        # explicit RRF/keyword evidence (`lexical_score` set by the hybrid pass
        # and preserved through the reranker) is accepted on that lexical
        # evidence even when its cosine falls below the cosine threshold.
        candidate_items: list[ContextItem] = []
        candidate_sources: list[dict[str, Any]] = []
        seen_text: set[tuple[str, str]] = set()

        for result in results:
            if not usable(result, dense_floor=self._min_score, query=query):
                # Dense and RRF scores have different scales. Only an
                # explicit dense score or reranker-confirmed exact lexical
                # evidence can admit a chunk below the dense floor.
                if self._min_score > 0:
                    continue
            chunk = result.chunk
            url = str(chunk.metadata.get("source_url") or "")
            title = str(chunk.metadata.get("title") or url or "Untitled")
            text_key = (url, chunk.chunk_text)
            if text_key in seen_text:
                continue
            seen_text.add(text_key)
            text = chunk.chunk_text
            if len(text) > self._max_chars_per_chunk:
                # RAG-06: cut at the last word boundary so the final chunk in
                # context never ends mid-word with a garbled tail.
                text = truncate_at_word_boundary(text, self._max_chars_per_chunk)
            candidate_items.append(
                ContextItem(
                    url=url,
                    title=title,
                    # Audit R-08: the chunk's nearest heading (stored in
                    # metadata at processing time) feeds the prompt's existing
                    # heading slot instead of being dropped.
                    heading=chunk.metadata.get("heading") or None,
                    text=text,
                )
            )
            candidate_sources.append(
                {
                    "chunk_id": chunk.id,
                    "url": url,
                    "title": title,
                    "score": result.score,
                }
            )

        # ------------------------------------------------------------------
        # Phase 2: Context optimization (opt-in).
        # ------------------------------------------------------------------
        opt_metrics: OptimizationMetrics | None = None
        if self._context_optimization_enabled and candidate_items:
            original_chars = sum(len(item.text) for item in candidate_items)
            original_count = len(candidate_items)

            # 2a. Near-duplicate removal.
            chunk_texts = [item.text for item in candidate_items]
            keep_indices = remove_near_duplicates(chunk_texts, threshold=0.75)
            deduped_items = [candidate_items[i] for i in keep_indices]
            deduped_sources = [candidate_sources[i] for i in keep_indices]
            removed_chunks = original_count - len(deduped_items)

            # 2b. Sentence-level compression.
            seen_sentences: set[str] = set()
            total_removed_sentences = 0
            compressed_items: list[ContextItem] = []
            for item in deduped_items:
                compressed, removed = compress_text(item.text, seen_sentences=seen_sentences)
                compressed_items.append(
                    ContextItem(
                        url=item.url,
                        title=item.title,
                        heading=item.heading,
                        text=compressed,
                    )
                )
                total_removed_sentences += removed
            optimized_chars = sum(len(ci.text) for ci in compressed_items)
            candidate_items = compressed_items
            candidate_sources = deduped_sources
            opt_metrics = OptimizationMetrics(
                original_chars=original_chars,
                optimized_chars=optimized_chars,
                removed_chunks=removed_chunks,
                removed_sentences=total_removed_sentences,
            )

        # ------------------------------------------------------------------
        # Phase 3: Budget capping (always runs).
        # ------------------------------------------------------------------
        budget = effective_max if effective_max > 0 else None
        items: list[ContextItem] = []
        sources: list[dict[str, Any]] = []
        for item, src in zip(candidate_items, candidate_sources, strict=True):
            text = item.text
            if budget is not None and budget >= 0:
                if len(text) > budget:
                    # RAG-06: avoid cutting the final word in half; the total
                    # character budget (per item) is still honored.
                    text = truncate_at_word_boundary(text, budget)
                    budget = 0
                else:
                    budget -= len(text)
            # Preserve the chunk's heading through budget capping (audit R-08).
            items.append(
                ContextItem(url=item.url, title=item.title, heading=item.heading, text=text)
            )
            sources.append({**src, "citation": len(sources) + 1})
            if budget == 0:
                break

        return items, sources, opt_metrics

    async def _emit_fallback(
        self,
        *,
        tenant_id: str,
        website_id: str,
        session: ChatSession,
        started: float,
        vector_queries: int,
        reason: str,
        query: str,
        scores: list[float] | None = None,
        confidence_metrics: ConfidenceMetrics | None = None,
    ) -> AsyncGenerator[dict[str, Any]]:
        """Emit the no-context fallback without ever calling the model."""
        logger.warning(
            "rag_retrieval_zero_context tenant=%s website=%s session=%s reason=%s "
            "vector_queries=%s top_k=%s scores=%s query_hash=%s query_length=%d",
            tenant_id,
            website_id,
            session.session_id,
            reason,
            vector_queries,
            self._top_k,
            scores or [],
            content_hash(query),
            len(query),
        )
        response_time = time.monotonic() - started
        assistant = ChatMessage.new(
            tenant_id=tenant_id,
            website_id=website_id,
            session_id=session.session_id,
            role=CHAT_ROLE_ASSISTANT,
            content=UNKNOWN_ANSWER_FALLBACK,
        )
        assistant.response_time = response_time
        async with chat_stage("persist.messages"):
            await self._messages.create(assistant)
        await asyncio.gather(
            self._sessions.touch(session.session_id),
            self._usage.increment(
                tenant_id=tenant_id,
                website_id=website_id,
                date=usage_date_key(),
                counters={"chats": 1, "messages": 2, "vector_queries": vector_queries},
            ),
        )
        yield {"event": "sources", "data": {"sources": []}}
        yield {"event": "message", "data": {"delta": UNKNOWN_ANSWER_FALLBACK}}
        yield {
            "event": "done",
            "data": self._build_done_data(
                assistant=assistant,
                session=session,
                usage=GenerationUsage(),
                model_name="",
                response_time=response_time,
                substituted_fallback=True,
                confidence_score=(
                    confidence_metrics.confidence if confidence_metrics is not None else None
                ),
                confidence_metrics=confidence_metrics,
                answerability_metrics=None,
                faithfulness_score=None,
            ),
        }

    def _build_done_data(
        self,
        *,
        assistant: ChatMessage,
        session: ChatSession,
        usage: Any,
        model_name: str,
        response_time: float,
        substituted_fallback: bool,
        confidence_score: float | None,
        confidence_metrics: ConfidenceMetrics | None,
        answerability_metrics: AnswerabilityMetrics | None,
        faithfulness_score: float | None,
    ) -> dict[str, Any]:
        """Build the terminal ``done`` SSE payload (BE-Q09 pipeline stage)."""
        done_data: dict[str, Any] = {
            "message_id": assistant.id,
            "session_id": session.session_id,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": assistant.total_tokens,
            "estimated_cost": assistant.estimated_cost,
            "model_name": model_name,
            "response_time_ms": int(response_time * 1000),
            "created_at": assistant.created_at.isoformat(),
            "prompt_version": self._prompt_version,
            # True when the safe fallback replaced the answer (empty
            # knowledge base, retrieval miss, low confidence, or a blank
            # generation).
            "fallback": substituted_fallback,
            # Confidence telemetry is always emitted (mirrors the fallback
            # path); the timing block below duplicates it for perf logs.
            "confidence_score": (
                round(confidence_score, 4) if confidence_score is not None else None
            ),
            "confidence_minimum_score": (
                confidence_metrics.minimum_score if confidence_metrics is not None else None
            ),
            "confidence_average_score": (
                confidence_metrics.average_score if confidence_metrics is not None else None
            ),
            "confidence_rejected_chunks_count": (
                confidence_metrics.rejected_chunks_count if confidence_metrics is not None else None
            ),
            "answerability_score": (
                round(answerability_metrics.answerability, 4)
                if answerability_metrics is not None
                else None
            ),
            "answerability_lexical_coverage": (
                round(answerability_metrics.lexical_coverage, 4)
                if answerability_metrics is not None
                else None
            ),
            "answerability_query_type": (
                answerability_metrics.query_type.value
                if answerability_metrics is not None
                else None
            ),
            "answerability_reason": (
                answerability_metrics.reason if answerability_metrics is not None else None
            ),
        }
        if faithfulness_score is not None:
            done_data["faithfulness_score"] = round(faithfulness_score, 3)
        return done_data

    def _log_rag_timing(
        self,
        *,
        tenant_id: str,
        website_id: str,
        session: ChatSession,
        embedding_ms: float,
        retrieval_ms: float,
        load_chunks_ms: float,
        context_ms: float,
        history_ms: float,
        generation_ms: float,
        generation_consumed_ms: float,
        delta_overhead_ms: float,
        delta_count: int,
        ttft_ms: float | None,
        persist_ms: float,
        website_lookup_ms: float,
        session_resolution_ms: float,
        user_message_persist_ms: float,
        prompt_construction_ms: float,
        rerank_ms: float,
        rerank_embedding_ms: float,
        rerank_input_count: int,
        total_ms: float,
        provider_name: str | None,
        model_name: str,
        estimated_cost: float,
        embedding_cache_hit: bool,
        retrieval_cache_hit: bool,
        context_chars: int,
        estimated_prompt_tokens: int,
        fallback_attempts: int,
        retrieval_metrics: RetrievalMetricsInfo,
        hybrid_candidate_count: int,
        adaptive_max_context_chars: int,
        confidence_score: float | None,
        confidence_metrics: ConfidenceMetrics | None,
        opt_metrics: OptimizationMetrics | None,
        faithfulness_score: float | None,
    ) -> None:
        """Emit the opt-in per-stage RAG performance log (BE-Q09 pipeline stage)."""
        logger.info(
            "rag_timing",
            extra={
                "request_id": get_request_id(),
                "tenant_id": tenant_id,
                "website_id": website_id,
                "session_id": session.session_id,
                "provider": provider_name,
                "embedding_cache": "hit" if embedding_cache_hit else "miss",
                "retrieval_cache": "hit" if retrieval_cache_hit else "miss",
                "embedding_ms": round(embedding_ms, 2),
                "retrieval_ms": round(retrieval_ms, 2),
                "load_chunks_ms": round(load_chunks_ms, 2),
                "context_ms": round(context_ms, 2),
                "history_ms": round(history_ms, 2),
                "generation_ms": round(generation_ms, 2),
                "generation_consumed_ms": round(generation_consumed_ms, 2),
                "delta_overhead_ms": round(delta_overhead_ms, 2),
                "delta_count": delta_count,
                "ttft_ms": round(ttft_ms, 2) if ttft_ms is not None else None,
                "persist_ms": round(persist_ms, 2),
                "website_lookup_ms": round(website_lookup_ms, 2),
                "session_resolution_ms": round(session_resolution_ms, 2),
                "user_message_persist_ms": round(user_message_persist_ms, 2),
                "prompt_construction_ms": round(prompt_construction_ms, 2),
                "rerank_ms": round(rerank_ms, 2),
                "rerank_embedding_ms": round(rerank_embedding_ms, 2),
                "rerank_input_count": rerank_input_count,
                "total_ms": round(total_ms, 2),
                "context_chars": context_chars,
                "estimated_prompt_tokens": estimated_prompt_tokens,
                "fallback_attempts": fallback_attempts,
                "retrieval_method": retrieval_metrics.retrieval_method,
                "vector_result_count": retrieval_metrics.vector_result_count,
                "keyword_result_count": retrieval_metrics.keyword_result_count,
                "final_result_count": retrieval_metrics.final_result_count,
                "reranked": self._reranker is not None,
                "hybrid_candidate_count": hybrid_candidate_count,
                "adaptive_max_context_chars": adaptive_max_context_chars,
                "confidence_score": (
                    round(confidence_score, 4) if confidence_score is not None else None
                ),
                "confidence_minimum_score": (
                    confidence_metrics.minimum_score if confidence_metrics is not None else None
                ),
                "confidence_average_score": (
                    confidence_metrics.average_score if confidence_metrics is not None else None
                ),
                "confidence_rejected_chunks_count": (
                    confidence_metrics.rejected_chunks_count
                    if confidence_metrics is not None
                    else None
                ),
                "original_context_chars": (
                    opt_metrics.original_chars if opt_metrics is not None else None
                ),
                "optimized_context_chars": (
                    opt_metrics.optimized_chars if opt_metrics is not None else None
                ),
                "removed_chunks_count": (
                    opt_metrics.removed_chunks if opt_metrics is not None else None
                ),
                "faithfulness_score": (
                    round(faithfulness_score, 3) if faithfulness_score is not None else None
                ),
            },
        )


def _safe_message(exc: Exception) -> str:
    """Never leak internal error details into the client stream."""
    if isinstance(exc, AppError):
        return exc.message
    return "An unexpected error occurred. Please try again later."


def _significant_words(text: str) -> set[str]:
    """Normalized significant tokens: alphanumeric runs longer than 3 chars.

    Stripping non-alphanumeric characters (instead of dropping tokens that
    contain them) keeps numeric and currency-bearing words — "$19", "99.9%",
    "200ms" — eligible as grounding evidence.  The previous alpha-only rule
    silently discarded them, systematically under-scoring pricing and
    metric-heavy answers.
    """
    words: set[str] = set()
    for token in text.lower().split():
        normalized = "".join(char for char in token if char.isalnum())
        if len(normalized) > 3:
            words.add(normalized)
    return words


def _check_faithfulness(answer: str, context_items: list["ContextItem"]) -> float:
    """Score answer faithfulness by checking if each sentence is grounded in context.

    Returns a value between 0.0 (no support) and 1.0 (fully grounded).
    Each sentence in the answer is checked for significant word overlap
    (>3 alphanumeric characters) with the context chunks.  Sentences with
    no significant words (trivial fragments) are counted as *unsupported*
    since they contribute no verifiable content.  An empty answer is
    scored 0.0 because there is nothing to be faithful *to*.
    """
    import re

    sentences = [s.strip() for s in re.split(r"[.!?]+", answer) if s.strip() and len(s.strip()) > 5]
    if not sentences:
        return 0.0

    context_lower = " ".join(item.text.lower() for item in context_items)
    context_words = _significant_words(context_lower)

    supported = 0
    for sentence in sentences:
        words = _significant_words(sentence)
        if not words:
            continue
        overlap = words & context_words
        if len(overlap) >= max(1, len(words) // 3):
            supported += 1

    return round(supported / len(sentences), 3)


# Citation markers are bracketed 1-2 digit indexes ("[1]", "[12]"). The digit
# bound keeps years in brackets ("[2024]") and markdown footnote-style text
# out of the matcher; sources never number past a few dozen.
_CITATION_MARKER_RE = re.compile(r"\[(\d{1,2})\]")


def _strip_invalid_citations(answer: str, source_count: int) -> tuple[str, list[int]]:
    """Drop ``[N]`` citation markers that reference no retrieved source.

    Audit fix (citation validation): the model is instructed to cite
    ``[1]..[n]``, but it can hallucinate an index beyond the rendered source
    list. Invalid markers are removed so the persisted answer and future
    conversation history never present an unverifiable citation; valid
    markers and all other formatting pass through untouched.

    Returns ``(sanitized_answer, removed_indexes)``.
    """
    if source_count <= 0:
        return _CITATION_MARKER_RE.sub("", answer), []

    removed: list[int] = []

    def _replace(match: re.Match[str]) -> str:
        index = int(match.group(1))
        if 1 <= index <= source_count:
            return match.group(0)
        removed.append(index)
        return ""

    return _CITATION_MARKER_RE.sub(_replace, answer), removed


__all__ = ["RagService"]
