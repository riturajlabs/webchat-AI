"""AI/RAG security hardening utilities (Phase 14.6).

Layer 1 — Input hardening:
  ``detect_context_breakout`` detects structural escape attempts in user
  questions (e.g. closing ``</context>`` tags, injecting role markers).

  ``sanitize_history_turn`` wraps suspicious conversation-history content
  with sanitization markers so stored prompt-injections cannot re-enter
  the model unframed.

Layer 2 — Enhanced injection detection:
  ``detect_encoded_injection`` catches simple encoding tricks (base64
  payloads, unicode homoglyphs for common keywords).

Layer 3 — Abuse tracking:
  ``InjectionTracker`` counts repeated HIGH-severity attempts per visitor
  and signals when escalation (temporary block) is warranted.

All functions are pure except ``InjectionTracker`` which is stateful.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict

from backend.core.prompt_guard import InjectionVerdict, detect_injection

logger = logging.getLogger("webchat_ai")


# ---------------------------------------------------------------------------
# Layer 1 — Context breakout detection
# ---------------------------------------------------------------------------

# Structural markers that a user question should never contain if it is
# a genuine support query.  Closing a ``<context>`` tag or injecting role
# prefixes can break out of the prompt structure.
_BREAKOUT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"</?\s*context\s*>", re.IGNORECASE),
        "context_tag_close",
    ),
    (
        re.compile(r"\[/?\s*SANITIZED\s*CONTENT", re.IGNORECASE),
        "sanitized_marker_injection",
    ),
    (
        re.compile(
            r"^(SYSTEM|ASSISTANT|USER|HUMAN|AI)\s*:",
            re.IGNORECASE | re.MULTILINE,
        ),
        "role_prefix_injection",
    ),
    (
        re.compile(
            r"\n(SYSTEM|ASSISTANT|USER|HUMAN)\s*:",
            re.IGNORECASE,
        ),
        "role_prefix_injection",
    ),
    (
        re.compile(
            r"<\|(im_start|im_end|system|user|assistant)\|>",
            re.IGNORECASE,
        ),
        "chatml_token_injection",
    ),
]


def detect_context_breakout(text: str) -> InjectionVerdict:
    """Detect structural escape attempts in a user question.

    Returns an ``InjectionVerdict`` if the question contains patterns
    that could break out of the prompt framing (context tags, role
    markers, chatml tokens).  HIGH severity triggers downstream caution.
    """
    matched: list[tuple[str, str]] = []
    for pattern, label in _BREAKOUT_PATTERNS:
        if pattern.search(text):
            matched.append(("high", label))
    if not matched:
        return InjectionVerdict(detected=False, severity="none")
    unique_labels = list(dict.fromkeys(label for _, label in matched))
    return InjectionVerdict(detected=True, severity="high", patterns=unique_labels)


# ---------------------------------------------------------------------------
# Layer 2 — Simple encoding detection
# ---------------------------------------------------------------------------

# Detect questions that are primarily a base64-encoded payload — a common
# technique to bypass text-based injection filters.
_BASE64_BLOCK = re.compile(
    r"[A-Za-z0-9+/]{40,}={0,2}",
)


def detect_encoded_injection(text: str) -> InjectionVerdict:
    """Detect simple encoding tricks used to bypass text filters.

    Catches questions that are predominantly base64-encoded blocks or
    that use unicode homoglyphs for common injection keywords.  Returns
    a verdict — callers decide whether to flag or block.
    """
    matched: list[str] = []

    # Base64 payload: if a single base64-looking block exceeds 40 chars
    # and the question is mostly that block, flag it.
    stripped = text.strip()
    b64_match = _BASE64_BLOCK.search(stripped)
    if b64_match and len(b64_match.group()) > 80:
        # Check if the block dominates the question (>60% of chars)
        if len(b64_match.group()) / max(len(stripped), 1) > 0.6:
            matched.append("base64_payload")

    # Unicode homoglyph check: common Cyrillic substitutions for "ignore"
    _HOMOGLYPH_PATTERNS = [
        "іgnore",  # Cyrillic і
        "іgnore",  # another variant
        "gпеss",  # Cyrillic р
    ]
    lowered = text.lower()
    for homoglyph in _HOMOGLYPH_PATTERNS:
        if homoglyph in lowered:
            matched.append("unicode_homoglyph")
            break

    if not matched:
        return InjectionVerdict(detected=False, severity="none")
    return InjectionVerdict(detected=True, severity="medium", patterns=matched)


# ---------------------------------------------------------------------------
# Layer 1 (enhanced) — Combined input scan
# ---------------------------------------------------------------------------


def scan_user_input(text: str) -> InjectionVerdict:
    """Run all input-layer security checks and return the highest severity.

    Combines the existing ``detect_injection`` with the new
    ``detect_context_breakout`` and ``detect_encoded_injection`` checks.
    The caller uses the returned verdict to decide whether to add caution
    markers or take other defensive action.
    """
    verdicts = [
        detect_injection(text),
        detect_context_breakout(text),
        detect_encoded_injection(text),
    ]

    severity_order = {"none": 0, "low": 1, "medium": 2, "high": 3}
    best = max(verdicts, key=lambda v: severity_order[v.severity])

    if best.detected:
        all_patterns: list[str] = []
        for v in verdicts:
            all_patterns.extend(v.patterns)
        return InjectionVerdict(
            detected=True,
            severity=best.severity,
            patterns=list(dict.fromkeys(all_patterns)),
        )
    return best


# ---------------------------------------------------------------------------
# History sanitization
# ---------------------------------------------------------------------------

_HISTORY_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"\b(ignore|disregard|forget|override)\b.{0,40}"
        r"\b(all |the |any |previous |above )?"
        r"(instructions?|rules?|prompts?|guidelines?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(you are now|from now on|new instructions?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(pretend|imagine|assume)\b.{0,20}\b(you are|to be|that)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(act as|roleplay as|simulate being)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(reveal|show|print|output)\b.{0,30}"
        r"\b(your |the )?(system prompt|instructions?|rules?)\b",
        re.IGNORECASE,
    ),
]

_HISTORY_SANITIZE_OPEN = "[SANITIZED HISTORY CONTENT]"
_HISTORY_SANITIZE_CLOSE = "[/SANITIZED HISTORY CONTENT]"


def sanitize_history_turn(role: str, content: str) -> str:
    """Wrap suspicious conversation-history content with safety markers.

    Conversation history is re-injected into the prompt on every turn.
    If a prior user message contains injection-like patterns, wrapping it
    with explicit sanitization markers reduces the risk of stored prompt
    injection attacks.
    """
    has_injection = any(p.search(content) for p in _HISTORY_INJECTION_PATTERNS)
    if not has_injection:
        return f"[{role}] {content}"
    logger.info(
        "prompt_security history_sanitize role=%s content_hash=%s",
        role,
        len(content),
    )
    return f"[{role}] {_HISTORY_SANITIZE_OPEN}\n{content}\n{_HISTORY_SANITIZE_CLOSE}"


# ---------------------------------------------------------------------------
# Abuse tracking
# ---------------------------------------------------------------------------


class InjectionTracker:
    """Track repeated injection attempts per visitor for escalation.

    When a single visitor triggers multiple HIGH-severity detections
    within the tracking window, the caller can escalate to a temporary
    block or increased rate-limiting.
    """

    def __init__(
        self,
        *,
        high_severity_threshold: int = 5,
        window_seconds: float = 300.0,
    ) -> None:
        self._threshold = high_severity_threshold
        self._window = window_seconds
        # visitor_id -> list of timestamps
        self._attempts: dict[str, list[float]] = defaultdict(list)

    def record(self, visitor_id: str, severity: str, *, now: float | None = None) -> None:
        """Record an injection attempt for *visitor_id*."""
        if severity != "high":
            return
        ts = now if now is not None else __import__("time").monotonic()
        self._attempts[visitor_id].append(ts)
        # Prune old entries outside the window
        cutoff = ts - self._window
        self._attempts[visitor_id] = [
            t for t in self._attempts[visitor_id] if t > cutoff
        ]

    def is_escalated(self, visitor_id: str, *, now: float | None = None) -> bool:
        """Return True if the visitor has exceeded the escalation threshold."""
        ts = now if now is not None else __import__("time").monotonic()
        cutoff = ts - self._window
        recent = [t for t in self._attempts.get(visitor_id, []) if t > cutoff]
        return len(recent) >= self._threshold

    def reset(self, visitor_id: str) -> None:
        """Clear tracking for a visitor (e.g. after a cooldown expires)."""
        self._attempts.pop(visitor_id, None)


__all__ = [
    "InjectionTracker",
    "detect_context_breakout",
    "detect_encoded_injection",
    "sanitize_history_turn",
    "scan_user_input",
]
