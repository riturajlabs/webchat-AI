"""Tests for the RAG answer pipeline (Phase 6, ADR-008).

Exercise the full retrieve -> context -> generate -> persist -> usage flow
with in-memory fakes, covering the hallucination guard (no context => no
model call), tenant isolation, conversation memory, and failure paths.
"""

import logging

from backend.core.config import get_settings
from backend.core.errors import EmbeddingUnavailableError, GenerationError
from backend.models.chat_message import CHAT_ROLE_ASSISTANT, CHAT_ROLE_USER
from backend.prompts.rag import RAG_PROMPT_VERSION, UNKNOWN_ANSWER_FALLBACK
from backend.services.chat.rag_service import RagService

from tests.chat_helpers import (
    build_chat_env,
    consume,
    make_chunk,
    make_website,
)

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
WEB_1 = "web-1"


def backend_settings():
    """The pydantic-settings singleton the RAG service reads at construction."""
    return get_settings()


async def _stream(env, **kwargs):
    return await consume(env.rag.stream_answer(**kwargs))


def _message_event(events):
    return [event["data"]["delta"] for event in events if event["event"] == "message"]


def _done_event(events):
    return next(event for event in events if event["event"] == "done")


async def test_answers_from_retrieval_and_persists_everything() -> None:
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT_A, website_id=WEB_1, text="We offer Pro and Team plans.")

    events = await _stream(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        question="What plans do you offer?",
    )

    # Sources emitted first, then streamed deltas, then done.
    sources = next(event for event in events if event["event"] == "sources")
    assert sources["data"]["sources"][0]["url"] == "https://example.com/page"
    assert sources["data"]["sources"][0]["citation"] == 1
    assert "".join(_message_event(events)) == "Hello world!"

    done = _done_event(events)
    assert done["data"]["fallback"] is False
    assert done["data"]["input_tokens"] == 10
    assert done["data"]["output_tokens"] == 20
    assert done["data"]["prompt_version"] == RAG_PROMPT_VERSION
    assert done["data"]["session_id"]

    # One user + one assistant message persisted; the assistant carries the
    # sources, latency and raw token usage (ADR-005 §5.8).
    assert len(env.messages.messages) == 2
    user, assistant = env.messages.messages
    assert user.role == CHAT_ROLE_USER and user.content == "What plans do you offer?"
    assert assistant.role == CHAT_ROLE_ASSISTANT
    assert assistant.sources and assistant.response_time is not None
    assert assistant.input_tokens == 10 and assistant.output_tokens == 20

    # A session was created for the tenant and website.
    session = next(iter(env.sessions.sessions.values()))
    assert session.tenant_id == TENANT_A and session.website_id == WEB_1

    # Daily usage rollup counters (ADR-005 §5.5).
    record = env.usage.records[0]
    assert record.counters["chats"] == 1
    assert record.counters["messages"] == 2
    assert record.counters["input_tokens"] == 10
    assert record.counters["output_tokens"] == 20
    assert record.counters["vector_queries"] == 1

    # The prompt reached the model with the retrieved context + system rules.
    call = env.generation.calls[0]
    assert "What plans do you offer?" in call["messages"][0][1]
    assert "We offer Pro and Team plans." in call["messages"][0][1]
    assert "reference material" in call["system"]


async def test_fallback_when_knowledge_base_empty_no_model_call() -> None:
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=0)

    events = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question="Anything at all?")

    assert env.generation.calls == []  # never call the model without context
    assert _message_event(events) == [UNKNOWN_ANSWER_FALLBACK]
    done = _done_event(events)
    assert done["data"]["fallback"] is True
    assert done["data"]["input_tokens"] == 0 and done["data"]["output_tokens"] == 0
    record = env.usage.records[0]
    assert record.counters["chats"] == 1
    assert record.counters["messages"] == 2
    assert record.counters["vector_queries"] == 0


async def test_fallback_when_no_search_hits_no_model_call() -> None:
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=1)

    events = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question="About nothing?")

    assert env.generation.calls == []
    assert _message_event(events) == [UNKNOWN_ANSWER_FALLBACK]
    assert env.usage.records[0].counters["vector_queries"] == 1


