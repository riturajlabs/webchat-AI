"""LLM-based RAG answer quality evaluation (Phase 7).

Uses a real LLM (Gemini) as a judge to evaluate answer quality across six
dimensions: correctness, completeness, relevance, hallucination risk,
citation quality, and overall quality.  Compares vector-only vs hybrid
retrieval by running each through the full RAG pipeline and scoring the
generated answers.

The judge prompt is designed to produce parseable JSON.  All parsing is
fault-tolerant: malformed responses yield a zero-scored fallback rather
than raising, so the benchmark can continue even when the judge misbehaves.

All operations are isolated — no production state mutation.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.ai.gemini import GenerationClient
from backend.benchmark.evaluation import SourceInfo
from backend.benchmark.golden import GoldenCase, GoldenDataset
from backend.benchmark.golden_eval import GoldenMetrics, evaluate_golden
from backend.benchmark.retrieval_metrics import RetrievalMetrics

# ---------------------------------------------------------------------------
# Score dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnswerQualityScore:
    """Six-dimensional quality score produced by the LLM judge.

    All scores are in [0.0, 1.0].  ``hallucination_risk`` is a *risk*
    metric — lower is better.  ``overall_score`` is the judge's aggregate
    quality assessment.
    """

    correctness: float = 0.0
    completeness: float = 0.0
    relevance: float = 0.0
    hallucination_risk: float = 0.0
    citation_quality: float = 0.0
    overall_score: float = 0.0
    reasoning: str = ""


# ---------------------------------------------------------------------------
# Judge prompt and parsing
# ---------------------------------------------------------------------------

_JUDGE_SYSTEM = """\
You are an expert evaluator of AI-generated answers for a RAG (Retrieval \
Augmented Generation) chatbot. You will be given a user question, the \
retrieved context, the expected answer characteristics, and the actual \
answer produced by the system.

Rate the answer on these dimensions (each 0.0 to 1.0, where 1.0 is best):
- correctness: factual accuracy given the context
- completeness: coverage of the expected information
- relevance: how well the answer addresses the user's question
- hallucination_risk: likelihood the answer contains fabricated information \
(lower is better)
- citation_quality: how well the answer references source material
- overall_score: your aggregate quality assessment

Return ONLY a JSON object with exactly these keys:
{
  "correctness": 0.0,
  "completeness": 0.0,
  "relevance": 0.0,
  "hallucination_risk": 0.0,
  "citation_quality": 0.0,
  "overall_score": 0.0,
  "reasoning": "brief explanation"
}

