"""Tests for LLM-based RAG answer quality evaluation.

Covers judge response parsing (malformed JSON, markdown fences, missing
keys, out-of-range values, valid responses), score aggregation, missing
response handling, LLM judge with fake generation client, full A/B
evaluation pipeline with both retrieval strategies, report generation,
and benchmark isolation (no I/O, no MongoDB, no network).
"""

from __future__ import annotations

import json

from backend.benchmark.evaluation import SourceInfo
from backend.benchmark.golden import GoldenCase, GoldenDataset
from backend.benchmark.golden_eval import GoldenMetrics
from backend.benchmark.llm_evaluation import (
    AnswerQualityScore,
    LLMJudge,
    LLMQueryResult,
    _build_judge_prompt,
    aggregate_scores,
    compute_llm_ab_report,
    format_llm_ab_report,
    parse_judge_response,
    run_llm_ab_evaluation,
)
from backend.benchmark.retrieval_metrics import RetrievalMetrics
from backend.services.chat.retrieval_strategy import HybridRetrievalStrategy

from tests.chat_helpers import build_chat_env, make_chunk, make_website
from tests.fakes import FakeGenerationClient

TENANT = "llm-eval-tenant"
WEBSITE = "llm-eval-website"


# ---------------------------------------------------------------------------
# parse_judge_response — unit tests
# ---------------------------------------------------------------------------


def test_parse_valid_json() -> None:
    raw = json.dumps({
        "correctness": 0.9,
        "completeness": 0.8,
        "relevance": 0.85,
        "hallucination_risk": 0.1,
        "citation_quality": 0.7,
        "overall_score": 0.82,
        "reasoning": "Good answer with minor gaps.",
    })
    score = parse_judge_response(raw)
    assert score.correctness == 0.9
    assert score.completeness == 0.8
    assert score.relevance == 0.85
    assert score.hallucination_risk == 0.1
    assert score.citation_quality == 0.7
    assert score.overall_score == 0.82
    assert score.reasoning == "Good answer with minor gaps."


def test_parse_json_in_markdown_fences() -> None:
    raw = (
        "```json\n"
        '{"correctness": 0.7, "completeness": 0.6, "relevance": 0.75, '
        '"hallucination_risk": 0.2, "citation_quality": 0.5, '
        '"overall_score": 0.65, "reasoning": "Decent."}\n'
        "```"
    )
    score = parse_judge_response(raw)
    assert score.correctness == 0.7
    assert score.overall_score == 0.65


def test_parse_json_with_surrounding_text() -> None:
    raw = (
        "Here is my evaluation:\n"
        '{"correctness": 0.8, "completeness": 0.9, "relevance": 0.8, '
        '"hallucination_risk": 0.05, "citation_quality": 0.6, '
        '"overall_score": 0.78, "reasoning": "Solid."}\n'
        "Hope this helps!"
    )
    score = parse_judge_response(raw)
    assert score.correctness == 0.8
    assert score.reasoning == "Solid."


def test_parse_empty_response() -> None:
    score = parse_judge_response("")
    assert score.overall_score == 0.0
    assert "empty" in score.reasoning


def test_parse_none_response() -> None:
    score = parse_judge_response("")
    assert score.overall_score == 0.0


def test_parse_garbage_response() -> None:
    score = parse_judge_response("this is not json at all!!!")
    assert score.overall_score == 0.0
    assert "unparseable" in score.reasoning


def test_parse_non_object_json() -> None:
    score = parse_judge_response("[1, 2, 3]")
    assert score.overall_score == 0.0
    assert "non-object" in score.reasoning


def test_parse_missing_keys() -> None:
    raw = json.dumps({"correctness": 0.5, "reasoning": "partial"})
    score = parse_judge_response(raw)
    assert score.correctness == 0.5
    assert score.completeness == 0.0
    assert score.relevance == 0.0
    assert score.hallucination_risk == 0.0
    assert score.citation_quality == 0.0
    assert score.overall_score == 0.0


def test_parse_out_of_range_values_clamped() -> None:
    raw = json.dumps({
        "correctness": 1.5,
        "completeness": -0.3,
        "relevance": 0.5,
        "hallucination_risk": 2.0,
        "citation_quality": 0.5,
        "overall_score": 0.5,
    })
    score = parse_judge_response(raw)
    assert score.correctness == 1.0
    assert score.completeness == 0.0
    assert score.hallucination_risk == 1.0