async def test_foreign_tenant_website_is_rejected() -> None:
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1)

    events = await _stream(env, tenant_id=TENANT_B, website_id=WEB_1, question="Hello?")

    assert events == [
        {"event": "error", "data": {"code": "WEBSITE_NOT_FOUND", "message": "Website not found."}}
    ]
    assert env.generation.calls == []
    assert env.messages.messages == []


async def test_unknown_session_is_rejected() -> None:
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1)

    events = await _stream(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        question="Hello?",
        session_id="does-not-exist",
    )

    assert events[0]["event"] == "error"
    assert events[0]["data"]["code"] == "SESSION_NOT_FOUND"


async def test_session_from_another_website_is_rejected() -> None:
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1)
    await make_website(
        env,
        tenant_id=TENANT_A,
        website_id="web-2",
        url="https://other.example",
        knowledge_chunks=1,
    )
    await make_chunk(env, tenant_id=TENANT_A, website_id="web-2", text="Other site data.")
    first_events = await _stream(env, tenant_id=TENANT_A, website_id="web-2", question="Hi")
    session_id = _done_event(first_events)["data"]["session_id"]

    events = await _stream(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        question="Hi",
        session_id=session_id,
    )

    assert events[0]["data"]["code"] == "SESSION_NOT_FOUND"
    # Only the first (web-2) question reached the model, never the rejected one.
    assert len(env.generation.calls) == 1


async def test_conversation_memory_flows_into_prompt() -> None:
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1)
    await make_chunk(env, tenant_id=TENANT_A, website_id=WEB_1, text="Pricing starts at $19.")

    first = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question="What are prices?")
    session_id = _done_event(first)["data"]["session_id"]

    second = await _stream(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        question="What about annual billing?",
        session_id=session_id,
    )

    call = env.generation.calls[-1]
    prompt = call["messages"][0][1]
    # Both prior turns are part of the new prompt's conversation history.
    assert "[user] What are prices?" in prompt
    assert "[assistant] Hello world!" in prompt
    assert _done_event(second)["data"]["session_id"] == session_id


async def test_generation_failure_emits_error_and_persists_user_turn() -> None:
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1)
    await make_chunk(env, tenant_id=TENANT_A, website_id=WEB_1, text="Some knowledge.")
    env.generation.failures = [GenerationError("model exploded")]

    events = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question="Hello?")

    assert events[0]["event"] == "sources"
    assert events[-1]["event"] == "error"
    assert events[-1]["data"]["code"] == "GENERATION_FAILED"
    # The user turn is persisted; no assistant message and no usage recorded.
    assert len(env.messages.messages) == 1
    assert env.messages.messages[0].role == CHAT_ROLE_USER
    assert env.usage.records == []


async def test_embedding_failure_emits_error_and_skips_model() -> None:
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1)

    class FailingEmbedder:
        async def embed(self, texts: list[str]) -> list[list[float]]:
            raise EmbeddingUnavailableError("GEMINI_API_KEY is not configured")

    env.rag = RagService(
        websites=env.websites,
        vector=env.vector,
        embedder=FailingEmbedder(),
        generation=env.generation,
        sessions=env.sessions,
        messages=env.messages,
        usage=env.usage,
    )

    events = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question="Hello?")

    assert events[-1]["data"]["code"] == "EMBEDDING_UNAVAILABLE"
    assert env.generation.calls == []


async def test_internal_errors_do_not_leak_details() -> None:
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1)
    await make_chunk(env, tenant_id=TENANT_A, website_id=WEB_1, text="Knowledge.")
    env.generation.failures = [RuntimeError("s3cr3t internal path")]

    events = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question="Hello?")

    error = events[-1]
    assert error["data"]["code"] == "INTERNAL_ERROR"
    assert "s3cr3t" not in error["data"]["message"]


