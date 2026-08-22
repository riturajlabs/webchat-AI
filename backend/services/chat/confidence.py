"""Pre-generation RAG confidence scoring.

Computes a relevance confidence score from existing retrieval/rerank scores
*before* the LLM is called.  When the score falls below a configurable
threshold, the pipeline returns a safe fallback instead of generating an
answer, preventing hallucinations on low-quality retrieval results.

No LLM calls, no external dependencies — pure arithmetic on existing scores.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConfidenceMetrics:
    """Inspectable confidence signals for one retrieval decision."""

    confidence: float
    minimum_score: float
    average_score: float
    rejected_chunks_count: int


def assess_confidence(
    scores: list[float],
    *,
    min_score: float = 0.0,
) -> ConfidenceMetrics:
    """Compute confidence and expose the signals used by the decision."""
    if not scores:
        return ConfidenceMetrics(0.0, 0.0, 0.0, 0)

    peak = max(scores)
    average = sum(scores) / len(scores)
    rejected = sum(1 for score in scores if score < min_score) if min_score > 0 else 0
    hit_ratio = (
        (len(scores) - rejected) / len(scores)
        if min_score > 0
        else average
    )
    confidence = 0.50 * average + 0.30 * hit_ratio + 0.20 * peak
    return ConfidenceMetrics(
        confidence=round(min(confidence, 1.0), 4),
        minimum_score=round(min(scores), 4),
        average_score=round(average, 4),
        rejected_chunks_count=rejected,
    )

def calculate_confidence(
    scores: list[float],
    *,
    min_score: float = 0.0,
) -> float:
    """Compute a 0.0–1.0 confidence score from retrieval results.

    Uses three signals derived entirely from existing rerank/vector scores:

    1. **Mean score** — average relevance of the top results.
    2. **Hit ratio** — fraction of results above ``min_score``.
    3. **Peak score** — highest individual score (top result quality).

    These are combined with fixed weights:

    ``confidence = 0.50 * mean + 0.30 * hit_ratio + 0.20 * peak``

    Parameters
    ----------
    scores:
        Relevance scores from the retrieval/rerank stage (descending order).
    min_score:
        The minimum relevance threshold used by ``_build_context``.  Results
        below this score are filtered out downstream, so a low hit ratio
        signals that few chunks are actually usable.

    Returns
    -------
    float
        A value between 0.0 (no confidence) and 1.0 (maximum confidence).
    """
    return assess_confidence(scores, min_score=min_score).confidence


__all__ = ["ConfidenceMetrics", "assess_confidence", "calculate_confidence"]
