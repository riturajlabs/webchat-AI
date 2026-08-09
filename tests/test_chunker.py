"""Tests for knowledge chunking (Phase 5, docs/02-TRD.md §6).

Chunk sizes and overlaps are token counts; `conftest.py` clears the settings
cache so tests use the default 700/100 unless overridden.
"""

import pytest
from backend.services.knowledge.chunker import TextChunk, chunk_text, count_tokens

SHORT = "This is a short page with a few tokens only."
LONG = "Sentence one. " * 50  # 100 sentences => plenty of tokens and boundaries.


def test_count_tokens_counts_words_and_punctuation() -> None:
    assert count_tokens("") == 0
    assert count_tokens("Hello world") == 2
    assert count_tokens("State-of-the-art, isn't it?") == 5
    assert count_tokens("a — b — c") == 5  # punctuation runs count as tokens


def test_empty_text_yields_no_chunks() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_short_text_is_a_single_chunk() -> None:
    chunks = chunk_text(SHORT)
    assert len(chunks) == 1
    assert chunks[0].index == 0
    assert chunks[0].text == SHORT
    assert chunks[0].tokens == count_tokens(SHORT)


def test_long_text_is_split_into_bounded_chunks() -> None:
    chunks = chunk_text(LONG, chunk_size=30, overlap=5)
    assert len(chunks) > 1
    assert all(chunk.tokens <= 30 for chunk in chunks)
    # Every chunk keeps whole words (whitespace-joined token runs).
    assert all(chunk.text == " ".join(chunk.text.split()) for chunk in chunks)


def test_overlap_shares_tokens_between_adjacent_chunks() -> None:
    chunks = chunk_text(LONG, chunk_size=40, overlap=10)
    assert len(chunks) > 1
    for i in range(len(chunks) - 1):
        left_tokens = chunks[i].text.split()
        right_tokens = chunks[i + 1].text.split()
        shared = set(left_tokens) & set(right_tokens)
        assert len(shared) > 0  # overlap window actually shares content


def test_overlap_is_clipped_to_size_minus_one() -> None:
    # overlap >= size would stall the window; the chunker must still advance.
    chunks = chunk_text(LONG, chunk_size=20, overlap=25)
    assert len(chunks) > 1
    assert all(chunk.tokens <= 20 for chunk in chunks)


def test_rejects_invalid_sizes() -> None:
    with pytest.raises(ValueError):
        chunk_text(SHORT, chunk_size=0)
    with pytest.raises(ValueError):
        chunk_text(SHORT, overlap=-1)


def test_prefers_sentence_boundaries_for_cuts() -> None:
    text = "Alpha beta. Gamma delta. " * 100  # clean two-word sentences
    chunks = chunk_text(text, chunk_size=20, overlap=0)
    assert len(chunks) > 1
    # A cut never lands mid-sentence here: every chunk ends with a period.
    assert all(chunk.text.endswith(".") for chunk in chunks)


def test_chunk_indices_are_sequential() -> None:
    chunks = chunk_text(LONG, chunk_size=30, overlap=5)
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))


def test_defaults_match_settings() -> None:
    chunks = chunk_text(LONG)
    assert chunks
    assert isinstance(chunks[0], TextChunk)
    # Default size is 700 tokens; even the largest chunk must not exceed it.
    assert max(chunk.tokens for chunk in chunks) <= 700