async def test_question_is_sanitized_before_generation() -> None:
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1)
    await make_chunk(env, tenant_id=TENANT_A, website_id=WEB_1, text="Knowledge.")

    await _stream(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        question="  what\x00\x07   is the price?  ",
    )

    assert env.messages.messages[0].content == "what is the price?"
    assert "Question: what is the price?" in env.generation.calls[0]["messages"][0][1]


async def test_chunks_are_deduplicated_by_url_and_text() -> None:
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1)
    await make_chunk(env, tenant_id=TENANT_A, website_id=WEB_1, text="Same content", chunk_index=0)
    await make_chunk(env, tenant_id=TENANT_A, website_id=WEB_1, text="Same content", chunk_index=1)

    events = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question="Tell me")

    sources = next(event for event in events if event["event"] == "sources")
    assert len(sources["data"]["sources"]) == 1
    assert len(env.generation.calls) == 1


async def test_top_k_limits_retrieved_chunks() -> None:
    env = build_chat_env(top_k=2)
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1)
    for index in range(4):
        await make_chunk(
            env,
            tenant_id=TENANT_A,
            website_id=WEB_1,
            text=f"chunk {index}",
            chunk_index=index,
        )

    events = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question="Hello")

    sources = next(event for event in events if event["event"] == "sources")
    assert len(sources["data"]["sources"]) == 2


async def test_known_question_gets_grounded_answer() -> None:
    """A known question must produce an answer grounded in the knowledge base,
    never the no-context fallback (RAG regression test for course questions)."""
    env = build_chat_env(deltas=["Indira University offers BA, B.Com, and B.Sc courses."])
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=1)
    await make_chunk(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        text="Undergraduate programs at Indira University include BA, B.Com, and B.Sc.",
        url="https://indirauniversity.edu.in/programs",
        title="Programs at Indira University",
    )

    events = await _stream(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        question="What courses are offered by Indira University?",
    )

    answer = "".join(_message_event(events))
    assert "courses" in answer.lower()
    assert answer != UNKNOWN_ANSWER_FALLBACK
    done = _done_event(events)
    assert done["data"]["fallback"] is False
    # The retrieved chunk really reached the model -> grounded generation.
    call = env.generation.calls[0]
    assert "BA, B.Com, and B.Sc" in call["messages"][0][1]
    assert "Indira University" in call["messages"][0][1]


async def test_prompt_includes_system_context_and_query() -> None:
    """The LLM prompt must contain system rules + retrieved context + query."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=1)
    await make_chunk(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        text="Indira offers BA and B.Com programs.",
        title="Programs",
    )

    await _stream(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        question="What programs are available?",
    )

    call = env.generation.calls[0]
    assert "reference material" in call["system"]
    assert "Answer only using the reference material" in call["system"]
    assert "Indira offers BA and B.Com programs." in call["messages"][0][1]
    assert "Question: What programs are available?" in call["messages"][0][1]


async def test_zero_context_retrieval_logs_warning(caplog) -> None:
    """When retrieval returns no context, a warning must include the website_id
    and query so the pipeline can be traced end-to-end (RAG observability)."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=1)

    with caplog.at_level(logging.WARNING, logger="webchat_ai"):
        await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question="About nothing?")

    assert "rag_retrieval_zero_context" in caplog.text
    assert "reason=retrieval_empty" in caplog.text
    assert f"website={WEB_1}" in caplog.text
    assert "About nothing?" in caplog.text


