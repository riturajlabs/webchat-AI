"""Tests for shared input sanitization utilities."""

from backend.utils.sanitization import safe_regex, sanitize_text


class TestSafeRegex:
    def test_escapes_special_characters(self) -> None:
        assert safe_regex("a.b*c+d") == r"a\.b\*c\+d"

    def test_escapes_mongodb_regex_operators(self) -> None:
        result = safe_regex(".*DROP")
        assert result == r"\.\*DROP"

    def test_passthrough_plain_text(self) -> None:
        assert safe_regex("hello") == "hello"

    def test_empty_string(self) -> None:
        assert safe_regex("") == ""

    def test_unicode_treated_as_literal(self) -> None:
        assert safe_regex("café") == "café"


class TestSanitizeText:
    def test_strips_control_characters(self) -> None:
        dirty = "hello\x00\x01\x02world"
        assert sanitize_text(dirty) == "helloworld"

    def test_collapses_whitespace(self) -> None:
        assert sanitize_text("hello   world  ") == "hello world"

    def test_strips_leading_trailing_whitespace(self) -> None:
        assert sanitize_text("  hello  ") == "hello"

    def test_caps_length(self) -> None:
        result = sanitize_text("a" * 10000, max_length=50)
        assert len(result) == 50

    def test_preserves_normal_text(self) -> None:
        assert sanitize_text("Hello, World!") == "Hello, World!"

    def test_empty_string(self) -> None:
        assert sanitize_text("") == ""

    def test_only_control_chars_returns_empty(self) -> None:
        assert sanitize_text("\x00\x01\x02") == ""

    def test_default_max_length(self) -> None:
        result = sanitize_text("a" * 10000)
        assert len(result) == 5000
