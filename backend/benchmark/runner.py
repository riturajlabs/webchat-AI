"""Benchmark runner: executes chat requests and collects latency + quality metrics.

The runner wires up in-memory fakes (via ``build_chat_env``) and runs each
``BenchmarkQuery`` through the ``RagService`` pipeline, capturing the per-stage
latency breakdown emitted in the SSE ``done`` event and evaluating answer
quality.  It never touches the network, modifies production prompts, or alters
generation settings.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from backend.benchmark.evaluation import QualityMetrics, SourceInfo, evaluate_quality
from backend.benchmark.golden import GoldenCase
from backend.benchmark.golden_eval import GoldenMetrics, evaluate_golden
from backend.benchmark.queries import BenchmarkQuery

TENANT_ID = "benchmark-tenant"
WEBSITE_ID = "benchmark-website"


@dataclass
class BenchmarkRequest:
    """Latency + quality metrics for a single benchmark request."""

    query_label: str
    total_ms: float = 0.0
    ttft_ms: float | None = None
    generation_ms: float | None = None
    embedding_ms: float | None = None
    retrieval_ms: float | None = None
    provider: str | None = None
    fallback_attempts: int = 0
    embedding_cache: str = "miss"
    retrieval_cache: str = "miss"
    estimated_prompt_tokens: int = 0
    fallback: bool = False
    error: str | None = None
    # --- quality fields ---
    quality: QualityMetrics = field(default_factory=QualityMetrics)
    golden_metrics: GoldenMetrics = field(default_factory=GoldenMetrics)


@dataclass
class BenchmarkRunner:
    """Orchestrates a benchmark run over a set of queries.

    Accepts a pre-built ``ChatEnv`` (from ``tests.chat_helpers.build_chat_env``)
    or creates one when *env* is ``None``.  The runner expects the environment
    to already have a website seeded with at least one knowledge chunk so the
    RAG pipeline exercises retrieval rather than always hitting the fallback
    path.
    """

    queries: list[BenchmarkQuery] = field(default_factory=list)
    rounds: int = 1
    tenant_id: str = TENANT_ID
    website_id: str = WEBSITE_ID
    golden_cases: list[GoldenCase] = field(default_factory=list)

    async def run(
        self,
        env: object | None = None,
    ) -> list[BenchmarkRequest]:
        """Execute the benchmark and return per-request metrics.

        When *env* is ``None`` a fresh ``ChatEnv`` is created with in-memory
        fakes.  The caller can pre-seed the environment (website, chunks) before
        passing it in.
        """
        if env is None:
            from tests.chat_helpers import build_chat_env

            env = build_chat_env()

        # Ensure timing is emitted in the done event.  ``_timing_enabled`` is
        # read at RagService construction time, so we patch the instance attr
        # directly — this never leaks into production.
        rag = env.rag  # type: ignore[attr-defined]
        rag._timing_enabled = True  # noqa: SLF001

        results: list[BenchmarkRequest] = []
        golden_map = {gc.short_label: gc for gc in self.golden_cases}
        for _round in range(self.rounds):
            for query in self.queries:
                golden_case = golden_map.get(query.short_label)
                result = await self._execute_one(env, query, golden_case)
                results.append(result)
        return results

    async def _execute_one(
        self,
        env: object,
        query: BenchmarkQuery,
        golden_case: GoldenCase | None = None,
    ) -> BenchmarkRequest:
        """Run a single query and extract timing + quality from SSE events."""
        from tests.chat_helpers import consume

        result = BenchmarkRequest(query_label=query.short_label)
        started = time.perf_counter()

        # Collect stream artefacts for quality evaluation.
        answer_parts: list[str] = []
        sources: list[SourceInfo] = []

        try:
            stream = env.rag.stream_answer(  # type: ignore[attr-defined]
                tenant_id=self.tenant_id,
                website_id=self.website_id,
                question=query.text,
            )
            events = await consume(stream)

            result.total_ms = (time.perf_counter() - started) * 1000.0

            for event in events:
                ev = event.get("event")
                if ev == "error":
                    result.error = event["data"].get("message", "unknown error")
                    break
                if ev == "sources":
                    for src in event["data"].get("sources", []):
                        sources.append(
                            SourceInfo(
                                url=src.get("url", ""),
                                title=src.get("title", ""),
                                score=src.get("score", 0.0),
                            )
                        )
                elif ev == "message":
                    answer_parts.append(event["data"].get("delta", ""))
                elif ev == "done":
                    data = event["data"]
                    result.fallback = data.get("fallback", False)
                    timing = data.get("timing")
                    if timing is not None:
                        result.ttft_ms = timing.get("ttft_ms")
                        result.generation_ms = timing.get("generation_ms")
                        result.embedding_ms = timing.get("embedding_ms")
                        result.retrieval_ms = timing.get("retrieval_ms")
                        result.provider = timing.get("provider")
                        result.fallback_attempts = timing.get("fallback_attempts", 0)
                        result.embedding_cache = timing.get("embedding_cache", "miss")
                        result.retrieval_cache = timing.get("retrieval_cache", "miss")
                        result.estimated_prompt_tokens = timing.get(
                            "estimated_prompt_tokens", 0
                        )
                    break
        except Exception as exc:
            result.total_ms = (time.perf_counter() - started) * 1000.0
            result.error = f"{type(exc).__name__}: {exc}"

        answer = "".join(answer_parts)
        result.quality = evaluate_quality(
            answer=answer,
            sources=sources,
            expected_fragment=query.expected_fragment,
            fallback=result.fallback,
        )

        if golden_case is not None:
            result.golden_metrics = evaluate_golden(
                answer=answer,
                sources=sources,
                case=golden_case,
            )

        return result
