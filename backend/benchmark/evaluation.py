"""AI answer quality evaluation metrics (Phase 3 Step 4).

Pure-function evaluator that scores a single benchmark response along
retrieval and answer dimensions.  No I/O, no side effects — easy to test.

Metrics
-------
**Retrieval**
- ``retrieved_chunk_count``: number of source chunks returned by the pipeline.
- ``avg_relevance_score``: mean of the per-chunk similarity scores.
- ``context_coverage``: fraction of retrieved sources the answer uses
  (0.0-1.0).  Counts distinct valid ``[N]`` citation markers when present
  (out-of-range citations are ignored), else falls back to matching
  source URL/title substrings in the answer text.  Higher means the
  answer actually uses the retrieved context.

**Answer**
- ``response_length``: character count of the full answer.
- ``is_empty``: ``True`` when the answer is blank or whitespace-only.
- ``is_truncated``: ``True`` when the answer ends mid-sentence (no
  terminal punctuation and no closing bracket/paren).
- ``citation_count``: number of ``[N]`` citation markers in the answer.
- ``context_used``: ``True`` when at least one ``[N]`` marker is present.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TERMINAL = re.compile(r"[.!?)\]}]\s*$")
_CITATION = re.compile(r"\[[0-9]+\]")


@dataclass(frozen=True)
class QualityMetrics:
    """Quality scores for a single benchmark response."""

    retrieved_chunk_count: int = 0
    avg_relevance_score: float = 0.0
    context_coverage: float = 0.0
    response_length: int = 0
    is_empty: bool = True
    is_truncated: bool = False
    citation_count: int = 0
    context_used: bool = False


@dataclass(frozen=True)
class SourceInfo:
    """Minimal source-chunk metadata extracted from the SSE ``sources`` event."""

    url: str = ""
    title: str = ""
    score: float = 0.0


def evaluate_quality(
    *,
    answer: str,
    sources: list[SourceInfo],
    expected_fragment: str = "",
    fallback: bool = False,
) -> QualityMetrics:
    """Score a single response for quality.

    Parameters
    ----------
    answer:
        The concatenated answer text produced by the LLM.
    sources:
        Source chunks returned by the retrieval pipeline (may be empty).
    expected_fragment:
        An optional substring that *should* appear in the answer when the
        knowledge base contains the relevant information.
    fallback:
        ``True`` when the pipeline fell back to the fixed no-context
        message (empty knowledge base or retrieval miss).
    """
    response_length = len(answer.strip())
    is_empty = response_length == 0

    citation_count = len(_CITATION.findall(answer))
    context_used = citation_count > 0

    is_truncated = _detect_truncation(answer, fallback)

    chunk_count = len(sources)
    avg_score = _avg_score(sources)
    coverage = _context_coverage(answer, sources)

    return QualityMetrics(
        retrieved_chunk_count=chunk_count,
        avg_relevance_score=avg_score,
        context_coverage=coverage,
        response_length=response_length,
        is_empty=is_empty,
        is_truncated=is_truncated,
        citation_count=citation_count,
        context_used=context_used,
    )


def _detect_truncation(answer: str, fallback: bool) -> bool:
    """Heuristic: an answer is truncated when it ends abruptly.

    Fallback answers are never considered truncated (they are a fixed
    known string).
    """
    if fallback or not answer:
        return False
    text = answer.rstrip()
    if _TERMINAL.search(text):
        return False
    # A very short answer (< 20 chars) that lacks a terminal is likely
    # just a fragment, not a truncation.
    if len(text) < 20:
        return False
    return True


def _avg_score(sources: list[SourceInfo]) -> float:
    """Mean similarity score across sources (0.0 when empty)."""
    if not sources:
        return 0.0
    return round(sum(s.score for s in sources) / len(sources), 4)


def _context_coverage(answer: str, sources: list[SourceInfo]) -> float:
    """Fraction of retrieved sources the answer actually uses.

    Production answers cite sources via ``[N]`` markers rather than by URL
    or title, so when any valid ``[N]`` marker is present coverage counts
    distinct in-range citations over the source count; out-of-range markers
    (hallucinated references) are ignored.  Answers without citation
    markers fall back to legacy URL/title substring matching.
    """
    if not sources or not answer:
        return 0.0
    cited = {
        number
        for marker in _CITATION.findall(answer)
        if 1 <= (number := int(marker[1:-1])) <= len(sources)
    }
    if cited:
        return round(len(cited) / len(sources), 4)
    answer_lower = answer.lower()
    hits = 0
    for src in sources:
        # Check URL substring first (more specific), then title.
        if src.url and src.url.lower() in answer_lower:
            hits += 1
        elif src.title and src.title.lower() in answer_lower:
            hits += 1
    return round(hits / len(sources), 4)