def test_parse_non_numeric_values_default_zero() -> None:
    raw = json.dumps({
        "correctness": "very good",
        "completeness": None,
        "relevance": 0.5,
        "hallucination_risk": 0.1,
        "citation_quality": 0.5,
        "overall_score": 0.5,
    })
    score = parse_judge_response(raw)
    assert score.correctness == 0.0
    assert score.completeness == 0.0
    assert score.relevance == 0.5


def test_parse_malformed_json_with_valid_brace() -> None:
    raw = (
        'Some text {"correctness": 0.5, "completeness": 0.6, '
        '"relevance": 0.7, "hallucination_risk": 0.1, '
        '"citation_quality": 0.4, "overall_score": 0.55} trailing'
    )
    score = parse_judge_response(raw)
    assert score.correctness == 0.5
    assert score.overall_score == 0.55


# ---------------------------------------------------------------------------
# aggregate_scores — unit tests
# ---------------------------------------------------------------------------


def test_aggregate_empty() -> None:
    result = aggregate_scores([])
    assert result.overall_score == 0.0
    assert result.correctness == 0.0


def test_aggregate_single() -> None:
    s = AnswerQualityScore(
        correctness=0.8, completeness=0.7, relevance=0.9,
        hallucination_risk=0.1, citation_quality=0.6, overall_score=0.75,
    )
    result = aggregate_scores([s])
    assert result.correctness == 0.8
    assert result.overall_score == 0.75
    assert "1 score" in result.reasoning


def test_aggregate_multiple() -> None:
    s1 = AnswerQualityScore(
        correctness=0.6, completeness=0.7, relevance=0.8,
        hallucination_risk=0.2, citation_quality=0.5, overall_score=0.65,
    )
    s2 = AnswerQualityScore(
        correctness=0.8, completeness=0.5, relevance=0.6,
        hallucination_risk=0.1, citation_quality=0.7, overall_score=0.75,
    )
    result = aggregate_scores([s1, s2])
    assert result.correctness == 0.7
    assert result.completeness == 0.6
    assert result.relevance == 0.7
    assert result.hallucination_risk == 0.15
    assert result.citation_quality == 0.6
    assert result.overall_score == 0.7
    assert "2 score" in result.reasoning


# ---------------------------------------------------------------------------
# LLMJudge with FakeGenerationClient
# ---------------------------------------------------------------------------


def _make_fake_judge_client(response_json: dict[str, object]) -> FakeGenerationClient:
    """Create a FakeGenerationClient that returns a canned judge response."""
    return FakeGenerationClient(deltas=[json.dumps(response_json)])


def _make_fake_judge_client_raw(raw_text: str) -> FakeGenerationClient:
    """Create a FakeGenerationClient that returns raw text."""
    return FakeGenerationClient(deltas=[raw_text])


async def test_llm_judge_valid_response() -> None:
    client = _make_fake_judge_client({
        "correctness": 0.9,
        "completeness": 0.8,
        "relevance": 0.85,
        "hallucination_risk": 0.1,
        "citation_quality": 0.7,
        "overall_score": 0.82,
        "reasoning": "Good.",
    })
    judge = LLMJudge(client)
    score = await judge.score_answer(
        question="What is pricing?",
        expected="Should mention plans",
        answer="We have Pro plan at $19/month.",
        sources=[SourceInfo(url="https://example.com/pricing", title="Pricing", score=0.9)],
    )
    assert score.correctness == 0.9
    assert score.overall_score == 0.82


async def test_llm_judge_empty_answer_returns_zero() -> None:
    client = FakeGenerationClient(deltas=[])
    judge = LLMJudge(client)
    score = await judge.score_answer(
        question="test",
        expected="exp",
        answer="",
        sources=[],
    )
    assert score.overall_score == 0.0
    assert "empty answer" in score.reasoning


async def test_llm_judge_whitespace_answer_returns_zero() -> None:
    client = FakeGenerationClient(deltas=[])
    judge = LLMJudge(client)
    score = await judge.score_answer(
        question="test",
        expected="exp",
        answer="   \n  ",
        sources=[],
    )
    assert score.overall_score == 0.0


