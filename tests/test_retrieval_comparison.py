"""Tests for retrieval comparison framework and retrieval metrics.

Covers comparison of vector-only, keyword-only, and hybrid retrieval methods,
precision@k, source accuracy, pairwise improvement, and aggregate metrics.
All pure functions — no I/O, no MongoDB.
"""

from backend.benchmark.retrieval_comparison import (
    RetrievalComparisonResult,
    RetrievalMethod,
    RetrievalMethodResult,
    compare_retrieval_methods,
)
from backend.benchmark.retrieval_metrics import (
    RetrievalMetrics,
    aggregate_retrieval_metrics,
    compute_pairwise_improvement,
    compute_retrieval_metrics,
)
from backend.repositories.vector.base import VectorSearchResult

from tests.chat_helpers import build_chat_env, make_chunk, make_website

TENANT = "bench-tenant"
WEBSITE = "bench-web"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_result(
    chunk_id: str,
    text: str,
    score: float = 0.5,
    source_url: str = "",
) -> VectorSearchResult:
    from backend.models.knowledge_chunk import KnowledgeChunk

    chunk = KnowledgeChunk.new(
        tenant_id=TENANT,
        website_id=WEBSITE,
        document_id="doc-1",
        chunk_text=text,
        embedding=[0.0],
        chunk_index=0,
        metadata={"source_url": source_url} if source_url else {},
    )
    object.__setattr__(chunk, "id", chunk_id)
    return VectorSearchResult(chunk=chunk, score=score)


# ---------------------------------------------------------------------------
# RetrievalMetrics
# ---------------------------------------------------------------------------


def test_retrieval_metrics_empty() -> None:
    m = compute_retrieval_metrics([], [])
    assert m.precision_at_k == 0.0
    assert m.source_accuracy == 0.0
    assert m.total_chunks_retrieved == 0
    assert m.unique_sources_retrieved == 0
    assert m.avg_score == 0.0


def test_retrieval_metrics_perfect_match() -> None:
    results = [
        _make_result("a", "pricing", 0.9, "https://example.com/pricing"),
        _make_result("b", "enterprise", 0.8, "https://example.com/enterprise"),
    ]
    m = compute_retrieval_metrics(results, ["/pricing", "/enterprise"])
    assert m.precision_at_k == 1.0
    assert m.source_accuracy == 1.0
    assert m.total_chunks_retrieved == 2
    assert m.unique_sources_retrieved == 2


def test_retrieval_metrics_partial_match() -> None:
    results = [
        _make_result("a", "pricing", 0.9, "https://example.com/pricing"),
        _make_result("b", "security", 0.8, "https://example.com/security"),
    ]
    m = compute_retrieval_metrics(results, ["/pricing", "/enterprise"])
    # precision: 1 of 2 chunks match /pricing -> 0.5
    # accuracy: 1 of 2 expected found -> 0.5
    assert m.precision_at_k == 0.5
    assert m.source_accuracy == 0.5


def test_retrieval_metrics_no_expected_sources() -> None:
    results = [_make_result("a", "pricing", 0.9, "https://example.com/pricing")]
    m = compute_retrieval_metrics(results, [])
    assert m.precision_at_k == 1.0
    assert m.source_accuracy == 1.0


def test_retrieval_metrics_top_k_limit() -> None:
    results = [
        _make_result("a", "pricing", 0.9, "https://example.com/pricing"),
        _make_result("b", "security", 0.8, "https://example.com/security"),
    ]
    m = compute_retrieval_metrics(results, ["/pricing"], top_k=1)
    assert m.total_chunks_retrieved == 1
    assert m.precision_at_k == 1.0


def test_retrieval_metrics_avg_score() -> None:
    results = [
        _make_result("a", "text", 0.8),
        _make_result("b", "text", 0.6),
    ]
    m = compute_retrieval_metrics(results, [])
    assert m.avg_score == 0.7


def test_retrieval_metrics_url_case_insensitive() -> None:
    results = [_make_result("a", "pricing", 0.9, "https://EXAMPLE.COM/Pricing")]
    m = compute_retrieval_metrics(results, ["/pricing"])
    assert m.source_accuracy == 1.0


