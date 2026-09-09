"""Tests for the pre-generation RAG confidence scorer."""

from datetime import UTC, datetime

from backend.models.knowledge_chunk import KnowledgeChunk
from backend.repositories.vector.base import VectorSearchResult
from backend.services.chat.confidence import (
    assess_confidence,
    calculate_confidence,
    usable,
)


def _chunk(text: str, *, title: str = "t") -> KnowledgeChunk:
    return KnowledgeChunk(
        id=f"chunk-{title}-{abs(hash(text)) % 10**9}",
        tenant_id="t",
        website_id="w",
        document_id="d",
        chunk_text=text,
        chunk_index=1,
        metadata={},
        created_at=datetime.now(UTC),
    )


def _vr(text: str, *, score: float = 0.05, **overrides: object) -> VectorSearchResult:
    """Below-floor result carrying no dense/lexical provenance by default.

    Mirrors the pure (reranker-less) env post-``_strip_lexical_scores`` shape:
    keyword-only RRF chunks have ``score`` = RRF, ``dense_score``/``lexical_score``
    detached.
    """
    return VectorSearchResult(
        chunk=_chunk(text),
        score=score,
        **overrides,  # type: ignore[arg-type]
    )


class TestCalculateConfidence:
    """Unit tests for calculate_confidence."""

    def test_empty_scores_returns_zero(self) -> None:
        assert calculate_confidence([]) == 0.0

    def test_single_high_score(self) -> None:
        score = calculate_confidence([0.9], min_score=0.25)
        assert 0.0 < score <= 1.0

    def test_all_high_scores(self) -> None:
        score = calculate_confidence([0.9, 0.85, 0.8], min_score=0.25)
        assert score > 0.5

    def test_all_low_scores_below_min(self) -> None:
        score = calculate_confidence([0.1, 0.05, 0.02], min_score=0.25)
        assert score < 0.3

    def test_mixed_scores(self) -> None:
        score = calculate_confidence([0.9, 0.3, 0.1], min_score=0.25)
        assert 0.0 < score < 1.0

    def test_confidence_bounded_at_one(self) -> None:
        score = calculate_confidence([1.0, 1.0, 1.0], min_score=0.0)
        assert score <= 1.0

    def test_min_score_zero_uses_mean_as_hit_ratio(self) -> None:
        score = calculate_confidence([0.5, 0.5], min_score=0.0)
        # mean=0.5, hit_ratio=0.5, peak=0.5
        expected = round(0.50 * 0.5 + 0.30 * 0.5 + 0.20 * 0.5, 4)
        assert score == expected

    def test_min_score_filters_hits(self) -> None:
        score = calculate_confidence([0.9, 0.1, 0.1], min_score=0.5)
        # mean=0.3667, hit_ratio=1/3, peak=0.9
        expected = round(0.50 * (1.1 / 3) + 0.30 * (1 / 3) + 0.20 * 0.9, 4)
        assert score == expected

    def test_single_zero_score(self) -> None:
        score = calculate_confidence([0.0], min_score=0.25)
        assert score == 0.0

    def test_returns_float(self) -> None:
        result = calculate_confidence([0.5])
        assert isinstance(result, float)

    def test_custom_min_score_threshold(self) -> None:
        # With high min_score, fewer hits → lower confidence
        score_high_min = calculate_confidence([0.6, 0.4], min_score=0.5)
        score_low_min = calculate_confidence([0.6, 0.4], min_score=0.1)
        assert score_high_min <= score_low_min

    def test_weight_formula(self) -> None:
        """Verify the exact formula: 0.50*mean + 0.30*hit_ratio + 0.20*peak."""
        scores = [0.8, 0.6]
        min_score = 0.5
        mean = 0.7
        hit_ratio = 1.0  # both >= 0.5
        peak = 0.8
        expected = round(0.50 * mean + 0.30 * hit_ratio + 0.20 * peak, 4)
        assert calculate_confidence(scores, min_score=min_score) == expected

    def test_metrics_expose_rejected_and_aggregate_scores(self) -> None:
        metrics = assess_confidence([0.9, 0.2, 0.1], min_score=0.25)
        assert metrics.minimum_score == 0.1
        assert metrics.average_score == 0.4
        assert metrics.rejected_chunks_count == 2

    def test_negative_scores_clamped_to_zero(self) -> None:
        # Reranker cosine scores can be negative; confidence telemetry must
        # stay within [0, 1].
        assert calculate_confidence([-0.5], min_score=0.25) == 0.0

    def test_negative_scores_metrics_clamped_but_raw_min_kept(self) -> None:
        metrics = assess_confidence([-0.4, -0.2], min_score=0.25)
        assert metrics.confidence == 0.0
        # Inputs are normalized into [0, 1] before aggregation, so the
        # reported signals describe exactly what the decision consumed.
        assert metrics.minimum_score == 0.0
        assert metrics.average_score == 0.0

    def test_mixed_negative_positive_scores_not_distorted(self) -> None:
        # A dissimilar cosine (-0.2) clamps to 0 instead of dragging the
        # average below the true similarity scale: avg=(0+0.9)/2=0.45,
        # hit_ratio=0.5 (one of two >= 0.25), peak=0.9.
        expected = round(0.50 * 0.45 + 0.30 * 0.5 + 0.20 * 0.9, 4)
        assert calculate_confidence([-0.2, 0.9], min_score=0.25) == expected


