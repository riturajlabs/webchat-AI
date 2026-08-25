"""Token-based chunking for the knowledge base (Phase 5, docs/02-TRD.md §6).

Splits cleaned page text into overlapping chunks sized by an approximate
tokenizer (words + punctuation runs). Chunk sizing is deterministic and
dependency-free: ~1 token per word or punctuation cluster, which tracks the
dense-embedding behavior of `gemini-embedding-001` closely enough for chunk
boundaries. Defaults follow the TRD: 500-800 tokens per chunk with a 100-token
overlap (ADR-008, Phase 5).
"""

import bisect
import re
from dataclasses import dataclass

from backend.core.config import get_settings

# Word or punctuation run; apostrophes/hyphens stay inside the word so
# "state-of-the-art" counts as one token.
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[''-][A-Za-z0-9]+)*|[^\sA-Za-z0-9]+")

# Sentence/paragraph boundaries are preferred chunk split points so a chunk is
# less likely to start/end mid-sentence (keeps semantic units intact).
_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+|\n\s*\n")

# Punctuation that closes a word; a space is dropped before these so a
# token-reconstructed chunk reads naturally ("only ." -> "only.").
_CLOSING_PUNCT_RE = re.compile(r"\s+([.,!?;:)%\"'\]}])")

# Markdown-style heading line emitted by the HTML cleaner (audit R-08):
# `#`..`######` followed by the heading text.
_HEADING_LINE_RE = re.compile(r"^ {0,3}(#{1,6})\s+(\S.*?)\s*#*\s*$")


def _join_tokens(tokens: list[str]) -> str:
    """Join tokenized words/punctuation into natural text."""
    return _CLOSING_PUNCT_RE.sub(r"\1", " ".join(tokens))


@dataclass(frozen=True)
class TextChunk:
    """One clean, chunked text unit ready for embedding."""

    index: int
    text: str
    tokens: int
    # Nearest heading at or above this chunk's start (audit R-08). `None`
    # when no heading precedes the chunk in the source document.
    heading: str | None = None


def count_tokens(text: str) -> int:
    """Approximate token count for `text` (deterministic)."""
    if not text:
        return 0
    return len(_TOKEN_RE.findall(text))


def _heading_index(text: str) -> tuple[list[int], list[int], list[str]]:
    """Map token positions to heading lines for nearest-heading lookups.

    Returns parallel lists sorted by position: token positions of each
    heading's first content token (right after its single `#`-run marker),
    token positions of each `#`-run marker itself, and the heading texts.
    Marker positions double as preferred chunk split points so a section
    heading leads the chunk that follows it.
    """
    positions: list[int] = []
    markers: list[int] = []
    headings: list[str] = []
    offset = 0
    for line in text.split("\n"):
        line_tokens = len(_TOKEN_RE.findall(line))
        match = _HEADING_LINE_RE.match(line)
        if match is not None and line_tokens > 1:
            positions.append(offset + 1)
            markers.append(offset)
            headings.append(match.group(2).strip())
        offset += line_tokens
    return positions, markers, headings


def _resolve_heading(
    positions: list[int],
    markers: list[int],
    headings: list[str],
    start: int,
    end: int,
) -> str | None:
    """Heading in effect for the token range `[start, end)`.

    Normally the last heading at-or-before the chunk start. When the chunk
    opens exactly at a section heading, or opens a document/section with the
    first heading beginning inside it, that heading is attributed instead so
    the section's first chunk still carries its context.
    """
    for i, marker in enumerate(markers):
        if marker == start:
            return headings[i]
    idx = bisect.bisect_right(positions, start) - 1
    if idx >= 0:
        return headings[idx]
    for i, marker in enumerate(markers):
        if start < marker < end:
            return headings[i]
    return None


def _iter_boundaries(tokens: list[str], start: int, end: int) -> list[int]:
    """Candidate split indexes strictly inside [start, end).

    `_BOUNDARY_RE` works on text, so we map split indexes back into token
    positions by rebuilding the original substring from tokens.
    """
    if end - start <= 2:
        return []
    segment = " ".join(tokens[start:end])
    points: list[int] = []
    for match in _BOUNDARY_RE.finditer(segment):
        # Approximate token position from whitespace run start.
        before = segment[: match.start()]
        approx_index = start + len(before.split())
        if start < approx_index < end:
            points.append(approx_index)
    return points


def chunk_text(
    text: str,
    *,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[TextChunk]:
    """Split `text` into overlapping token-bounded chunks.

    `chunk_size` and `overlap` are token counts; both default from settings
    (`KNOWLEDGE_CHUNK_SIZE_TOKENS=700`, `KNOWLEDGE_CHUNK_OVERLAP_TOKENS=100`).
    Overlap is clipped to chunk_size - 1 so the window always advances.
    """
    settings = get_settings()
    size = chunk_size if chunk_size is not None else settings.knowledge_chunk_size_tokens
    step_overlap = overlap if overlap is not None else settings.knowledge_chunk_overlap_tokens
    if size < 1:
        raise ValueError("chunk_size must be >= 1 token")
    if step_overlap < 0:
        raise ValueError("overlap must be >= 0 tokens")
    if step_overlap >= size:
        step_overlap = size - 1

    tokens = _TOKEN_RE.findall(text or "")
    if not tokens:
        return []

    # Audit R-08: track the nearest preceding heading so each chunk can carry
    # its section context into metadata without any schema change.
    heading_positions, marker_positions, heading_texts = _heading_index(text or "")

    chunks: list[TextChunk] = []
    start = 0
    index = 0
    while start < len(tokens):
        end = min(start + size, len(tokens))
        # Prefer a sentence/paragraph boundary inside the window as the cut.
        preferred = _iter_boundaries(tokens, start, end)
        # The final window consumes everything: a boundary cut there would
        # strand tiny fragments behind it (and can stall the window).
        if end == len(tokens):
            cut = end
        else:
            # A section heading inside the window is the strongest cut point:
            # the next chunk then opens with its own heading (audit R-08).
            marker_cuts = [p for p in marker_positions if start < p < end]
            cut = marker_cuts[-1] if marker_cuts else (preferred[-1] if preferred else end)
        chunk_tokens = tokens[start:cut]
        chunk = _join_tokens(chunk_tokens).strip()
        if chunk:
            chunks.append(
                TextChunk(
                    index=index,
                    text=chunk,
                    tokens=len(chunk_tokens),
                    heading=_resolve_heading(
                        heading_positions, marker_positions, heading_texts, start, cut
                    ),
                )
            )
            index += 1
        if cut == len(tokens):
            break
        # Advance by the overlap-adjusted stride; always move forward so the
        # window can never stall when a boundary cut sits close to `start`.
        start = max(start + 1, cut - step_overlap)

    return chunks


__all__ = ["TextChunk", "chunk_text", "count_tokens"]
