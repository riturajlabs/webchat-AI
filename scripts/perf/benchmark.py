#!/usr/bin/env python3
"""CLI entry point for the AI latency benchmark (Phase 3 Step 3).

Runs the benchmark with in-memory fakes and prints a summary report.

Usage:
    uv run python scripts/perf/benchmark.py
    uv run python scripts/perf/benchmark.py --rounds 5
    uv run python scripts/perf/benchmark.py --queries pricing_plans,free_trial
"""

import argparse
import asyncio
import json
import sys
import time

from backend.benchmark.queries import QUERIES
from backend.benchmark.report import compute_summary, format_report
from backend.benchmark.runner import BenchmarkRunner


async def _run_benchmark(
    rounds: int,
    query_labels: list[str] | None,
    output_json: bool,
    seed_knowledge: bool,
) -> None:
    """Set up environment, run the benchmark, print the report."""
    from tests.chat_helpers import build_chat_env, make_chunk, make_website

    env = build_chat_env()

    if seed_knowledge:
        await make_website(
            env,
            tenant_id="bench-tenant",
            website_id="bench-web",
            knowledge_chunks=3,
        )
        for i in range(3):
            await make_chunk(
                env,
                tenant_id="bench-tenant",
                website_id="bench-web",
                text=f"Performance benchmark knowledge chunk {i}: "
                "This is representative content for latency measurement.",
                document_id=f"bench-doc-{i}",
                chunk_index=i,
                url=f"https://bench.example.com/page-{i}",
                title=f"Benchmark Page {i}",
            )

    queries = QUERIES
    if query_labels:
        queries = [q for q in QUERIES if q.label in query_labels]
        if not queries:
            print(f"Unknown query labels: {query_labels}", file=sys.stderr)
            print(f"Available: {[q.label for q in QUERIES]}", file=sys.stderr)
            sys.exit(1)

    runner = BenchmarkRunner(
        queries=queries,
        rounds=rounds,
        tenant_id="bench-tenant",
        website_id="bench-web",
    )

    started = time.perf_counter()
    results = await runner.run(env=env)
    wall_ms = (time.perf_counter() - started) * 1000.0

    report = compute_summary(results)

    if output_json:
        output = {
            "request_count": report.request_count,
            "success_count": report.success_count,
            "error_count": report.error_count,
            "total_latency": {
                "mean": report.total_latency.mean,
                "median": report.total_latency.median,
                "p95": report.total_latency.p95,
                "min": report.total_latency.min,
                "max": report.total_latency.max,
            },
            "ttft": {
                "mean": report.ttft.mean,
                "median": report.ttft.median,
                "p95": report.ttft.p95,
            },
            "generation_latency": {
                "mean": report.generation_latency.mean,
                "median": report.generation_latency.median,
                "p95": report.generation_latency.p95,
            },
            "embedding_latency": {
                "mean": report.embedding_latency.mean,
                "median": report.embedding_latency.median,
                "p95": report.embedding_latency.p95,
            },
            "retrieval_latency": {
                "mean": report.retrieval_latency.mean,
                "median": report.retrieval_latency.median,
                "p95": report.retrieval_latency.p95,
            },
            "provider_success_rate": report.provider_success_rate,
            "fallback_rate": report.fallback_rate,
            "cache_hit_rate": report.cache_hit_rate,
            "fallback_attempts_total": report.fallback_attempts_total,
            "estimated_tokens_total": report.estimated_tokens_total,
            "provider_counts": report.provider_counts,
            "wall_time_ms": round(wall_ms, 2),
        }
        json.dump(output, sys.stdout, indent=2)
        print()
    else:
        print(format_report(report))
        print(f"\n  Wall time: {wall_ms:.1f} ms")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI latency benchmark runner")
    parser.add_argument(
        "--rounds",
        type=int,
        default=1,
        help="Number of times to repeat each query (default: 1)",
    )
    parser.add_argument(
        "--queries",
        type=str,
        default=None,
        help="Comma-separated query labels to benchmark (default: all)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output results as JSON instead of a formatted report",
    )
    parser.add_argument(
        "--no-seed",
        action="store_true",
        dest="no_seed",
        help="Skip seeding knowledge chunks (run without retrieval context)",
    )
    args = parser.parse_args()

    query_labels = args.queries.split(",") if args.queries else None
    asyncio.run(
        _run_benchmark(
            rounds=args.rounds,
            query_labels=query_labels,
            output_json=args.output_json,
            seed_knowledge=not args.no_seed,
        )
    )


if __name__ == "__main__":
    main()
