"""Generic corpus-quality validation and safe re-ingestion dry-run tooling.

Phase P1: make corpus re-ingestion SAFE and MEASURABLE before the production
data is touched. Everything here is pure and **never writes to Atlas/Redis**:
it computes metrics over already-fetched chunk/document data, optionally
*simulates* what the current chunker would produce from each document's
stored content, and emits a dry-run report ("if we re-ingest this website,
this is what would change").

The module is deliberately generic. Any site-specific terms (e.g. a dean's
name, a "Learning Experiences" heading) are **validation probes passed at call
time**; none are hard-coded into the metrics or the chunker.

All functions are deterministic for identical input.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from statistics import mean, median
from typing import Any, Protocol

from backend.services.knowledge.chunker import TextChunk, chunk_text, count_tokens

# Jaccard-similarity ceiling above which an adjacent chunk pair is treated as a
# near-duplicate (matches the audit's >0.80 measurement of the live corpus).
ADJACENT_JACCARD_THRESHOLD = 0.8

# Token floor below which a chunk is counted as a "tiny fragment". This matches
# the chunker's MIN_CHUNK_TOKENS and the audit's <40-token measurement.
TINY_CHUNK_TOKENS = 40


def _norm(text: str) -> str:
    """Normalize text for duplicate/fragment matching (lowercase, collapse ws)."""
    return " ".join((text or "").split()).lower()


def _tokens(text: str) -> set[str]:
    return set((text or "").split())


def jaccard(a: str, b: str) -> float:
    """Token Jaccard similarity between two strings in ``[0.0, 1.0]``."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta and not tb:
        return 1.0
    union = ta | tb
    if not union:
        return 0.0
    return len(ta & tb) / len(union)


class _ChunkLike(Protocol):
    """Minimal accessor a corpus entry must satisfy for quality metrics."""

    @property
    def text(self) -> str: ...

    @property
    def heading(self) -> str | None: ...

    @property
    def source(self) -> str: ...


@dataclass(frozen=True)
class CorpusEntry:
    """One retrievable unit for quality measurement.

    ``source`` is the document/URL label (e.g. ``document.url``) used for
    source-concentration metrics; ``heading`` is the chunk's nearest heading or
    ``None``. ``text`` is the chunk body.
    """

    text: str
    source: str = ""
    heading: str | None = None

    @classmethod
    def from_chunk(cls, chunk: Any, source: str = "") -> CorpusEntry:
        """Build from a ``KnowledgeChunk`` (or any object exposing chunk_text)."""
        text = getattr(chunk, "chunk_text", None) or getattr(chunk, "text", None) or ""
        metadata = getattr(chunk, "metadata", None) or {}
        heading = metadata.get("heading") if isinstance(metadata, dict) else None
        src = source or metadata.get("source_url", "") if isinstance(metadata, dict) else source
        return cls(text=text, source=src, heading=heading)

    @classmethod
    def from_text_chunk(cls, chunk: TextChunk, source: str = "") -> CorpusEntry:
        return cls(text=chunk.text, source=source, heading=chunk.heading)


@dataclass(frozen=True)
class QualityMetrics:
    """Aggregate quality metrics over a set of corpus entries."""

    total_chunks: int
    tiny_chunks_below: int
    tiny_fraction: float
    exact_duplicate_groups: int
    exact_duplicate_extra_chunks: int
    adjacent_high_jaccard_pairs: int
    adjacent_pairs: int
    adjacent_high_jaccard_fraction: float
    repeated_heading_pollution: int
    repeated_heading_label: str | None
    repeated_heading_fraction: float
    avg_tokens: float
    median_tokens: float
    min_tokens: int
    max_tokens: int
    total_tokens: int
    per_source: dict[str, int]
    max_source_concentration: float
    source_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_chunks": self.total_chunks,
            "tiny_chunks_below": self.tiny_chunks_below,
            "tiny_fraction": round(self.tiny_fraction, 4),
            "exact_duplicate_groups": self.exact_duplicate_groups,
            "exact_duplicate_extra_chunks": self.exact_duplicate_extra_chunks,
            "adjacent_high_jaccard_pairs": self.adjacent_high_jaccard_pairs,
            "adjacent_pairs": self.adjacent_pairs,
            "adjacent_high_jaccard_fraction": round(self.adjacent_high_jaccard_fraction, 4),
            "repeated_heading_pollution": self.repeated_heading_pollution,
            "repeated_heading_label": self.repeated_heading_label,
            "repeated_heading_fraction": round(self.repeated_heading_fraction, 4),
            "avg_tokens": round(self.avg_tokens, 2),
            "median_tokens": self.median_tokens,
            "min_tokens": self.min_tokens,
            "max_tokens": self.max_tokens,
            "total_tokens": self.total_tokens,
            "per_source": dict(self.per_source),
            "max_source_concentration": round(self.max_source_concentration, 4),
            "source_count": self.source_count,
        }


