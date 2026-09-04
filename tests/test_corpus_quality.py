"""Tests for generic corpus-quality validation and safe re-ingestion tooling.

Phase P1: these pin the measurable quality gates used BEFORE a production
re-ingestion is allowed to run. Everything here is pure — it never writes to
Atlas/Redis and never re-embeds. The module under test is deliberately generic:
any site-specific terms are supplied as validation probes at call time.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.services.knowledge.corpus_quality import (
    ADJACENT_JACCARD_THRESHOLD,
    TINY_CHUNK_TOKENS,
    CorpusEntry,
    DryRunResult,
    SimulatedDocument,
    build_dry_run_report,
    compute_metrics,
    evaluate_gates,
    jaccard,
    probe_factual_preservation,
    simulate_rechunk,
)


@dataclass
class FakeChunk:
    """Minimal object exposing the required `corpus_quality` accessors."""

    text: str
    source: str = ""
    heading: str | None = None


# --------------------------------------------------------------------------- #
# jaccard
# --------------------------------------------------------------------------- #


def test_jaccard_identical_is_one() -> None:
    assert jaccard("alpha beta gamma", "alpha beta gamma") == 1.0


def test_jaccard_disjoint_is_zero() -> None:
    assert jaccard("alpha beta", "gamma delta") == 0.0


def test_jaccard_partial_overlap() -> None:
    a = "alpha beta gamma"
    b = "alpha beta delta"
    # union {alpha,beta,gamma,delta} = 4, intersection {alpha,beta} = 2
    assert jaccard(a, b) == 2 / 4


def test_jaccard_empty_both_is_one() -> None:
    assert jaccard("", "") == 1.0


# --------------------------------------------------------------------------- #
# compute_metrics — duplicates, tiny chunks, heading pollution, concentration
# --------------------------------------------------------------------------- #


def test_metrics_count_exact_duplicate_groups_within_document() -> None:
    entries = [
        CorpusEntry(text="same text here", source="a"),
        CorpusEntry(text="Same Text Here", source="b"),  # exact dup after normalize
        CorpusEntry(text="distinct text", source="c"),
    ]
    m = compute_metrics(entries)
    assert m.total_chunks == 3
    # G1 is scoped WITHIN a document: each copy lives in a different source, so
    # this is NOT counted as duplicate (cross-document content is legitimate).
    assert m.exact_duplicate_groups == 0
    assert m.exact_duplicate_extra_chunks == 0


def test_metrics_cross_document_identical_not_counted_as_duplicate() -> None:
    """P1.1 G1: identical text on DIFFERENT documents is NOT stored noise.

    Per-document ingestion keeps one copy per document for correct source
    attribution, so identical text repeated across documents (e.g. a shared
    branded "Learning Experiences" intro on several course pages) must not be
    counted as a duplicate.
    """
    entries = [
        CorpusEntry(text="Learning Experiences intro copy", source="doc-1"),
        CorpusEntry(text="Learning Experiences intro copy", source="doc-2"),
        CorpusEntry(text="Learning Experiences intro copy", source="doc-3"),
    ]
    m = compute_metrics(entries)
    assert m.exact_duplicate_groups == 0
    assert m.exact_duplicate_extra_chunks == 0


def test_metrics_within_document_duplicate_still_counted() -> None:
    """P1.1 G1: a duplicate WITHIN one document is still counted and fails G1."""
    entries = [
        CorpusEntry(text="repeated intro", source="doc-1"),
        CorpusEntry(text="Repeated Intro", source="doc-1"),  # normalize-identical
        CorpusEntry(text="other text", source="doc-1"),
    ]
    m = compute_metrics(entries)
    assert m.exact_duplicate_groups == 1
    assert m.exact_duplicate_extra_chunks == 1


def test_metrics_count_tiny_chunks() -> None:
    entries = [
        CorpusEntry(text="tiny"),                                     # < 40 tokens
        CorpusEntry(text="word " * 100),                              # ~100 tokens
    ]
    m = compute_metrics(entries, tiny_token_threshold=40)
    assert m.tiny_chunks_below == 1
    assert m.tiny_fraction == 0.5


def test_metrics_adjacent_high_jaccard_pairs() -> None:
    entries = [
        CorpusEntry(text="alpha beta gamma delta"),
        # Same token set (delta repeated) -> Jaccard 1.0, far above the 0.8 gate.
        CorpusEntry(text="alpha beta gamma delta delta"),
        CorpusEntry(text="completely unrelated topic here"),
    ]
    m = compute_metrics(entries)
    assert m.adjacent_pairs == 2
    assert m.adjacent_high_jaccard_pairs == 1
    assert m.adjacent_high_jaccard_fraction == 0.5


def test_metrics_repeated_heading_pollution() -> None:
    entries = [
        CorpusEntry(text="a", heading="Learning Experiences"),
        CorpusEntry(text="b", heading="Learning Experiences"),
        CorpusEntry(text="c", heading="Admission"),
    ]
    m = compute_metrics(entries)
    assert m.repeated_heading_label == "Learning Experiences"
    assert m.repeated_heading_pollution == 2
    assert m.repeated_heading_fraction == 2 / 3


def test_metrics_source_concentration() -> None:
    entries = [
        CorpusEntry(text="a", source="http://s1"),
        CorpusEntry(text="b", source="http://s1"),
        CorpusEntry(text="c", source="http://s2"),
    ]
    m = compute_metrics(entries)
    assert m.source_count == 2
    assert m.max_source_concentration == 2 / 3
    assert m.per_source == {"http://s1": 2, "http://s2": 1}


def test_metrics_empty_corpus_is_safe() -> None:
    m = compute_metrics([])
    assert m.total_chunks == 0
    assert m.tiny_chunks_below == 0
    assert m.adjacent_pairs == 0
    assert m.max_source_concentration == 0.0
    assert m.avg_tokens == 0.0


def test_metrics_average_and_median_size() -> None:
    entries = [
        CorpusEntry(text="one two three four five"),
        CorpusEntry(text="six seven"),
    ]
    m = compute_metrics(entries)
    assert m.avg_tokens == 3.5
    assert m.median_tokens == 3.5
    assert m.min_tokens == 2
    assert m.max_tokens == 5


# --------------------------------------------------------------------------- #
# probe_factual_preservation
# --------------------------------------------------------------------------- #


def test_probe_preservation_finds_fragment_case_insensitive() -> None:
    entries = [
        CorpusEntry(text="THE Dean of SOIT is Dr. Example."),
        CorpusEntry(text="admission process details here"),
    ]
    results = probe_factual_preservation(
        entries,
        [("dean", "dean of soit"), ("admission", "admission process")],
    )
    assert results[0].present is True
    assert results[0].matched_chunk_count == 1
    assert results[1].present is True


def test_probe_preservation_reports_missing() -> None:
    results = probe_factual_preservation(
        [CorpusEntry(text="nothing relevant")],
        [("missing", "dean of soit")],
    )
    assert results[0].present is False
    assert results[0].matched_chunk_count == 0


# --------------------------------------------------------------------------- #
# simulate_rechunk
# --------------------------------------------------------------------------- #


def test_simulate_rechunk_produces_entries_from_stored_content() -> None:
    docs = [
        SimulatedDocument(source="http://a", content="word " * 500),
        SimulatedDocument(source="http://b", content="word " * 500),
    ]
    entries = simulate_rechunk(docs)
    assert entries
    assert all(entry.source in {"http://a", "http://b"} for entry in entries)
    # Deterministic: two simulations over identical input are identical.
    again = simulate_rechunk(docs)
    assert [e.text for e in entries] == [e.text for e in again]


def test_simulate_rechunk_is_pure_and_writes_nothing() -> None:
    docs = [SimulatedDocument(source="http://a", content="word " * 300)]
    before = [d.content for d in docs]
    simulate_rechunk(docs)
    assert [d.content for d in docs] == before


# --------------------------------------------------------------------------- #
# build_dry_run_report
# --------------------------------------------------------------------------- #


def test_dry_run_report_compares_old_vs_simulated_new() -> None:
    old = [
        CorpusEntry(text="tiny"),
        CorpusEntry(text="tiny"),                              # duplicate
        CorpusEntry(text="word " * 200, heading="Learning Experiences"),
    ]
    docs = [SimulatedDocument(source="http://a", content="word " * 800)]
    report = build_dry_run_report(old, docs)
    assert isinstance(report, DryRunResult)
    assert report.old.total_chunks == 3
    assert report.old.exact_duplicate_extra_chunks == 1
    assert report.new.total_chunks >= 1
    # The simulation removed the notional duplicate pollution.
    assert report.new.exact_duplicate_extra_chunks == 0


def test_dry_run_report_probes_applied_to_both_corpora() -> None:
    old = [CorpusEntry(text="dean of soit is dr example", source="http://a")]
    docs = [SimulatedDocument(source="http://a", content="dean of soit is dr example")]
    report = build_dry_run_report(old, docs, probes=[("dean", "dean of soit")])
    assert report.probes_old[0].present is True
    assert report.probes_new[0].present is True


# --------------------------------------------------------------------------- #
# evaluate_gates — explicit PASS/FAIL corpus-quality gates
# --------------------------------------------------------------------------- #


def test_gates_pass_on_a_clean_simulated_corpus() -> None:
    old = [
        CorpusEntry(text="tiny"),
        CorpusEntry(text="tiny"),
        CorpusEntry(text="word " * 200, heading="Learning Experiences"),
    ]
    docs = [
        SimulatedDocument(source="http://a", content="word " * 800 + " dean of soit example"),
        SimulatedDocument(source="http://b", content="other " * 400 + " admission process example"),
    ]
    report = build_dry_run_report(
        old,
        docs,
        probes=[("dean", "dean of soit"), ("admission", "admission process")],
    )
    gates = evaluate_gates(
        report, probes=[("dean", "dean of soit"), ("admission", "admission process")]
    )
    by_name = {g.name: g for g in gates}

    assert by_name["duplication_reduction"].passed is True
    assert by_name["tiny_chunk_reduction"].passed is True
    assert by_name["heading_pollution_reduction"].passed is True
    assert by_name["factual_preservation"].passed is True
    assert by_name["deterministic_chunking"].passed is True
    assert by_name["source_coverage"].passed is True


def test_gates_fail_when_probe_content_is_missing() -> None:
    old = [CorpusEntry(text="word " * 300, source="http://a")]
    docs = [SimulatedDocument(source="http://a", content="word " * 800)]
    report = build_dry_run_report(
        old,
        docs,
        probes=[("dean", "dean of soit")],
    )
    gates = evaluate_gates(report, probes=[("dean", "dean of soit")])
    preservation = next(g for g in gates if g.name == "factual_preservation")
    assert preservation.passed is False
    assert "dean" in preservation.detail


def test_gates_duplication_fails_when_simulation_keeps_duplicates() -> None:
    # A hand-built report whose "new" corpus has duplicates should fail G1.
    old = [CorpusEntry(text="x")]
    new = [
        CorpusEntry(text="dup"),
        CorpusEntry(text="dup"),
        CorpusEntry(text="other " * 100),
    ]
    report = DryRunResult(
        old_entries=old,
        new_entries=new,
        old=compute_metrics(old),
        new=compute_metrics(new),
    )
    gates = evaluate_gates(report, probes=[])
    dup_gate = next(g for g in gates if g.name == "duplication_reduction")
    assert dup_gate.passed is False


def test_threshold_constants_align_with_chunker() -> None:
    # The quality gates' token floor must match the chunker's MIN_CHUNK_TOKENS
    # so a "tiny" simulated chunk is exactly what the chunker would refuse.
    from backend.services.knowledge import chunker

    assert TINY_CHUNK_TOKENS == chunker.MIN_CHUNK_TOKENS
    assert ADJACENT_JACCARD_THRESHOLD == 0.8


# P1.1 G3: legitimate structural headings are not boilerplate pollution.
def test_g3_structural_heading_excluded_from_pollution() -> None:
    """A dominant structural section header ('Curriculum') must not fail G3.

    Course pages legitimately repeat a "## Curriculum" section header; that is
    website structure, not boilerplate pollution. Supplying it as a structural
    heading means the gate measures only genuinely polluting (non-structural)
    headings.
    """
    old = [CorpusEntry(text="word " * 200, heading="Learning Experiences")]
    new = [CorpusEntry(text="word " * 200, heading="Curriculum") for _ in range(18)]
    new.append(CorpusEntry(text="word " * 200, heading="Admission"))
    new.append(CorpusEntry(text="word " * 200, heading="Fees"))
    report = DryRunResult(
        old_entries=old,
        new_entries=new,
        old=compute_metrics(old),
        new=compute_metrics(new),
    )
    # Without the whitelist, 'Curriculum' at 18/20 would dominate the gate.
    gates = evaluate_gates(report, probes=[], structural_headings=["Curriculum"])
    g3 = next(g for g in gates if g.name == "heading_pollution_reduction")
    assert g3.passed is True, f"G3 should pass with structural exclusion: {g3.detail}"


def test_g3_boilerplate_pollution_still_detected() -> None:
    """Actual boilerplate ('Learning Experiences') must still fail G3.

    The structural-heading refinement may not silence real pollution: a
    repeated boilerplate heading that is NOT whitelisted must keep the gate
    failing.
    """
    new = [
        CorpusEntry(text="word " * 200, heading="Learning Experiences"),
        CorpusEntry(text="word " * 200, heading="Learning Experiences"),
        CorpusEntry(text="word " * 200, heading="Admission"),
    ]
    report = DryRunResult(
        old_entries=[CorpusEntry(text="x")],
        new_entries=new,
        old=compute_metrics([CorpusEntry(text="x")]),
        new=compute_metrics(new),
    )
    # Whitelist only the structural heading, not the boilerplate.
    gates = evaluate_gates(report, probes=[], structural_headings=["Curriculum"])
    g3 = next(g for g in gates if g.name == "heading_pollution_reduction")
    assert g3.passed is False
    assert "Learning Experiences" in g3.detail


def test_adjacent_threshold_constant_value() -> None:
    assert ADJACENT_JACCARD_THRESHOLD == 0.8