# ---------------------------------------------------------------------------
# PairwiseImprovement
# ---------------------------------------------------------------------------


def test_pairwise_improvement_positive() -> None:
    baseline = RetrievalMetrics(precision_at_k=0.5, source_accuracy=0.5)
    treatment = RetrievalMetrics(precision_at_k=0.8, source_accuracy=0.7)
    p = compute_pairwise_improvement(
        baseline, treatment, metric_name="precision_at_k"
    )
    assert p.delta == 0.3
    assert p.relative_improvement_pct == 60.0
    assert p.baseline_method == "vector"
    assert p.treatment_method == "hybrid"


def test_pairwise_improvement_negative() -> None:
    baseline = RetrievalMetrics(precision_at_k=0.8)
    treatment = RetrievalMetrics(precision_at_k=0.5)
    p = compute_pairwise_improvement(baseline, treatment, metric_name="precision_at_k")
    assert p.delta == -0.3
    assert p.relative_improvement_pct < 0


def test_pairwise_improvement_zero_baseline() -> None:
    baseline = RetrievalMetrics(precision_at_k=0.0)
    treatment = RetrievalMetrics(precision_at_k=0.5)
    p = compute_pairwise_improvement(baseline, treatment, metric_name="precision_at_k")
    assert p.delta == 0.5
    assert p.relative_improvement_pct == 0.0


def test_pairwise_improvement_custom_labels() -> None:
    baseline = RetrievalMetrics(precision_at_k=0.5)
    treatment = RetrievalMetrics(precision_at_k=0.7)
    p = compute_pairwise_improvement(
        baseline,
        treatment,
        baseline_method="vector",
        treatment_method="keyword",
        metric_name="precision_at_k",
    )
    assert p.baseline_method == "vector"
    assert p.treatment_method == "keyword"


# ---------------------------------------------------------------------------
# Aggregate metrics
# ---------------------------------------------------------------------------


def test_aggregate_retrieval_metrics_empty() -> None:
    result = aggregate_retrieval_metrics([])
    assert result == {}


def test_aggregate_retrieval_metrics_multiple() -> None:
    metrics = [
        RetrievalMetrics(precision_at_k=0.8, source_accuracy=0.6, avg_score=0.7),
        RetrievalMetrics(precision_at_k=0.6, source_accuracy=0.8, avg_score=0.5),
        RetrievalMetrics(precision_at_k=1.0, source_accuracy=1.0, avg_score=0.9),
    ]
    result = aggregate_retrieval_metrics(metrics)
    assert "precision_at_k_mean" in result
    assert "precision_at_k_median" in result
    assert "source_accuracy_mean" in result
    assert "source_accuracy_median" in result
    assert "avg_score_mean" in result
    assert abs(result["precision_at_k_mean"] - 0.8) < 0.01


# ---------------------------------------------------------------------------
# RetrievalComparisonResult
# ---------------------------------------------------------------------------


def test_comparison_result_methods_enum() -> None:
    assert RetrievalMethod.VECTOR.value == "vector"
    assert RetrievalMethod.KEYWORD.value == "keyword"
    assert RetrievalMethod.HYBRID.value == "hybrid"


def test_comparison_result_frozen() -> None:
    vector = RetrievalMethodResult(
        method=RetrievalMethod.VECTOR, results=[], chunk_count=0
    )
    keyword = RetrievalMethodResult(
        method=RetrievalMethod.KEYWORD, results=[], chunk_count=0
    )
    hybrid = RetrievalMethodResult(
        method=RetrievalMethod.HYBRID, results=[], chunk_count=0
    )
    result = RetrievalComparisonResult(
        query="test", vector=vector, keyword=keyword, hybrid=hybrid
    )
    assert result.query == "test"


# ---------------------------------------------------------------------------
# compare_retrieval_methods
# ---------------------------------------------------------------------------


