"""Phase 1 cost tracking tests (ADR-005 §5.5 rollups, docs/07 observability).

Covers the pure rate-card math (`backend/services/billing/pricing.py`), the
end-to-end persistence of token/cost/model telemetry through
`RagService.stream_answer` (assistant message fields, `done` event payload,
daily `usage_records` rollup), non-billability of failed generations, and the
tenant/website cost aggregations (fake + Mongo-shaped repositories).
"""

import logging
from unittest.mock import patch

import pytest
from backend.core.config import get_settings
from backend.core.errors import GenerationError
from backend.models.chat_message import CHAT_ROLE_ASSISTANT, CHAT_ROLE_USER
from backend.repositories.usage_record_repository import (
    MongoUsageRecordRepository,
    TenantUsageSummary,
)
from backend.services.billing.pricing import (
    DEFAULT_RATE_CARD,
    ModelPrice,
    dollars_to_micros,
    estimate_embedding_cost,
    estimate_generation_cost,
    get_model_price,
    load_rate_card,
    micros_to_dollars,
)

from tests.chat_helpers import (
    build_chat_env,
    consume,
    make_chunk,
    make_website,
)

TENANT_A = "tenant-a"
WEB_1 = "web-1"

# Rates chosen so the math is easy to verify by hand:
# 10 input * $1/M + 20 output * $3/M = 10e-6 + 60e-6 = 70e-6 USD = 70 micros.
FAKE_MODEL_PRICING = '{"fake-model": {"input_per_million": 1.0, "output_per_million": 3.0}}'


async def _stream(env, **kwargs):
    return await consume(env.rag.stream_answer(**kwargs))


def _done(events):
    return next(event for event in events if event["event"] == "done")


async def _seed_answerable_website(env) -> None:
    await make_website(env, tenant_id=TENANT_A, website_id=WEB_1, knowledge_chunks=1)
    await make_chunk(env, tenant_id=TENANT_A, website_id=WEB_1, text="We offer Pro plans.")


# ---------------------------------------------------------------------------
# Pure pricing math
# ---------------------------------------------------------------------------


def test_estimate_generation_cost_matches_hand_computation() -> None:
    price = ModelPrice(input_per_million=0.30, output_per_million=2.50)
    # 10 * 0.30 / 1e6 + 20 * 2.50 / 1e6 = 3e-6 + 50e-6 = 53e-6 USD.
    assert estimate_generation_cost(price, input_tokens=10, output_tokens=20) == pytest.approx(
        53e-6
    )


def test_zero_tokens_cost_nothing() -> None:
    price = ModelPrice(input_per_million=5.0, output_per_million=5.0)
    assert estimate_generation_cost(price, input_tokens=0, output_tokens=0) == 0.0
    assert estimate_embedding_cost(price, tokens=0) == 0.0
    assert dollars_to_micros(0.0) == 0


def test_micro_dollar_conversion_roundtrips() -> None:
    assert dollars_to_micros(53e-6) == 53
    assert micros_to_dollars(53) == pytest.approx(53e-6)
    assert micros_to_dollars(dollars_to_micros(1.234567)) == pytest.approx(1.234567)


def test_load_rate_card_defaults_include_gemini_flash() -> None:
    card = load_rate_card(None)
    assert card["gemini-2.5-flash"] == DEFAULT_RATE_CARD["gemini-2.5-flash"]
    assert card["gemini-2.5-flash"].input_per_million > 0


def test_load_rate_card_overrides_merge_partially() -> None:
    # Overriding one rate keeps the other built-in rate for a known model...
    card = load_rate_card('{"gemini-2.5-flash": {"input_per_million": 9.0}}')
    assert card["gemini-2.5-flash"].input_per_million == 9.0
    assert card["gemini-2.5-flash"].output_per_million == (
        DEFAULT_RATE_CARD["gemini-2.5-flash"].output_per_million
    )
    # ...while an unknown model starts from zero for unspecified rates.
    card = load_rate_card('{"mystery": {"output_per_million": 2.0}}')
    assert card["mystery"] == ModelPrice(0.0, 2.0)


def test_get_model_price_prefers_explicit_over_wildcard() -> None:
    card = load_rate_card('{"*": {"input_per_million": 1.0}, "x": {"input_per_million": 2.0}}')
    assert get_model_price(card, "x").input_per_million == 2.0
    assert get_model_price(card, "other").input_per_million == 1.0
    assert get_model_price(load_rate_card(None), "unknown-model") is None


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        '["list"]',
        '{"m": "scalar"}',
        '{"m": {"input_per_million": -1}}',
        '{"m": {"output_per_million": "free"}}',
    ],
)
def test_load_rate_card_rejects_malformed_config(raw: str) -> None:
    with pytest.raises(ValueError):
        load_rate_card(raw)


