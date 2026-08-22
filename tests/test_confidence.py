"""Tests for the pre-generation RAG confidence scorer."""

from backend.services.chat.confidence import assess_confidence, calculate_confidence


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
