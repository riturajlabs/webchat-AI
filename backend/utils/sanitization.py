"""Shared input sanitization utilities.

Provides reusable helpers for safe string handling across the backend:
  - `safe_regex()` — escape user input before passing to MongoDB ``$regex``.
  - `sanitize_text()` — strip control characters and collapse whitespace.
  - `truncate_at_word_boundary()` — cap length without cutting mid-word.

These are general-purpose building blocks; domain-specific sanitization (e.g.
LLM prompt injection defense) lives in its own module (``prompts/rag.py``,
``core/prompt_guard.py``).
"""

import re

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def safe_regex(value: str) -> str:
    """Escape ``value`` for safe use in a MongoDB ``$regex`` operator.

    Applies ``re.escape()`` so regex metacharacters (``.``, ``*``, ``(``, …)
    are treated as literals.  Always use this when user-provided text flows
    into a ``$regex`` query filter.
    """
    return re.escape(value)


def sanitize_text(value: str, *, max_length: int = 5000) -> str:
    """Strip control characters, collapse whitespace, and cap length.

    This is a generic pre-processing step for user-supplied text that will
    be stored or displayed.  It does **not** perform HTML escaping — use
    the framework's built-in escaping (e.g. Jinja2 autoescape) at the
    rendering boundary.
    """
    cleaned = _CONTROL_CHARS.sub("", value)
    cleaned = " ".join(cleaned.split())
    return cleaned[:max_length]


def truncate_at_word_boundary(text: str, limit: int) -> str:
    """Cap *text* at *limit* characters without splitting the last word.

    Cuts at the last whitespace inside the limit so the returned text cannot
    end mid-word with a garbled tail (RAG-06).  When the limit falls inside a
    single unbroken token, falls back to a plain character cut so the caller
    never receives truncated-at-word-boundary empty context for a valid
    positive limit.
    """
    if limit < 0 or len(text) <= limit:
        return text
    boundary = text.rfind(" ", 0, limit)
    if boundary > 0:
        return text[:boundary]
    return text[:limit]