async def test_llm_judge_malformed_response_returns_zero() -> None:
    client = _make_fake_judge_client_raw("I cannot evaluate this.")
    judge = LLMJudge(client)
    score = await judge.score_answer(
        question="test",
        expected="exp",
        answer="Some answer.",
        sources=[],
    )
    assert score.overall_score == 0.0
    assert "unparseable" in score.reasoning


async def test_llm_judge_exception_returns_zero() -> None:
    client = FakeGenerationClient(deltas=[])
    client.failures.append(RuntimeError("API down"))
    judge = LLMJudge(client)
    score = await judge.score_answer(
        question="test",
        expected="exp",
        answer="Answer text.",
        sources=[],
    )
    assert score.overall_score == 0.0
    assert "failed" in score.reasoning


# ---------------------------------------------------------------------------
# _build_judge_prompt
# ---------------------------------------------------------------------------


def test_build_judge_prompt_contains_all_sections() -> None:
    prompt = _build_judge_prompt(
        question="What is pricing?",
        expected="Should mention plans and prices",
        answer="Pro plan is $19/month.",
        sources=[
            SourceInfo(url="https://example.com/pricing", title="Pricing", score=0.9),
        ],
    )
    assert "What is pricing?" in prompt
    assert "Should mention plans and prices" in prompt
    assert "Pro plan is $19/month." in prompt
    assert "[1] Pricing" in prompt


def test_build_judge_prompt_empty_sources() -> None:
    prompt = _build_judge_prompt(
        question="test",
        expected="exp",
        answer="answer",
        sources=[],
    )
    assert "(none)" in prompt


# ---------------------------------------------------------------------------
# AnswerQualityScore frozen dataclass
# ---------------------------------------------------------------------------


def test_answer_quality_score_defaults() -> None:
    score = AnswerQualityScore()
    assert score.correctness == 0.0
    assert score.completeness == 0.0
    assert score.relevance == 0.0
    assert score.hallucination_risk == 0.0
    assert score.citation_quality == 0.0
    assert score.overall_score == 0.0
    assert score.reasoning == ""


def test_answer_quality_score_frozen() -> None:
    score = AnswerQualityScore(correctness=0.9, overall_score=0.8)
    # Frozen — assignment should raise
    import pytest
    with pytest.raises(AttributeError):
        score.correctness = 0.5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# LLMQueryResult frozen dataclass
# ---------------------------------------------------------------------------


def test_llm_query_result_frozen() -> None:
    r = LLMQueryResult(
        query="test q",
        label="test",
        vector_answer="v answer",
        vector_sources=[],
        vector_score=AnswerQualityScore(overall_score=0.7),
        vector_golden=GoldenMetrics(overall_quality_score=0.6),
        vector_retrieval=RetrievalMetrics(precision_at_k=0.8),
        vector_latency_ms=100.0,
        hybrid_answer="h answer",
        hybrid_sources=[],
        hybrid_score=AnswerQualityScore(overall_score=0.8),
        hybrid_golden=GoldenMetrics(overall_quality_score=0.7),
        hybrid_retrieval=RetrievalMetrics(precision_at_k=0.9),
        hybrid_latency_ms=110.0,
        judge_latency_ms=500.0,
    )
    assert r.query == "test q"
    assert r.vector_score.overall_score == 0.7
    assert r.hybrid_score.overall_score == 0.8


# ---------------------------------------------------------------------------
# compute_llm_ab_report — pure function tests
# ---------------------------------------------------------------------------


