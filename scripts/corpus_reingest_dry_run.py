"""READ-ONLY corpus re-ingestion dry-run simulator (Phase P1).

Simulates what re-ingesting a website with the CURRENT chunker would do to the
corpus, and reports the change structurally - WITHOUT writing anything to
Atlas/Redis and WITHOUT re-embedding or crawling.

Safety contract (matches P1):
  * Atlas writes            = 0  (only `find` / `list_chunks_light`)
  * Redis writes            = 0  (no cache/client constructed)
  * production crawl        = 0
  * production re-embedding = 0
  * config/threshold        = 0

Metrics computed (generic, site-agnostic):
  * total chunks
  * chunks below the token floor
  * exact-duplicate groups / extra chunks
  * adjacent high-Jaccard duplicate pairs
  * repeated-heading pollution
  * average / median chunk size
  * source / document concentration
  * factual-content preservation (probes supplied at the command line)
  * deterministic chunking

Gates: PASS/FAIL evaluated via `corpus_quality.evaluate_gates`.

Usage (run inside the webchat-api container, with production env loaded):
    python scripts/corpus_reingest_dry_run.py \
        --tenant <tenant_id> --website <website_id> \
        --probe "dean of soit:dean of soit" \
        --probe "AI & Data Science:ai & data science" \
        --out /tmp/corpus_dry_run.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from typing import Any

from backend.core.config import get_settings
from backend.repositories.document_repository import MongoDocumentRepository
from backend.repositories.vector.mongodb import MongoVectorRepository
from backend.services.knowledge.corpus_quality import (
    CorpusEntry,
    SimulatedDocument,
    build_dry_run_report,
    evaluate_gates,
)
from motor.motor_asyncio import AsyncIOMotorClient


def _parse_probes(raw: list[str] | None) -> list[tuple[str, str]]:
    """Convert `label:fragment` CLI args into (label, fragment) probe tuples."""
    probes: list[tuple[str, str]] = []
    for item in raw or []:
        if ":" not in item:
            print(f"  [warning] probe '{item}' has no ':' separator; skipped", file=sys.stderr)
            continue
        label, fragment = item.split(":", 1)
        label = label.strip()
        fragment = fragment.strip()
        if label and fragment:
            probes.append((label, fragment))
    return probes


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True, help="tenant id")
    parser.add_argument("--website", required=True, help="website id")
    parser.add_argument(
        "--probe",
        action="append",
        default=[],
        metavar="LABEL:FRAGMENT",
        help="factual-preservation probe; repeatable.",
    )
    parser.add_argument(
        "--structural-heading",
        action="append",
        default=[],
        metavar="HEADING",
        help="legitimate structural section heading to exclude from G3 "
        "heading-pollution (e.g. 'Curriculum'); repeatable.",
    )
    parser.add_argument("--out", default="/tmp/corpus_reingest_dry_run.json")
    parser.add_argument(
        "--source-filter",
        default=None,
        help="optional substring to limit simulated documents ('' = all, default all).",
    )
    args = parser.parse_args()

    settings = get_settings()
    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(
        settings.mongodb_uri, serverSelectionTimeoutMS=20000
    )
    db = client[settings.mongodb_db]
    docs_repo = MongoDocumentRepository(db)
    vector = MongoVectorRepository(db)

    probes = _parse_probes(args.probe)

    print(f"READ-ONLY simulation :: tenant={args.tenant} website={args.website}")
    print(f"  probes: {[p[0] for p in probes] or '<none>'}")

    # 1. OLD corpus (embedding-free, read-only).
    t0 = time.perf_counter()
    old_chunks = await vector.list_chunks_light(args.tenant, args.website, limit=0)
    old_ms = (time.perf_counter() - t0) * 1000.0
    print(f"  old corpus chunks={len(old_chunks)} (load {old_ms:.0f}ms, embedding-free)")

    old_entries = [CorpusEntry.from_chunk(chunk) for chunk in old_chunks]

    # 2. Documents (source content for the simulated re-chunk).
    documents = await docs_repo.list_by_website(args.tenant, args.website)
    sim_docs = [
        SimulatedDocument(source=doc.url, content=doc.content)
        for doc in documents
        if (args.source_filter is None or args.source_filter in (doc.url or ""))
    ]
    print(f"  documents loaded={len(documents)} (simulated={len(sim_docs)})")

    # 3. Dry-run: old vs simulated-new metrics + probes.
    t0 = time.perf_counter()
    report = build_dry_run_report(old_entries, sim_docs, probes=probes)
    sim_ms = (time.perf_counter() - t0) * 1000.0
    print(
        f"  chunker simulation done in {sim_ms:.0f}ms "
        f"-> simulated-new chunks={report.new.total_chunks}"
    )

    # 4. Gates.
    gates = evaluate_gates(
        report,
        probes=probes,
        structural_headings=args.structural_heading,
    )

    result: dict[str, Any] = {
        "read_only": True,
        "tenant": args.tenant,
        "website": args.website,
        "old_corpus_chunks": report.old.total_chunks,
        "simulated_new_chunks": report.new.total_chunks,
        "old": report.old.to_dict(),
        "new": report.new.to_dict(),
        "probes_old": [p.to_dict() for p in report.probes_old],
        "probes_new": [p.to_dict() for p in report.probes_new],
        "gates": [{"name": g.name, "passed": g.passed, "detail": g.detail} for g in gates],
        "all_gates_passed": all(g.passed for g in gates),
        "probes": [{"label": label, "fragment": fragment} for label, fragment in probes],
        "structural_headings": list(args.structural_heading),
    }

    json_out = {
        **result,
        "old_entries_sample": [
            {"source": e.source, "heading": e.heading, "text": e.text[:120]}
            for e in report.old_entries[:5]
        ],
        "new_entries_sample": [
            {"source": e.source, "heading": e.heading, "text": e.text[:120]}
            for e in report.new_entries[:5]
        ],
    }

    def _write_out() -> None:
        with open(args.out, "w") as f:
            json.dump(json_out, f, indent=2)

    await asyncio.to_thread(_write_out)
    print(f"  written {args.out}")

    # 5. Human-readable summary.
    old, new = report.old, report.new
    print("\n=== OLD vs SIMULATED-NEW ===")
    print(f"  total chunks          : {old.total_chunks} -> {new.total_chunks}")
    print(f"  tiny (<40 tokens)     : {old.tiny_chunks_below} -> {new.tiny_chunks_below}")
    print(
        "  exact-dup extra chunks: "
        f"{old.exact_duplicate_extra_chunks} -> {new.exact_duplicate_extra_chunks}"
    )
    print(
        "  adj >0.8 jaccard frac : "
        f"{old.adjacent_high_jaccard_fraction:.4f} -> {new.adjacent_high_jaccard_fraction:.4f}"
    )
    print(
        "  top heading pollution : "
        f"{old.repeated_heading_pollution} -> {new.repeated_heading_pollution}"
    )
    print(
        "  avg/median tokens     : "
        f"{old.avg_tokens:.1f}/{old.median_tokens} -> {new.avg_tokens:.1f}/{new.median_tokens}"
    )
    print(f"  source count          : {old.source_count} -> {new.source_count}")

    print("\n=== GATES ===")
    for g in gates:
        print(f"  [{('PASS' if g.passed else 'FAIL')}] {g.name}: {g.detail}")
    print(f"\nALL GATES PASSED: {result['all_gates_passed']}")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
