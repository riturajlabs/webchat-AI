"""Spam-heuristic unit tests (Phase 8, ADR-004 §3.6)."""

from backend.services.widget.spam_filter import (
    is_bare_url,
    is_spam,
    reject_all_caps,
    reject_repeated_chars,
    reject_repeated_punctuation,
)


def test_legitimate_questions_pass() -> None:
    assert not is_spam("How do I reset my password?")
    assert not is_spam("What are the Pro plan features?")
    assert not is_spam("Do you support API integrations?")
    assert not is_spam("Can I cancel anytime?")
    assert not is_spam("Where can I find the mobile app?")


def test_blank_and_symbol_only_rejected() -> None:
    assert is_spam("")
    assert is_spam("!!!")
    assert is_spam("...")
    assert is_spam("??")
    assert is_spam("??? ?? ??")


def test_repeated_punctuation_rejected() -> None:
    assert reject_repeated_punctuation("buy now!!!!!!!")
    assert reject_repeated_punctuation("What??????")
    assert is_spam("free money!!!!!!!")
    assert not reject_repeated_punctuation("How are you doing?")


def test_repeated_character_runs_rejected() -> None:
    assert reject_repeated_chars("aaaaaazzzzzz")
    assert is_spam("wwwwwwwwww")
    assert not reject_repeated_chars("hello world")


def test_all_caps_rejected() -> None:
    assert reject_all_caps("BUY NOW CLICK HERE")
    assert is_spam("WIN FREE PRIZE")
    assert not reject_all_caps("What is your return policy?")
    # Mixed-case but mostly uppercase is still spammy.
    assert reject_all_caps("DEAL Of The DAY!")


def test_bare_url_rejected() -> None:
    assert is_bare_url("https://example.com")
    assert is_bare_url("http://example.com/path")
    assert is_spam("https://spam.example.com/click")
    # A question containing a URL alongside prose is allowed.
    assert not is_bare_url("See https://example.com for details")
