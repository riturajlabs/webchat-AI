"""Lightweight context optimization for RAG pipelines.

Provides near-duplicate chunk detection and sentence-level context compression
without any LLM calls or external dependencies.

Near-duplicate detection uses word-level Jaccard similarity to identify chunks
that are substantively the same content (e.g. re-crawled pages with minor
formatting differences).  Compression strips sentences from a chunk that
overlap heavily with sentences already kept, reducing token usage while
preserving the unique information from each source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Similarity
# ---------------------------------------------------------------------------

def _word_set(text: str) -> set[str]:
    """Extract a normalized word set from text."""
    return {w for w in re.split(r"\W+", text.lower()) if len(w) > 2}


def text_similarity(a: str, b: str) -> float:
    """Compute word-level Jaccard similarity between two texts.

    Returns a value between 0.0 (no overlap) and 1.0 (identical word sets).
    """
    words_a = _word_set(a)
    words_b = _word_set(b)
    if not words_a or not words_b:
        return 0.0
    intersection = len(words_a & words_b)
    union = len(words_a | words_b)
    return intersection / union if union > 0 else 0.0


# ---------------------------------------------------------------------------
# Near-duplicate removal
# ---------------------------------------------------------------------------

def remove_near_duplicates(
    texts: list[str],
    *,
    threshold: float = 0.75,
) -> list[int]:
    """Return indices of texts to keep after near-duplicate removal.

    Compares each text against all previously kept texts.  If the Jaccard
    similarity exceeds *threshold*, the new text is considered a duplicate
    and its index is excluded.

    Parameters
    ----------
    texts:
        Ordered list of chunk texts (highest-scored first).
    threshold:
        Similarity threshold for considering two texts duplicates.
        0.75 means 75% word overlap is required to consider them the same.

    Returns
    -------
    list[int]
        Indices of texts that should be kept.
    """
    kept: list[int] = []
    kept_words: list[set[str]] = []
    for i, text in enumerate(texts):
        words = _word_set(text)
        is_dup = False
        for existing in kept_words:
            if not words or not existing:
                continue
            intersection = len(words & existing)
            union = len(words | existing)
            if union > 0 and intersection / union >= threshold:
                is_dup = True
                break
        if not is_dup:
            kept.append(i)
            kept_words.append(words)
    return kept


# ---------------------------------------------------------------------------
# Sentence-level compression
# ---------------------------------------------------------------------------

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    parts = _SENTENCE_RE.split(text.strip())
    return [s.strip() for s in parts if s.strip()]


def compress_text(
    text: str,
    *,
    seen_sentences: set[str] | None = None,
    overlap_threshold: float = 0.7,
) -> tuple[str, int]:
    """Remove redundant sentences that overlap with already-seen content.

    Each sentence is checked against *seen_sentences* (accumulated from earlier
    chunks).  If a sentence's word-level Jaccard similarity to any seen
    sentence exceeds *overlap_threshold*, it is dropped.  Retained sentences
    are added to *seen_sentences* in-place so subsequent chunks benefit.

    Parameters
    ----------
    text:
        The chunk text to compress.
    seen_sentences:
        Mutable set of normalized sentence fingerprints from earlier chunks.
        Modified in-place.
    overlap_threshold:
        Similarity threshold for considering a sentence redundant.

    Returns
    -------
    tuple[str, int]
        The compressed text and the number of sentences removed.
    """
    sentences = _split_sentences(text)
    if not sentences:
        return text, 0

    if seen_sentences is None:
        seen_sentences = set()

    kept: list[str] = []
    removed = 0
    for sentence in sentences:
        words = _word_set(sentence)
        if not words:
            kept.append(sentence)
            continue
        is_redundant = False
        for seen in seen_sentences:
            seen_words = _word_set(seen)
            if not seen_words:
                continue
            intersection = len(words & seen_words)
            union = len(words | seen_words)
            if union > 0 and intersection / union >= overlap_threshold:
                is_redundant = True
                break
        if is_redundant:
            removed += 1
        else:
            kept.append(sentence)
            seen_sentences.add(sentence)

    compressed = " ".join(kept) if kept else text
    return compressed, removed


# ---------------------------------------------------------------------------
# Metrics dataclass
# ---------------------------------------------------------------------------

@dataclass
class OptimizationMetrics:
    """Metrics emitted after context optimization."""

    original_chars: int
    optimized_chars: int
    removed_chunks: int
    removed_sentences: int

    @property
    def savings_chars(self) -> int:
        return self.original_chars - self.optimized_chars

    @property
    def savings_pct(self) -> float:
        if self.original_chars == 0:
            return 0.0
        return round(self.savings_chars / self.original_chars * 100, 2)


__all__ = [
    "OptimizationMetrics",
    "compress_text",
    "remove_near_duplicates",
    "text_similarity",
]
