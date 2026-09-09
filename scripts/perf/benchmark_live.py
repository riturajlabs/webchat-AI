#!/usr/bin/env python3
"""Live production RAG benchmark driver for RAG-PERF-07 / REAL-TTFT-02.

Auth: dashboard owner via `/api/auth/login`. Streams N real chat turns over
`POST /api/chat/stream` (SSE) against Tenant A ("BCA Academy A", tuition Rs 80,000)
and Tenant B ("BCA Academy B", Rs 65,000) with known ground truth.

Outputs one NDJSON row per request to stdout (and to a results file when
`--tag` is given) with client-side e2e TTFT + full done-frame `timing` and the
assistant answer (for offline accuracy scoring).

Usage:
    .venv/bin/python scripts/perf/benchmark_live.py \
        --tag a --tenant-id <tenant_a> --website-id <website_a> --email bench-a@example.com \
        --questions 8 --cold  (and --warm for cache-hit phase)
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field

import httpx

API = os.environ.get("API_BASE_URL", "http://localhost:8000")

QUESTIONS_TENANT_A = [
    "What is the annual fee for the BCA programme at BCA Academy A?",
    "How much does BCA cost per year at BCA Academy A?",
    "What is the BCA tuition fee at BCA Academy A in rupees?",
    "What does the annual BCA fee of Rs 80,000 at BCA Academy A include?",
    "Does BCA Academy A charge a fee for its B.C.A. course?",
    "What are the payment installments for the BCA fee at BCA Academy A?",
    "Is the BCA fee at BCA Academy A refundable after admission?",
    "Apart from the Rs 80,000 BCA fee, what else does BCA Academy A charge?",
]
QUESTIONS_TENANT_B = [
    "What is the annual fee for the BCA programme at BCA Academy B?",
    "How much does BCA cost per year at BCA Academy B?",
    "What is the BCA tuition fee at BCA Academy B in rupees?",
    "What does the annual BCA fee of Rs 65,000 at BCA Academy B include?",
    "Does BCA Academy B charge a fee for its B.C.A. course?",
    "What is the exact annual programme fee at BCA Academy B?",
    "Is the BCA fee at BCA Academy B refundable after admission?",
    "What is the total annual tuition for the B.C.A. programme at BCA Academy B?",
]


@dataclass
class Result:
    tenant: str
    site: str
    phase: str
    question: str
    ok: bool = False
    e2e_ttft_ms: float | None = None
    msg_first_ms: float | None = None
    first_delta_ts: float | None = None
    timing: dict = field(default_factory=dict)
    answer: str = ""
    done: dict = field(default_factory=dict)
    error: str = ""
    http_status: int = 0
    elapsed_ms: float | None = None


def parse_sse_lines(lines: list[str], res: Result) -> None:
    current_event = None
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("event:"):
            current_event = line.split("event:", 1)[1].strip()
            continue
        if line.startswith("data:"):
            payload = line.split("data:", 1)[1].strip()
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if current_event == "message":
                delta = data.get("delta", "")
                if res.first_delta_ts is None and delta:
                    res.first_delta_ts = time.monotonic()
                res.answer += delta
            elif current_event == "done":
                res.done = data
                if "timing" in data:
                    res.timing = data["timing"]
            elif current_event == "error":
                res.error = data.get("message", json.dumps(data))
                res.ok = False


def run_one(
    client: httpx.Client,
    *,
    tenant: str,
    site: str,
    phase: str,
    website_id: str,
    question: str,
) -> Result:
    res = Result(tenant=tenant, site=site, phase=phase, question=question)
    t0 = time.monotonic()
    answer_started: float | None = None
    buffered: list[str] = []
    try:
        with client.stream(
            "POST",
            "/api/chat/stream",
            json={"website_id": website_id, "question": question},
        ) as stream:
            res.http_status = stream.status_code
            for line in stream.iter_lines():
                if not line:
                    continue
                if answer_started is None and ("event:" in line or "data:" in line):
                    # first SSE frame arrival == first bytes of the response
                    answer_started = time.monotonic()
                buffered.append(line)
    except httpx.HTTPError as exc:
        res.error = f"transport:{exc}"
        res.elapsed_ms = (time.monotonic() - t0) * 1000.0
        return res
    elapsed = (time.monotonic() - t0) * 1000.0
    res.elapsed_ms = elapsed
    if answer_started is not None:
        res.e2e_ttft_ms = (answer_started - t0) * 1000.0
    parse_sse_lines(buffered, res)
    if res.first_delta_ts is not None:
        res.msg_first_ms = (res.first_delta_ts - t0) * 1000.0
    res.ok = (res.error == "") and bool(res.answer)
    return res


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def summarize(results: list[Result], key: str) -> dict:
    vals = [getattr(r, key) for r in results if getattr(r, key) is not None]
    if not vals:
        return {}
    return {
        "n": len(vals),
        "mean_ms": round(statistics.mean(vals), 1),
        "median_ms": round(statistics.median(vals), 1),
        "p50_ms": round(percentile(vals, 50), 1),
        "p95_ms": round(percentile(vals, 95), 1),
        "p99_ms": round(percentile(vals, 99), 1),
        "min_ms": round(min(vals), 1),
        "max_ms": round(max(vals), 1),
    }


def stage_summary(results: list[Result], stage: str) -> dict:
    vals = []
    for r in results:
        v = r.timing.get(stage)
        if isinstance(v, (int, float)) and v is not None:
            vals.append(float(v))
    if not vals:
        return {}
    return {
        "n": len(vals),
        "mean_ms": round(statistics.mean(vals), 1),
        "median_ms": round(statistics.median(vals), 1),
        "p95_ms": round(percentile(vals, 95), 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--website-id", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--questions", type=int, default=8)
    parser.add_argument("--repeats", type=int, default=4)
    parser.add_argument("--phase", default="cold", choices=["cold", "warm"])
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    with httpx.Client(base_url=API, timeout=30.0) as client:
        login = client.post(
            "/api/auth/login",
            json={"email": args.email, "password": "bench-prod-pass-2026"},
        )
        if login.status_code != 200:
            print(f"LOGIN_FAILED {login.status_code}: {login.text[:400]}", file=sys.stderr)
            return 1
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        client.headers.update(headers)

        if args.tenant_id.endswith("5310b4f9-34dd-4e24-9677-5c022c5f04f2"):
            questions = QUESTIONS_TENANT_A
        else:
            questions = QUESTIONS_TENANT_B

        results: list[Result] = []
        for rep in range(args.repeats):
            for idx in range(args.questions):
                q = questions[idx % len(questions)]
                res = run_one(
                    client,
                    tenant=args.tag,
                    site=args.tag,
                    phase=args.phase,
                    website_id=args.website_id,
                    question=q,
                )
                results.append(res)
                row = {
                    "rep": rep,
                    "idx": idx,
                    "question": q,
                    "ok": res.ok,
                    "http_status": res.http_status,
                    "e2e_ttft_ms": res.e2e_ttft_ms,
                    "msg_first_ms": res.msg_first_ms,
                    "elapsed_ms": res.elapsed_ms,
                    "timing": res.timing,
                    "answer": res.answer,
                    "error": res.error,
                    "done": res.done,
                }
                print(json.dumps(row), flush=True)
                if rep == 0 and idx == 0:
                    time.sleep(1.0)  # warm provider connection on first request

        if args.output:
            with open(args.output, "w") as fh:
                for r in results:
                    fh.write(
                        json.dumps(
                            {
                                "tenant": r.tenant,
                                "phase": r.phase,
                                "question": r.question,
                                "ok": r.ok,
                                "e2e_ttft_ms": r.e2e_ttft_ms,
                                "msg_first_ms": r.msg_first_ms,
                                "elapsed_ms": r.elapsed_ms,
                                "timing": r.timing,
                                "answer": r.answer,
                                "error": r.error,
                            }
                        )
                        + "\n"
                    )

        n_fail = sum(1 for r in results if not r.ok)
        summary = (
            f"tenant={args.tag} phase={args.phase} attempts={len(results)} "
            f"ok={len(results) - n_fail} failed={n_fail}"
        )
        print("=== SUMMARY ===", flush=True)
        print(summary, flush=True)
        for key in ("e2e_ttft_ms", "msg_first_ms", "elapsed_ms"):
            s = summarize(results, key)
            if s:
                print(f"{key} {json.dumps(s)}", flush=True)
        for stage in (
            "embedding_ms",
            "retrieval_ms",
            "load_chunks_ms",
            "context_ms",
            "history_ms",
            "generation_ms",
            "ttft_ms",
            "total_ms",
            "rerank_ms",
        ):
            s = stage_summary(results, stage)
            if s:
                print(f"stage.{stage} {json.dumps(s)}", flush=True)

        # cache / provider telemetry
        embed_cache = [r.timing.get("embedding_cache") for r in results]
        ret_cache = [r.timing.get("retrieval_cache") for r in results]
        providers = [r.timing.get("provider") for r in results]
        print(
            "embed_cache_counts:", {v: embed_cache.count(v) for v in set(embed_cache)}, flush=True
        )
        print(
            "retrieval_cache_counts:", {v: ret_cache.count(v) for v in set(ret_cache)}, flush=True
        )
        print("provider_counts:", {v: providers.count(v) for v in set(providers)}, flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\naborted", file=sys.stderr)
        raise SystemExit(130) from None
