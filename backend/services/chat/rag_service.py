"""Retrieval-augmented answer generation (Phase 6, ADR-008).

Per question: validate website ownership -> sanitize -> persist the user turn
-> embed the question -> tenant-filtered Top-5 vector search -> build context
-> load conversation memory -> stream the Gemini answer -> persist the answer
with sources + tokens + latency -> roll up `usage_records` (ADR-005 §5.5/§5.8).

Hallucination guard (docs/06 Phase 6 rules): the model is never called without
retrieved context. When the knowledge base is empty or search yields no hits,
a fixed fallback (docs/02-TRD.md §8) is returned instead, so the chatbot
cannot fabricate answers. All failures are surfaced as SSE `error` events so
the streaming endpoint stays uniform.
"""

import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from backend.ai.gemini import GenerationClient
from backend.core.config import get_settings
from backend.core.errors import AppError, SessionNotFoundError
from backend.core.security import new_id
from backend.models.chat_message import (
    CHAT_ROLE_ASSISTANT,
    CHAT_ROLE_USER,
    ChatMessage,
)
from backend.models.chat_session import ChatSession
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

logger = logging.getLogger("webchat_ai")


def _error_event(code: str, message: str) -> dict[str, Any]:
    return {"event": "error", "data": {"code": code, "message": message}}


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
        self._top_k = top_k if top_k is not None else settings.chat_top_k
        self._prompt_version = (
            prompt_version if prompt_version is not None else settings.rag_prompt_version
        )
        self._memory_turns = (
            memory_turns if memory_turns is not None else settings.chat_memory_turns
        )
        self._max_chars_per_chunk = settings.chat_context_chunk_chars

    async def stream_answer(
        self,
        *,
        tenant_id: str,
        website_id: str,
        question: str,
        session_id: str | None = None,
        visitor_id: str | None = None,
        user_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Answer `question` as a stream of SSE events.

        Events: `sources`, `message` (one per delta), `done`, or `error`.
        """
        started = time.monotonic()
        try:
            website = await self._websites.find_by_id(tenant_id, website_id)
            if website is None:
                yield _error_event("WEBSITE_NOT_FOUND", "Website not found.")
                return
            question = sanitize_question(question)
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
        await self._messages.create(user_message)

        if website.knowledge_chunks == 0:
            async for event in self._emit_fallback(
                tenant_id=tenant_id,
                website_id=website_id,
                session=session,
                started=started,
                vector_queries=0,
            ):
                yield event
            return

        try:
            vectors = await self._embedder.embed([question])
            query_vector = vectors[0]
        except Exception as exc:
            logger.exception("question embedding failed (tenant=%s)", tenant_id)
            yield _error_event(_error_code(exc), _safe_message(exc))
            return

        try:
            results = await self._vector.similarity_search(
                tenant_id, website_id, query_vector, top_k=self._top_k
            )
        except Exception as exc:
            logger.exception("vector search failed (tenant=%s)", tenant_id)
            yield _error_event(_error_code(exc), _safe_message(exc))
            return

        if not results:
            async for event in self._emit_fallback(
                tenant_id=tenant_id,
                website_id=website_id,
                session=session,
                started=started,
                vector_queries=1,
            ):
                yield event
            return

        context_items, sources = self._build_context(results)
        try:
            history = await self._load_history(tenant_id, session.session_id)
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

        deltas: list[str] = []
        try:
            async for delta in self._generation.stream_generate(
                system=system_prompt,
                messages=[(CHAT_ROLE_USER, user_prompt)],
            ):
                deltas.append(delta)
                yield {"event": "message", "data": {"delta": delta}}
        except Exception as exc:
            logger.exception("answer generation failed (session=%s)", session.session_id)
            yield _error_event(_error_code(exc), _safe_message(exc))
            return

        answer = "".join(deltas)
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
        await self._messages.create(assistant)
        await self._sessions.touch(session.session_id)
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
        yield {
            "event": "done",
            "data": {
                "message_id": assistant.id,
                "session_id": session.session_id,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "response_time_ms": int(response_time * 1000),
                "created_at": assistant.created_at.isoformat(),
                "prompt_version": self._prompt_version,
                "fallback": False,
            },
        }

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
        self, tenant_id: str, session_id: str
    ) -> list[tuple[str, str]]:
        recent = await self._messages.list_recent(
            tenant_id, session_id, limit=self._memory_turns
        )
        return [(message.role, message.content) for message in recent]

    def _build_context(
        self, results: list[VectorSearchResult]
    ) -> tuple[list[ContextItem], list[dict[str, Any]]]:
        """Deduplicate hits and produce prompt context + client-facing sources."""
        items: list[ContextItem] = []
        sources: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for _index, result in enumerate(results, start=1):
            chunk = result.chunk
            url = str(chunk.metadata.get("source_url") or "")
            title = str(chunk.metadata.get("title") or url or "Untitled")
            key = (url, chunk.chunk_text)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                ContextItem(url=url, title=title, heading=None, text=chunk.chunk_text)
            )
            sources.append(
                {
                    "chunk_id": chunk.id,
                    "url": url,
                    "title": title,
                    "score": result.score,
                    "citation": len(sources) + 1,
                }
            )
        return items, sources

    async def _emit_fallback(
        self,
        *,
        tenant_id: str,
        website_id: str,
        session: ChatSession,
        started: float,
        vector_queries: int,
    ) -> AsyncIterator[dict[str, Any]]:
        """Emit the no-context fallback without ever calling the model."""
        response_time = time.monotonic() - started
        assistant = ChatMessage.new(
            tenant_id=tenant_id,
            website_id=website_id,
            session_id=session.session_id,
            role=CHAT_ROLE_ASSISTANT,
            content=UNKNOWN_ANSWER_FALLBACK,
        )
        assistant.response_time = response_time
        await self._messages.create(assistant)
        await self._sessions.touch(session.session_id)
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
