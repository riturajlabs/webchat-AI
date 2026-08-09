"""Versioned prompt catalog for the RAG pipeline (Phase 6, ADR-008).

Prompts are Git-tracked versioned templates; bumping a version is a config
change, not a code change. See `backend/prompts/rag.py` for the current
catalog and builder functions.
"""

from backend.prompts.rag import (
    RAG_PROMPT_VERSION,
    UNKNOWN_ANSWER_FALLBACK,
    ContextItem,
    build_user_prompt,
    get_system_prompt,
    render_context,
    render_history,
    sanitize_question,
)

__all__ = [
    "ContextItem",
    "RAG_PROMPT_VERSION",
    "UNKNOWN_ANSWER_FALLBACK",
    "build_user_prompt",
    "get_system_prompt",
    "render_context",
    "render_history",
    "sanitize_question",
]
