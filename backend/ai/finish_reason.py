"""Provider termination reasons, normalized across the AI abstraction layer.

Providers report *why* a generation stopped in their own vocabulary (Gemini's
`FinishReason` enum vs. OpenAI-compatible `choices[].finish_reason` strings).
Downstream — the RAG pipeline, SSE `done` frame, persistence and telemetry —
must not branch on provider-specific strings, so each provider maps its raw
value onto the shared vocabulary defined here.

Normalized values (production-fix scope):
    STOP        - generation ended naturally; the answer is complete.
    MAX_TOKENS  - Gemini stopped because the configured output cap was hit.
    LENGTH      - OpenAI-compatible providers stopped because the output cap
                  (`max_tokens`) was hit ("length"). Same class as MAX_TOKENS.
    SAFETY      - stopped by a content-safety filter (Gemini SAFETY,
                  OpenAI "content_filter").
    RECITATION  - Gemini stopped to avoid reciting copyrighted material.
    OTHER       - a recognized-but-unmapped provider reason.
    ERROR       - the stream failed and no terminal reason was produced.
    UNKNOWN     - no termination reason was observed.

A generation is *truncated* (not complete) when it ended on a token-limit
reason: the provider would have kept writing but was capped.
"""

from typing import Any

FINISH_REASON_STOP = "STOP"
FINISH_REASON_MAX_TOKENS = "MAX_TOKENS"
FINISH_REASON_LENGTH = "LENGTH"
FINISH_REASON_SAFETY = "SAFETY"
FINISH_REASON_RECITATION = "RECITATION"
FINISH_REASON_OTHER = "OTHER"
FINISH_REASON_ERROR = "ERROR"
FINISH_REASON_UNKNOWN = "UNKNOWN"

# Reasons that mean "the model wanted to keep writing but hit the output cap".
TRUNCATING_FINISH_REASONS = frozenset({FINISH_REASON_MAX_TOKENS, FINISH_REASON_LENGTH})


def normalize_gemini_finish_reason(value: Any) -> str:
    """Map a Gemini ``FinishReason`` (enum or value) onto the normalized set.

    ``value`` arrives as a ``google.genai.types.FinishReason`` member or its
    string value. ``None`` (mid-stream chunks) maps to ``UNKNOWN`` — the final
    chunk carries the real reason, so callers must keep the last non-``None``
    value.
    """
    if value is None:
        return FINISH_REASON_UNKNOWN
    raw = str(value).upper().split(".")[-1]
    mapping = {
        "STOP": FINISH_REASON_STOP,
        "MAX_TOKENS": FINISH_REASON_MAX_TOKENS,
        "SAFETY": FINISH_REASON_SAFETY,
        "RECITATION": FINISH_REASON_RECITATION,
    }
    return mapping.get(raw, FINISH_REASON_OTHER)


def normalize_openai_finish_reason(value: Any) -> str:
    """Map an OpenAI-compatible ``choices[].finish_reason`` onto the set.

    Known strings: ``stop``, ``length``, ``content_filter``. Anything else
    (including the schema-extended ``tool_calls``) is preserved as ``OTHER``,
    never silently dropped; ``None``/missing is ``UNKNOWN``.
    """
    if value is None:
        return FINISH_REASON_UNKNOWN
    raw = str(value).strip().lower()
    mapping = {
        "stop": FINISH_REASON_STOP,
        "length": FINISH_REASON_LENGTH,
        "content_filter": FINISH_REASON_SAFETY,
    }
    return mapping.get(raw, FINISH_REASON_OTHER)


__all__ = [
    "FINISH_REASON_ERROR",
    "FINISH_REASON_LENGTH",
    "FINISH_REASON_MAX_TOKENS",
    "FINISH_REASON_OTHER",
    "FINISH_REASON_RECITATION",
    "FINISH_REASON_SAFETY",
    "FINISH_REASON_STOP",
    "FINISH_REASON_UNKNOWN",
    "TRUNCATING_FINISH_REASONS",
    "normalize_gemini_finish_reason",
    "normalize_openai_finish_reason",
]