def test_build_chat_env_fails_fast_on_bad_pricing_json() -> None:
    with (
        patch.object(get_settings(), "ai_model_pricing_json", "{oops"),
        pytest.raises(ValueError, match="AI_MODEL_PRICING_JSON"),
    ):
        build_chat_env()


# ---------------------------------------------------------------------------
# End-to-end persistence through stream_answer
# ---------------------------------------------------------------------------


async def test_stream_persists_tokens_cost_and_model() -> None:
    with patch.object(get_settings(), "ai_model_pricing_json", FAKE_MODEL_PRICING):
        env = build_chat_env()
    await _seed_answerable_website(env)

    events = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question="Plans?")

    # 10 input * $1/M + 20 output * $3/M = 70 micro-dollars.
    done = _done(events)
    assert done["data"]["total_tokens"] == 30
    assert done["data"]["estimated_cost"] == pytest.approx(70e-6)
    assert done["data"]["model_name"] == "fake-model"

    _user, assistant = env.messages.messages
    assert assistant.role == CHAT_ROLE_ASSISTANT
    assert assistant.input_tokens == 10 and assistant.output_tokens == 20
    assert assistant.total_tokens == 30
    assert assistant.estimated_cost == pytest.approx(70e-6)
    assert assistant.model_name == "fake-model"

    record = env.usage.records[0]
    assert record.counters["input_tokens"] == 10
    assert record.counters["output_tokens"] == 20
    assert record.counters["estimated_cost_micros"] == 70


async def test_zero_token_generation_costs_zero() -> None:
    with patch.object(get_settings(), "ai_model_pricing_json", FAKE_MODEL_PRICING):
        env = build_chat_env()
    await _seed_answerable_website(env)
    env.generation.input_tokens = 0
    env.generation.output_tokens = 0

    events = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question="Plans?")

    done = _done(events)
    assert done["data"]["input_tokens"] == 0
    assert done["data"]["output_tokens"] == 0
    assert done["data"]["total_tokens"] == 0
    assert done["data"]["estimated_cost"] == 0.0

    _, assistant = env.messages.messages
    assert assistant.total_tokens == 0
    assert assistant.estimated_cost == 0.0
    assert env.usage.records[0].counters.get("estimated_cost_micros", 0) == 0


async def test_failed_generation_is_not_billed() -> None:
    with patch.object(get_settings(), "ai_model_pricing_json", FAKE_MODEL_PRICING):
        env = build_chat_env()
    await _seed_answerable_website(env)
    env.generation.failures = [GenerationError("model exploded")]

    events = await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question="Plans?")

    assert events[-1]["event"] == "error"
    assert events[-1]["data"]["code"] == "GENERATION_FAILED"
    # Only the user turn persisted; no usage rollup (and therefore no cost).
    assert len(env.messages.messages) == 1
    assert env.messages.messages[0].role == CHAT_ROLE_USER
    assert env.usage.records == []


async def test_models_with_different_rates_accrue_different_costs() -> None:
    premium = '{"fake-model": {"input_per_million": 2.0, "output_per_million": 4.0}}'
    budget = '{"*": {"input_per_million": 1.0, "output_per_million": 1.0}}'

    with patch.object(get_settings(), "ai_model_pricing_json", premium):
        env_premium = build_chat_env()
    with patch.object(get_settings(), "ai_model_pricing_json", budget):
        env_budget = build_chat_env()
    await _seed_answerable_website(env_premium)
    await _seed_answerable_website(env_budget)

    await _stream(env_premium, tenant_id=TENANT_A, website_id=WEB_1, question="Plans?")
    await _stream(env_budget, tenant_id=TENANT_A, website_id=WEB_1, question="Plans?")

    premium_cost = env_premium.messages.messages[-1].estimated_cost
    budget_cost = env_budget.messages.messages[-1].estimated_cost
    # Same 10/20 tokens: premium = 20+80=100 micros, budget = 10+20=30 micros.
    assert premium_cost == pytest.approx(100e-6)
    assert budget_cost == pytest.approx(30e-6)
    assert env_premium.usage.records[0].counters["estimated_cost_micros"] == 100
    assert env_budget.usage.records[0].counters["estimated_cost_micros"] == 30