async def test_repeated_question_reuses_the_embedding_cache() -> None:
    """Asking the same question twice embeds once; generation still runs both turns."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT_A, website_id=WEB_1, text="Knowledge.")

    question = "What is the price?"
    first = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question=question)
    session_id = _done_event(first)["data"]["session_id"]
    second = await _stream(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        question=question,
        session_id=session_id,
    )

    # The second question never calls the embedding API; retrieval + generation
    # still run (cache is a question-embedding shortcut, not a full answer cache).
    assert len(env.embedder.calls) == 1
    assert len(env.generation.calls) == 2
    assert _done_event(second)["data"]["session_id"] == session_id


async def test_embedding_cache_is_bounded(monkeypatch) -> None:
    """Eviction is size-only: an LRU of N=1 forgets the first question.

    Each question is asked on a different website so the (per-website)
    retrieval cache can never serve the repeat - the embedding LRU alone
    decides whether the provider is called again.
    """
    monkeypatch.setattr(backend_settings(), "embedding_cache_size", 1)
    env = build_chat_env()
    for index, question in enumerate(["What is A?", "What is B?", "What is A?"]):
        await make_website(
            env,
            tenant_id=TENANT_A,
            website_id=f"web-{index}",
            knowledge_chunks=1,
        )
        await make_chunk(
            env, tenant_id=TENANT_A, website_id=f"web-{index}", text="Knowledge."
        )
        await _stream(env, tenant_id=TENANT_A, website_id=f"web-{index}", question=question)

    # B evicted A -> the final A is a fresh embedding (miss), so three calls.
    assert len(env.embedder.calls) == 3


async def test_done_event_includes_timing_breakdown_when_enabled(monkeypatch, caplog) -> None:
    """The opt-in timing flag adds a phase breakdown to `done` + a `rag_timing` log."""
    monkeypatch.setattr(backend_settings(), "perf_timing_log_enabled", True)
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT_A, website_id=WEB_1, text="Knowledge.")

    with caplog.at_level(logging.INFO, logger="webchat_ai"):
        events = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question="Pricing?")

    timing = _done_event(events)["data"]["timing"]
    assert set(timing) == {
        "embedding_ms",
        "retrieval_ms",
        "context_ms",
        "history_ms",
        "generation_ms",
        "ttft_ms",
        "total_ms",
    }
    assert timing["total_ms"] >= timing["embedding_ms"]

    records = [r for r in caplog.records if r.getMessage() == "rag_timing"]
    assert records
    assert records[0].embedding_cache == "miss"
    assert records[0].retrieval_cache == "miss"
    assert records[0].website_id == WEB_1
    assert records[0].total_ms >= 0


async def test_done_event_omits_timing_when_disabled() -> None:
    """Default (timing disabled) never leaks timing data into the SSE `done` event."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT_A, website_id=WEB_1, text="Knowledge.")

    events = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question="Pricing?")

    assert "timing" not in _done_event(events)["data"]


async def test_retrieval_cache_reuses_embedding_and_search_but_not_generation() -> None:
    """Same question + website inside the TTL skips the embedding AND the
    vector search, but generation still runs (answers are never cached)."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT_A, website_id=WEB_1, text="Knowledge.")

    question = "What is the price?"
    first = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question=question)
    session_id = _done_event(first)["data"]["session_id"]
    await _stream(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        question=question,
        session_id=session_id,
    )

    assert len(env.embedder.calls) == 1
    assert env.vector.search_calls == 1
    assert len(env.generation.calls) == 2


async def test_retrieval_cache_is_scoped_per_website() -> None:
    """The cache key includes the website: the same question on another
    website runs its own embedding (if uncached globally) and its own search."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=1)
    await make_website(env, tenant_id=TENANT_A, website_id="web-2", knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT_A, website_id=WEB_1, text="Knowledge A.")
    await make_chunk(env, tenant_id=TENANT_A, website_id="web-2", text="Knowledge B.")

    question = "Same question?"
    for website_id in (WEB_1, "web-2"):
        await _stream(env, tenant_id=TENANT_A, website_id=website_id, question=question)

    assert len(env.embedder.calls) == 1
    assert env.vector.search_calls == 2


async def test_retrieval_cache_expires_after_ttl(monkeypatch) -> None:
    """Cache entries expire after `chat_retrieval_cache_ttl_seconds`."""
    monkeypatch.setattr(backend_settings(), "chat_retrieval_cache_ttl_seconds", 100)
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT_A, website_id=WEB_1, text="Knowledge.")

    import backend.services.chat.rag_service as rag_module

    clock = 0.0
    monkeypatch.setattr(rag_module, "_now", lambda: clock)

    await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question="Pricing?")
    clock += 50.0
    await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question="Pricing?")
    assert env.vector.search_calls == 1  # still fresh: 50s < 100s TTL

    clock += 60.0  # 110s total -> expired
    await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question="Pricing?")
    assert env.vector.search_calls == 2