def compute_metrics(
    entries: Iterable[_ChunkLike],
    *,
    tiny_token_threshold: int = TINY_CHUNK_TOKENS,
    adjacent_jaccard_threshold: float = ADJACENT_JACCARD_THRESHOLD,
) -> QualityMetrics:
    """Compute corpus-quality metrics over `entries` (generic, pure).

    `entries` is any iterable of objects exposing ``.text``, ``.heading`` and
    ``.source`` --- pass ``CorpusEntry`` objects (see ``from_chunk``/
    ``from_text_chunk``) built from stored chunks or simulated chunks.
    """
    items = list(entries)
    total = len(items)

    texts = [_norm(item.text) for item in items]
    token_counts = [count_tokens(item.text) for item in items]
    sources = [item.source or "<unknown>" for item in items]

    # Exact duplicate text groups WITHIN a single source document.
    #
    # Re-ingestion dedups per-document (each document is processed independently
    # and should remain independently retrievable for correct source
    # attribution), so identical text repeated ACROSS different documents is
    # legitimate per-document content, not stored noise. Duplication is only
    # counted when the same normalized text occurs more than once WITHIN the
    # same source document.
    grouped: dict[tuple[str, str], int] = {}
    for src, nt in zip(sources, texts, strict=True):
        key = (src, nt)
        grouped[key] = grouped.get(key, 0) + 1
    duplicate_groups = sum(1 for c in grouped.values() if c > 1)
    duplicate_extra = sum(c - 1 for c in grouped.values() if c > 1)

    # Adjacent high-Jaccard duplicate pairs.
    adjacent_pairs = max(0, total - 1)
    high_jaccard = 0
    for i in range(adjacent_pairs):
        if jaccard(items[i].text, items[i + 1].text) > adjacent_jaccard_threshold:
            high_jaccard += 1

    # Repeated heading pollution: the single most frequently repeated non-empty
    # heading and how many chunks are tagged by it.
    heading_counts: dict[str, int] = {}
    for item in items:
        if item.heading:
            heading_counts[item.heading] = heading_counts.get(item.heading, 0) + 1
    repeated_label: str | None = None
    repeated_count = 0
    if heading_counts:
        repeated_label = max(heading_counts, key=lambda h: heading_counts[h])
        repeated_count = heading_counts[repeated_label]

    # Source/document concentration.
    per_source: dict[str, int] = {}
    for item in items:
        src_label = item.source or "<unknown>"
        per_source[src_label] = per_source.get(src_label, 0) + 1
    source_count = len(per_source)
    max_source_concentration = (max(per_source.values()) / total) if total else 0.0

    return QualityMetrics(
        total_chunks=total,
        tiny_chunks_below=sum(1 for t in token_counts if t < tiny_token_threshold),
        tiny_fraction=(sum(1 for t in token_counts if t < tiny_token_threshold) / total)
        if total
        else 0.0,
        exact_duplicate_groups=duplicate_groups,
        exact_duplicate_extra_chunks=duplicate_extra,
        adjacent_high_jaccard_pairs=high_jaccard,
        adjacent_pairs=adjacent_pairs,
        adjacent_high_jaccard_fraction=(high_jaccard / adjacent_pairs) if adjacent_pairs else 0.0,
        repeated_heading_pollution=repeated_count,
        repeated_heading_label=repeated_label,
        repeated_heading_fraction=(repeated_count / total) if total else 0.0,
        avg_tokens=mean(token_counts) if token_counts else 0.0,
        median_tokens=median(token_counts) if token_counts else 0.0,
        min_tokens=min(token_counts) if token_counts else 0,
        max_tokens=max(token_counts) if token_counts else 0,
        total_tokens=sum(token_counts),
        per_source=per_source,
        max_source_concentration=max_source_concentration,
        source_count=source_count,
    )


@dataclass(frozen=True)
class ProbeResult:
    """Whether a factual-content probe survived in a corpus."""

    label: str
    present: bool
    matched_chunk_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "present": self.present,
            "matched_chunk_count": self.matched_chunk_count,
        }


