"""Pre-generation RAG confidence and answerability scoring.

Two complementary, deterministic signals are computed from the *existing*
retrieval results before the LLM is called:

* ``assess_result_confidence`` — the relevance-confidence formula
  (``0.50*mean + 0.30*hit_ratio + 0.20*peak``).  This is kept unchanged and
  measures how semantically similar the retrieved evidence is.
* ``assess_answerability`` — an evidence-aware decision about whether the
  evidence *actually addresses the question's requested entity/fact*, not
  just whether it is generically similar.

The answerability decision classes the query into a *closed* (specific
entity/fact) or *open* (broad informational) question and inspects the
strength of the entity/lexical evidence.  A high-cosine result set that
lacks the requested entity cannot authorise generation for a factual
question, while strong entity evidence can authorise generation even when
the cosine is below the calibrated floor.

No LLM calls, no external dependencies — pure arithmetic on existing
retrieval results and query tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from backend.repositories.vector.base import VectorSearchResult
from backend.repositories.vector.hybrid import tokenize


@dataclass(frozen=True)
class ConfidenceMetrics:
    """Inspectable confidence signals for one retrieval decision."""

    confidence: float
    minimum_score: float
    average_score: float
    rejected_chunks_count: int


class QueryType(StrEnum):
    """Deterministic, site-agnostic question-intent classification."""

    CLOSED = "closed"  # specific entity/fact: "who is the dean", "what is the phone number"
    OPEN = "open"  # broad informational: "which courses are available", "tell me about X"
    UNKNOWN = "unknown"


class EvidenceStrength(StrEnum):
    """Strength of the entity/lexical evidence found in the retrieved results."""

    NONE = "none"  # no query content token present
    PARTIAL = "partial"  # some (ambiguous) tokens present
    STRONG = "strong"  # the query's distinguishing/entity terms are present


class AnswerabilityDecision(StrEnum):
    """Final answerability outcome for the generation gate."""

    GENERATE = "generate"
    FALLBACK = "fallback"


@dataclass(frozen=True)
class AnswerabilityMetrics:
    """Evidence-aware answerability decision for one retrieval result set.

    ``confidence`` holds the unchanged base confidence (for telemetry).
    ``answerability`` is a 0..1 quality measure; ``allowed`` is the strict
    boolean decision the generation gate consumes.  ``reason`` and
    ``category`` explain why the query was allowed or fell back.
    """

    allowed: bool
    answerability: float
    lexical_coverage: float
    confidence: float
    query_type: QueryType
    evidence_strength: EvidenceStrength
    reason: str
    category: str


# ── Deterministic query-type classification ────────────────────────────────

# Pure function / interrogative words that never constitue *evidence* of the
# requested entity/fact.  These are structural and universally ambiguous, so a
# match on them alone is never treated as meaningful evidence (the requirement
# example: high-cosine generic campus chunks must not authorize a phone-number
# query).  Cross-domain / university-agnostic.
_STRUCTURAL_WORDS = {
    "what",
    "which",
    "who",
    "whom",
    "whose",
    "when",
    "where",
    "how",
    "why",
    "is",
    "are",
    "was",
    "were",
    "am",
    "be",
    "being",
    "been",
    "do",
    "does",
    "did",
    "can",
    "could",
    "would",
    "should",
    "may",
    "might",
    "the",
    "a",
    "an",
    "of",
    "for",
    "to",
    "in",
    "on",
    "at",
    "with",
    "and",
    "or",
    "by",
    "from",
    "about",
    "please",
    "tell",
    "me",
    "my",
    "your",
    # Broad generic descriptors that do not name a specific fact/entity.
    "available",
    "availability",
    "list",
    "details",
    "detail",
    "information",
    "info",
    "process",
    "processes",
    "procedure",
    "procedures",
    "steps",
    "step",
    "course",
    "courses",
    "program",
    "programs",
    "programme",
    "programmes",
    "year",
    "years",
    "overview",
}

# Generic factual/entity *attribute* targets that make a query CLOSED.  These
# are the specific facts a user asks about (a role holder, a contact point, an
# admission/fee fact, …) and are the evidence requirement of a factual query.
# Cross-domain / university-agnostic — no hardcoded institution entities.
_FACTUAL_ATTRIBUTE_TERMS = {
    "dean",
    "chairperson",
    "chancellor",
    "vice_chancellor",
    "registrar",
    "director",
    "principal",
    "head",
    "faculty",
    "professor",
    "coordinator",
    "phone",
    "number",
    "contact",
    "email",
    "telephone",
    "phone_number",
    "admission",
    "admissions",
    "eligibility",
    "eligibilty",
    "fee",
    "fees",
    "placement",
    "placements",
    "application",
    "deadline",
    "scholarship",
    "scholarships",
    "tuition",
    "timing",
    "timings",
    "hours",
    "location",
    "address",
    "website",
    "url",
    "office",
    "department",
    "departments",
    "graduation",
}


def classify_query(query: str) -> QueryType:
    """Deterministically classify a query's intent (site-agnostic).

    * ``CLOSED`` — a specific entity/fact question: the user names an
      attribute target (role holder, contact point, admission/fee fact) or a
      specific entity subject, so the evidence must demonstrably contain that
      subject.  E.g. "who is the dean of SOIT", "what is the phone number",
      "what is the admission process", "cyber security admission".
    * ``OPEN`` — a broad informational question with no single-entity target,
      e.g. "which courses are available".  Semantic evidence remains valid.
    * ``UNKNOWN`` — cannot be classified (empty / no tokens).
    """
    tokens = tokenize(query)
    if not tokens:
        return QueryType.UNKNOWN

    has_wh = any(t in {"what", "which", "who", "whom", "whose", "when", "where"} for t in tokens)
    has_attribute = any(t in _FACTUAL_ATTRIBUTE_TERMS for t in tokens)
    has_specific_subject = any(t not in _STRUCTURAL_WORDS for t in tokens)

    # A factual attribute is named as the target -> specific fact question.
    if has_attribute:
        return QueryType.CLOSED

    # A wh-question that names a specific (non-structural) entity subject,
    # e.g. "what is SOIT", "which BCA program" -> entity/fact question.
    if has_wh and has_specific_subject:
        return QueryType.CLOSED

    # Otherwise it is a broad / unclassifiable informational query (or an
    # open-ended command like "tell me about X").
    return QueryType.OPEN


def _required_evidence_tokens(query: str) -> list[str]:
    """Return the content tokens that must be evidenced to answer a query.

    Only tokens that carry real content (not pure structure/function words)
    are required.  These include both the specific entity terms ("soit",
    "cyber") and the factual attribute targets ("admission", "phone",
    "number").  A match on nothing but structural words is never evidence.
    """
    return [t for t in tokenize(query) if t not in _STRUCTURAL_WORDS]


def _evidence_strength(
    query: str, results: list[VectorSearchResult]
) -> tuple[EvidenceStrength, float]:
    """Assess the strength of entity/lexical evidence across results.

    Returns ``(strength, lexical_coverage)`` where coverage is the fraction
    of the query's *required evidence tokens* found in the retrieved evidence.
    Only token presence in the retrieved chunk text counts; a match on
    structural/function words alone is ignored.  A partial / ambiguous
    coincidence (e.g. only "security" of "cyber security admission") maps to
    ``PARTIAL`` and, for a factual query, never authorizes generation.
    """
    all_text_tokens: set[str] = set()
    for result in results:
        all_text_tokens.update(tokenize(result.chunk.chunk_text))

    required = _required_evidence_tokens(query)
    if not required:
        tokens = tokenize(query)
        if not tokens:
            return EvidenceStrength.NONE, 0.0
        matched = sum(1 for t in tokens if t in all_text_tokens)
        coverage = matched / len(tokens)
        return _strength_from_coverage(coverage), coverage

    matched = sum(1 for t in required if t in all_text_tokens)
    coverage = matched / len(required)
    return _strength_from_coverage(coverage), coverage


def _strength_from_coverage(coverage: float) -> EvidenceStrength:
    """Map lexical evidence coverage to a strength bucket.

    ``STRONG`` requires the large majority (>=0.7) of the required content
    tokens to be present, so a lone ambiguous term on a multi-token factual
    query remains ``PARTIAL`` and never authorizes generation.
    """
    if coverage >= 0.7:
        return EvidenceStrength.STRONG
    if coverage > 0.0:
        return EvidenceStrength.PARTIAL
    return EvidenceStrength.NONE


def _distinct_sources(results: list[VectorSearchResult]) -> int:
    """Count the distinct source documents in the retrieved result set.

    Used by the open/broad query path to avoid letting repeated generic chunks
    from a single source dominate the decision (the ``MAX-2`` source cap in
    ``_build_context`` remains the downstream guard; this is a decision-level
    check on evidence provenance, bounded O(len(results))).
    """
    sources: set[str] = set()
    for result in results:
        # Source is identified by the page URL, matching the MAX-2-per-source
        # diversity key used in _build_context (falls back to document/website
        # id when a result lacks URL metadata).
        source = result.chunk.metadata.get("source_url")
        if not source:
            source = result.chunk.document_id or str(result.chunk.website_id)
        sources.add(source)
    return len(sources)


def assess_answerability(
    query: str,
    results: list[VectorSearchResult],
    *,
    min_score: float = 0.0,
) -> AnswerabilityMetrics:
    """Deterministic, evidence-aware answerability decision.

    Distinguishes:
    A. Strong factual/entity evidence          -> GENERATE
    B. Answerable, low cosine, strong lexical  -> GENERATE
    C. Generic high-cosine, no query evidence  -> FALLBACK
    D. No meaningful evidence                  -> FALLBACK

    Decision rules (all deterministic, no external calls):
    * Empty results  -> FALLBACK.
    * Closed/factual query:
        - STRONG entity/lexical evidence (the query's required content terms
          are present) -> GENERATE, even below the cosine floor.
        - NONE or PARTIAL evidence -> FALLBACK, regardless of cosine.  A
          high-cosine generic chunk or a lone ambiguous token must not answer
          "what is the phone number" or "cyber security admission".
    * Open/broad query:
        - Semantic evidence is valid; GENERATE when the base confidence is
          adequate and there is at least some genuine lexical grounding, but
          never from pure structural/noise matches alone.
    """
    confidence_metrics = assess_result_confidence(results, min_score=min_score, query=query)
    confidence = confidence_metrics.confidence

    if not results:
        return AnswerabilityMetrics(
            allowed=False,
            answerability=0.0,
            lexical_coverage=0.0,
            confidence=confidence,
            query_type=QueryType.UNKNOWN,
            evidence_strength=EvidenceStrength.NONE,
            reason="no_evidence",
            category="D",
        )

    query_type = classify_query(query)
    strength, coverage = _evidence_strength(query, results)

    # ── Unclassifiable queries ────────────────────────────────────────────
    # Empty / tokenless queries carry no specific requirement and must never be
    # answered from merely-generic semantically-similar evidence.
    if query_type == QueryType.UNKNOWN:
        return AnswerabilityMetrics(
            allowed=False,
            answerability=0.0,
            lexical_coverage=coverage,
            confidence=confidence,
            query_type=query_type,
            evidence_strength=strength,
            reason="unclassifiable_query",
            category="C",
        )

    # ── Closed / factual queries ─────────────────────────────────────────
    if query_type == QueryType.CLOSED:
        if strength == EvidenceStrength.STRONG:
            return AnswerabilityMetrics(
                allowed=True,
                answerability=max(confidence, coverage),
                lexical_coverage=coverage,
                confidence=confidence,
                query_type=query_type,
                evidence_strength=strength,
                reason="strong_entity_evidence",
                category="A",
            )
        # Weak/ambiguous or absent entity evidence: must not generate even
        # with high cosine.
        return AnswerabilityMetrics(
            allowed=False,
            answerability=min(confidence, coverage),
            lexical_coverage=coverage,
            confidence=confidence,
            query_type=query_type,
            evidence_strength=strength,
            reason="missing_entity_evidence"
            if strength == EvidenceStrength.NONE
            else "ambiguous_entity_evidence",
            category="C" if strength == EvidenceStrength.NONE else "B",
        )

    # ── Open / broad queries ─────────────────────────────────────────────
    # Semantic evidence remains valid for broad queries (requirement 7): a
    # literal match of every query token is NOT required.  Generation requires
    # adequate base confidence AND either (a) some genuine lexical grounding,
    # (b) evidence drawn from multiple sources, or (c) a single strong
    # semantic hit.  A pile of repeated generic chunks from a single source
    # with no query grounding must not dominate the decision (the existing
    # MAX-2 source diversity remains unchanged).
    distinct_sources = _distinct_sources(results)
    if confidence >= 0.3 and (coverage > 0.0 or distinct_sources >= 2 or len(results) == 1):
        return AnswerabilityMetrics(
            allowed=True,
            answerability=max(confidence, coverage),
            lexical_coverage=coverage,
            confidence=confidence,
            query_type=query_type,
            evidence_strength=strength,
            reason="semantic_evidence",
            category="B",
        )
    return AnswerabilityMetrics(
        allowed=False,
        answerability=min(confidence, coverage),
        lexical_coverage=coverage,
        confidence=confidence,
        query_type=query_type,
        evidence_strength=strength,
        reason="insufficient_open_evidence",
        category="C",
    )


# A below-floor candidate may still be admitted by the short-query leniency
# when the query carries few independent content tokens and the chunk's own
# text covers an independent-content-token share of them. Larger queries (more
# content tokens than this) keep the strict dense-only floor: their evidence
# must clear the cosine threshold.
_SHORT_QUERY_MAX_REQUIRED_TOKENS = 3


def _required_overlap(required: list[str]) -> int:
    """Minimum distinct content-token overlap the short-query leniency demands.

    A lone shared token on a multi-term query is ambiguous, so a 2-token
    query requires both tokens while a 3-token query requires at least two
    independent terms (a generic single-topic chunk such as "BCA ..." cannot
    qualify on its own).
    """
    return 1 if len(required) <= 1 else 2


def usable(
    result: VectorSearchResult,
    *,
    dense_floor: float,
    query: str | None = None,
) -> bool:
    """Return whether a result has evidence safe for LLM context.

    ``score`` is intentionally not inspected: vector candidates and keyword-only
    RRF candidates use different scales. A dense score must clear the calibrated
    floor, or the reranker must confirm an exact lexical match that also carries
    keyword retrieval evidence.

    ``query`` enables the short-query leniency for the RAG fast path (which runs
    without a reranker in the narrow-accuracy environment): when a short query's
    content tokens independently appear in a below-floor chunk that the hybrid
    pass actually surfaced, the chunk is preserved on that lexical evidence
    instead of being dropped by a cosine threshold calibrated for full queries.
    The rule stays narrow — at most ``_SHORT_QUERY_MAX_REQUIRED_TOKENS`` content
    tokens, demanding an independent-token overlap — so an unrelated chunk
    cannot slip through on a single coincidental word.
    """
    if dense_floor <= 0:
        return True
    dense_score = getattr(result, "dense_score", None)
    # Backward compatibility for repository implementations that predate the
    # explicit provenance field: score is dense only when no lexical score is
    # attached. RRF-only results must never be treated as cosine values.
    lexical_score = getattr(result, "lexical_score", None)
    if dense_score is None and lexical_score is None:
        dense_score = result.score
    if dense_score is not None and dense_score >= dense_floor:
        return True
    if getattr(result, "lexical_exact", False) and lexical_score is not None:
        return True
    if query:
        required = _required_evidence_tokens(query)
        if required and len(required) <= _SHORT_QUERY_MAX_REQUIRED_TOKENS:
            chunk_tokens = set(tokenize(result.chunk.chunk_text))
            matched = sum(1 for t in required if t in chunk_tokens)
            if matched >= _required_overlap(required):
                return True
    return False


def assess_result_confidence(
    results: list[VectorSearchResult],
    *,
    min_score: float = 0.0,
    query: str | None = None,
) -> ConfidenceMetrics:
    """Assess confidence using dense scores and explicit lexical evidence only."""
    if not results:
        return ConfidenceMetrics(0.0, 0.0, 0.0, 0)

    dense_scores = [
        getattr(result, "dense_score", None)
        if getattr(result, "dense_score", None) is not None
        else result.score
        for result in results
        if getattr(result, "dense_score", None) is not None or result.lexical_score is None
    ]
    lexical_hits = sum(
        1 for result in results if result.lexical_exact and result.lexical_score is not None
    )
    if not dense_scores:
        confidence = 1.0 if lexical_hits else 0.0
        return ConfidenceMetrics(confidence, confidence, confidence, len(results) - lexical_hits)

    metrics = assess_confidence(cast(list[float], dense_scores), min_score=min_score)
    accepted = sum(1 for result in results if usable(result, dense_floor=min_score, query=query))
    return ConfidenceMetrics(
        confidence=round(metrics.confidence, 4),
        minimum_score=metrics.minimum_score,
        average_score=metrics.average_score,
        rejected_chunks_count=len(results) - accepted,
    )


def _normalize_scores(scores: list[float]) -> list[float]:
    """Clamp raw retrieval scores into the [0, 1] similarity scale.

    Different retrieval stages produce different scales: exact cosine scans
    yield [-1, 1], Atlas ``vectorSearchScore`` is normalized similarity, and
    hybrid/rerank blends can exceed 1.0 or dip below 0. Feeding those raw
    values into the weighted formula makes confidence incomparable across
    strategies (a BM25-style 2.4 would saturate it at 1.0; a dissimilar
    cosine of -0.6 would drag it artificially low). Clamping each input to
    [0, 1] keeps every signal on one scale. Scores already inside [0, 1]
    pass through unchanged, so existing calibrated behavior is preserved.
    """
    return [max(0.0, min(score, 1.0)) for score in scores]


def assess_confidence(
    scores: list[float],
    *,
    min_score: float = 0.0,
) -> ConfidenceMetrics:
    """Compute confidence and expose the signals used by the decision."""
    if not scores:
        return ConfidenceMetrics(0.0, 0.0, 0.0, 0)

    normalized = _normalize_scores(scores)
    peak = max(normalized)
    average = sum(normalized) / len(normalized)
    rejected = sum(1 for score in normalized if score < min_score) if min_score > 0 else 0
    hit_ratio = (len(normalized) - rejected) / len(normalized) if min_score > 0 else average
    confidence = 0.50 * average + 0.30 * hit_ratio + 0.20 * peak
    # Clamp to [0, 1]: defensive only after input normalization, kept so a
    # caller-supplied out-of-range min_score cannot push the ratio negative.
    confidence = max(0.0, min(confidence, 1.0))
    return ConfidenceMetrics(
        confidence=round(confidence, 4),
        minimum_score=round(min(normalized), 4),
        average_score=round(average, 4),
        rejected_chunks_count=rejected,
    )


def calculate_confidence(
    scores: list[float],
    *,
    min_score: float = 0.0,
) -> float:
    """Compute a 0.0–1.0 confidence score from retrieval results.

    Uses three signals derived entirely from existing rerank/vector scores:

    1. **Mean score** — average relevance of the top results.
    2. **Hit ratio** — fraction of results above ``min_score``.
    3. **Peak score** — highest individual score (top result quality).

    These are combined with fixed weights:

    ``confidence = 0.50 * mean + 0.30 * hit_ratio + 0.20 * peak``

    Parameters
    ----------
    scores:
        Relevance scores from the retrieval/rerank stage (descending order).
    min_score:
        The minimum relevance threshold used by ``_build_context``.  Results
        below this score are filtered out downstream, so a low hit ratio
        signals that few chunks are actually usable.

    Returns
    -------
    float
        A value between 0.0 (no confidence) and 1.0 (maximum confidence).
    """
    return assess_confidence(scores, min_score=min_score).confidence


__all__ = [
    "AnswerabilityDecision",
    "AnswerabilityMetrics",
    "ConfidenceMetrics",
    "EvidenceStrength",
    "QueryType",
    "assess_answerability",
    "assess_confidence",
    "assess_result_confidence",
    "calculate_confidence",
    "classify_query",
    "usable",
]
