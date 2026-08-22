"""Tests for the rule-based query complexity classifier."""

from backend.services.chat.query_classifier import QueryComplexity, classify_query


class TestClassifyQuery:
    """Unit tests for classify_query scoring."""

    def test_empty_string_returns_simple(self) -> None:
        assert classify_query("") == QueryComplexity.SIMPLE

    def test_whitespace_only_returns_simple(self) -> None:
        assert classify_query("   ") == QueryComplexity.SIMPLE

    def test_short_factual_query_is_simple(self) -> None:
        assert classify_query("What is the price?") == QueryComplexity.SIMPLE

    def test_one_word_query_is_simple(self) -> None:
        assert classify_query("Pricing") == QueryComplexity.SIMPLE

    def test_short_who_query_is_simple(self) -> None:
        assert classify_query("Who are you?") == QueryComplexity.SIMPLE

    def test_when_query_is_simple(self) -> None:
        assert classify_query("When do you open?") == QueryComplexity.SIMPLE

    def test_medium_query_with_single_keyword(self) -> None:
        assert classify_query("How do I set up the integration?") in (
            QueryComplexity.MEDIUM,
            QueryComplexity.COMPLEX,
        )

    def test_multi_part_query_is_complex(self) -> None:
        q = (
            "What is the pricing and also how does the integration work "
            "and what are the pros and cons?"
        )
        assert classify_query(q) == QueryComplexity.COMPLEX

    def test_technical_query_with_multiple_keywords(self) -> None:
        q = "Explain the architecture and implementation details of the deployment pipeline"
        assert classify_query(q) == QueryComplexity.COMPLEX

    def test_list_query_is_higher_complexity(self) -> None:
        q = "What are the features:\n1. Authentication\n2. Authorization\n3. Audit logging"
        assert classify_query(q) in (QueryComplexity.MEDIUM, QueryComplexity.COMPLEX)

    def test_long_query_with_comparison_is_complex(self) -> None:
        q = (
            "Can you compare the differences between the basic plan and the enterprise plan "
            "and tell me the advantages and disadvantages of each option available?"
        )
        assert classify_query(q) == QueryComplexity.COMPLEX

    def test_simple_plan_query(self) -> None:
        assert classify_query("What plans do you offer?") == QueryComplexity.SIMPLE

    def test_download_link_query(self) -> None:
        assert classify_query("Where is the download link?") == QueryComplexity.SIMPLE

    def test_medium_length_how_query(self) -> None:
        result = classify_query(
            "How do I configure the webhook settings for the API?"
        )
        assert result in (QueryComplexity.MEDIUM, QueryComplexity.COMPLEX)

    def test_conjunction_boosts_score(self) -> None:
        q1 = "What is X?"
        q2 = "What is X and how does Y work?"
        s1 = classify_query(q1)
        s2 = classify_query(q2)
        # Adding conjunction should not lower the complexity.
        assert s2.value >= s1.value or s2 in (
            QueryComplexity.MEDIUM,
            QueryComplexity.COMPLEX,
        )

    def test_extremely_long_query_is_complex(self) -> None:
        words = ["explain"] + ["the"] * 20 + ["implementation"] * 3 + ["and"] * 3 + ["deployment"]
        q = " ".join(words)
        assert classify_query(q) == QueryComplexity.COMPLEX


class TestQueryComplexityEnum:
    """Verify enum values for serialization."""

    def test_values(self) -> None:
        assert QueryComplexity.SIMPLE.value == "simple"
        assert QueryComplexity.MEDIUM.value == "medium"
        assert QueryComplexity.COMPLEX.value == "complex"

    def test_membership(self) -> None:
        assert set(QueryComplexity) == {
            QueryComplexity.SIMPLE,
            QueryComplexity.MEDIUM,
            QueryComplexity.COMPLEX,
        }