No markdown, no extra text — just the JSON object."""

_REQUIRED_KEYS = {
    "correctness",
    "completeness",
    "relevance",
    "hallucination_risk",
    "citation_quality",
    "overall_score",
}


def _build_judge_prompt(
    *,
    question: str,
    expected: str,
    answer: str,
    sources: list[SourceInfo],
) -> str:
    source_list = (
        "\n".join(
            f"  [{i}] {s.title or 'Untitled'} — {s.url} (score={s.score:.3f})"
            for i, s in enumerate(sources, 1)
        )
        or "  (none)"
    )

    return (
        f"## User Question\n{question}\n\n"
        f"## Retrieved Context\n{source_list}\n\n"
        f"## Expected Answer Characteristics\n{expected}\n\n"
        f"## System Answer\n{answer or '(empty)'}\n\n"
        "Rate the system answer against the expected characteristics. "
        "Return ONLY the JSON object."
    )


def parse_judge_response(raw: str) -> AnswerQualityScore:
    """Parse the LLM judge's JSON response into an AnswerQualityScore.

    Handles:
    - Markdown code fences (```json ... ```)
    - Trailing/leading whitespace
    - Missing keys (defaults to 0.0)
    - Out-of-range values (clamped to [0.0, 1.0])
    - Completely unparseable responses (returns zero score)
    """
    if not raw or not raw.strip():
        return AnswerQualityScore(reasoning="empty judge response")

    text = raw.strip()

    # Strip markdown code fences.
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    # Find the first { ... } block in case there's surrounding text.
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        text = brace_match.group(0)

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return AnswerQualityScore(reasoning=f"unparseable judge response: {text[:200]}")

    if not isinstance(data, dict):
        return AnswerQualityScore(reasoning="judge returned non-object")

    reasoning = str(data.get("reasoning", ""))

    # Extract and clamp each score.
    scores: dict[str, float] = {}
    for key in _REQUIRED_KEYS:
        raw_val = data.get(key, 0.0)
        try:
            val = float(raw_val)
        except (TypeError, ValueError):
            val = 0.0
        scores[key] = max(0.0, min(1.0, val))

    return AnswerQualityScore(
        correctness=scores["correctness"],
        completeness=scores["completeness"],
        relevance=scores["relevance"],
        hallucination_risk=scores["hallucination_risk"],
        citation_quality=scores["citation_quality"],
        overall_score=scores["overall_score"],
        reasoning=reasoning,
    )


def aggregate_scores(scores: list[AnswerQualityScore]) -> AnswerQualityScore:
    """Compute the mean of each dimension across multiple judge scores.

    Returns a single ``AnswerQualityScore`` with averaged values and a
    combined reasoning string.
    """
    if not scores:
        return AnswerQualityScore()

    n = len(scores)

    def _mean(getter: Callable[[AnswerQualityScore], float]) -> float:
        vals = [getter(s) for s in scores]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    return AnswerQualityScore(
        correctness=_mean(lambda s: s.correctness),
        completeness=_mean(lambda s: s.completeness),
        relevance=_mean(lambda s: s.relevance),
        hallucination_risk=_mean(lambda s: s.hallucination_risk),
        citation_quality=_mean(lambda s: s.citation_quality),
        overall_score=_mean(lambda s: s.overall_score),
        reasoning=f"aggregated from {n} score(s)",
    )


# ---------------------------------------------------------------------------
# LLM Judge
# ---------------------------------------------------------------------------


class LLMJudge:
    """Evaluates RAG answer quality using a real LLM as judge.

    Parameters
    ----------
    client:
        A ``GenerationClient`` (real ``GoogleGeminiClient`` for production
        benchmarks, or ``FakeGenerationClient`` for tests).
    """

    def __init__(self, client: GenerationClient) -> None:
        self._client = client

    async def score_answer(
        self,
        *,
        question: str,
        expected: str,
        answer: str,
        sources: list[SourceInfo],
    ) -> AnswerQualityScore:
        """Score a single RAG answer using the LLM judge.

        Returns a zero-scored fallback if the judge fails or returns
        unparseable output — never raises.
        """
        if not answer or not answer.strip():
            return AnswerQualityScore(reasoning="empty answer — nothing to judge")

        prompt = _build_judge_prompt(
            question=question,
            expected=expected,
            answer=answer,
            sources=sources,
        )

        try:
            chunks: list[str] = []
            async for delta in self._client.stream_generate(
                system=_JUDGE_SYSTEM,
                messages=[("user", prompt)],
            ):
                chunks.append(delta)
            raw = "".join(chunks)
        except Exception as exc:  # noqa: BLE001
            return AnswerQualityScore(reasoning=f"judge call failed: {type(exc).__name__}: {exc}")

        return parse_judge_response(raw)


# ---------------------------------------------------------------------------
# LLM A/B result and report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMQueryResult:
    """Per-query comparison of vector vs hybrid with LLM-judged quality."""

    query: str
    label: str
    # Vector path
    vector_answer: str
    vector_sources: list[SourceInfo]
    vector_score: AnswerQualityScore
    vector_golden: GoldenMetrics
    vector_retrieval: RetrievalMetrics
    vector_latency_ms: float
    # Hybrid path
    hybrid_answer: str
    hybrid_sources: list[SourceInfo]
    hybrid_score: AnswerQualityScore
    hybrid_golden: GoldenMetrics
    hybrid_retrieval: RetrievalMetrics
    hybrid_latency_ms: float
    # Judge latency
    judge_latency_ms: float


@dataclass
class LLMABReport:
    """Aggregated LLM-judged A/B report across all queries."""

    query_count: int = 0
    # Mean quality scores
    vector_mean: AnswerQualityScore = field(default_factory=AnswerQualityScore)
    hybrid_mean: AnswerQualityScore = field(default_factory=AnswerQualityScore)
    # Score deltas (hybrid - vector)
    correctness_delta: float = 0.0
    completeness_delta: float = 0.0
    relevance_delta: float = 0.0
    hallucination_risk_delta: float = 0.0
    citation_quality_delta: float = 0.0
    overall_delta: float = 0.0
    # Golden quality (mean)
    vector_golden_mean: float = 0.0
    hybrid_golden_mean: float = 0.0
    golden_improvement_pct: float = 0.0
    # Latency
    vector_latency_mean: float = 0.0
    hybrid_latency_mean: float = 0.0
    latency_delta_ms: float = 0.0
    judge_latency_mean: float = 0.0
    # Per-query
    per_query: list[LLMQueryResult] = field(default_factory=list)
    # Recommendation
    recommendation: str = ""


# ---------------------------------------------------------------------------
# Single-query evaluation
# ---------------------------------------------------------------------------


async def evaluate_single_query(
    *,
    vector_rag: Any,
    hybrid_rag: Any,
    judge: LLMJudge,
    golden_case: GoldenCase,
    tenant_id: str,
    website_id: str,
    top_k: int = 5,
) -> LLMQueryResult:
    """Run both pipelines and LLM-judge the answers for one query.

    Parameters
    ----------
    vector_rag:
        ``RagService`` configured with ``VectorRetrievalStrategy``.
    hybrid_rag:
        ``RagService`` configured with ``HybridRetrievalStrategy``.
    judge:
        The LLM judge for answer quality scoring.
    golden_case:
        The golden case providing expected keywords/sources/concepts.
    """
    from tests.chat_helpers import consume

    question = golden_case.question
    label = golden_case.short_label

    # --- Vector path ---
    v_started = time.perf_counter()
    v_answer_parts: list[str] = []
    v_sources: list[SourceInfo] = []
    try:
        stream = vector_rag.stream_answer(
            tenant_id=tenant_id,
            website_id=website_id,
            question=question,
        )
        events = await consume(stream)
        for event in events:
            ev = event.get("event")
            if ev == "error":
                break
            if ev == "sources":
                for src in event["data"].get("sources", []):
                    v_sources.append(
                        SourceInfo(
                            url=src.get("url", ""),
                            title=src.get("title", ""),
                            score=src.get("score", 0.0),
                        )
                    )
            elif ev == "message":
                v_answer_parts.append(event["data"].get("delta", ""))
            elif ev == "done":
                break
    except Exception:  # noqa: BLE001
        pass
    v_latency_ms = (time.perf_counter() - v_started) * 1000.0
    v_answer = "".join(v_answer_parts)
    v_golden = evaluate_golden(answer=v_answer, sources=v_sources, case=golden_case)

    # --- Hybrid path ---
    h_started = time.perf_counter()
    h_answer_parts: list[str] = []
    h_sources: list[SourceInfo] = []
    try:
        stream = hybrid_rag.stream_answer(
            tenant_id=tenant_id,
            website_id=website_id,
            question=question,
        )
        events = await consume(stream)
        for event in events:
            ev = event.get("event")
            if ev == "error":
                break
            if ev == "sources":
                for src in event["data"].get("sources", []):
                    h_sources.append(
                        SourceInfo(
                            url=src.get("url", ""),
                            title=src.get("title", ""),
                            score=src.get("score", 0.0),
                        )
                    )
            elif ev == "message":
                h_answer_parts.append(event["data"].get("delta", ""))
            elif ev == "done":
                break
    except Exception:  # noqa: BLE001
        pass
    h_latency_ms = (time.perf_counter() - h_started) * 1000.0
    h_answer = "".join(h_answer_parts)
    h_golden = evaluate_golden(answer=h_answer, sources=h_sources, case=golden_case)

    # --- Build expected-characteristics text for judge ---
    expected_parts = []
    if golden_case.expected_keywords:
        expected_parts.append(f"Keywords to include: {', '.join(golden_case.expected_keywords)}")
    if golden_case.expected_sources:
        expected_parts.append(f"Sources to reference: {', '.join(golden_case.expected_sources)}")
    if golden_case.expected_concepts:
        expected_parts.append(f"Concepts to address: {', '.join(golden_case.expected_concepts)}")
    expected_text = "\n".join(expected_parts) or "(no specific expectations)"

    # --- LLM judge evaluation ---
    judge_started = time.perf_counter()
    v_score = await judge.score_answer(
        question=question,
        expected=expected_text,
        answer=v_answer,
        sources=v_sources,
    )
    h_score = await judge.score_answer(
        question=question,
        expected=expected_text,
        answer=h_answer,
        sources=h_sources,
    )
    judge_latency_ms = (time.perf_counter() - judge_started) * 1000.0

    # --- Retrieval metrics ---
    v_retrieval = _compute_retrieval_from_sources(v_sources, golden_case.expected_sources)
    h_retrieval = _compute_retrieval_from_sources(h_sources, golden_case.expected_sources)

    return LLMQueryResult(
        query=question,
        label=label,
        vector_answer=v_answer,
        vector_sources=v_sources,
        vector_score=v_score,
        vector_golden=v_golden,
        vector_retrieval=v_retrieval,
        vector_latency_ms=round(v_latency_ms, 2),
        hybrid_answer=h_answer,
        hybrid_sources=h_sources,
        hybrid_score=h_score,
        hybrid_golden=h_golden,
        hybrid_retrieval=h_retrieval,
        hybrid_latency_ms=round(h_latency_ms, 2),
        judge_latency_ms=round(judge_latency_ms, 2),
    )


def _compute_retrieval_from_sources(
    sources: list[SourceInfo],
    expected_sources: list[str],
) -> RetrievalMetrics:
    """Build RetrievalMetrics from SourceInfo list (no raw chunks needed)."""
    if not sources:
        return RetrievalMetrics()

    retrieved_urls = {s.url for s in sources if s.url}

    if expected_sources:
        expected_lower = {e.lower() for e in expected_sources}
        hits = sum(1 for s in sources if any(e in s.url.lower() for e in expected_lower))
        precision = round(hits / len(sources), 4)
    else:
        precision = 1.0

    if expected_sources:
        found = 0
        for exp in expected_sources:
            exp_lower = exp.lower()
            if any(exp_lower in url.lower() for url in retrieved_urls):
                found += 1
        accuracy = round(found / len(expected_sources), 4)
    else:
        accuracy = 1.0

    avg = round(sum(s.score for s in sources) / len(sources), 4)

    return RetrievalMetrics(
        precision_at_k=precision,
        source_accuracy=accuracy,
        total_chunks_retrieved=len(sources),
        unique_sources_retrieved=len(retrieved_urls),
        avg_score=avg,
    )


# ---------------------------------------------------------------------------
# Full LLM A/B evaluation
# ---------------------------------------------------------------------------


async def run_llm_ab_evaluation(
    *,
    vector_rag: Any,
    hybrid_rag: Any,
    judge: LLMJudge,
    golden_dataset: GoldenDataset | None = None,
    tenant_id: str = "llm-eval-tenant",
    website_id: str = "llm-eval-website",
    top_k: int = 5,
) -> list[LLMQueryResult]:
    """Run LLM-judged A/B evaluation across all golden cases.

    Each case runs through both the vector and hybrid RAG pipelines, and
    the generated answers are scored by the LLM judge.
    """
    dataset = golden_dataset if golden_dataset is not None else GoldenDataset.load_default()
    results: list[LLMQueryResult] = []

    for case in dataset:
        result = await evaluate_single_query(
            vector_rag=vector_rag,
            hybrid_rag=hybrid_rag,
            judge=judge,
            golden_case=case,
            tenant_id=tenant_id,
            website_id=website_id,
            top_k=top_k,
        )
        results.append(result)

    return results


# ---------------------------------------------------------------------------
# Report aggregation
# ---------------------------------------------------------------------------


def compute_llm_ab_report(results: list[LLMQueryResult]) -> LLMABReport:
    """Aggregate per-query LLM-judged results into a summary report."""
    if not results:
        return LLMABReport(recommendation="No queries evaluated.")

    n = len(results)
    report = LLMABReport(query_count=n, per_query=results)

    report.vector_mean = aggregate_scores([r.vector_score for r in results])
    report.hybrid_mean = aggregate_scores([r.hybrid_score for r in results])

    report.correctness_delta = round(
        report.hybrid_mean.correctness - report.vector_mean.correctness, 4
    )
    report.completeness_delta = round(
        report.hybrid_mean.completeness - report.vector_mean.completeness, 4
    )
    report.relevance_delta = round(report.hybrid_mean.relevance - report.vector_mean.relevance, 4)
    report.hallucination_risk_delta = round(
        report.hybrid_mean.hallucination_risk - report.vector_mean.hallucination_risk, 4
    )
    report.citation_quality_delta = round(
        report.hybrid_mean.citation_quality - report.vector_mean.citation_quality, 4
    )
    report.overall_delta = round(
        report.hybrid_mean.overall_score - report.vector_mean.overall_score, 4
    )

    report.vector_golden_mean = _mean([r.vector_golden.overall_quality_score for r in results])
    report.hybrid_golden_mean = _mean([r.hybrid_golden.overall_quality_score for r in results])
    report.golden_improvement_pct = _improvement_pct(
        report.vector_golden_mean, report.hybrid_golden_mean
    )

    report.vector_latency_mean = _mean([r.vector_latency_ms for r in results])
    report.hybrid_latency_mean = _mean([r.hybrid_latency_ms for r in results])
    report.latency_delta_ms = round(report.hybrid_latency_mean - report.vector_latency_mean, 2)
    report.judge_latency_mean = _mean([r.judge_latency_ms for r in results])

    report.recommendation = _generate_llm_recommendation(report)
    return report


def format_llm_ab_report(report: LLMABReport) -> str:
    """Render a human-readable LLM-judged A/B comparison report."""
    lines: list[str] = []
    lines.append("=" * 64)
    lines.append("  LLM-Judged Hybrid vs Vector RAG Evaluation Report")
    lines.append("=" * 64)
    lines.append("")
    lines.append(f"  Queries evaluated: {report.query_count}")
    lines.append("")

    lines.append("  --- LLM Quality Scores (0.0-1.0) ---")
    hdr = f"  {'Metric':<22s} {'Vector':>8s} {'Hybrid':>8s} {'Delta':>8s}"
    lines.append(hdr)
    lines.append("  " + "-" * 48)

    vm = report.vector_mean
    hm = report.hybrid_mean
    h_risk_d = report.hallucination_risk_delta
    cite_d = report.citation_quality_delta
    score_rows = [
        ("Correctness", vm.correctness, hm.correctness, report.correctness_delta),
        ("Completeness", vm.completeness, hm.completeness, report.completeness_delta),
        ("Relevance", vm.relevance, hm.relevance, report.relevance_delta),
        ("Hallucination*", vm.hallucination_risk, hm.hallucination_risk, h_risk_d),
        ("Citation quality", vm.citation_quality, hm.citation_quality, cite_d),
        ("OVERALL", vm.overall_score, hm.overall_score, report.overall_delta),
    ]
    for name, v, h, d in score_rows:
        sign = "+" if d >= 0 else ""
        lines.append(f"  {name:<22s} {v:>8.3f} {h:>8.3f} {sign}{d:>7.3f}")

    lines.append("")
    lines.append("  * Hallucination risk: lower is better")
    lines.append("")

    lines.append("  --- Golden Quality (retrieval-based) ---")
    lines.append(
        f"  Vector mean:  {report.vector_golden_mean:.3f}   "
        f"Hybrid mean: {report.hybrid_golden_mean:.3f}   "
        f"Improvement: {report.golden_improvement_pct:+.1f}%"
    )
    lines.append("")

    lines.append("  --- Latency ---")
    lines.append(f"  Vector pipeline:   {report.vector_latency_mean:>8.2f} ms")
    lines.append(f"  Hybrid pipeline:   {report.hybrid_latency_mean:>8.2f} ms")
    sign = "+" if report.latency_delta_ms >= 0 else ""
    lines.append(f"  Delta:             {sign}{report.latency_delta_ms:>7.2f} ms")
    lines.append(f"  Judge overhead:    {report.judge_latency_mean:>8.2f} ms")
    lines.append("")

    lines.append("  --- Per-Query Breakdown ---")
    for qr in report.per_query:
        v_ov = qr.vector_score.overall_score
        h_ov = qr.hybrid_score.overall_score
        delta = h_ov - v_ov
        sign = "+" if delta >= 0 else ""
        lines.append(
            f"  {qr.label:<20s}  vector={v_ov:.3f}  hybrid={h_ov:.3f}  delta={sign}{delta:.3f}"
        )
    lines.append("")

    lines.append("  --- Recommendation ---")
    for line in report.recommendation.split("\n"):
        lines.append(f"  {line}")
    lines.append("")
    lines.append("=" * 64)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _improvement_pct(baseline: float, treatment: float) -> float:
    if baseline <= 0:
        return 0.0
    return round((treatment - baseline) / baseline * 100, 1)


def _generate_llm_recommendation(report: LLMABReport) -> str:
    """Generate a recommendation based on LLM-judged quality deltas."""
    improvements: list[str] = []
    concerns: list[str] = []

    if report.correctness_delta > 0.02:
        improvements.append(f"Correctness improved by {report.correctness_delta:+.3f}")
    elif report.correctness_delta < -0.02:
        concerns.append(f"Correctness regressed by {report.correctness_delta:.3f}")

    if report.completeness_delta > 0.02:
        improvements.append(f"Completeness improved by {report.completeness_delta:+.3f}")
    elif report.completeness_delta < -0.02:
        concerns.append(f"Completeness regressed by {report.completeness_delta:.3f}")

    if report.relevance_delta > 0.02:
        improvements.append(f"Relevance improved by {report.relevance_delta:+.3f}")
    elif report.relevance_delta < -0.02:
        concerns.append(f"Relevance regressed by {report.relevance_delta:.3f}")

    if report.hallucination_risk_delta < -0.02:
        improvements.append(
            f"Hallucination risk reduced by {abs(report.hallucination_risk_delta):.3f}"
        )
    elif report.hallucination_risk_delta > 0.02:
        concerns.append(f"Hallucination risk increased by {report.hallucination_risk_delta:.3f}")

    if report.citation_quality_delta > 0.02:
        improvements.append(f"Citation quality improved by {report.citation_quality_delta:+.3f}")
    elif report.citation_quality_delta < -0.02:
        concerns.append(f"Citation quality regressed by {report.citation_quality_delta:.3f}")

    latency_ok = abs(report.latency_delta_ms) < 50.0

    parts: list[str] = []
    if improvements:
        parts.append("Strengths: " + "; ".join(improvements) + ".")
    if concerns:
        parts.append("Concerns: " + "; ".join(concerns) + ".")
    if latency_ok:
        parts.append(f"Latency impact is minimal ({report.latency_delta_ms:+.1f}ms).")
    else:
        parts.append(
            f"Latency increase is significant ({report.latency_delta_ms:+.1f}ms) "
            "— optimize before production."
        )

    has_improvement = len(improvements) > 0
    has_regression = len(concerns) > 0

    if has_improvement and not has_regression:
        verdict = "RECOMMEND: Hybrid retrieval improves LLM-judged answer quality."
    elif has_regression and not has_improvement:
        verdict = "DO NOT ENABLE: Hybrid shows quality regressions. Investigate."
    elif has_improvement and has_regression:
        verdict = (
            "MIXED: Hybrid shows both improvements and regressions. "
            "Run larger evaluation before deciding."
        )
    else:
        verdict = "NEUTRAL: No meaningful quality difference detected."

    parts.append(verdict)
    return "\n".join(parts)


__all__ = [
    "AnswerQualityScore",
    "LLMABReport",
    "LLMJudge",
    "LLMQueryResult",
    "aggregate_scores",
    "compute_llm_ab_report",
    "format_llm_ab_report",
    "parse_judge_response",
    "run_llm_ab_evaluation",
]