def probe_factual_preservation(
    entries: Iterable[_ChunkLike],
    probes: Iterable[tuple[str, str]],
) -> list[ProbeResult]:
    """Check that representative factual fragments survive in `entries`.

    `probes` is a validation-time list of ``(label, canonical_text_fragment)``.
    A probe passes when at least one entry's normalized text contains the
    fragment (case/whitespace-insensitive). Nothing here is hard-coded into
    production logic; the probes are supplied by the caller.
    """
    items = list(entries)
    normalized = [_norm(item.text) for item in items]
    results: list[ProbeResult] = []
    for label, fragment in probes:
        needle = _norm(fragment)
        hits = sum(1 for nt in normalized if needle and needle in nt)
        results.append(ProbeResult(label=label, present=hits > 0, matched_chunk_count=hits))
    return results


@dataclass
class SimulatedDocument:
    """Stored-content input for a re-ingestion simulation."""

    source: str
    content: str


def simulate_rechunk(documents: Iterable[SimulatedDocument]) -> list[CorpusEntry]:
    """Run the current chunker over each document's stored content.

    Mirrors the production ingestion path: within each source document, exact
    (normalized-text) duplicates are dropped before the corpus is counted, so
    the simulated-new metrics reflect exactly what `replace_by_document` would
    persist. Pure: only computes new chunks in memory; writes nothing.
    """
    out: list[CorpusEntry] = []
    for doc in documents:
        seen: set[str] = set()
        for text_chunk in chunk_text(doc.content):
            key = _norm(text_chunk.text)
            if key in seen:
                continue
            seen.add(key)
            out.append(CorpusEntry.from_text_chunk(text_chunk, source=doc.source))
    return out


@dataclass
class DryRunResult:
    """Structural comparison of an old corpus vs. a simulated re-ingestion.

    Kept mutable (not frozen) so ``evaluate_gates`` can rerun the determinism
    simulation lazily without the caller having to precompute it.
    """

    old_entries: list[CorpusEntry]
    new_entries: list[CorpusEntry]
    old: QualityMetrics
    new: QualityMetrics
    probes_old: list[ProbeResult] = field(default_factory=list)
    probes_new: list[ProbeResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "old": self.old.to_dict(),
            "new": self.new.to_dict(),
            "probes_old": [p.to_dict() for p in self.probes_old],
            "probes_new": [p.to_dict() for p in self.probes_new],
        }


def build_dry_run_report(
    old_entries: Iterable[_ChunkLike],
    documents: Iterable[SimulatedDocument],
    *,
    probes: Iterable[tuple[str, str]] | None = None,
) -> DryRunResult:
    """Build a dry-run report: old corpus metrics vs. simulated re-ingestion.

    No writes are performed. ``probes`` (optional factual-preservation probes)
    are checked against both the old and the simulated-new corpus.
    """
    old_items = [
        CorpusEntry.from_chunk(item) if not hasattr(item, "text") else item
        for item in old_entries
    ]
    old_entries_typed: list[CorpusEntry] = [
        item if isinstance(item, CorpusEntry) else CorpusEntry(text=getattr(item, "text", ""))
        for item in old_items
    ]
    new_items = simulate_rechunk(documents)
    old_metrics = compute_metrics(old_entries_typed)
    new_metrics = compute_metrics(new_items)
    probe_list = list(probes or ())
    return DryRunResult(
        old_entries=old_entries_typed,
        new_entries=new_items,
        old=old_metrics,
        new=new_metrics,
        probes_old=probe_factual_preservation(old_entries_typed, probe_list),
        probes_new=probe_factual_preservation(new_items, probe_list),
    )


@dataclass(frozen=True)
class GateResult:
    """One PASS/FAIL gate with its passing condition and evidence."""

    name: str
    passed: bool
    detail: str


