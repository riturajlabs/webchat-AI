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
import json
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any

from backend.ai.gemini import GenerationClient
from backend.core.cache import CacheStore
from backend.core.config import get_settings
from backend.core.errors import AppError, SessionNotFoundError
from backend.core.logging import get_request_id
from backend.core.privacy import content_hash
from backend.core.prompt_guard import validate_response
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
from backend.repositories.vector.reranker import EmbeddingReranker
from backend.repositories.website_repository import WebsiteRepository
from backend.services.chat.confidence import ConfidenceMetrics, assess_confidence
from backend.services.chat.context_optimizer import (
    OptimizationMetrics,
    compress_text,
    remove_near_duplicates,
)
from backend.services.chat.query_classifier import QueryComplexity, classify_query
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
from backend.workers.timing import chat_stage

logger = logging.getLogger("webchat_ai")


def _error_event(code: str, message: str) -> dict[str, Any]:
    return {"event": "error", "data": {"code": code, "message": message}}


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
        self._generation = generation
        self._sessions = sessions
        self._messages = messages
        self._usage = usage
        self._cache = cache
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
        # Retrieval strategy: explicit override or config-driven default.
        if retrieval_strategy is not None:
            self._retrieval_strategy = retrieval_strategy
        elif settings.enable_hybrid_search:
            self._retrieval_strategy = HybridRetrievalStrategy(
                rrf_k=settings.hybrid_rrf_k,
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

    async def _embed_question(
        self, question: str
    ) -> tuple[list[float], bool, EmbeddingIdentity]:
        """Embed `question`, caching identical questions across turns.

        Returns `(vector, cache_hit, identity)` so callers can report hit/miss and the
        opt-in timing breakdown. The cache is a bounded per-process LRU keyed on
        the normalized (case-folded) question text; repeated/echoed questions hit
        the cache and skip the provider call. Eviction is size-only so entries
        never go stale.
        """
        key = question.strip().lower()
        if self._cache is not None and self._embedding_cache_size > 0:
            raw = await self._cache.get("embed", key)
            if raw is not None:
                try:
                    entry = json.loads(raw)
                    identity_data = entry["embedding_identity"]
                    identity = EmbeddingIdentity(
                        provider=identity_data["provider"],
                        model=identity_data["model"],
                        dimensions=identity_data["dimensions"],
                        version=identity_data["version"],
                    )
                    return entry["vector"], True, identity
                except (json.JSONDecodeError, TypeError):
                    pass
        vectors = await self._embedder.embed([question])
        vector = vectors[0]
        identity = self._embedder.embedding_identity
        if self._cache is not None and self._embedding_cache_size > 0:
            ttl = self._embedding_cache_ttl if self._embedding_cache_ttl > 0 else None
            await self._cache.set(
                "embed",
                key,
                json.dumps({"vector": vector, "embedding_identity": identity.as_dict()}),
                ttl=ttl,
            )
        return vector, False, identity

    async def _retrieve(
        self,
        *,
        tenant_id: str,
        website_id: str,
        question: str,
    ) -> tuple[
        list[float],
        list[VectorSearchResult],
        float,
        float,
        bool,
        bool,
        RetrievalMetricsInfo,
        float,
        float,
        float,
        int,
        int,
        int,
    ]:
        """Embed + search, memoizing repeats within the retrieval TTL.

        Returns `(query_vector, results, embedding_ms, retrieval_ms,
        embedding_cache_hit, retrieval_cache_hit, retrieval_metrics,
        load_chunks_ms, rerank_ms, rerank_embedding_ms,
        rerank_input_count, hybrid_candidate_count,
        adaptive_max_context_chars)`.
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
        cache = self._cache
        cache_key = f"{website_id}:{question.strip().lower()}"
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
                        vector = entry["vector"]
                        identity_data = entry["embedding_identity"]
                        query_identity = EmbeddingIdentity(
                            provider=identity_data["provider"],
                            model=identity_data["model"],
                            dimensions=identity_data["dimensions"],
                            version=identity_data["version"],
                        )
                        raw_results = [
                            VectorSearchResult(
                                chunk=KnowledgeChunk(**r["chunk"]),
                                score=r["score"],
                            )
                            for r in entry["results"]
                        ]
                        for raw_result in raw_results:
                            ensure_embedding_compatibility(raw_result.chunk, query_identity)
                        # Hybrid keyword matching reranks cached vector hits
                        # only; it must not load unrelated website chunks.
                        load_chunks_ms = 0.0
                        hybrid_candidate_count = len(raw_results) if isinstance(
                            self._retrieval_strategy, HybridRetrievalStrategy
                        ) else 0
                        all_chunks = None
                        results, metrics = self._retrieval_strategy.search(
                            query=question,
                            vector_results=raw_results,
                            all_chunks=all_chunks,
                            top_k=effective_top_k,
                        )
                        # Apply reranking to cached results too.
                        rerank_ms = 0.0
                        rerank_embedding_ms = 0.0
                        rerank_input_count = 0
                        if self._reranker is not None and results:
                            rerank_input_count = len(results)
                            results, rerank_metrics = await self._reranker.rerank(
                                question, results, query_embedding=vector
                            )
                            rerank_ms = rerank_metrics.rerank_ms
                            rerank_embedding_ms = rerank_metrics.rerank_embedding_ms
                        return (
                            vector,
                            results,
                            0.0,
                            0.0,
                            True,
                            True,
                            metrics,
                            load_chunks_ms,
                            rerank_ms,
                            rerank_embedding_ms,
                            rerank_input_count,
                            hybrid_candidate_count,
                            adaptive_max_context_chars,
                        )
                except (json.JSONDecodeError, TypeError, KeyError):
                    pass
        t0 = time.perf_counter()
        async with chat_stage("retrieval.embed"):
            query_vector, embedding_cache_hit, query_identity = await self._embed_question(question)
        embedding_ms = (time.perf_counter() - t0) * 1000.0
        t1 = time.perf_counter()
        async with chat_stage("retrieval.vector_search"):
            raw_results = await self._vector.similarity_search(
                tenant_id,
                website_id,
                query_vector,
                top_k=effective_top_k,
                embedding_identity=query_identity,
            )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "mongodb_vector_search_debug question=%r vector_result_count=%d",
                question,
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
        # Cache raw vector results (before strategy) so deserialization
        # always produces clean VectorSearchResult/KnowledgeChunk objects.
        if retrieval_enabled:
            assert cache is not None  # guaranteed by retrieval_enabled
            entry = {
                "vector": query_vector,
                "embedding_identity": query_identity.as_dict(),
                "results": [
                    {"chunk": r.chunk.model_dump(mode="json"), "score": r.score}
                    for r in raw_results
                ],
                "cached_at": _now(),
            }
            await cache.set(
                "retrieval", cache_key, json.dumps(entry), ttl=self._retrieval_cache_ttl
            )
        # Hybrid keyword matching reranks vector hits only; it must not load
        # or introduce unrelated chunks from the rest of the website.
        load_chunks_ms = 0.0
        hybrid_candidate_count = len(raw_results) if isinstance(
            self._retrieval_strategy, HybridRetrievalStrategy
        ) else 0
        all_chunks = None
        results, metrics = self._retrieval_strategy.search(
            query=question,
            vector_results=raw_results,
            all_chunks=all_chunks,
            top_k=effective_top_k,
        )
        # Apply reranking to improve ordering quality.
        rerank_ms = 0.0
        rerank_embedding_ms = 0.0
        rerank_input_count = 0
        if self._reranker is not None and results:
            rerank_input_count = len(results)
            results, rerank_metrics = await self._reranker.rerank(
                question, results, query_embedding=query_vector
            )
            rerank_ms = rerank_metrics.rerank_ms
            rerank_embedding_ms = rerank_metrics.rerank_embedding_ms
        return (
            query_vector,
            results,
            embedding_ms,
            retrieval_ms,
            embedding_cache_hit,
            False,
            metrics,
            load_chunks_ms,
            rerank_ms,
            rerank_embedding_ms,
            rerank_input_count,
            hybrid_candidate_count,
            adaptive_max_context_chars,
        )

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
        try:
            t_lookup = time.perf_counter()
            async with chat_stage("website.lookup"):
                website = await self._websites.find_by_id(tenant_id, website_id)
            website_lookup_ms = (time.perf_counter() - t_lookup) * 1000.0
            if website is None:
                yield _error_event("WEBSITE_NOT_FOUND", "Website not found.")
                return
            question = sanitize_question(question)
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
            async for event in self._emit_fallback(
                tenant_id=tenant_id,
                website_id=website_id,
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
        history_task = asyncio.create_task(self._load_history(tenant_id, session.session_id))
        try:
            retrieval = await self._retrieve(
                tenant_id=tenant_id,
                website_id=website_id,
                question=question,
            )
            (
                query_vector,
                results,
                embedding_ms,
                retrieval_ms,
                embedding_cache_hit,
                retrieval_cache_hit,
                retrieval_metrics,
                load_chunks_ms,
                rerank_ms,
                rerank_embedding_ms,
                rerank_input_count,
                hybrid_candidate_count,
                adaptive_max_context_chars,
            ) = retrieval
        except Exception as exc:
            history_task.cancel()
            logger.exception("question embedding failed (tenant=%s)", tenant_id)
            yield _error_event(_error_code(exc), _safe_message(exc))
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
            history_task.cancel()
            async for event in self._emit_fallback(
                tenant_id=tenant_id,
                website_id=website_id,
                session=session,
                started=started,
                vector_queries=1,
                reason="retrieval_empty",
                query=question,
            ):
                yield event
            return

        # Pre-generation confidence check.  When enabled, the retrieval
        # scores are evaluated before the LLM is called.  Low confidence
        # means the knowledge base likely lacks relevant content, so we
        # return the safe fallback instead of risking a hallucinated answer.
        retrieval_scores = [r.score for r in results]
        confidence_score: float | None = None
        confidence_metrics: ConfidenceMetrics | None = None
        if self._confidence_check_enabled:
            confidence_metrics = assess_confidence(
                retrieval_scores, min_score=self._min_score
            )
            confidence_score = confidence_metrics.confidence
            if confidence_score < self._confidence_threshold:
                logger.warning(
                    "rag_confidence_low score=%.4f threshold=%.4f tenant=%s "
                    "website=%s session=%s result_count=%d",
                    confidence_score,
                    self._confidence_threshold,
                    tenant_id,
                    website_id,
                    session.session_id,
                    len(results),
                )
                history_task.cancel()
                async for event in self._emit_fallback(
                    tenant_id=tenant_id,
                    website_id=website_id,
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
                results, max_context_chars=adaptive_max_context_chars
            )
        context_ms = (time.perf_counter() - t_context) * 1000.0
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "chat_context_build question=%r context_count=%d",
                question,
                len(context_items),
            )
            for idx, (item, src) in enumerate(
                zip(context_items, sources, strict=True)
            ):
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
            logger.exception("answer generation failed (session=%s)", session.session_id)
            yield _error_event(_error_code(exc), _safe_message(exc))
            return

        answer = "".join(deltas)
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
        if self._enable_faithfulness_check and context_items and answer:
            faithfulness_score = _check_faithfulness(answer, context_items)
            if faithfulness_score < self._faithfulness_warning_threshold:
                logger.warning(
                    "faithfulness_low score=%.2f threshold=%.2f tenant=%s website=%s "
                    "session=%s",
                    faithfulness_score,
                    self._faithfulness_warning_threshold,
                    tenant_id,
                    website_id,
                    session.session_id,
                )
        response_time = time.monotonic() - started
        usage = self._generation.usage

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
        # Persist the per-stage latency breakdown for the performance
        # dashboard (Phase 12.6). Durations only - never content or secrets.
        assistant.latency_embedding_ms = _round_ms(embedding_ms)
        assistant.latency_retrieval_ms = _round_ms(retrieval_ms)
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
                    "vector_queries": 1,
                },
            ),
        )
        persist_ms = (time.perf_counter() - t_persist) * 1000.0
        assistant.latency_persist_ms = _round_ms(persist_ms)
        total_ms = (time.perf_counter() - perf_started) * 1000.0

        fallback_attempts = 0
        if hasattr(self._generation, "last_latency_metrics"):
            metrics = self._generation.last_latency_metrics
            if metrics is not None:
                fallback_attempts = metrics.fallback_attempts

        done_data: dict[str, Any] = {
            "message_id": assistant.id,
            "session_id": session.session_id,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "response_time_ms": int(response_time * 1000),
            "created_at": assistant.created_at.isoformat(),
            "prompt_version": self._prompt_version,
            "fallback": False,
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
                confidence_metrics.rejected_chunks_count
                if confidence_metrics is not None
                else None
            ),
        }
        if faithfulness_score is not None:
            done_data["faithfulness_score"] = round(faithfulness_score, 3)
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
                        round(confidence_score, 4)
                        if confidence_score is not None
                        else None
                    ),
                    "confidence_minimum_score": (
                        confidence_metrics.minimum_score
                        if confidence_metrics is not None
                        else None
                    ),
                    "confidence_average_score": (
                        confidence_metrics.average_score
                        if confidence_metrics is not None
                        else None
                    ),
                    "confidence_rejected_chunks_count": (
                        confidence_metrics.rejected_chunks_count
                        if confidence_metrics is not None
                        else None
                    ),
                    "original_context_chars": (
                        opt_metrics.original_chars
                        if opt_metrics is not None
                        else None
                    ),
                    "optimized_context_chars": (
                        opt_metrics.optimized_chars
                        if opt_metrics is not None
                        else None
                    ),
                    "removed_chunks_count": (
                        opt_metrics.removed_chunks
                        if opt_metrics is not None
                        else None
                    ),
                    "faithfulness_score": (
                        round(faithfulness_score, 3)
                        if faithfulness_score is not None
                        else None
                    ),
                },
            )
        yield {"event": "done", "data": done_data}

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

    async def _load_history(self, tenant_id: str, session_id: str) -> list[tuple[str, str]]:
        recent = await self._messages.list_recent(tenant_id, session_id, limit=self._memory_turns)
        return [(message.role, message.content) for message in recent]

    async def _load_all_chunks(
        self, tenant_id: str, website_id: str, *, limit: int = 0
    ) -> list[VectorSearchResult]:
        """Fetch knowledge chunks for a tenant/website for hybrid keyword scoring.

        .. deprecated::
            This method is **dead code** — the production ``_retrieve()`` flow
            always passes ``all_chunks=None`` to the retrieval strategy, and
            ``HybridSearcher`` restricts keyword scoring to vector-search
            results only.  Retained for potential future full-scan keyword
            mode and for test coverage of the chunk-loading path.

        When *limit* > 0, at most *limit* chunks are loaded (bounded candidate
        loading).  When *limit* == 0, all chunks are returned (legacy behavior).
        Returns ``VectorSearchResult`` objects with a uniform score of 0.5
        (the keyword scorer will re-rank them).
        """
        chunks = await self._vector.list_chunks(tenant_id, website_id, limit=limit)
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
        # ------------------------------------------------------------------
        candidate_items: list[ContextItem] = []
        candidate_sources: list[dict[str, Any]] = []
        seen_text: set[tuple[str, str]] = set()

        for result in results:
            if self._min_score > 0 and result.score < self._min_score:
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
                text = text[: self._max_chars_per_chunk]
            candidate_items.append(ContextItem(url=url, title=title, heading=None, text=text))
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
                compressed, removed = compress_text(
                    item.text, seen_sentences=seen_sentences
                )
                compressed_items.append(
                    ContextItem(
                        url=item.url, title=item.title,
                        heading=item.heading, text=compressed,
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
                    text = text[:budget]
                    budget = 0
                else:
                    budget -= len(text)
            items.append(ContextItem(url=item.url, title=item.title, heading=None, text=text))
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
            "data": {
                "message_id": assistant.id,
                "session_id": session.session_id,
                "input_tokens": 0,
                "output_tokens": 0,
                "response_time_ms": int(response_time * 1000),
                "created_at": assistant.created_at.isoformat(),
                "prompt_version": self._prompt_version,
                "fallback": True,
                "confidence_score": (
                    confidence_metrics.confidence if confidence_metrics is not None else None
                ),
                "confidence_minimum_score": (
                    confidence_metrics.minimum_score
                    if confidence_metrics is not None
                    else None
                ),
                "confidence_average_score": (
                    confidence_metrics.average_score
                    if confidence_metrics is not None
                    else None
                ),
                "confidence_rejected_chunks_count": (
                    confidence_metrics.rejected_chunks_count
                    if confidence_metrics is not None
                    else None
                ),
            },
        }


def _safe_message(exc: Exception) -> str:
    """Never leak internal error details into the client stream."""
    if isinstance(exc, AppError):
        return exc.message
    return "An unexpected error occurred. Please try again later."


def _check_faithfulness(answer: str, context_items: list["ContextItem"]) -> float:
    """Score answer faithfulness by checking if each sentence is grounded in context.

    Returns a value between 0.0 (no support) and 1.0 (fully grounded).
    Each sentence in the answer is checked for significant word overlap
    (>3 chars, alpha-only) with the context chunks.  Sentences with no
    significant words (trivial fragments) are counted as *unsupported*
    since they contribute no verifiable content.  An empty answer is
    scored 0.0 because there is nothing to be faithful *to*.
    """
    import re

    sentences = [s.strip() for s in re.split(r"[.!?]+", answer) if s.strip() and len(s.strip()) > 5]
    if not sentences:
        return 0.0

    context_lower = " ".join(item.text.lower() for item in context_items)
    context_words = {
        w for w in context_lower.split() if len(w) > 3 and w.isalpha()
    }

    supported = 0
    for sentence in sentences:
        words = {
            w for w in sentence.lower().split() if len(w) > 3 and w.isalpha()
        }
        if not words:
            continue
        overlap = words & context_words
        if len(overlap) >= max(1, len(words) // 3):
            supported += 1

    return round(supported / len(sentences), 3)


__all__ = ["RagService"]
