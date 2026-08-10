"""Low-cost spam heuristics for public widget questions (Phase 8, ADR-004).

Pure functions, no I/O: each heuristic is cheap and conservative to avoid false
positives on legitimate questions. The route runs these after Pydantic
normalization and before the question reaches `RagService`.
"""

import re
from urllib.parse import urlparse

# A URL is "bare" when it occupies the entire normalized question.
_URL_SCHEMES = {"http", "https"}

# Repeated non-word runs, e.g. "??????", "....", "!!!!!!!!".
_REPEATED_PUNCTUATION = re.compile(r"([!?.]){6,}")

# Runs of the same word char, e.g. "aaa", "zzz".
_REPEATED_CHARS = re.compile(r"(\w)\1{5,}")

# Max share of uppercase letters before a question counts as all-caps spam.
_ALL_CAPS_RATIO = 0.7

# A question must have some non-punctuation content to be meaningful.
_MIN_ALPHA_CHARS = 3


def reject_repeated_punctuation(text: str) -> bool:
    """True when the text contains long runs of identical punctuation."""
    return _REPEATED_PUNCTUATION.search(text) is not None


def reject_repeated_chars(text: str) -> bool:
    """True when the text contains runs of 6+ of the same character."""
    return _REPEATED_CHARS.search(text) is not None


def reject_all_caps(text: str) -> bool:
    """True when uppercase letters dominate the alphabetic content."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    uppercase = sum(1 for ch in letters if ch.isupper())
    return uppercase / len(letters) >= _ALL_CAPS_RATIO


def is_bare_url(text: str) -> bool:
    """True when the normalized text is exactly one http(s) URL."""
    candidate = text.strip()
    parsed = urlparse(candidate)
    return parsed.scheme in _URL_SCHEMES and parsed.netloc != "" and candidate == parsed.geturl()


def is_spam(question: str) -> bool:
    """Run every heuristic against a normalized question.

    `question` is expected to already be whitespace-normalized (schema-level),
    so blank and control-character inputs are handled upstream.
    """
    text = question.strip()
    if len([ch for ch in text if ch.isalpha()]) < _MIN_ALPHA_CHARS:
        return True
    if reject_repeated_punctuation(text):
        return True
    if reject_repeated_chars(text):
        return True
    if reject_all_caps(text):
        return True
    return is_bare_url(text)


__all__ = [
    "is_spam",
    "is_bare_url",
    "reject_all_caps",
    "reject_repeated_chars",
    "reject_repeated_punctuation",
]