def test_compare_retrieval_methods_basic() -> None:
    vector_results = [
        _make_result("a", "pricing plan", 0.9, "https://example.com/pricing"),
        _make_result("b", "security page", 0.8, "https://example.com/security"),
    ]
    all_chunks = [
        _make_result("a", "pricing plan", 0.9, "https://example.com/pricing"),
        _make_result("b", "security page", 0.8, "https://example.com/security"),
        _make_result("c", "pricing details", 0.7, "https://example.com/pricing-details"),
    ]
    result = compare_retrieval_methods(
        "pricing plan", vector_results, all_chunks, top_k=3
    )
    assert result.query == "pricing plan"
    assert result.vector.method == RetrievalMethod.VECTOR
    assert result.keyword.method == RetrievalMethod.KEYWORD
    assert result.hybrid.method == RetrievalMethod.HYBRID


def test_compare_retrieval_methods_empty_vector() -> None:
    result = compare_retrieval_methods("test", [], [], top_k=3)
    assert result.vector.chunk_count == 0
    assert result.keyword.chunk_count == 0
    assert result.hybrid.chunk_count == 0


def test_compare_retrieval_methods_overlap() -> None:
    vector_results = [
        _make_result("a", "pricing plan", 0.9, "https://example.com/pricing"),
        _make_result("b", "security", 0.8, "https://example.com/security"),
    ]
    all_chunks = [
        _make_result("a", "pricing plan", 0.9, "https://example.com/pricing"),
        _make_result("b", "security", 0.8, "https://example.com/security"),
        _make_result("c", "pricing details", 0.7, "https://example.com/pricing-details"),
    ]
    result = compare_retrieval_methods(
        "pricing", vector_results, all_chunks, top_k=3
    )
    # Vector has /pricing and /security; keyword will match "pricing" in a and c
    assert result.overlap_vector_keyword >= 0


def test_compare_retrieval_methods_top_k() -> None:
    vector_results = [
        _make_result(f"c{i}", f"chunk {i}", 0.9 - i * 0.1)
        for i in range(10)
    ]
    result = compare_retrieval_methods("chunk", vector_results, vector_results, top_k=3)
    assert result.vector.chunk_count <= 3
    assert result.keyword.chunk_count <= 3
    assert result.hybrid.chunk_count <= 3


# ---------------------------------------------------------------------------
# Integration with seeded data
# ---------------------------------------------------------------------------


async def test_compare_methods_with_seeded_data() -> None:
    """End-to-end: seed chunks, run vector search, compare all three methods."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=3)
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Pro plan costs $19/mo with 10GB storage.",
        url="https://example.com/pricing",
        title="Pricing",
        chunk_index=0,
    )
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Enterprise plan includes SSO and audit logs.",
        url="https://example.com/enterprise",
        title="Enterprise",
        chunk_index=1,
    )
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Free trial gives 14 days of full access.",
        url="https://example.com/trial",
        title="Trial",
        chunk_index=2,
    )

    vector_results = await env.vector.similarity_search(
        TENANT, WEBSITE, [0.0, 0.0, 0.0, 0.0], top_k=3
    )
    all_chunks = [
        VectorSearchResult(chunk=chunk, score=0.5)
        for chunk in await env.vector.list_chunks(TENANT, WEBSITE)
    ]

    comparison = compare_retrieval_methods(
        "pricing plan", vector_results, all_chunks, top_k=3
    )
    assert comparison.vector.chunk_count > 0
    assert comparison.hybrid.chunk_count > 0
    assert comparison.overlap_vector_keyword >= 0


async def test_retrieval_metrics_with_seeded_data() -> None:
    """End-to-end: seed chunks, run vector search, compute retrieval metrics."""
    env = build_chat_env()
    await make_website(env, tenant_id=TENANT, website_id=WEBSITE, knowledge_chunks=2)
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Pricing plan details.",
        url="https://example.com/pricing",
        title="Pricing",
    )
    await make_chunk(
        env,
        tenant_id=TENANT,
        website_id=WEBSITE,
        text="Security information.",
        url="https://example.com/security",
        title="Security",
    )

    vector_results = await env.vector.similarity_search(
        TENANT, WEBSITE, [0.0, 0.0, 0.0, 0.0], top_k=2
    )

    m = compute_retrieval_metrics(vector_results, ["/pricing"])
    assert m.total_chunks_retrieved > 0
    assert m.avg_score > 0.0
