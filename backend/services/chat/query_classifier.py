"""Lightweight rule-based query complexity classifier for adaptive retrieval.

Classifies user queries into ``SIMPLE``, ``MEDIUM``, or ``COMPLEX`` buckets
using only string signals (word count, length, keywords, structure).  No
external API calls, no LLM, no ML model — pure Python rules.

The classification drives adaptive retrieval parameters in ``RagService``:
simple queries use smaller top_k and context budgets, complex queries use
larger ones.  Disabled by default via ``enable_adaptive_retrieval``.
"""

from __future__ import annotations

import re
from enum import Enum


class QueryComplexity(Enum):
    """Query complexity levels for adaptive retrieval."""

    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


# ---------------------------------------------------------------------------
# Signal keywords
# ---------------------------------------------------------------------------

# Words that indicate the user is asking for comparison, multi-part, or
# detailed explanations.  A query containing 2+ of these is COMPLEX.
_MULTI_PART_KEYWORDS: frozenset[str] = frozenset(
    {
        "and",
        "also",
        "additionally",
        "moreover",
        "furthermore",
        "compare",
        "comparison",
        "versus",
        "vs",
        "difference",
        "differences",
        "pros",
        "cons",
        "advantages",
        "disadvantages",
        "alternatives",
    }
)

# Words that signal a request for deep / technical / detailed content.
_DETAIL_KEYWORDS: frozenset[str] = frozenset(
    {
        "explain",
        "explanation",
        "how",
        "why",
        "describe",
        "detailed",
        "architecture",
        "implementation",
        "configure",
        "setup",
        "install",
        "integrate",
        "integration",
        "deploy",
        "deployment",
        "migrate",
        "migration",
        "troubleshoot",
        "debug",
        "optimize",
        "performance",
        "security",
        "compliance",
        "audit",
        "specification",
        "requirements",
        "workflow",
        "pipeline",
    }
)

# Words that signal simple factual / lookup queries.
_SIMPLE_KEYWORDS: frozenset[str] = frozenset(
    {
        "what",
        "who",
        "when",
        "where",
        "price",
        "pricing",
        "cost",
        "plan",
        "plans",
        "feature",
        "features",
        "contact",
        "phone",
        "email",
        "address",
        "hours",
        "open",
        "close",
        "link",
        "url",
        "login",
        "signin",
        "sign",
        "download",
    }
)

# Pattern for detecting questions with multiple clauses (e.g., "X and Y?").
_MULTI_CLAUSE_RE = re.compile(
    r"\b(?:and|also|additionally|moreover|furthermore|but|however)\b",
    re.IGNORECASE,
)

# Pattern for detecting numbered lists or bullet-like structures.
_LIST_RE = re.compile(r"(?:\d+[\.\)]\s|[-•*]\s)")


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def classify_query(question: str) -> QueryComplexity:
    """Classify a user question into a complexity bucket.

    Uses a scoring system based on multiple lightweight signals:
    - Word count
    - Character length
    - Multi-part keywords
    - Detail/technical keywords
    - Simple/factual keywords
    - Clause structure (conjunctions, lists)

    Parameters
    ----------
    question:
        The sanitized user question.

    Returns
    -------
    QueryComplexity
        ``SIMPLE`` for factual lookups, ``MEDIUM`` for standard questions,
        ``COMPLEX`` for multi-part or technical questions.
    """
    text = question.strip()
    if not text:
        return QueryComplexity.SIMPLE

    words = text.split()
    word_count = len(words)
    char_count = len(text)
    lower_text = text.lower()
    lower_words = set(lower_text.split())

    score = 0

    # --- Signal 1: Word count ---
    if word_count <= 4:
        score -= 1  # very short → likely simple
    elif word_count >= 15:
        score += 2  # long → likely complex
    elif word_count >= 8:
        score += 1

    # --- Signal 2: Character length ---
    if char_count <= 20:
        score -= 1
    elif char_count >= 100:
        score += 1

    # --- Signal 3: Multi-part keywords ---
    multi_hits = len(lower_words & _MULTI_PART_KEYWORDS)
    if multi_hits >= 2:
        score += 2
    elif multi_hits == 1:
        score += 1

    # --- Signal 4: Detail / technical keywords ---
    detail_hits = len(lower_words & _DETAIL_KEYWORDS)
    if detail_hits >= 2:
        score += 2
    elif detail_hits == 1:
        score += 1

    # --- Signal 5: Simple / factual keywords (inverse signal) ---
    simple_hits = len(lower_words & _SIMPLE_KEYWORDS)
    if simple_hits >= 2:
        score -= 1
    elif simple_hits == 1 and word_count <= 6:
        score -= 1

    # --- Signal 6: Clause structure ---
    clause_count = len(_MULTI_CLAUSE_RE.findall(text))
    if clause_count >= 2:
        score += 2
    elif clause_count == 1:
        score += 1

    # --- Signal 7: List / enumeration ---
    if _LIST_RE.search(text):
        score += 1

    # --- Map score to complexity ---
    if score <= 0:
        return QueryComplexity.SIMPLE
    if score <= 2:
        return QueryComplexity.MEDIUM
    return QueryComplexity.COMPLEX


__all__ = ["QueryComplexity", "classify_query"]
