"""Tests for privacy utilities (backend.core.privacy)."""

import hashlib

from backend.core.privacy import content_hash, mask_email, safe_query_meta


class TestContentHash:
    def test_returns_16_char_hex_string(self) -> None:
        result = content_hash("hello world")
        assert len(result) == 16
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self) -> None:
        assert content_hash("test") == content_hash("test")

    def test_different_inputs_different_hashes(self) -> None:
        assert content_hash("foo") != content_hash("bar")

    def test_matches_full_sha256_prefix(self) -> None:
        text = "What is the pricing?"
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        assert content_hash(text) == expected

    def test_unicode_input(self) -> None:
        result = content_hash("héllo wörld 日本語")
        assert len(result) == 16

    def test_empty_string(self) -> None:
        result = content_hash("")
        assert len(result) == 16


class TestSafeQueryMeta:
    def test_contains_hash_and_length(self) -> None:
        meta = safe_query_meta("hello")
        assert "query_hash" in meta
        assert "query_length" in meta
        assert meta["query_length"] == 5

    def test_hash_matches_content_hash(self) -> None:
        text = "What plans do you offer?"
        meta = safe_query_meta(text)
        assert meta["query_hash"] == content_hash(text)

    def test_length_is_character_count(self) -> None:
        text = "日本語テスト"
        meta = safe_query_meta(text)
        assert meta["query_length"] == len(text)

    def test_no_raw_text_in_result(self) -> None:
        meta = safe_query_meta("sensitive question about PII")
        assert "sensitive" not in str(meta)
        assert "PII" not in str(meta)


class TestMaskEmail:
    def test_masks_local_part(self) -> None:
        result = mask_email("john.doe@example.com")
        assert result == "jo***@example.com"

    def test_does_not_expose_full_local_part(self) -> None:
        assert "john.doe" not in mask_email("john.doe@example.com")

    def test_keeps_domain(self) -> None:
        assert mask_email("a@acme.org").endswith("@acme.org")

    def test_short_local_part(self) -> None:
        result = mask_email("ab@acme.org")
        assert result == "ab***@acme.org"

    def test_no_at_sign_masked_fully(self) -> None:
        assert mask_email("not-an-email") == "***"

    def test_empty_string(self) -> None:
        assert mask_email("") == "***"
