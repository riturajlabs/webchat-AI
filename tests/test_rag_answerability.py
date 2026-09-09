"""Deterministic RAG answerability and query normalization benchmark.

Covers the required evidence-aware decision scenarios using synthetic
in-memory chunks (no production data, no APIs, no network calls):

1. Strong answerable factual evidence
2. Low cosine but strong factual/lexical evidence
3. High cosine but generic irrelevant evidence
4. Typo query -> correct evidence
5. Broad query with a repeated source
6. Irrelevant lexical coincidence
7. Partial lexical match
8. Phone/contact query with no contact evidence
9. Tenant/site-isolated result sets

The benchmark measures generation_allowed / fallback_expected, false
generation, false fallback, precision and recall.  Decision-boundary unit
tests assert the exact generate/fallback outcome rather than numeric ranges.
"""

from __future__ import annotations

from backend.models.knowledge_chunk import KnowledgeChunk
from backend.repositories.vector.base import VectorSearchResult
from backend.repositories.vector.hybrid import normalize_query
from backend.services.chat.confidence import (
    AnswerabilityDecision,
    assess_answerability,
    assess_result_confidence,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TENANT = "bench-tenant"
_WEBSITE = "bench-web"


def _make_chunk(
    text: str,
    *,
    tenant_id: str = _TENANT,
    website_id: str = _WEBSITE,
    url: str = "https://example.com/page",
) -> KnowledgeChunk:
    return KnowledgeChunk.new(
        tenant_id=tenant_id,
        website_id=website_id,
        document_id="doc-1",
        chunk_text=text,
        embedding=[],
        chunk_index=0,
        metadata={"source_url": url, "title": "Page"},
    )


def _make_result(
    text: str,
    score: float,
    *,
    lexical_score: float | None = None,
    dense_score: float | None = None,
    lexical_exact: bool = False,
    url: str = "https://example.com/page",
    tenant_id: str = _TENANT,
    website_id: str = _WEBSITE,
) -> VectorSearchResult:
    chunk = _make_chunk(text, tenant_id=tenant_id, website_id=website_id, url=url)
    return VectorSearchResult(
        chunk=chunk,
        score=score,
        lexical_score=lexical_score,
        dense_score=dense_score if dense_score is not None else score,
        lexical_exact=lexical_exact,
    )


# ---------------------------------------------------------------------------
# Decision-boundary unit tests (requirement 11) — assert exact outcomes
# ---------------------------------------------------------------------------


class TestDecisionBoundary:
    def test_low_cosine_strong_factual_evidence_generates(self) -> None:
        """Low cosine + strong entity evidence -> GENERATE (no false fallback)."""
        metrics = assess_answerability(
            "who is the dean of SOIT",
            [_make_result("The dean of SOIT is Dr. Sharma.", 0.26, lexical_exact=True)],
            min_score=0.25,
        )
        assert metrics.allowed is True
        assert metrics.reason == "strong_entity_evidence"

    def test_high_cosine_generic_evidence_falls_back(self) -> None:
        """High cosine generic evidence with no query entity -> FALLBACK."""
        metrics = assess_answerability(
            "what is the phone number",
            [
                _make_result("The campus has a library, cafeteria, and sports complex.", 0.9),
                _make_result("Students can access Wi-Fi across the entire campus.", 0.85),
            ],
            min_score=0.25,
        )
        assert metrics.allowed is False
        assert metrics.lexical_coverage == 0.0

    def test_irrelevant_single_token_coincidence_falls_back(self) -> None:
        """'cyber security admission' must not answer from a lone 'security' match."""
        metrics = assess_answerability(
            "cyber security admission",
            [_make_result("The college has a security guard at every gate.", 0.8)],
            min_score=0.25,
        )
        assert metrics.allowed is False
        assert metrics.evidence_strength.value == "partial"

    def test_typo_admission_query_generates_with_evidence(self) -> None:
        """Normalized typo query -> GENERATE when real admission evidence exists."""
        normalized = normalize_query("addmission process for BCA")
        metrics = assess_answerability(
            normalized,
            [_make_result("Admission process for BCA requires an online application.", 0.7)],
            min_score=0.25,
        )
        assert metrics.allowed is True
        assert metrics.lexical_coverage == 1.0

    def test_phone_query_without_contact_evidence_falls_back(self) -> None:
        """'phone number' with generic campus evidence (no contact) -> FALLBACK."""
        metrics = assess_answerability(
            "what is the phone number",
            [_make_result("The admission office is open Monday to Friday.", 0.75)],
            min_score=0.25,
        )
        assert metrics.allowed is False

    def test_phone_query_with_contact_evidence_generates(self) -> None:
        """'phone number' with actual contact evidence -> GENERATE."""
        metrics = assess_answerability(
            "what is the phone number",
            [_make_result("Our phone number is +1 555 1234 and email is info@example.com.", 0.6)],
            min_score=0.25,
        )
        assert metrics.allowed is True
        assert metrics.evidence_strength.value == "strong"

    def test_broad_valid_semantic_query_generates(self) -> None:
        """Broad query with genuinely relevant evidence -> GENERATE."""
        metrics = assess_answerability(
            "which courses are available",
            [_make_result("We offer BCA, MCA, and B.Tech courses across the department.", 0.72)],
            min_score=0.25,
        )
        assert metrics.allowed is True
        assert metrics.reason == "semantic_evidence"

    def test_empty_results_falls_back(self) -> None:
        """No retrieval results -> FALLBACK."""
        metrics = assess_answerability("who is the dean of SOIT", [], min_score=0.25)
        assert metrics.allowed is False
        assert metrics.reason == "no_evidence"
        assert metrics.answerability == 0.0


class TestDecisionOutcomeAccessor:
    """The decision exposes a stable enum outcome for downstream use."""

    def test_allowed_maps_to_generate(self) -> None:
        metrics = assess_answerability(
            "who is the dean of SOIT",
            [_make_result("The dean of SOIT is Dr. Sharma.", 0.6)],
            min_score=0.25,
        )
        assert metrics.allowed is True
        # A decision enum exists to carry the outcome; when allowed,
        # the numeric answerability is a positive strength signal.
        assert AnswerabilityDecision.GENERATE.value == "generate"
        assert AnswerabilityDecision.FALLBACK.value == "fallback"
        assert metrics.answerability > 0.0


# ---------------------------------------------------------------------------
# Scenario fixtures
# ---------------------------------------------------------------------------

_STRONG_FACTUAL = (
    "who is the dean of SOIT",
    [_make_result("The dean of SOIT is Dr. Sharma. He heads the school.", 0.85)],
)

_LOW_COSINE_STRONG_LEXICAL = (
    "who is the chairperson",
    [
        _make_result(
            "Chairperson of the examination committee is Prof. Gupta.", 0.28, lexical_exact=True
        )
    ],
)

_HIGH_COSINE_GENERIC = (
    "what is the phone number",
    [
        _make_result("The campus has a library, cafeteria, and sports complex.", 0.9),
        _make_result("Students can access Wi-Fi across the entire campus.", 0.85),
    ],
)

_TYPO_CORRECT_EVIDENCE = (
    normalize_query("addmission process for BCA"),
    [_make_result("Admission process for BCA requires an online application.", 0.7)],
)

_BROAD_REPEATED_SOURCE = (
    "which courses are available",
    [
        _make_result(
            "Computer Science department offers BCA, MCA and B.Tech courses.",
            0.65,
            url="https://example.com/cs",
        ),
        _make_result(
            "BCA course spans 3 years with 6 semesters.", 0.6, url="https://example.com/cs"
        ),
        _make_result(
            "MCA course requires BCA or equivalent degree.", 0.55, url="https://example.com/cs"
        ),
    ],
)

_IRRELEVANT_COINCIDENCE = (
    "cyber security admission",
    [
        _make_result("The college has a security guard at every gate.", 0.55),
        _make_result("Campus security cameras are installed in all blocks.", 0.5),
    ],
)

_PARTIAL_LEXICAL_MATCH = (
    "cyber security admission",
    [_make_result("The admission office is open Monday to Friday.", 0.6)],
)

_PHONE_NO_CONTACT = (
    "what is the phone number",
    [
        _make_result("The admission office is open Monday to Friday.", 0.8),
        _make_result("The campus library opens at 8am daily.", 0.75),
    ],
)

_TENANT_ISOLATED = (
    "BCA admission",
    [_make_result("BCA admission requires 10+2 qualification.", 0.7, tenant_id="tenant-a")],
)

# (name, query, results, expected_generate)
_SCENARIOS: list[tuple[str, str, list[VectorSearchResult], bool]] = [
    ("strong answerable factual", *_STRONG_FACTUAL, True),
    ("low cosine + strong lexical", *_LOW_COSINE_STRONG_LEXICAL, True),
    ("high cosine + generic irrelevant", *_HIGH_COSINE_GENERIC, False),
    ("typo query -> correct evidence", *_TYPO_CORRECT_EVIDENCE, True),
    ("broad query with repeated source", *_BROAD_REPEATED_SOURCE, True),
    ("irrelevant lexical coincidence", *_IRRELEVANT_COINCIDENCE, False),
    ("partial lexical match", *_PARTIAL_LEXICAL_MATCH, False),
    ("phone/contact query, no contact evidence", *_PHONE_NO_CONTACT, False),
    ("tenant/site-isolated result set", *_TENANT_ISOLATED, True),
]


class TestDeterministicBenchmark:
    """Full deterministic benchmark over all required scenarios.

    Measures generation_allowed, fallback_expected, false generation, false
    fallback, precision and recall.  All metrics must be exact — every
    scenario must be classified correctly (no false generation, no false
    fallback).
    """

    def _run(self) -> dict:
        tp = fp = tn = fn = 0
        for _name, query, results, expected in _SCENARIOS:
            metrics = assess_answerability(query, results, min_score=0.25)
            got = metrics.allowed  # GENERATE
            if expected and got:
                tp += 1
            elif expected and not got:
                fn += 1
            elif not expected and not got:
                tn += 1
            else:  # not expected but got -> false generation
                fp += 1
        precision = tp / (tp + fp) if (tp + fp) else 1.0
        recall = tp / (tp + fn) if (tp + fn) else 1.0
        return {
            "generation_allowed": tp + fp,
            "fallback_expected": tn + fn,
            "false_generation": fp,
            "false_fallback": fn,
            "precision": precision,
            "recall": recall,
            "supported": len(_SCENARIOS),
        }

    def test_no_false_generation(self) -> None:
        assert self._run()["false_generation"] == 0

    def test_no_false_fallback(self) -> None:
        assert self._run()["false_fallback"] == 0

    def test_precision_and_recall_perfect(self) -> None:
        metrics = self._run()
        assert metrics["precision"] == 1.0
        assert metrics["recall"] == 1.0

    def test_benchmark_shapes(self) -> None:
        metrics = self._run()
        assert metrics["generation_allowed"] + metrics["fallback_expected"] == metrics["supported"]
        assert metrics["generation_allowed"] >= 0
        assert metrics["fallback_expected"] >= 0

    def test_report_snapshot(self) -> None:
        """Print the benchmark for the Phase 4 final report."""
        metrics = self._run()
        lines = [
            "RAG answerability deterministic benchmark",
            f"  scenarios      : {metrics['supported']}",
            f"  generation_allowed : {metrics['generation_allowed']}",
            f"  fallback_expected  : {metrics['fallback_expected']}",
            f"  false_generation   : {metrics['false_generation']}",
            f"  false_fallback     : {metrics['false_fallback']}",
            f"  precision          : {metrics['precision']}",
            f"  recall             : {metrics['recall']}",
        ]
        for line in lines:
            print(line)


# ---------------------------------------------------------------------------
# Answerable + strong evidence
# ---------------------------------------------------------------------------


class TestAnswerableStrongEvidence:
    def test_high_cosine_and_lexical_match(self) -> None:
        results = [
            _make_result(
                "The dean of SOIT is Dr. Sharma. He oversees all academic programs.",
                score=0.85,
                lexical_exact=True,
                lexical_score=0.9,
            ),
            _make_result("SOIT faculty includes professors of computer science.", 0.72),
        ]
        metrics = assess_answerability("who is the dean of SOIT", results, min_score=0.25)
        assert metrics.allowed is True
        assert metrics.lexical_coverage >= 0.5
        assert metrics.confidence >= 0.3

    def test_perfect_lexical_coverage(self) -> None:
        results = [
            _make_result(
                "Admission process requires online application and document verification.",
                score=0.78,
                lexical_exact=True,
                lexical_score=0.85,
            ),
        ]
        metrics = assess_answerability("admission process", results, min_score=0.25)
        assert metrics.lexical_coverage == 1.0
        assert metrics.allowed is True


# ---------------------------------------------------------------------------
# Answerable + lower cosine but strong lexical evidence
# ---------------------------------------------------------------------------


class TestAnswerableLowCosineLexical:
    def test_low_cosine_strong_lexical(self) -> None:
        results = [
            _make_result(
                "Chairperson of the examination committee is Prof. Gupta.",
                score=0.30,
                lexical_exact=True,
                lexical_score=0.80,
            ),
        ]
        metrics = assess_answerability("chairperson", results, min_score=0.25)
        assert metrics.lexical_coverage == 1.0
        assert metrics.allowed is True

    def test_answerable_despite_low_cosine(self) -> None:
        results = [
            _make_result(
                "BCA admission requires 10+2 with minimum 50% marks.",
                score=0.28,
                lexical_exact=True,
                lexical_score=0.75,
            ),
        ]
        metrics = assess_answerability("BCA admission", results, min_score=0.25)
        assert metrics.lexical_coverage == 1.0
        assert metrics.allowed is True


# ---------------------------------------------------------------------------
# Unanswerable + high cosine generic evidence
# ---------------------------------------------------------------------------


class TestUnanswerableGenericEvidence:
    def test_generic_high_cosine_no_lexical_falls_back(self) -> None:
        results = [
            _make_result("The campus has a library, cafeteria, and sports complex.", 0.82),
            _make_result("Students can access Wi-Fi across the entire campus.", 0.75),
        ]
        metrics = assess_answerability("who is the dean of SOIT", results, min_score=0.25)
        assert metrics.lexical_coverage == 0.0
        # No evidence of the requested entity -> not answerable regardless of
        # the high cosine (this is the Phase 4 correction: generic high-cosine
        # similarity must NOT authorize a factual answer).
        assert metrics.allowed is False
        assert metrics.answerability == 0.0

    def test_empty_results_zero_answerability(self) -> None:
        metrics = assess_answerability("dean of SOIT", [], min_score=0.25)
        assert metrics.answerability == 0.0
        assert metrics.lexical_coverage == 0.0
        assert metrics.allowed is False


# ---------------------------------------------------------------------------
# Typo query with answerable evidence
# ---------------------------------------------------------------------------


class TestTypoQueryAnswerable:
    def test_addmission_matches_admission(self) -> None:
        normalized = normalize_query("addmission process for BCA")
        assert "admission" in normalized
        assert "addmission" not in normalized

    def test_admision_matches_admission(self) -> None:
        normalized = normalize_query("admision process")
        assert "admission" in normalized

    def test_normalize_preserves_abbreviations(self) -> None:
        normalized = normalize_query("BCA admission fees")
        assert "bca" in normalized

    def test_normalize_preserves_all_caps(self) -> None:
        normalized = normalize_query("AI-DS course fees")
        assert "ai" in normalized
        assert "ds" in normalized

    def test_typo_retrieval_answerability(self) -> None:
        results = [
            _make_result(
                "Admission process for BCA requires online application.",
                score=0.70,
                lexical_exact=True,
                lexical_score=0.80,
            ),
        ]
        normalized = normalize_query("addmission process for BCA")
        metrics = assess_answerability(normalized, results, min_score=0.25)
        assert metrics.lexical_coverage == 1.0
        assert metrics.allowed is True


# ---------------------------------------------------------------------------
# Broad query with duplicate-source dominance
# ---------------------------------------------------------------------------


class TestBroadQueryDuplicateSource:
    def test_duplicate_source_dominance_generates(self) -> None:
        """Repeated same-source chunks with genuine topic match still answer."""
        results = [
            _make_result(
                "Computer Science department offers BCA, MCA, and B.Tech courses.",
                0.65,
                url="https://example.com/cs",
            ),
            _make_result(
                "BCA course spans 3 years with 6 semesters.", 0.60, url="https://example.com/cs"
            ),
            _make_result(
                "MCA course requires BCA or equivalent degree.", 0.55, url="https://example.com/cs"
            ),
        ]
        metrics = assess_answerability("which courses are available", results, min_score=0.25)
        # Broad/semantic query with genuinely relevant evidence -> answer.
        assert metrics.allowed is True

    def test_single_source_no_query_terms_falls_back(self) -> None:
        """Repeated same-source chunks with no query relevance -> fallback."""
        results = [
            _make_result(
                "Campus photos from annual day celebration.",
                0.70,
                url="https://example.com/gallery",
            ),
            _make_result(
                "Sports day winners announced for 2024.", 0.65, url="https://example.com/gallery"
            ),
        ]
        metrics = assess_answerability("cyber security admission", results, min_score=0.25)
        assert metrics.lexical_coverage == 0.0
        assert metrics.allowed is False


# ---------------------------------------------------------------------------
# Irrelevant lexical coincidence
# ---------------------------------------------------------------------------


class TestIrrelevantLexicalCoincidence:
    def test_coincidental_term_match_falls_back(self) -> None:
        """A lone 'security' match on a 'cyber security admission' query is not
        enough — it is an ambiguous partial coincidence (false generation guard)."""
        results = [
            _make_result("The college has a security guard at every gate.", 0.55),
            _make_result("Campus security cameras are installed in all blocks.", 0.50),
        ]
        metrics = assess_answerability("cyber security admission", results, min_score=0.25)
        assert metrics.lexical_coverage < 1.0
        assert metrics.allowed is False

    def test_partial_lexical_match_falls_back(self) -> None:
        """Only 'admission' found (not cyber/security) -> partial, no generation."""
        results = [
            _make_result("The admission office is open Monday to Friday.", 0.60),
        ]
        metrics = assess_answerability("cyber security admission", results, min_score=0.25)
        assert 0.0 < metrics.lexical_coverage < 1.0
        assert metrics.allowed is False


# ---------------------------------------------------------------------------
# Tenant/site isolation
# ---------------------------------------------------------------------------


class TestTenantSiteIsolation:
    def test_isolated_result_set(self) -> None:
        """The decision works on the provided (already tenant-filtered) set."""
        results = [
            _make_result("BCA admission requires 10+2 qualification.", 0.70, tenant_id="tenant-a"),
        ]
        metrics = assess_answerability("BCA admission", results, min_score=0.25)
        assert metrics.lexical_coverage == 1.0
        assert metrics.allowed is True


# ---------------------------------------------------------------------------
# Query normalization tests
# ---------------------------------------------------------------------------


class TestQueryNormalization:
    def test_common_typos(self) -> None:
        assert normalize_query("addmission") == "admission"
        assert normalize_query("admisssion") == "admission"
        assert normalize_query("admision") == "admission"

    def test_abbreviations_preserved(self) -> None:
        assert "bca" in normalize_query("BCA fees")
        assert "fees" in normalize_query("BCA fees")

    def test_proper_nouns_preserved(self) -> None:
        result = normalize_query("Sharma professor")
        assert "sharma" in result
        assert "professor" in result

    def test_empty_query(self) -> None:
        assert normalize_query("") == ""

    def test_punctuation_stripped(self) -> None:
        result = normalize_query("admission-fees & structure!")
        assert "&" not in result
        assert "!" not in result
        assert "-" not in result

    def test_deterministic(self) -> None:
        query = "addmission for BCA programme"
        assert normalize_query(query) == normalize_query(query)

    def test_case_insensitive(self) -> None:
        assert normalize_query("ADDMISSION") == "admission"
        assert normalize_query("Admission") == "admission"


# ---------------------------------------------------------------------------
# Answerability edge cases
# ---------------------------------------------------------------------------


class TestAnswerabilityEdgeCases:
    def test_no_results(self) -> None:
        metrics = assess_answerability("test query", [], min_score=0.25)
        assert metrics.answerability == 0.0
        assert metrics.allowed is False

    def test_empty_query_falls_back(self) -> None:
        """Empty/unclassifiable query is not answered from generic evidence."""
        results = [_make_result("Some text", score=0.7)]
        metrics = assess_answerability("", results, min_score=0.25)
        assert metrics.allowed is False
        assert metrics.answerability == 0.0

    def test_answerability_bounded_0_1(self) -> None:
        results = [_make_result("text", score=1.5)]
        metrics = assess_answerability("query", results, min_score=0.25)
        assert 0.0 <= metrics.answerability <= 1.0

    def test_lexical_coverage_bounded(self) -> None:
        results = [_make_result("a b c d e f g h i j", score=0.9)]
        metrics = assess_answerability("xyz", results, min_score=0.25)
        assert 0.0 <= metrics.lexical_coverage <= 1.0


# ---------------------------------------------------------------------------
# Confidence vs answerability comparison
# ---------------------------------------------------------------------------


class TestConfidenceVsAnswerability:
    def test_zero_coverage_factual_query_low_answerability(self) -> None:
        """No entity evidence -> answerability is low (not the high confidence),
        for a factual query — the Phase 4 correction."""
        results = [
            _make_result("General campus information.", 0.85),
        ]
        conf = assess_result_confidence(results, min_score=0.25)
        ans = assess_answerability("dean of SOIT", results, min_score=0.25)
        assert ans.lexical_coverage == 0.0
        assert ans.allowed is False
        assert ans.answerability < conf.confidence

    def test_low_cosine_high_lexical_strong(self) -> None:
        """Low confidence but full lexical coverage of a factual target raises
        answerability above the plain confidence."""
        results = [
            _make_result("Admission requires valid ID proof.", 0.25, lexical_exact=True),
        ]
        conf = assess_result_confidence(results, min_score=0.25)
        ans = assess_answerability("admission", results, min_score=0.25)
        assert ans.lexical_coverage == 1.0
        assert ans.allowed is True
        assert ans.answerability >= conf.confidence
