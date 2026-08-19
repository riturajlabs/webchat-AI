#!/usr/bin/env python3
"""Hybrid Search A/B Evaluation — Vector vs Hybrid retrieval comparison.

Seeds an in-memory environment with representative knowledge chunks covering
pricing, trial, integrations, support, security, and team content.  Runs
each golden dataset query through both vector-only and hybrid (RRF) retrieval,
collects retrieval/quality/performance metrics, and prints a comparison report
with a production rollout recommendation.

Usage:
    uv run python scripts/perf/ab_evaluation.py
    uv run python scripts/perf/ab_evaluation.py --json
    uv run python scripts/perf/ab_evaluation.py --top-k 3
    uv run python scripts/perf/ab_evaluation.py --rrf-k 30
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

TENANT_ID = "ab-eval-tenant"
WEBSITE_ID = "ab-eval-website"

# ---------------------------------------------------------------------------
# Knowledge chunk seed data — mirrors what a real website crawl produces.
# Each chunk has a source_url and title so retrieval metrics can match
# against golden case expected_sources.
# ---------------------------------------------------------------------------

SEED_CHUNKS: list[dict[str, str]] = [
    # Pricing
    {
        "text": (
            "We offer three pricing tiers: Starter ($9/mo) for individuals, "
            "Pro ($29/mo) for small teams, and Enterprise (custom pricing) "
            "for large organizations.  All plans include a 14-day free trial."
        ),
        "url": "https://example.com/pricing",
        "title": "Pricing Plans",
        "document_id": "doc-pricing",
    },
    {
        "text": (
            "The Pro plan includes unlimited widgets, priority support, "
            "custom branding, and API access.  Upgrade anytime from your "
            "dashboard settings."
        ),
        "url": "https://example.com/pricing",
        "title": "Pro Plan Details",
        "document_id": "doc-pricing",
        "chunk_index": 1,
    },
    # Free trial
    {
        "text": (
            "Our free trial gives you 14 days of full Pro-level access. "
            "No credit card required.  Sign up at example.com/trial and "
            "start embedding the widget on your site immediately."
        ),
        "url": "https://example.com/trial",
        "title": "Free Trial",
        "document_id": "doc-trial",
    },
    {
        "text": (
            "After the trial ends you can choose to upgrade to a paid plan "
            "or downgrade to the free Starter tier.  All your data and "
            "configuration are preserved."
        ),
        "url": "https://example.com/trial",
        "title": "Trial FAQ",
        "document_id": "doc-trial",
        "chunk_index": 1,
    },
    # Integrations
    {
        "text": (
            "We support integrations with Slack, Microsoft Teams, Zapier, "
            "HubSpot, Salesforce, and Intercom.  Each integration can be "
            "configured from the Integrations page in your dashboard."
        ),
        "url": "https://example.com/integrations",
        "title": "Integrations",
        "document_id": "doc-integrations",
    },
    {
        "text": (
            "The REST API allows you to build custom integrations.  Full "
            "documentation is available at docs.example.com/api.  API keys "
            "can be generated under Settings > API Keys."
        ),
        "url": "https://example.com/integrations",
        "title": "API & Custom Integrations",
        "document_id": "doc-integrations",
        "chunk_index": 1,
    },
    # Support / Contact
    {
        "text": (
            "You can reach our support team via email at support@example.com "
            "or through the live chat widget on any page.  Our support hours "
            "are Monday-Friday, 9am-6pm EST."
        ),
        "url": "https://example.com/support",
        "title": "Contact Support",
        "document_id": "doc-support",
    },
    {
        "text": (
            "For urgent issues, Enterprise customers have a dedicated Slack "
            "channel and a guaranteed 1-hour response time.  Pro customers "
            "receive priority queue placement."
        ),
        "url": "https://example.com/support",
        "title": "Support Tiers",
        "document_id": "doc-support",
        "chunk_index": 1,
    },
    # Security
    {
        "text": (
            "We are SOC 2 Type II certified and GDPR compliant.  All data "
            "is encrypted at rest (AES-256) and in transit (TLS 1.3).  We "
            "conduct annual penetration tests with third-party auditors."
        ),
        "url": "https://example.com/security",
        "title": "Security & Compliance",
        "document_id": "doc-security",
    },
    {
        "text": (
            "Enterprise plans include SSO via SAML 2.0, role-based access "
            "control, audit logs, and data residency options in the US, EU, "
            "and APAC regions."
        ),
        "url": "https://example.com/security",
        "title": "Enterprise Security",
        "document_id": "doc-security",
        "chunk_index": 1,
    },
    # Teams / Enterprise
    {
        "text": (
            "The Teams plan ($49/mo) supports up to 25 members with shared "
            "workspaces, team-level analytics, and centralized billing.  "
            "Add members from the Team Settings page."
        ),
        "url": "https://example.com/teams",
        "title": "Teams Plan",
        "document_id": "doc-teams",
    },
    {
        "text": (
            "Enterprise customers get a dedicated account manager, custom "
            "SLA, on-premise deployment options, and volume discounts.  "
            "Contact sales@example.com for a quote."
        ),
        "url": "https://example.com/teams",
        "title": "Enterprise Features",
        "document_id": "doc-teams",
        "chunk_index": 1,
    },
]


async def _run_ab_evaluation(
    *,
    top_k: int,
    rrf_k: int,
    output_json: bool,
) -> None:
    """Seed environment, run A/B evaluation, print report."""
    from backend.benchmark.ab_evaluation import (
        compute_ab_report,
        format_ab_report,
        run_ab_evaluation,
    )
    from backend.benchmark.golden import GoldenDataset
    from tests.chat_helpers import build_chat_env, make_chunk, make_website

    # 1. Build and seed the environment
    env = build_chat_env(deltas=["I", " found", " relevant", " information."])
    await make_website(
        env,
        tenant_id=TENANT_ID,
        website_id=WEBSITE_ID,
        knowledge_chunks=len(SEED_CHUNKS),
    )
    for i, chunk_data in enumerate(SEED_CHUNKS):
        await make_chunk(
            env,
            tenant_id=TENANT_ID,
            website_id=WEBSITE_ID,
            text=chunk_data["text"],
            url=chunk_data["url"],
            title=chunk_data["title"],
            document_id=chunk_data.get("document_id", f"doc-{i}"),
            chunk_index=int(chunk_data.get("chunk_index", 0)),
        )

    # 2. Load golden dataset
    golden = GoldenDataset.load_default()
    print(f"  Seeded {len(SEED_CHUNKS)} knowledge chunks across 6 topics")
    print(f"  Running A/B evaluation on {len(golden)} golden cases")
    print(f"  top_k={top_k}  rrf_k={rrf_k}")
    print()

    # 3. Run A/B evaluation for each golden case
    results = []
    started = time.perf_counter()

    for case in golden:
        print(f"  [{case.label}] ", end="", flush=True)
        t0 = time.perf_counter()
        result = await run_ab_evaluation(
            env=env,
            golden_case=case,
            tenant_id=TENANT_ID,
            website_id=WEBSITE_ID,
            question=case.question,
            top_k=top_k,
            rrf_k=rrf_k,
        )
        elapsed = (time.perf_counter() - t0) * 1000
        v_acc = result.vector_retrieval.source_accuracy
        h_acc = result.hybrid_retrieval.source_accuracy
        delta = "+" if h_acc - v_acc >= 0 else ""
        print(
            f"vector={v_acc:.3f}  hybrid={h_acc:.3f}  "
            f"delta={delta}{h_acc - v_acc:.3f}  ({elapsed:.0f}ms)"
        )
        results.append(result)

    wall_ms = (time.perf_counter() - started) * 1000

    # 4. Compute aggregated report
    report = compute_ab_report(results)

    # 5. Output
    print()

    if output_json:
        output = {
            "query_count": report.query_count,
            "retrieval": {
                "vector": {
                    "precision_mean": report.vector_precision_mean,
                    "source_accuracy_mean": report.vector_source_accuracy_mean,
                    "avg_score_mean": report.vector_avg_score_mean,
                    "unique_sources_mean": report.vector_unique_sources_mean,
                },
                "hybrid": {
                    "precision_mean": report.hybrid_precision_mean,
                    "source_accuracy_mean": report.hybrid_source_accuracy_mean,
                    "avg_score_mean": report.hybrid_avg_score_mean,
                    "unique_sources_mean": report.hybrid_unique_sources_mean,
                },
                "precision_improvement_pct": report.precision_improvement_pct,
                "source_accuracy_improvement_pct": report.source_accuracy_improvement_pct,
            },
            "golden_quality": {
                "vector": {
                    "overall_mean": report.vector_golden_overall_mean,
                    "keyword_coverage_mean": report.vector_keyword_coverage_mean,
                    "context_coverage_mean": report.vector_context_coverage_mean,
                },
                "hybrid": {
                    "overall_mean": report.hybrid_golden_overall_mean,
                    "keyword_coverage_mean": report.hybrid_keyword_coverage_mean,
                    "context_coverage_mean": report.hybrid_context_coverage_mean,
                },
                "golden_overall_improvement_pct": report.golden_overall_improvement_pct,
            },
            "latency": {
                "vector_mean_ms": report.vector_latency_mean,
                "hybrid_mean_ms": report.hybrid_latency_mean,
                "delta_ms": report.latency_delta_ms,
            },
            "recommendation": report.recommendation,
            "per_query": [
                {
                    "label": qr.label,
                    "vector_source_accuracy": qr.vector_retrieval.source_accuracy,
                    "hybrid_source_accuracy": qr.hybrid_retrieval.source_accuracy,
                    "vector_golden_overall": qr.vector_golden.overall_quality_score,
                    "hybrid_golden_overall": qr.hybrid_golden.overall_quality_score,
                    "vector_latency_ms": qr.vector_latency_ms,
                    "hybrid_latency_ms": qr.hybrid_latency_ms,
                }
                for qr in report.per_query
            ],
            "wall_time_ms": round(wall_ms, 2),
        }
        json.dump(output, sys.stdout, indent=2)
        print()
    else:
        print(format_ab_report(report))
        print(f"  Wall time: {wall_ms:.1f} ms")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hybrid Search A/B Evaluation — Vector vs Hybrid"
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Max retrieval results per method (default: 5)",
    )
    parser.add_argument(
        "--rrf-k",
        type=int,
        default=60,
        help="RRF constant for hybrid fusion (default: 60)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output results as JSON",
    )
    args = parser.parse_args()

    asyncio.run(
        _run_ab_evaluation(
            top_k=args.top_k,
            rrf_k=args.rrf_k,
            output_json=args.output_json,
        )
    )


if __name__ == "__main__":
    main()