def _make_llm_result(
    *,
    label: str = "q1",
    v_overall: float = 0.6,
    h_overall: float = 0.8,
    v_correctness: float | None = None,
    h_correctness: float | None = None,
    v_completeness: float | None = None,
    h_completeness: float | None = None,
    v_relevance: float | None = None,
    h_relevance: float | None = None,
    v_hallucination_risk: float | None = None,
    h_hallucination_risk: float | None = None,
    v_citation_quality: float | None = None,
    h_citation_quality: float | None = None,
    v_latency: float = 100.0,
    h_latency: float = 110.0,
    v_golden: float = 0.5,
    h_golden: float = 0.7,
) -> LLMQueryResult:
    v_h_risk = (
        v_hallucination_risk if v_hallucination_risk is not None
        else (1.0 - v_overall)
    )
    v_cite = (
        v_citation_quality if v_citation_quality is not None else v_overall
    )
    h_h_risk = (
        h_hallucination_risk if h_hallucination_risk is not None
        else (1.0 - h_overall)
    )
    h_cite = (
        h_citation_quality if h_citation_quality is not None else h_overall
    )
    return LLMQueryResult(
        query=f"question for {label}",
        label=label,
        vector_answer="v answer",
        vector_sources=[],
        vector_score=AnswerQualityScore(
            correctness=v_correctness if v_correctness is not None else v_overall,
            completeness=v_completeness if v_completeness is not None else v_overall,
            relevance=v_relevance if v_relevance is not None else v_overall,
            hallucination_risk=v_h_risk,
            citation_quality=v_cite,
            overall_score=v_overall,
        ),
        vector_golden=GoldenMetrics(overall_quality_score=v_golden),
        vector_retrieval=RetrievalMetrics(),
        vector_latency_ms=v_latency,
        hybrid_answer="h answer",
        hybrid_sources=[],
        hybrid_score=AnswerQualityScore(
            correctness=h_correctness if h_correctness is not None else h_overall,
            completeness=h_completeness if h_completeness is not None else h_overall,
            relevance=h_relevance if h_relevance is not None else h_overall,
            hallucination_risk=h_h_risk,
            citation_quality=h_cite,
            overall_score=h_overall,
        ),
        hybrid_golden=GoldenMetrics(overall_quality_score=h_golden),
        hybrid_retrieval=RetrievalMetrics(),
        hybrid_latency_ms=h_latency,
        judge_latency_ms=500.0,
    )


def test_llm_ab_report_empty() -> None:
    report = compute_llm_ab_report([])
    assert report.query_count == 0
    assert report.recommendation == "No queries evaluated."


def test_llm_ab_report_single() -> None:
    r = _make_llm_result(v_overall=0.6, h_overall=0.8)
    report = compute_llm_ab_report([r])
    assert report.query_count == 1
    assert report.vector_mean.overall_score == 0.6
    assert report.hybrid_mean.overall_score == 0.8
    assert report.overall_delta == 0.2


def test_llm_ab_report_multiple_averages() -> None:
    r1 = _make_llm_result(label="q1", v_overall=0.5, h_overall=0.7)
    r2 = _make_llm_result(label="q2", v_overall=0.7, h_overall=0.9)
    report = compute_llm_ab_report([r1, r2])
    assert report.vector_mean.overall_score == 0.6
    assert report.hybrid_mean.overall_score == 0.8
    assert report.overall_delta == 0.2


def test_llm_ab_report_latency() -> None:
    r1 = _make_llm_result(v_latency=100.0, h_latency=120.0)
    r2 = _make_llm_result(v_latency=200.0, h_latency=220.0)
    report = compute_llm_ab_report([r1, r2])
    assert report.vector_latency_mean == 150.0
    assert report.hybrid_latency_mean == 170.0
    assert report.latency_delta_ms == 20.0


def test_llm_ab_report_golden_improvement() -> None:
    r1 = _make_llm_result(v_golden=0.5, h_golden=0.7)
    r2 = _make_llm_result(v_golden=0.5, h_golden=0.7)
    report = compute_llm_ab_report([r1, r2])
    assert report.vector_golden_mean == 0.5
    assert report.hybrid_golden_mean == 0.7
    assert report.golden_improvement_pct == 40.0


def test_llm_ab_report_recommendation_recommends() -> None:
    r = _make_llm_result(v_overall=0.5, h_overall=0.8)
    report = compute_llm_ab_report([r])
    assert "RECOMMEND" in report.recommendation


def test_llm_ab_report_recommendation_do_not_enable() -> None:
    r = _make_llm_result(v_overall=0.9, h_overall=0.5)
    report = compute_llm_ab_report([r])
    assert "DO NOT ENABLE" in report.recommendation


def test_llm_ab_report_recommendation_neutral() -> None:
    r = _make_llm_result(v_overall=0.7, h_overall=0.71)
    report = compute_llm_ab_report([r])
    assert "NEUTRAL" in report.recommendation