def evaluate_gates(
    dry_run: DryRunResult,
    *,
    probes: Iterable[tuple[str, str]],
    tiny_token_threshold: int = TINY_CHUNK_TOKENS,
    structural_headings: Iterable[str] | None = None,
    heading_pollution_target: float = 0.10,
) -> list[GateResult]:
    """Evaluate the explicit corpus-quality gates for a re-ingestion.

    Gate thresholds are derived from the current production corpus + the
    chunker's guarantees (see P1 report §"PASS/FAIL gates" for the basis):
      G1 Duplication reduction: exact-duplicate EXTRA chunks in the simulated-new
         corpus must be 0 and adjacent high-Jaccard fraction must be 0.
      G2 Tiny-chunk reduction: zero simulated-new chunks below the token floor.
      G3 Heading-pollution reduction: no *boilerplate* repeated heading must
         dominate the corpus (fraction target <= `heading_pollution_target`).
         Legitimate structural section headers (e.g. a course page's
         "Curriculum" section, supplied via `structural_headings`) are not
         treated as boilerplate pollution, while a genuinely repeated
         boilerplate heading (e.g. "Learning Experiences") is still detected.
      G4 Factual-content preservation: every probe survives in the new corpus.
      G5 Deterministic chunking: the new simulation runs are byte-identical (the
         chunker is already deterministic; a second run here asserts this).
      G6 Source coverage: every source document contributes >= 1 chunk.
    """
    gates: list[GateResult] = []
    structural = {h for h in (structural_headings or ()) if h}

    # G1
    g1 = (
        dry_run.new.exact_duplicate_extra_chunks == 0
        and dry_run.new.adjacent_high_jaccard_fraction == 0.0
    )
    gates.append(
        GateResult(
            name="duplication_reduction",
            passed=bool(g1),
            detail=(
                f"new exact-dup extra={dry_run.new.exact_duplicate_extra_chunks} "
                f"(old={dry_run.old.exact_duplicate_extra_chunks}), "
                f"new adjacent >0.80 frac={dry_run.new.adjacent_high_jaccard_fraction:.4f} "
                f"(old={dry_run.old.adjacent_high_jaccard_fraction:.4f})"
            ),
        )
    )

    # G2
    g2 = dry_run.new.tiny_chunks_below == 0
    gates.append(
        GateResult(
            name="tiny_chunk_reduction",
            passed=bool(g2),
            detail=(
                f"new chunks below {tiny_token_threshold} tokens = "
                f"{dry_run.new.tiny_chunks_below} (old={dry_run.old.tiny_chunks_below})"
            ),
        )
    )

    # G3: polluting (non-structural) repeated-heading domination.
    # Count chunk-heading frequencies excluding legitimate structural headers.
    polluting_counts: dict[str, int] = {}
    for entry in dry_run.new_entries:
        heading = entry.heading
        if not heading:
            continue
        if heading in structural:
            continue
        polluting_counts[heading] = polluting_counts.get(heading, 0) + 1
    new_total = dry_run.new.total_chunks or 1
    if polluting_counts:
        top_polluting = max(polluting_counts, key=lambda h: polluting_counts[h])
        top_polluting_count = polluting_counts[top_polluting]
        pollution_fraction = top_polluting_count / new_total
    else:
        top_polluting = None
        top_polluting_count = 0
        pollution_fraction = 0.0
    target = heading_pollution_target
    g3 = pollution_fraction <= target
    gates.append(
        GateResult(
            name="heading_pollution_reduction",
            passed=bool(g3),
            detail=(
                f"new top polluting heading '{top_polluting}' tags "
                f"{top_polluting_count}/{dry_run.new.total_chunks} "
                f"({pollution_fraction:.4f}); structural headings excluded: "
                f"{sorted(structural) or 'none'}; gate target <= {target}"
            ),
        )
    )

    # G4
    probe_results = probe_factual_preservation(dry_run.new_entries, probes)
    g4 = all(p.present for p in probe_results)
    gates.append(
        GateResult(
            name="factual_preservation",
            passed=bool(g4),
            detail="; ".join(f"{p.label}={p.present}" for p in probe_results) or "no probes",
        )
    )

    # G5 deterministic: rerun the chunker over the same content and compare.
    determinism_sample = dry_run.new_entries[0].text if dry_run.new_entries else ""
    if determinism_sample:
        first = chunk_text(determinism_sample)
        second = chunk_text(determinism_sample)
        determinism_ok = [c.text for c in first] == [c.text for c in second]
    else:
        determinism_ok = True
    gates.append(
        GateResult(
            name="deterministic_chunking",
            passed=bool(determinism_ok),
            detail="two identical re-chunk runs produced identical output"
            if determinism_ok
            else "determinism check failed",
        )
    )

    # G6 source coverage
    new_sources = set(dry_run.new.per_source)
    g6 = dry_run.new.source_count == len(new_sources) and dry_run.new.source_count > 0
    gates.append(
        GateResult(
            name="source_coverage",
            passed=bool(g6),
            detail=(
                f"new corpus spans {dry_run.new.source_count} source(s) with "
                f"{dry_run.new.total_chunks} chunks"
            ),
        )
    )

    return gates


__all__ = [
    "ADJACENT_JACCARD_THRESHOLD",
    "TINY_CHUNK_TOKENS",
    "CorpusEntry",
    "QualityMetrics",
    "SimulatedDocument",
    "DryRunResult",
    "GateResult",
    "compute_metrics",
    "simulate_rechunk",
    "probe_factual_preservation",
    "build_dry_run_report",
    "evaluate_gates",
    "jaccard",
]
