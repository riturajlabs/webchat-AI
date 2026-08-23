"""Deterministic conversational query rewriting for multi-turn retrieval.

Follow-up questions ("what about refunds?", "and for enterprises?") embed
poorly on their own: the vector carries no subject, so vector search returns
weak or unrelated hits and the confidence gate falls back even when the
knowledge base contains the answer.

This module detects context-dependent questions with lightweight lexical
signals and, when prior conversation history exists, prepends the most
recent user turn to form a standalone *search* query.  The rewrite affects
retrieval only - the model still receives the original question verbatim.
No LLM calls, no external dependencies.  Flag-gated via
``enable_conversational_query_rewrite`` (backend.core.config).

Detection is deliberately conservative: only explicit anaphora/continuation
markers trigger a rewrite, so self-contained questions ("how do I reset my
password?") are never modified.
"""

from __future__ import annotations

import re

# Question openers that refer back to the conversation instead of standing
# alone.  Matched against the stripped, lowercased question start.
_ANAPHORA_START_RE = re.compile(
    r"^(it|its|it's|this|that|these|those|they|them|their|theirs|"
    r"he|she|his|her|hers)\b",
    re.IGNORECASE,
)
_CONTINUATION_START_RE = re.compile(
    r"^(what\s+about|how\s+about|and\b|also\b|plus\b|any\b|other\b|"
    r"tell\s+me\s+more|more\s+(details|info|information)|go\s+on\b|"
    r"continue\b|elaborate\b|why\s+is\s+that|what\s+else\b|anything\s+else\b)",
    re.IGNORECASE,
)

_HISTORY_ROLE_USER = "user"

DEFAULT_REWRITE_CONTEXT_CHARS = 200


def needs_conversation_context(question: str) -> bool:
    """True when *question* cannot be understood without prior turns.

    Conservative lexical check: pronoun-led questions and continuation
    phrases ("what about ...", "also ...") are context-dependent; everything
    else is treated as standalone.
    """
    text = question.strip()
    if not text:
        return False
    return bool(_ANAPHORA_START_RE.match(text) or _CONTINUATION_START_RE.match(text))


def build_search_query(
    question: str,
    history: list[tuple[str, str]],
    *,
    max_context_chars: int = DEFAULT_REWRITE_CONTEXT_CHARS,
) -> str:
    """Combine the most recent user turn with *question* for retrieval.

    Parameters
    ----------
    question:
        The current (sanitized) user question.
    history:
        Conversation memory as ``(role, content)`` tuples, oldest first,
        EXCLUDING the current turn.
    max_context_chars:
        Cap on the contributed history fragment so a long previous turn
        cannot dominate the embedding.

    Returns
    -------
    str
        ``"<previous user turn> <question>"`` when a previous user turn
        exists, otherwise ``question`` unchanged.  The result never equals
        an empty string while ``question`` is non-empty.
    """
    text = question.strip()
    if not text:
        return text

    previous_user_turn = ""
    for role, content in reversed(history):
        if role == _HISTORY_ROLE_USER and content.strip():
            previous_user_turn = " ".join(content.split())
            break
    if not previous_user_turn:
        return text

    context = previous_user_turn[:max_context_chars]
    return f"{context} {text}"


__all__ = [
    "DEFAULT_REWRITE_CONTEXT_CHARS",
    "build_search_query",
    "needs_conversation_context",
]