class TestScoreNormalization:
    """Audit regression: mixed retrieval scales must not distort confidence.

    Exact cosine scans produce [-1, 1] similarities, Atlas vectorSearchScore
    is normalized similarity, and hybrid blends can exceed 1. Inputs are
    clamped into [0, 1] before the weighted formula; in-range inputs are
    unaffected.
    """

    def test_in_range_scores_are_unchanged(self) -> None:
        # Normalization is a no-op on the calibrated cosine scale.
        expected = round(0.50 * 0.75 + 0.30 * 0.75 + 0.20 * 0.9, 4)
        assert calculate_confidence([0.9, 0.6]) == expected
        assert calculate_confidence([0.9, 0.6]) == calculate_confidence([0.9, 0.6])

    def test_above_one_scores_saturate_at_one(self) -> None:
        # A dot-product/BM25-style scale must not push confidence past 1 or
        # mask weaker results: everything maps onto the same [0, 1] scale.
        assert calculate_confidence([2.5]) == calculate_confidence([1.0])
        metrics = assess_confidence([1.8, 1.2, 0.4], min_score=0.25)
        assert metrics.confidence <= 1.0
        assert metrics.minimum_score == 0.4
        assert metrics.rejected_chunks_count == 0

    def test_below_zero_scores_clamp_to_zero(self) -> None:
        assert assess_confidence([-0.7]).confidence == assess_confidence([0.0]).confidence

    def test_mixed_scale_result_stays_bounded(self) -> None:
        metrics = assess_confidence([1.4, -0.3, 0.8], min_score=0.25)
        assert 0.0 <= metrics.confidence <= 1.0
        # Clamped inputs: [-0.3 -> 0.0]; only that chunk misses the threshold.
        assert metrics.minimum_score == 0.0
        assert metrics.average_score == round((1.0 + 0.0 + 0.8) / 3, 4)
        assert metrics.rejected_chunks_count == 1

    def test_scale_change_does_not_flip_threshold_decision(self) -> None:
        # The same relevance profile expressed on two different scales must
        # produce the same above/below-threshold decision.
        strong_cosine = assess_confidence([0.95, 0.9], min_score=0.5)
        rescaled = assess_confidence([1.9, 1.8], min_score=0.5)
        assert (strong_cosine.confidence >= 0.5) == (rescaled.confidence >= 0.5)


class TestShortQueryLeniency:
    """RAG-ACC-03 short-query gate: below-floor chunks may be preserved on
    independent content-token overlap for queries with few content terms.

    The leniency only applies to the query-aware fast path (``query`` passed);
    it must never weaken the strict dense-only floor for ordinary queries.
    """

    def test_requires_query_for_leniency(self) -> None:
        # Legacy signature / reranker-path gate: below-floor chunk is dropped
        # even with identical text overlap when no query is supplied.
        assert not usable(_vr("The BCA admissions are open"), dense_floor=0.25)

    def test_single_token_query_admits_chunk_covering_it(self) -> None:
        res = _vr("The BCA admissions are open each fall")
        assert usable(res, dense_floor=0.25, query="Admissions?")

    def test_single_token_query_rejects_chunk_without_the_token(self) -> None:
        res = _vr("The campus has a library and labs")
        assert not usable(res, dense_floor=0.25, query="Admissions?")

    def test_two_token_query_requires_both_tokens(self) -> None:
        # Only {campus} of {campus, hostel} overlaps -> must not qualify.
        res = _vr("The BCA campus sits near the metro")
        assert not usable(res, dense_floor=0.25, query="Campus hostel?")

    def test_three_token_query_requires_two_independent_terms(self) -> None:
        # {fee, scholarship} cover 2 of the 3 content tokens -> admitted.
        res = _vr("The BCA fee and scholarship details")
        assert usable(res, dense_floor=0.25, query="Tell me about fees scholarships campus")

    def test_three_token_query_rejects_single_generic_overlap(self) -> None:
        # Only "bca" overlaps; a generic topic header must not qualify.
        res = _vr("BCA is a three year undergraduate degree")
        assert not usable(res, dense_floor=0.25, query="Tell me about fee hostel placement")

    def test_four_plus_token_query_keeps_strict_floor(self) -> None:
        # Leniency cap at 3 content tokens: an unsupported "Academy B academy"
        # style long query must never be rescued by token overlap.
        res = _vr("The BCA program includes fee hostel campus placements")
        assert not usable(
            res,
            dense_floor=0.25,
            query="Does the BCA Academy have hostel fees placements",
        )

    def test_above_floor_dense_score_still_admitted_without_leniency(self) -> None:
        res = _vr("BCA placement policy", score=0.0, dense_score=0.9)
        assert usable(res, dense_floor=0.25, query="nothing in common here")

    def test_reranker_protection_path_unchanged(self) -> None:
        # Strong-lexical reranker protection still requires lexical evidence:
        # with no reranker proof, a 4+-content-token query keeps the strict
        # floor even when the chunk scores high on the wrong scale.
        below_floor = _vr("Application deadlines are in march", score=0.05)
        protected = _vr(
            "Application deadlines are in march",
            score=0.05,
            lexical_score=0.9,
            lexical_exact=True,
        )
        query = "deadline policy summer transfer deadline"
        assert not usable(below_floor, dense_floor=0.25, query=query)
        assert usable(protected, dense_floor=0.25, query=query)

    def test_zero_floor_never_freezes_unrelated_chunks(self) -> None:
        # dense_floor <= 0 keeps legacy behavior: everything admitted.
        assert usable(_vr("unrelated"), dense_floor=0.0, query="anything")
