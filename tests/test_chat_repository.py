"""Regression tests for the chat repositories (Phase 6).

F1 regression: `MongoChatMessageRepository.list_recent` must return the
*latest* `limit` turns in chronological order, not the oldest ones. The fake
collection below mirrors real MongoDB `find().sort().limit()` semantics
(ascending/descending sort, then the first N documents), so a naive
"ASCENDING + limit" query is caught exactly as it would be against a real
cluster.
"""

from datetime import datetime, timedelta

from backend.models.chat_message import CHAT_ROLE_USER, ChatMessage
from backend.repositories.chat_message_repository import MongoChatMessageRepository

TENANT = "tenant-a"
SESSION = "session-1"
WEBSITE = "web-1"


def _message(created_at: datetime, content: str) -> ChatMessage:
    return ChatMessage(
        id=f"msg-{content}",
        tenant_id=TENANT,
        website_id=WEBSITE,
        session_id=SESSION,
        role=CHAT_ROLE_USER,
        content=content,
        created_at=created_at,
    )


class _FakeCursor:
    """Mirror Mongo's `find().sort().limit()` (first N after sort)."""

    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def sort(self, key: str, direction: int) -> "_FakeCursor":
        reverse = direction < 0
        self._docs = sorted(self._docs, key=lambda doc: doc[key], reverse=reverse)
        return self

    def limit(self, n: int) -> "_FakeCursor":
        self._docs = self._docs[:n]
        return self

    def __aiter__(self) -> "_FakeCursor":
        return self

    async def __anext__(self) -> dict:
        if not self._docs:
            raise StopAsyncIteration
        return self._docs.pop(0)


class _FakeMessageCollection:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def find(self, query: dict) -> _FakeCursor:
        def matches(doc: dict) -> bool:
            return all(doc.get(key) == value for key, value in query.items())

        return _FakeCursor([doc for doc in self._docs if matches(doc)])


class _FakeDb:
    def __init__(self, collection: _FakeMessageCollection) -> None:
        self._collection = collection

    def __getitem__(self, name: str) -> _FakeMessageCollection:
        assert name == "messages"
        return self._collection


def _docs(messages: list[ChatMessage]) -> list[dict]:
    return [message.to_doc() for message in messages]


async def test_list_recent_returns_latest_messages_in_chronological_order() -> None:
    # 12 turns in one session; memory_turns defaults to 8.
    start = datetime(2026, 8, 1, 12, 0, 0)
    messages = [
        _message(start + timedelta(minutes=index), content=f"turn-{index}") for index in range(12)
    ]
    repo = MongoChatMessageRepository(_FakeDb(_FakeMessageCollection(_docs(messages))))

    recent = await repo.list_recent(TENANT, SESSION, limit=8)

    # Latest 8 turns, oldest -> newest.
    assert [m.content for m in recent] == [f"turn-{index}" for index in range(4, 12)]
    # Chronological: created_at is strictly increasing.
    stamps = [m.created_at for m in recent]
    assert stamps == sorted(stamps)
    # The oldest turns are never included.
    assert "turn-0" not in {m.content for m in recent}


async def test_list_recent_returns_all_when_below_limit() -> None:
    start = datetime(2026, 8, 1, 12, 0, 0)
    messages = [
        _message(start + timedelta(minutes=index), content=f"turn-{index}") for index in range(3)
    ]
    repo = MongoChatMessageRepository(_FakeDb(_FakeMessageCollection(_docs(messages))))

    recent = await repo.list_recent(TENANT, SESSION, limit=8)

    assert [m.content for m in recent] == ["turn-0", "turn-1", "turn-2"]


async def test_list_recent_is_tenant_scoped() -> None:
    start = datetime(2026, 8, 1, 12, 0, 0)
    own = _message(start, content="own")
    foreign = ChatMessage(
        id="msg-foreign",
        tenant_id="tenant-b",
        website_id=WEBSITE,
        session_id=SESSION,
        role=CHAT_ROLE_USER,
        content="foreign",
        created_at=start,
    )
    repo = MongoChatMessageRepository(_FakeDb(_FakeMessageCollection(_docs([own, foreign]))))

    recent = await repo.list_recent(TENANT, SESSION, limit=8)

    assert [m.content for m in recent] == ["own"]
