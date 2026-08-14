"""Tests for the RAG answer pipeline (Phase 6, ADR-008).

Exercise the full retrieve -> context -> generate -> persist -> usage flow
with in-memory fakes, covering the hallucination guard (no context => no
model call), tenant isolation, conversation memory, and failure paths.
"""

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
