"""AI benchmark system (Phase 3 Steps 3-7).

Isolated benchmarking harness that measures real chat pipeline performance
and answer quality using representative queries against in-memory fakes.
Never modifies the production chat flow, prompts, retrieval, or generation
settings.
"""

from backend.benchmark.ab_evaluation import (
    ABReport,
    QueryABResult,
    compute_ab_report,
    format_ab_report,
    run_ab_evaluation,
)
from backend.benchmark.evaluation import QualityMetrics, SourceInfo, evaluate_quality
from backend.benchmark.golden import GoldenCase, GoldenDataset
from backend.benchmark.golden_eval import GoldenMetrics, evaluate_golden
from backend.benchmark.llm_evaluation import (
    AnswerQualityScore,
    LLMABReport,
    LLMJudge,
    LLMQueryResult,
    aggregate_scores,
    compute_llm_ab_report,
    format_llm_ab_report,
    parse_judge_response,
    run_llm_ab_evaluation,
)
from backend.benchmark.queries import QUERIES, BenchmarkQuery
from backend.benchmark.report import BenchmarkReport, SummaryStats, compute_summary
from backend.benchmark.retrieval_comparison import (
    RetrievalComparisonResult,
    RetrievalMethod,
    compare_retrieval_methods,
)
from backend.benchmark.retrieval_metrics import (
    PairwiseImprovement,
    RetrievalMetrics,
    compute_pairwise_improvement,
    compute_retrieval_metrics,
)
from backend.benchmark.runner import BenchmarkRequest, BenchmarkRunner

__all__ = [
    "ABReport",
    "AnswerQualityScore",
    "BenchmarkQuery",
    "BenchmarkReport",
    "BenchmarkRequest",
    "BenchmarkRunner",
    "GoldenCase",
    "GoldenDataset",
    "GoldenMetrics",
    "LLMABReport",
    "LLMJudge",
    "LLMQueryResult",
    "PairwiseImprovement",
    "QualityMetrics",
    "QueryABResult",
    "QUERIES",
    "RetrievalComparisonResult",
    "RetrievalMethod",
    "RetrievalMetrics",
    "SourceInfo",
    "SummaryStats",
    "aggregate_scores",
    "compare_retrieval_methods",
    "compute_ab_report",
    "compute_llm_ab_report",
    "compute_pairwise_improvement",
    "compute_retrieval_metrics",
    "compute_summary",
    "evaluate_golden",
    "evaluate_quality",
    "format_ab_report",
    "format_llm_ab_report",
    "parse_judge_response",
    "run_ab_evaluation",
    "run_llm_ab_evaluation",
]