def test_llm_ab_report_mixed_recommendation() -> None:
    r = _make_llm_result(
        v_overall=0.5, h_overall=0.8,
        v_correctness=0.9, h_correctness=0.5,
    )
    report = compute_llm_ab_report([r])
    assert "MIXED" in report.recommendation


def test_llm_ab_report_per_query() -> None:
    r1 = _make_llm_result(label="q1")
    r2 = _make_llm_result(label="q2")
    report = compute_llm_ab_report([r1, r2])
    assert len(report.per_query) == 2
    assert report.per_query[0].label == "q1"
    assert report.per_query[1].label == "q2"


# ---------------------------------------------------------------------------
# format_llm_ab_report — string output
# ---------------------------------------------------------------------------


def test_format_llm_ab_report_empty() -> None:
    report = compute_llm_ab_report([])
    text = format_llm_ab_report(report)
    assert "LLM-Judged" in text
    assert "No queries evaluated" in text


def test_format_llm_ab_report_structure() -> None:
    r = _make_llm_result(label="pricing_q")
    report = compute_llm_ab_report([r])
    text = format_llm_ab_report(report)
    assert "LLM Quality Scores" in text
    assert "Golden Quality" in text
    assert "Latency" in text
    assert "Per-Query Breakdown" in text
    assert "Recommendation" in text
    assert "pricing_q" in text


def test_format_llm_ab_report_recommends() -> None:
    r = _make_llm_result(v_overall=0.5, h_overall=0.8)
    report = compute_llm_ab_report([r])
    text = format_llm_ab_report(report)
    assert "RECOMMEND" in text


def test_format_llm_ab_report_hallucination_note() -> None:
    r = _make_llm_result()
    report = compute_llm_ab_report([r])
    text = format_llm_ab_report(report)
    assert "lower is better" in text


# ---------------------------------------------------------------------------
# Benchmark isolation — e2e with both retrieval strategies
# ---------------------------------------------------------------------------


async def test_llm_ab_evaluation_end_to_end() -> None:
    """Full pipeline: seed data, run both strategies, judge, report."""
    judge_client_json = {
        "correctness": 0.85,
        "completeness": 0.75,
        "relevance": 0.9,
        "hallucination_risk": 0.1,
        "citation_quality": 0.6,
        "overall_score": 0.8,
        "reasoning": "Good answer.",
    }

    # Vector env
    v_env = build_chat_env(deltas=["The", " Pro", " plan", " is", " $19", "."])
    await make_website(v_env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=2)
    await make_chunk(
        v_env, tenant_id=TENANT, website_id=WEBSITE,
        text="Pro plan costs $19 per month.",
        url="https://example.com/pricing", title="Pricing", chunk_index=0,
    )
    await make_chunk(
        v_env, tenant_id=TENANT, website_id=WEBSITE,
        text="Enterprise includes SSO.",
        url="https://example.com/enterprise", title="Enterprise", chunk_index=1,
    )

    # Hybrid env (separate RagService with hybrid strategy)
    h_env = build_chat_env(deltas=["The", " Pro", " plan", " is", " $19", "."])
    await make_website(h_env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=2)
    await make_chunk(
        h_env, tenant_id=TENANT, website_id=WEBSITE,
        text="Pro plan costs $19 per month.",
        url="https://example.com/pricing", title="Pricing", chunk_index=0,
    )
    await make_chunk(
        h_env, tenant_id=TENANT, website_id=WEBSITE,
        text="Enterprise includes SSO.",
        url="https://example.com/enterprise", title="Enterprise", chunk_index=1,
    )

    # Replace rag in h_env with hybrid-strategy rag
    hybrid_rag = type(v_env.rag)(
        websites=h_env.websites,
        vector=h_env.vector,
        embedder=h_env.embedder,  # type: ignore[arg-type]
        generation=h_env.generation,
        sessions=h_env.sessions,
        messages=h_env.messages,
        usage=h_env.usage,  # type: ignore[arg-type]
        cache=h_env.cache,
        retrieval_strategy=HybridRetrievalStrategy(rrf_k=60),
    )
    h_env.rag = hybrid_rag

    case = GoldenCase(
        question="What pricing plans do you offer?",
        label="pricing_plans",
        expected_keywords=["plan", "price"],
        expected_sources=["/pricing"],
        min_answer_length=10,
        expected_concepts=["pricing", "plans"],
    )

    judge_client = _make_fake_judge_client(judge_client_json)
    judge = LLMJudge(judge_client)

    results = await run_llm_ab_evaluation(
        vector_rag=v_env.rag,
        hybrid_rag=h_env.rag,
        judge=judge,
        golden_dataset=GoldenDataset(cases=[case]),
        tenant_id=TENANT,
        website_id=WEBSITE,
        top_k=2,
    )

    assert len(results) == 1
    qr = results[0]
    assert qr.label == "pricing_plans"
    assert qr.vector_score.overall_score == 0.8
    assert qr.hybrid_score.overall_score == 0.8
    assert qr.vector_latency_ms > 0
    assert qr.hybrid_latency_ms > 0
    assert qr.judge_latency_ms > 0

    report = compute_llm_ab_report(results)
    assert report.query_count == 1
    text = format_llm_ab_report(report)
    assert "LLM Quality Scores" in text


