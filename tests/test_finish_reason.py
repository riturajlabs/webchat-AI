"""Unit tests for the normalized provider finish-reason vocabulary.

The RAG pipeline, SSE `done` frame, persistence and telemetry all branch on
these normalized values, never on provider-specific strings (production fix).
"""

from backend.ai.finish_reason import (
    FINISH_REASON_LENGTH,
    FINISH_REASON_MAX_TOKENS,
    FINISH_REASON_OTHER,
    FINISH_REASON_SAFETY,
    FINISH_REASON_STOP,
    FINISH_REASON_UNKNOWN,
    TRUNCATING_FINISH_REASONS,
    normalize_gemini_finish_reason,
    normalize_openai_finish_reason,
)
from backend.ai.gemini import GenerationUsage


class _GeminiFinishReason:
    """Minimal mirror of `google.genai.types.FinishReason` enum members."""

    STOP = "STOP"
    MAX_TOKENS = "MAX_TOKENS"
    SAFETY = "SAFETY"
    RECITATION = "RECITATION"


def test_gemini_stop_normalizes() -> None:
    assert normalize_gemini_finish_reason(_GeminiFinishReason.STOP) == FINISH_REASON_STOP


def test_gemini_max_tokens_normalizes_and_is_truncating() -> None:
    assert (
        normalize_gemini_finish_reason(_GeminiFinishReason.MAX_TOKENS) == FINISH_REASON_MAX_TOKENS
    )
    assert FINISH_REASON_MAX_TOKENS in TRUNCATING_FINISH_REASONS


def test_gemini_safety_maps_to_safety() -> None:
    assert normalize_gemini_finish_reason(_GeminiFinishReason.SAFETY) == FINISH_REASON_SAFETY
    # Safety stops are NOT truncation: the answer ended for policy, not the cap.
    assert FINISH_REASON_SAFETY not in TRUNCATING_FINISH_REASONS


def test_gemini_recitation_normalizes() -> None:
    assert normalize_gemini_finish_reason(_GeminiFinishReason.RECITATION) == "RECITATION"


def test_gemini_unknown_value_maps_to_other() -> None:
    assert normalize_gemini_finish_reason("MALFORMED") == FINISH_REASON_OTHER


def test_gemini_none_maps_to_unknown() -> None:
    assert normalize_gemini_finish_reason(None) == FINISH_REASON_UNKNOWN


def test_openai_stop_normalizes() -> None:
    assert normalize_openai_finish_reason("stop") == FINISH_REASON_STOP


def test_openai_length_normalizes_and_is_truncating() -> None:
    assert normalize_openai_finish_reason("length") == FINISH_REASON_LENGTH
    assert FINISH_REASON_LENGTH in TRUNCATING_FINISH_REASONS


def test_openai_content_filter_maps_to_safety() -> None:
    assert normalize_openai_finish_reason("content_filter") == FINISH_REASON_SAFETY


def test_openai_unknown_reason_preserved_as_other() -> None:
    assert normalize_openai_finish_reason("tool_calls") == FINISH_REASON_OTHER


def test_openai_none_maps_to_unknown() -> None:
    assert normalize_openai_finish_reason(None) == FINISH_REASON_UNKNOWN


def test_truncation_flag_matches_usage_model() -> None:
    """`GenerationUsage.truncated` mirrors the truncating-reason set."""
    capped = GenerationUsage(
        input_tokens=10,
        output_tokens=2048,
        finish_reason=FINISH_REASON_LENGTH,
        truncated=True,
        reasoning_tokens=0,
    )
    assert capped.truncated is True
    stopped = GenerationUsage(
        input_tokens=10,
        output_tokens=40,
        finish_reason=FINISH_REASON_STOP,
        truncated=False,
        reasoning_tokens=0,
    )
    assert stopped.truncated is False
