"""Tests for knowledge chunking (Phase 5, docs/02-TRD.md §6).

Chunk sizes and overlaps are token counts; `conftest.py` clears the settings
cache so tests use the default 700/100 unless overridden.
"""

import pytest
from backend.services.knowledge.chunker import TextChunk, chunk_text, clean_html, count_tokens

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


def test_clean_html_removes_boilerplate_and_preserves_main_headings() -> None:
    html = """
        <html><body>
            <header>Global navigation</header>
            <nav>Home Pricing Login</nav>
            <main><h1>Pricing</h1><p>Pro costs nineteen dollars.</p>
                <aside>Related links</aside>
            </main>
            <footer>Copyright notice</footer>
            <script>alert('ignore');</script><style>.hidden { display: none; }</style>
        </body></html>
        """

    cleaned = clean_html(html)
    assert "# Pricing" in cleaned
    assert "Pro costs nineteen dollars." in cleaned
    assert "Global navigation" not in cleaned
    assert "Related links" not in cleaned
    assert "Copyright notice" not in cleaned
    assert "alert" not in cleaned


def test_chunk_text_cleans_html_before_heading_tracking() -> None:
    chunks = chunk_text("<nav>Pricing Login</nav><main><h2>Pricing</h2>Pro costs $19.</main>")

    assert len(chunks) == 1
    assert chunks[0].heading == "Pricing"
    assert "Pricing Login" not in chunks[0].text


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


# ---------------------------------------------------------------------------
# Heading propagation (audit R-08)
# ---------------------------------------------------------------------------


def _heading_of(chunks: list[TextChunk], needle: str) -> str | None:
    for chunk in chunks:
        if needle in chunk.text:
            return chunk.heading
    raise AssertionError(f"no chunk contains {needle!r}")


def test_chunks_carry_nearest_preceding_heading() -> None:
    doc = (
        "# Pricing\nStarter costs nine dollars. Pro costs nineteen. \n"
        "Enterprise is custom quoted. Annual plans save money. \n"
        "## Support\nEmail us any time. We reply within one day. \n"
        "Phone support runs on weekdays. Chat is available too. "
    )
    chunks = chunk_text(doc, chunk_size=15, overlap=0)

    assert len(chunks) >= 2
    assert _heading_of(chunks, "Starter costs") == "Pricing"
    # A chunk fully inside the Support section carries the Support heading.
    support_chunks = [c for c in chunks if c.text and "Email" in c.text or "Chat" in c.text]
    assert support_chunks
    assert all(c.heading == "Support" for c in support_chunks)
    # No chunk from the Pricing section leaks a Support heading.
    pricing = [c for c in chunks if "nine dollars" in c.text]
    assert all(c.heading == "Pricing" for c in pricing)


def test_text_without_headings_yields_none() -> None:
    chunks = chunk_text(LONG, chunk_size=30, overlap=0)
    assert chunks
    assert all(chunk.heading is None for chunk in chunks)


def test_heading_before_any_content_is_attached_to_first_chunk() -> None:
    chunks = chunk_text("# Intro\nAlpha beta. Gamma delta. Epsilon zeta.", chunk_size=10, overlap=0)
    assert len(chunks) == 2
    assert all(chunk.heading == "Intro" for chunk in chunks)


# ---------------------------------------------------------------------------
# Corpus-quality: no 1-token near-duplicate chain, fragments merged, sections
# start fresh (accuracy phase; generic, no site-specific hardcoding)
# ---------------------------------------------------------------------------