async def test_unpriced_model_costs_zero_but_warns_once(caplog) -> None:
    """Default rate card has no row for the fake model: cost accrues at 0."""
    env = build_chat_env()
    await _seed_answerable_website(env)

    with caplog.at_level(logging.WARNING):
        await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question="First?")
        await _stream(env, tenant_id=TENANT_A, website_id=WEB_1, question="Second?")

    warnings = [r for r in caplog.records if "cost_unpriced_model" in r.getMessage()]
    assert len(warnings) == 1
    for message in env.messages.messages:
        if message.role == CHAT_ROLE_ASSISTANT:
            assert message.estimated_cost == 0.0
            assert message.model_name == "fake-model"
    for record in env.usage.records:
        assert record.counters.get("estimated_cost_micros", 0) == 0


# ---------------------------------------------------------------------------
# Tenant / website cost aggregations
# ---------------------------------------------------------------------------


async def test_sum_by_tenant_and_by_website_aggregate_cost() -> None:
    with patch.object(get_settings(), "ai_model_pricing_json", FAKE_MODEL_PRICING):
        env = build_chat_env()
    usage = env.usage
    await usage.increment(
        tenant_id=TENANT_A,
        website_id="web-1",
        date="2026-08-01",
        counters={
            "chats": 1,
            "messages": 2,
            "input_tokens": 10,
            "output_tokens": 20,
            "estimated_cost_micros": 100,
        },
    )
    await usage.increment(
        tenant_id=TENANT_A,
        website_id="web-2",
        date="2026-08-01",
        counters={"chats": 1, "messages": 2, "estimated_cost_micros": 250},
    )
    await usage.increment(
        tenant_id="tenant-b",
        website_id="web-9",
        date="2026-08-02",
        counters={"chats": 1, "messages": 2, "estimated_cost_micros": 999},
    )

    tenant_total = await usage.sum_by_tenant(TENANT_A)
    assert tenant_total.chats == 2
    assert tenant_total.messages == 4
    assert tenant_total.input_tokens == 10
    assert tenant_total.output_tokens == 20
    assert tenant_total.estimated_cost_micros == 350
    assert tenant_total.estimated_cost_usd == pytest.approx(350e-6)

    web_total = await usage.sum_by_website(TENANT_A, "web-2")
    assert web_total.chats == 1
    assert web_total.estimated_cost_micros == 250

    empty = await usage.sum_by_website(TENANT_A, "web-missing")
    assert empty.estimated_cost_micros == 0
    assert empty.estimated_cost_usd == 0.0


class _FakeAggregateCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def __aiter__(self) -> "_FakeAggregateCursor":
        return self

    async def __anext__(self) -> dict:
        if not self._docs:
            raise StopAsyncIteration
        return self._docs.pop(0)


class _FakeUsageCollection:
    """Mongo-shaped collection evaluating `$match` then `$group` sums."""

    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def _matches(self, query: dict, doc: dict) -> bool:
        return all(doc.get(key) == value for key, value in query.items())

    def aggregate(self, pipeline: list[dict]) -> "_FakeAggregateCursor":
        selected = [doc for doc in self._docs if self._matches(pipeline[0]["$match"], doc)]
        group_stage = pipeline[1]["$group"]
        result: dict = {"_id": None}
        for field, spec in group_stage.items():
            if field == "_id":
                continue
            source = spec["$sum"].lstrip("$").split(".")[-1]  # "counters.chats" -> "chats"
            result[field] = sum(doc.get("counters", {}).get(source, 0) for doc in selected)
        return _FakeAggregateCursor([result])


class _FakeUsageDatabase:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def __getitem__(self, name: str) -> _FakeUsageCollection:
        return _FakeUsageCollection(self._docs)


def _doc(tenant: str, website: str, micros: int) -> dict:
    return {
        "tenant_id": tenant,
        "website_id": website,
        "counters": {"messages": 2, "input_tokens": 5, "estimated_cost_micros": micros},
    }


async def test_mongo_summary_aggregations_match_contract() -> None:
    db = _FakeUsageDatabase(
        [_doc(TENANT_A, "web-1", 100), _doc(TENANT_A, "web-2", 250), _doc("t-b", "w", 999)]
    )
    repo = MongoUsageRecordRepository(db)  # type: ignore[arg-type]

    by_tenant = await repo.sum_by_tenant(TENANT_A)
    assert by_tenant.estimated_cost_micros == 350
    assert by_tenant.input_tokens == 10
    assert by_tenant.messages == 4

    by_website = await repo.sum_by_website(TENANT_A, "web-1")
    assert by_website.estimated_cost_micros == 100
    assert by_website.input_tokens == 5

    empty_db = MongoUsageRecordRepository(_FakeUsageDatabase([]))  # type: ignore[arg-type]
    empty = await empty_db.sum_by_tenant("nobody")
    assert empty == TenantUsageSummary(chats=0, messages=0, input_tokens=0, output_tokens=0)
    assert empty.estimated_cost_micros == 0
    assert empty.estimated_cost_usd == 0.0