async def test_context_is_capped_at_total_budget(monkeypatch) -> None:
    """The combined context never exceeds `chat_context_max_chars`: the last
    fitting chunk is truncated to the remaining budget and lower-ranked chunks
    are dropped entirely."""
    monkeypatch.setattr(backend_settings(), "chat_context_max_chars", 40)
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=3)
    await make_chunk(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        text="A" * 30,
        url="https://a.test",
        title="A",
    )
    await make_chunk(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        text="B" * 30,
        url="https://b.test",
        title="B",
        chunk_index=1,
    )
    await make_chunk(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        text="C" * 30,
        url="https://c.test",
        title="C",
        chunk_index=2,
    )

    events = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question="Pricing?")
    sources = next(event for event in events if event["event"] == "sources")["data"]["sources"]
    user_prompt = env.generation.calls[-1]["messages"][0][1]

    assert [s["url"] for s in sources] == ["https://a.test", "https://b.test"]
    assert "A" * 30 in user_prompt
    assert "B" * 10 in user_prompt
    assert "C" * 30 not in user_prompt


async def test_context_min_score_drops_low_ranked_chunks(monkeypatch) -> None:
    """`chat_context_min_score` filters retrieved chunks below the threshold."""
    monkeypatch.setattr(backend_settings(), "chat_context_min_score", 0.895)
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=2)
    await make_chunk(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        text="Top result.",
        url="https://a.test",
        title="A",
    )
    await make_chunk(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        text="Worse result.",
        url="https://b.test",
        title="B",
        chunk_index=1,
    )

    events = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question="Pricing?")
    sources = next(event for event in events if event["event"] == "sources")["data"]["sources"]
    user_prompt = env.generation.calls[-1]["messages"][0][1]

    assert [s["url"] for s in sources] == ["https://a.test"]
    assert "Top result." in user_prompt
    assert "Worse result." not in user_prompt


async def test_stream_persists_stage_latencies() -> None:
    """Assistant messages carry the per-stage latency breakdown (ms) used by
    the performance dashboard."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT_A, website_id=WEB_1, text="Knowledge.")

    events = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question="Pricing?")
    message_id = _done_event(events)["data"]["message_id"]
    message = await env.messages.find_by_id(TENANT_A, message_id)
    assert message is not None

    assert message.latency_embedding_ms is not None
    assert message.latency_retrieval_ms is not None
    assert message.latency_context_ms is not None
    assert message.latency_history_ms is not None
    assert message.latency_generation_ms is not None
    assert message.latency_ttft_ms is not None
    assert message.latency_total_ms is not None
    assert message.latency_total_ms >= message.latency_generation_ms


async def test_context_cap_zero_disables_budget(monkeypatch) -> None:
    """`chat_context_max_chars=0` means "no budget" - all chunks are kept."""
    monkeypatch.setattr(backend_settings(), "chat_context_max_chars", 0)
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=3)
    await make_chunk(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        text="A" * 30,
        url="https://a.test",
        title="A",
    )
    await make_chunk(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        text="B" * 30,
        url="https://b.test",
        title="B",
        chunk_index=1,
    )
    await make_chunk(
        env,
        tenant_id=TENANT_A,
        website_id=WEB_1,
        text="C" * 30,
        url="https://c.test",
        title="C",
        chunk_index=2,
    )

    events = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question="Pricing?")
    sources = next(event for event in events if event["event"] == "sources")["data"]["sources"]

    assert [s["url"] for s in sources] == ["https://a.test", "https://b.test", "https://c.test"]


async def test_retrieval_cache_disabled_when_ttl_zero(monkeypatch) -> None:
    """`chat_retrieval_cache_ttl_seconds=0` turns the retrieval cache off."""
    monkeypatch.setattr(backend_settings(), "chat_retrieval_cache_ttl_seconds", 0)
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT_A, website_id=WEB_1, text="Knowledge.")

    question = "Pricing?"
    for _ in range(2):
        await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question=question)

    assert env.vector.search_calls == 2
