"""Golden dataset evaluator for RAG answer quality.

Pure-function evaluator that scores a single benchmark response against
a ``GoldenCase``.  Computes keyword coverage, source accuracy, answer
completeness, and an overall quality score (0.0-1.0).  No I/O, no side
effects — easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.benchmark.evaluation import SourceInfo
from backend.benchmark.golden import GoldenCase


@dataclass(frozen=True)
class GoldenMetrics:
    """Per-response golden dataset scores.

    All scores are between 0.0 and 1.0 inclusive.

    Attributes
    ----------
    keyword_coverage_score:
        Fraction of ``expected_keywords`` found in the answer (case-insensitive).
    source_accuracy_score:
        Fraction of ``expected_sources`` whose URL substring appears among
        the retrieved source URLs.
    answer_completeness_score:
        ``1.0`` when the answer meets ``min_answer_length``, else 0.0.
    concept_coverage_score:
        Fraction of ``expected_concepts`` found in the answer (case-insensitive).
    overall_quality_score:
        Weighted average: 35% keyword + 30% source + 20% completeness + 15% concept.
    """

    keyword_coverage_score: float = 0.0
    source_accuracy_score: float = 0.0
    answer_completeness_score: float = 0.0
    concept_coverage_score: float = 0.0
    overall_quality_score: float = 0.0


def evaluate_golden(
    *,
    answer: str,
    sources: list[SourceInfo],
    case: GoldenCase,
) -> GoldenMetrics:
    """Score a single response against a golden case.

    Parameters
    ----------
    answer:
        The concatenated answer text produced by the LLM.
    sources:
        Source chunks returned by the retrieval pipeline (may be empty).
    case:
        The golden case that generated this question.
    """
    kw_score = _keyword_coverage(answer, case.expected_keywords)
    src_score = _source_accuracy(sources, case.expected_sources)
    comp_score = _answer_completeness(answer, case.min_answer_length)
    concept_score = _concept_coverage(answer, case.expected_concepts)

    overall = (
        0.35 * kw_score
        + 0.30 * src_score
        + 0.20 * comp_score
        + 0.15 * concept_score
    )

    return GoldenMetrics(
        keyword_coverage_score=round(kw_score, 4),
        source_accuracy_score=round(src_score, 4),
        answer_completeness_score=round(comp_score, 4),
        concept_coverage_score=round(concept_score, 4),
        overall_quality_score=round(overall, 4),
    )


def _keyword_coverage(answer: str, expected_keywords: list[str]) -> float:
    """Fraction of expected keywords found in the answer."""
    if not expected_keywords:
        return 1.0
    if not answer:
        return 0.0
    answer_lower = answer.lower()
    hits = sum(1 for kw in expected_keywords if kw.lower() in answer_lower)
    return hits / len(expected_keywords)


def _source_accuracy(
    sources: list[SourceInfo], expected_sources: list[str]
) -> float:
    """Fraction of expected source URL substrings found in retrieved sources."""
    if not expected_sources:
        return 1.0
    if not sources:
        return 0.0
    retrieved_urls = {s.url.lower() for s in sources if s.url}
    hits = 0
    for expected in expected_sources:
        expected_lower = expected.lower()
        if any(expected_lower in url for url in retrieved_urls):
            hits += 1
    return hits / len(expected_sources)


def _answer_completeness(answer: str, min_length: int) -> float:
    """Returns 1.0 when answer meets the minimum length, else 0.0."""
    if min_length <= 0:
        return 1.0
    return 1.0 if len(answer.strip()) >= min_length else 0.0


def _concept_coverage(answer: str, expected_concepts: list[str]) -> float:
    """Fraction of expected concepts found in the answer."""
    if not expected_concepts:
        return 1.0
    if not answer:
        return 0.0
    answer_lower = answer.lower()
    hits = sum(1 for c in expected_concepts if c.lower() in answer_lower)
    return hits / len(expected_concepts)