def _is_suffix_shift(prev: str, nxt: str) -> bool:
    """True when `nxt` is just `prev` with a leading portion dropped.

    This is the window-stall signature that used to produce runs of
    near-identical chunks that each dropped only the first word or two
    (e.g. "and industrial visits...", "industrial visits...", "visits...").
    """
    a, b = prev.strip(), nxt.strip()
    if not a or not b or a == b:
        return False
    return a.endswith(b) or (len(b) < len(a) and b in a and a.find(b) <= len(a) // 4)


def test_no_adjacent_near_duplicate_chain_on_long_paragraph() -> None:
    # A long paragraph with sentence boundaries must advance the window forward,
    # never emit the same text shifted by one token (the overcut/overlap stall).
    sentences = " ".join(
        f"Module {i} introduces the concept of item {i} and applies it to scenario "
        f"number {i} within the curriculum for the current year. "
        for i in range(1, 200)
    )
    chunks = chunk_text(sentences, chunk_size=200, overlap=100)
    assert len(chunks) > 1
    shift_pairs = sum(
        1 for i in range(len(chunks) - 1) if _is_suffix_shift(chunks[i].text, chunks[i + 1].text)
    )
    assert shift_pairs == 0


def test_no_adjacent_near_duplicate_chain_across_section_headings() -> None:
    # A section between two headings must not be re-emitted as a shifted chain,
    # and must stay within a sane chunk count (not a runaway stall).
    intro = " ".join(f"Intro paragraph sentence number {i} about the topic. " for i in range(1, 60))
    curriculum = " ".join(
        f"Mandatory module {i} covers learning outcome and credit weight. " for i in range(1, 200)
    )
    doc = f"## Intro\n{intro}\n## Curriculum\n{curriculum}\n"
    chunks = chunk_text(doc, chunk_size=250, overlap=100)
    shift_pairs = sum(
        1 for i in range(len(chunks) - 1) if _is_suffix_shift(chunks[i].text, chunks[i + 1].text)
    )
    assert shift_pairs == 0
    # Every curriculum chunk is correctly attributed to its own section (never
    # the Intro heading that precedes it).
    for c in chunks:
        if "Mandatory module" in c.text:
            assert c.heading == "Curriculum"


def test_section_heading_starts_a_fresh_chunk() -> None:
    # A heading that begins a new section must open its own chunk (no overlap
    # pull-back that re-labels the previous section's tail under the new one).
    doc = (
        "## Alpha\nAlpha content only. " * 60 + "\n"
        "## Beta\nBeta content only and nothing else. " * 60 + "\n"
    )
    chunks = chunk_text(doc, chunk_size=200, overlap=100)
    beta_chunks = [c for c in chunks if "Beta content" in c.text]
    assert beta_chunks
    # A chunk containing Beta content must carry the Beta heading (never Alpha).
    assert all(c.heading == "Beta" for c in beta_chunks if "Beta" in c.text[:40])
    # Alpha content must not be mislabeled Beta.
    for c in chunks:
        if "Alpha content" in c.text and "Beta content" not in c.text:
            assert c.heading == "Alpha"


def test_tiny_trailing_fragment_merged_into_previous_chunk() -> None:
    # A short tail (shorter than the min-chunk floor) is merged into the prior
    # chunk instead of stored as a low-value standalone embedding.
    doc = (
        "A sufficiently long opening paragraph that fills out the chunk size so "
        "that we have room for fragmentation. " * 30 + "Tiny tail fact: the dean is Dr Pawar."
    )
    chunks = chunk_text(doc, chunk_size=200, overlap=50, min_chunk_tokens=20)
    assert chunks
    # The tiny tail sentence is inside some chunk (not dropped) and no chunk is
    # a bare fragment below the floor.
    assert any("Dr Pawar" in c.text for c in chunks)
    assert all(c.tokens >= 20 for c in chunks[1:])


def test_default_min_chunk_fragment_merge_generic() -> None:
    # Generic guarantee: no emitted chunk (after the first) is a bare fragment.
    doc = ("Sentence number one. " * 40) + ("Ending tiny bit." * 3)
    chunks = chunk_text(doc)  # production default size
    assert all(c.tokens >= 5 for c in chunks)  # no near-empty fragment chunks
    assert all(c.text.strip() for c in chunks)
