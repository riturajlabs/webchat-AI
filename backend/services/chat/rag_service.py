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
from backend.repositories.website_repository import WebsiteRepository
from backend.services.knowledge.embedding import EmbeddingClient
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

    async def _embed_question(self, question: str) -> tuple[list[float], bool]:
        """Embed `question`, caching identical questions across turns.

        Returns `(vector, cache_hit)` so callers can report hit/miss and the
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
                    return json.loads(raw), True
                except (json.JSONDecodeError, TypeError):
                    pass
        vectors = await self._embedder.embed([question])
        vector = vectors[0]
        if self._cache is not None and self._embedding_cache_size > 0:
            ttl = self._embedding_cache_ttl if self._embedding_cache_ttl > 0 else None
            await self._cache.set("embed", key, json.dumps(vector), ttl=ttl)
        return vector, False

    async def _retrieve(
        self,
        *,
        tenant_id: str,
        website_id: str,
        question: str,
    ) -> tuple[list[float], list[VectorSearchResult], float, float, bool, bool]:
        """Embed + search, memoizing repeats within the retrieval TTL.

        Returns `(query_vector, results, embedding_ms, retrieval_ms,
        embedding_cache_hit, retrieval_cache_hit)`. A retrieval-cache hit
        reports zero stage latency (the work was already done) and skips both
        the embedding provider and the vector query.
        """
        cache = self._cache
        cache_key = f"{website_id}:{question.strip().lower()}"
        now = _now()
        retrieval_enabled = (
            cache is not None
            and self._retrieval_cache_size > 0
            and self._retrieval_cache_ttl > 0
        )
        if retrieval_enabled:
            assert cache is not None  # guaranteed by retrieval_enabled
            raw = await cache.get("retrieval", cache_key)
            if raw is not None:
                try:
                    entry = json.loads(raw)
                    if now - entry["cached_at"] < self._retrieval_cache_ttl:
                        vector = entry["vector"]
                        results = [
                            VectorSearchResult(
                                chunk=KnowledgeChunk(**r["chunk"]),
                                score=r["score"],
                            )
                            for r in entry["results"]
                        ]
                        return vector, results, 0.0, 0.0, True, True
                except (json.JSONDecodeError, TypeError, KeyError):
                    pass
        t0 = time.perf_counter()
        async with chat_stage("retrieval.embed"):
            query_vector, embedding_cache_hit = await self._embed_question(question)
        embedding_ms = (time.perf_counter() - t0) * 1000.0
        t1 = time.perf_counter()
        async with chat_stage("retrieval.vector_search"):
            results = await self._vector.similarity_search(
                tenant_id, website_id, query_vector, top_k=self._top_k
            )
        retrieval_ms = (time.perf_counter() - t1) * 1000.0
        if retrieval_enabled:
            assert cache is not None  # guaranteed by retrieval_enabled
            entry = {
                "vector": query_vector,
                "results": [
                    {"chunk": r.chunk.model_dump(mode="json"), "score": r.score}
                    for r in results
                ],
                "cached_at": _now(),
            }
            await cache.set(
                "retrieval", cache_key, json.dumps(entry), ttl=self._retrieval_cache_ttl
            )
        return query_vector, results, embedding_ms, retrieval_ms, embedding_cache_hit, False

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
        # perf_counter for the phase breakdown; only measured when the opt-in
        # timing flag is on (the value is unused otherwise).
        perf_started = time.perf_counter()
        try:
            async with chat_stage("website.lookup"):
                website = await self._websites.find_by_id(tenant_id, website_id)
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
                session = await self._ensure_session(
                    tenant_id=tenant_id,
                    website_id=website_id,
                    session_id=session_id,
                    visitor_id=visitor_id,
                    user_id=user_id,
                )
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
        async with chat_stage("persist.user_message"):
            await self._messages.create(user_message)

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

        t_context = time.perf_counter()
        async with chat_stage("retrieval.context"):
            context_items, sources = self._build_context(results)
        context_ms = (time.perf_counter() - t_context) * 1000.0
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

        system_prompt = get_system_prompt(self._prompt_version)
        user_prompt = build_user_prompt(
            question=question,
            context=context_items,
            history=history,
            max_chars_per_chunk=self._max_chars_per_chunk,
        )
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
            "chat_prompt_full tenant=%s website=%s system_chars=%d "
            "user_hash=%s user_length=%d",
            tenant_id,
            website_id,
            len(system_prompt),
            content_hash(user_prompt),
            len(user_prompt),
        )

        deltas: list[str] = []
        ttft_ms: float | None = None
        try:
            t2 = time.perf_counter()
            async with chat_stage("generation.stream"):
                async for delta in self._generation.stream_generate(
                    system=system_prompt,
                    messages=[(CHAT_ROLE_USER, user_prompt)],
                ):
                    if ttft_ms is None:
                        ttft_ms = (time.perf_counter() - t2) * 1000.0
                    deltas.append(delta)
                    yield {"event": "message", "data": {"delta": delta}}
            generation_ms = (time.perf_counter() - t2) * 1000.0
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
        assistant.latency_total_ms = round(response_time * 1000.0, 2)
        async with chat_stage("persist.messages"):
            await self._messages.create(assistant)
        async with chat_stage("persist.session_touch"):
            await self._sessions.touch(session.session_id)
        async with chat_stage("persist.usage"):
            await self._usage.increment(
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
            )
        done_data: dict[str, Any] = {
            "message_id": assistant.id,
            "session_id": session.session_id,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "response_time_ms": int(response_time * 1000),
            "created_at": assistant.created_at.isoformat(),
            "prompt_version": self._prompt_version,
            "fallback": False,
        }
        if self._timing_enabled:
            total_ms = (time.perf_counter() - perf_started) * 1000.0
            done_data["timing"] = {
                "embedding_ms": round(embedding_ms, 2),
                "retrieval_ms": round(retrieval_ms, 2),
                "context_ms": round(context_ms, 2),
                "history_ms": round(history_ms, 2),
                "generation_ms": round(generation_ms, 2),
                "ttft_ms": round(ttft_ms, 2) if ttft_ms is not None else None,
                "total_ms": round(total_ms, 2),
            }
            logger.info(
                "rag_timing",
                extra={
                    "tenant_id": tenant_id,
                    "website_id": website_id,
                    "session_id": session.session_id,
                    "embedding_cache": "hit" if embedding_cache_hit else "miss",
                    "retrieval_cache": "hit" if retrieval_cache_hit else "miss",
                    "embedding_ms": round(embedding_ms, 2),
                    "retrieval_ms": round(retrieval_ms, 2),
                    "context_ms": round(context_ms, 2),
                    "history_ms": round(history_ms, 2),
                    "generation_ms": round(generation_ms, 2),
                    "ttft_ms": round(ttft_ms, 2) if ttft_ms is not None else None,
                    "total_ms": round(total_ms, 2),
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

    @staticmethod
    def _provider_name(embedder: Any) -> str:
        """Best-effort provider label for observability (never fails)."""
        return (
            getattr(embedder, "active_provider", None)
            or getattr(embedder, "name", None)
            or type(embedder).__name__
        )

    def _build_context(
        self, results: list[VectorSearchResult]
    ) -> tuple[list[ContextItem], list[dict[str, Any]]]:
        """Deduplicate hits, apply the relevance floor, and cap total size.

        Low-score chunks are dropped (when `chat_context_min_score` > 0) and
        the combined context is bounded by `chat_context_max_chars`: the last
        chunk that does not fit is truncated to the remaining budget and the
        rest of the ranking is dropped, so the prompt never grows unbounded.
        """
        items: list[ContextItem] = []
        sources: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        # `chat_context_max_chars <= 0` means "no total budget" (disabled).
        budget = self._max_context_chars if self._max_context_chars > 0 else None
        for _index, result in enumerate(results, start=1):
            if self._min_score > 0 and result.score < self._min_score:
                continue
            chunk = result.chunk
            url = str(chunk.metadata.get("source_url") or "")
            title = str(chunk.metadata.get("title") or url or "Untitled")
            key = (url, chunk.chunk_text)
            if key in seen:
                continue
            seen.add(key)
            text = chunk.chunk_text
            if len(text) > self._max_chars_per_chunk:
                text = text[: self._max_chars_per_chunk]
            if budget is not None and budget >= 0:
                if len(text) > budget:
                    text = text[:budget]
                    budget = 0
                else:
                    budget -= len(text)
            items.append(ContextItem(url=url, title=title, heading=None, text=text))
            sources.append(
                {
                    "chunk_id": chunk.id,
                    "url": url,
                    "title": title,
                    "score": result.score,
                    "citation": len(sources) + 1,
                }
            )
            if budget == 0:
                break
        return items, sources

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
        async with chat_stage("persist.session_touch"):
            await self._sessions.touch(session.session_id)
        async with chat_stage("persist.usage"):
            await self._usage.increment(
                tenant_id=tenant_id,
                website_id=website_id,
                date=usage_date_key(),
                counters={"chats": 1, "messages": 2, "vector_queries": vector_queries},
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
            },
        }


def _safe_message(exc: Exception) -> str:
    """Never leak internal error details into the client stream."""
    if isinstance(exc, AppError):
        return exc.message
    return "An unexpected error occurred. Please try again later."


__all__ = ["RagService"]
