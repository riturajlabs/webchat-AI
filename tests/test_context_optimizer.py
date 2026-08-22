"""Tests for the context optimizer (near-duplicate removal + compression)."""

from backend.services.chat.context_optimizer import (
    OptimizationMetrics,
    compress_text,
    remove_near_duplicates,
    text_similarity,
)


class TestTextSimilarity:
    """Unit tests for word-level Jaccard similarity."""

    def test_identical_texts(self) -> None:
        assert text_similarity("hello world", "hello world") == 1.0

    def test_completely_different(self) -> None:
        assert text_similarity("cat dog", "fish bird") == 0.0

    def test_partial_overlap(self) -> None:
        score = text_similarity("the quick brown fox", "the quick red fox")
        assert 0.0 < score < 1.0

    def test_empty_strings(self) -> None:
        assert text_similarity("", "") == 0.0

    def test_one_empty(self) -> None:
        assert text_similarity("hello world", "") == 0.0

    def test_case_insensitive(self) -> None:
        assert text_similarity("Hello World", "hello world") == 1.0

    def test_short_words_filtered(self) -> None:
        # "a" and "I" are filtered out (< 3 chars)
        score = text_similarity("a big cat", "a big dog")
        assert score >= 0.0


class TestRemoveNearDuplicates:
    """Unit tests for near-duplicate chunk removal."""

    def test_no_duplicates(self) -> None:
        texts = ["cats are great", "dogs are loyal", "birds can fly"]
        assert remove_near_duplicates(texts) == [0, 1, 2]

    def test_exact_duplicate_removed(self) -> None:
        texts = ["cats are great pets", "cats are great pets", "dogs are loyal"]
        kept = remove_near_duplicates(texts, threshold=0.75)
        assert len(kept) == 2
        assert 0 in kept
        assert 2 in kept

    def test_near_duplicate_removed(self) -> None:
        texts = [
            "the quick brown fox jumps over the lazy dog",
            "the quick brown fox jumps over the lazy dog today",
            "completely different text about cooking recipes",
        ]
        kept = remove_near_duplicates(texts, threshold=0.7)
        assert len(kept) == 2

    def test_empty_input(self) -> None:
        assert remove_near_duplicates([]) == []

    def test_single_text(self) -> None:
        assert remove_near_duplicates(["hello world"]) == [0]

    def test_all_same_keeps_first(self) -> None:
        texts = ["same text"] * 5
        kept = remove_near_duplicates(texts)
        assert kept == [0]

    def test_preserves_order(self) -> None:
        texts = ["alpha bravo", "charlie delta", "echo foxtrot"]
        kept = remove_near_duplicates(texts, threshold=0.75)
        assert kept == sorted(kept)

    def test_threshold_sensitivity(self) -> None:
        texts = [
            "the quick brown fox",
            "the quick brown fox jumps",
        ]
        # High threshold: not duplicates
        kept_strict = remove_near_duplicates(texts, threshold=0.99)
        assert len(kept_strict) == 2
        # Low threshold: treated as duplicates
        kept_loose = remove_near_duplicates(texts, threshold=0.5)
        assert len(kept_loose) == 1


class TestCompressText:
    """Unit tests for sentence-level compression."""

    def test_no_redundancy(self) -> None:
        text = "Cats are independent. Dogs are loyal. Birds fly south."
        compressed, removed = compress_text(text)
        assert compressed == text
        assert removed == 0

    def test_redundant_sentence_removed(self) -> None:
        seen = {"Cats are independent animals."}
        text = "Cats are independent animals. Dogs are loyal companions."
        compressed, removed = compress_text(text, seen_sentences=seen)
        assert "Dogs are loyal" in compressed
        assert removed == 1

    def test_empty_text(self) -> None:
        compressed, removed = compress_text("")
        assert compressed == ""
        assert removed == 0

    def test_single_sentence(self) -> None:
        compressed, removed = compress_text("Hello world.")
        assert compressed == "Hello world."
        assert removed == 0

    def test_seen_sentences_mutated(self) -> None:
        seen: set[str] = set()
        compress_text("First sentence. Second sentence.", seen_sentences=seen)
        assert len(seen) == 2

    def test_cross_chunk_dedup(self) -> None:
        seen: set[str] = set()
        _, r1 = compress_text(
            "Cats are great pets. They are independent.", seen_sentences=seen
        )
        _, r2 = compress_text(
            "Cats are great pets. Dogs are loyal.", seen_sentences=seen
        )
        assert r1 == 0  # First chunk: nothing to compress
        assert r2 == 1  # Second chunk: "Cats are great pets" removed

    def test_preserves_unique_content(self) -> None:
        text = "Our company was founded in 2020. We serve customers across 50 countries worldwide."
        compressed, removed = compress_text(text)
        assert "founded" in compressed
        assert "countries" in compressed
        assert removed == 0


class TestOptimizationMetrics:
    """Unit tests for the metrics dataclass."""

    def test_savings_chars(self) -> None:
        m = OptimizationMetrics(
            original_chars=1000, optimized_chars=700,
            removed_chunks=2, removed_sentences=5,
        )
        assert m.savings_chars == 300

    def test_savings_pct(self) -> None:
        m = OptimizationMetrics(
            original_chars=1000, optimized_chars=700,
            removed_chunks=2, removed_sentences=5,
        )
        assert m.savings_pct == 30.0

    def test_zero_original_chars(self) -> None:
        m = OptimizationMetrics(
            original_chars=0, optimized_chars=0,
            removed_chunks=0, removed_sentences=0,
        )
        assert m.savings_pct == 0.0