async def test_llm_ab_evaluation_empty_dataset() -> None:
    """Empty golden dataset yields empty results."""
    judge = LLMJudge(FakeGenerationClient(deltas=[]))
    v_env = build_chat_env()
    h_env = build_chat_env()

    results = await run_llm_ab_evaluation(
        vector_rag=v_env.rag,
        hybrid_rag=h_env.rag,
        judge=judge,
        golden_dataset=GoldenDataset(cases=[]),
        tenant_id=TENANT,
        website_id=WEBSITE,
    )
    assert results == []


async def test_llm_ab_evaluation_fallback_no_chunks() -> None:
    """With no chunks, both pipelines fall back — judge still scores."""
    judge_client_json = {
        "correctness": 0.2,
        "completeness": 0.1,
        "relevance": 0.3,
        "hallucination_risk": 0.0,
        "citation_quality": 0.0,
        "overall_score": 0.15,
        "reasoning": "Empty KB fallback.",
    }

    v_env = build_chat_env()
    await make_website(v_env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=0)
    h_env = build_chat_env()
    await make_website(h_env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=0)

    judge_client = _make_fake_judge_client(judge_client_json)
    judge = LLMJudge(judge_client)

    case = GoldenCase(
        question="test?",
        label="fallback_q",
        expected_keywords=[],
        expected_sources=[],
        min_answer_length=0,
    )

    results = await run_llm_ab_evaluation(
        vector_rag=v_env.rag,
        hybrid_rag=h_env.rag,
        judge=judge,
        golden_dataset=GoldenDataset(cases=[case]),
        tenant_id=TENANT,
        website_id=WEBSITE,
    )
    assert len(results) == 1
    assert results[0].vector_retrieval.total_chunks_retrieved == 0
    assert results[0].vector_score.overall_score == 0.15


# ---------------------------------------------------------------------------
# __all__ exports
# ---------------------------------------------------------------------------


def test_module_all() -> None:
    from backend.benchmark import llm_evaluation as mod
    assert hasattr(mod, "AnswerQualityScore")
    assert hasattr(mod, "LLMABReport")
    assert hasattr(mod, "LLMJudge")
    assert hasattr(mod, "LLMQueryResult")
    assert hasattr(mod, "aggregate_scores")
    assert hasattr(mod, "compute_llm_ab_report")
    assert hasattr(mod, "format_llm_ab_report")
    assert hasattr(mod, "parse_judge_response")
    assert hasattr(mod, "run_llm_ab_evaluation")


def test_benchmark_init_exports() -> None:
    from backend.benchmark import (
        AnswerQualityScore,
        LLMABReport,
        LLMJudge,
        LLMQueryResult,
        aggregate_scores,
        compute_llm_ab_report,
        format_llm_ab_report,
        parse_judge_response,
        run_llm_ab_evaluation,
    )
    assert AnswerQualityScore is not None
    assert LLMABReport is not None
    assert LLMJudge is not None
    assert LLMQueryResult is not None
    assert aggregate_scores is not None
    assert compute_llm_ab_report is not None
    assert format_llm_ab_report is not None
    assert parse_judge_response is not None
    assert run_llm_ab_evaluation is not None
