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


def _normalize_scores(scores: list[float]) -> list[float]:
    """Clamp raw retrieval scores into the [0, 1] similarity scale.

    Different retrieval stages produce different scales: exact cosine scans
    yield [-1, 1], Atlas ``vectorSearchScore`` is normalized similarity, and
    hybrid/rerank blends can exceed 1.0 or dip below 0. Feeding those raw
    values into the weighted formula makes confidence incomparable across
    strategies (a BM25-style 2.4 would saturate it at 1.0; a dissimilar
    cosine of -0.6 would drag it artificially low). Clamping each input to
    [0, 1] keeps every signal on one scale. Scores already inside [0, 1]
    pass through unchanged, so existing calibrated behavior is preserved.
    """
    return [max(0.0, min(score, 1.0)) for score in scores]


def assess_confidence(
    scores: list[float],
    *,
    min_score: float = 0.0,
) -> ConfidenceMetrics:
    """Compute confidence and expose the signals used by the decision."""
    if not scores:
        return ConfidenceMetrics(0.0, 0.0, 0.0, 0)

    normalized = _normalize_scores(scores)
    peak = max(normalized)
    average = sum(normalized) / len(normalized)
    rejected = sum(1 for score in normalized if score < min_score) if min_score > 0 else 0
    hit_ratio = (len(normalized) - rejected) / len(normalized) if min_score > 0 else average
    confidence = 0.50 * average + 0.30 * hit_ratio + 0.20 * peak
    # Clamp to [0, 1]: defensive only after input normalization, kept so a
    # caller-supplied out-of-range min_score cannot push the ratio negative.
    confidence = max(0.0, min(confidence, 1.0))
    return ConfidenceMetrics(
        confidence=round(confidence, 4),
        minimum_score=round(min(normalized), 4),
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
