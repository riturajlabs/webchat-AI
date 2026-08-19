"""Retrieval quality metrics: precision@k, source accuracy, pairwise improvement.

Pure-function evaluators that score retrieval results against expected
source URLs.  No I/O, no side effects — easy to test.

Metrics
-------
- **Precision@k**: fraction of retrieved chunks whose source URL matches an
  expected source (0.0-1.0).
- **Source accuracy**: fraction of *expected* sources found in the results
  (0.0-1.0).
- **Overlap rate**: fraction of results shared between two retrieval methods.
- **Pairwise improvement**: difference in a metric between two methods
  (positive = improvement).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from backend.repositories.vector.base import VectorSearchResult


@dataclass(frozen=True)
class RetrievalMetrics:
    """Quantitative scores for a retrieval method against ground truth."""

    precision_at_k: float = 0.0
    source_accuracy: float = 0.0
    total_chunks_retrieved: int = 0
    unique_sources_retrieved: int = 0
    avg_score: float = 0.0


@dataclass(frozen=True)
class PairwiseImprovement:
    """Delta between two retrieval methods for a single metric."""

    baseline_method: str
    treatment_method: str
    metric_name: str
    baseline_value: float
    treatment_value: float
    delta: float = 0.0
    relative_improvement_pct: float = 0.0


def compute_retrieval_metrics(
    results: list[VectorSearchResult],
    expected_sources: list[str],
    *,
    top_k: int | None = None,
) -> RetrievalMetrics:
    """Score retrieval results against expected source URL substrings.

    Parameters
    ----------
    results:
        Ranked retrieval results.
    expected_sources:
        URL substrings that *should* appear in the result set (e.g. from
        a golden case's ``expected_sources``).
    top_k:
        If provided, only the first *top_k* results are scored.
    """
    scored = results[:top_k] if top_k else results
    if not scored:
        return RetrievalMetrics()

    retrieved_urls = {
        r.chunk.metadata.get("source_url", "")
        for r in scored
        if r.chunk.metadata and r.chunk.metadata.get("source_url")
    }
    retrieved_urls.discard("")

    # Precision@k: fraction of retrieved chunks that match any expected source
    if expected_sources:
        expected_lower = {e.lower() for e in expected_sources}
        hits = sum(
            1
            for r in scored
            if any(e in r.chunk.metadata.get("source_url", "").lower() for e in expected_lower)
            if r.chunk.metadata
        )
        precision = round(hits / len(scored), 4) if scored else 0.0
    else:
        precision = 1.0

    # Source accuracy: fraction of expected sources found in results
    if expected_sources:
        found = 0
        for exp in expected_sources:
            exp_lower = exp.lower()
            if any(exp_lower in url.lower() for url in retrieved_urls):
                found += 1
        accuracy = round(found / len(expected_sources), 4)
    else:
        accuracy = 1.0

    avg = round(sum(r.score for r in scored) / len(scored), 4)

    return RetrievalMetrics(
        precision_at_k=precision,
        source_accuracy=accuracy,
        total_chunks_retrieved=len(scored),
        unique_sources_retrieved=len(retrieved_urls),
        avg_score=avg,
    )


def compute_pairwise_improvement(
    baseline: RetrievalMetrics,
    treatment: RetrievalMetrics,
    *,
    baseline_method: str = "vector",
    treatment_method: str = "hybrid",
    metric_name: str = "precision_at_k",
) -> PairwiseImprovement:
    """Compute the delta between two retrieval methods for a named metric.

    Parameters
    ----------
    baseline:
        Metrics from the reference method (e.g. vector-only).
    treatment:
        Metrics from the improved method (e.g. hybrid).
    baseline_method:
        Label for the baseline (used in the result).
    treatment_method:
        Label for the treatment (used in the result).
    metric_name:
        Which field of ``RetrievalMetrics`` to compare.
    """
    base_val = getattr(baseline, metric_name, 0.0)
    treat_val = getattr(treatment, metric_name, 0.0)
    delta = treat_val - base_val
    relative = round(delta / base_val * 100, 2) if base_val > 0 else 0.0

    return PairwiseImprovement(
        baseline_method=baseline_method,
        treatment_method=treatment_method,
        metric_name=metric_name,
        baseline_value=round(base_val, 4),
        treatment_value=round(treat_val, 4),
        delta=round(delta, 4),
        relative_improvement_pct=relative,
    )


def aggregate_retrieval_metrics(
    metrics_list: list[RetrievalMetrics],
) -> dict[str, float]:
    """Compute mean/median for each field across multiple RetrievalMetrics.

    Returns a flat dict with keys like ``precision_at_k_mean``,
    ``precision_at_k_median``, ``source_accuracy_mean``, etc.
    """
    if not metrics_list:
        return {}

    fields = ["precision_at_k", "source_accuracy", "avg_score"]
    result: dict[str, float] = {}
    for field_name in fields:
        values = [getattr(m, field_name) for m in metrics_list]
        result[f"{field_name}_mean"] = round(statistics.mean(values), 4)
        result[f"{field_name}_median"] = round(statistics.median(values), 4)
    return result


__all__ = [
    "PairwiseImprovement",
    "RetrievalMetrics",
    "aggregate_retrieval_metrics",
    "compute_pairwise_improvement",
    "compute_retrieval_metrics",
]
