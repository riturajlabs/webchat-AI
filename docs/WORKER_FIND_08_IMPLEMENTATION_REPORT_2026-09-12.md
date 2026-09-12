# FIND-08 IMPLEMENTATION REPORT — 2026-09-12

Branch: `main` @ `3f49f3f` (HEAD). No commits, no pushes were made for this work.

## Files changed

Tracked, uncommitted:

- `backend/core/config.py` — new `crawl_job_timeout_seconds: int = 3600` (env `CRAWL_JOB_TIMEOUT_SECONDS`), with a sizing comment.
- `backend/workers/tasks.py` — `crawl_website` registered as an ARQ `Function` with its own timeout (`CRAWL_FUNCTION`); `TASKS` rewired.
- `backend/workers/jobs/crawl.py` — new `except asyncio.CancelledError:` clause in `_run_crawl_job_impl` plus the `_finalize_crawl_cancelled` terminalizer.
- `.env.production.example` — `CRAWL_JOB_TIMEOUT_SECONDS=3600` with a FIND-08 comment block.
- `tests/test_crawl_worker.py` — 5 new FIND-08 tests.

Untracked, newly created (not staged):

- `docs/WORKER_FIND_08_IMPLEMENTATION_REPORT_2026-09-12.md` (this file).

Untracked reports preserved as-is: `docs/WORKER_COMPREHENSIVE_PRODUCTION_AUDIT_2026-09-12.md` (canon for the finding, lines 143–149), `docs/WORKER_FIND_02_...`, `docs/WORKER_FIND_05_CRAWL_NO_SANDBOX_INVESTIGATION_2026-09-12.md`, `docs/WORKER_FIND_08_INVESTIGATION_2026-09-12.md`, `MOBILE_REVIEW_REPORT.md`. No audit or FIND report was modified or staged.

## Timeout setting/default

- Global ARQ `job_timeout` stays `600` s (`backend/workers/app.py`) for all non-crawl tasks.
- `crawl_website` gets its own finite budget: `crawl_job_timeout_seconds` (pydantic field) / `CRAWL_JOB_TIMEOUT_SECONDS` (env), default `3600`.

## Why this timeout value was selected

- Worst honest per-page bound (unchanged per-page settings): 30 s nav timeout + bounded retry delay (Retry-After up to 30 s, backoff 1→5 s capped) + second 30 s HTTP attempt + 30 s browser fallback ≈ 120 s/page → 50 pages ≈ up to 6000 s (~100 min). Realistic slow crawls (JS-heavy, sparse fallbacks) land well under ~25–30 min.
- 3600 s ≈ ~2x above a realistic slow crawl, keeps a finite stop for a rogue/hung crawl, and degrades gracefully: a timeout now terminalizes instead of stranding (partial pages preserved, website re-crawlable). Per-page `crawl_navigation_timeout_ms` remains 30 s; `crawl_http_max_attempts`/retry/backoff unchanged; no concurrency change (`CRAWL_MAX_CONCURRENT=1`); 1 GiB/2 vCPU posture untouched; memory-guard behavior unchanged (recoverable/retryable — distinct from the terminal timeout path).

## ARQ registration behaviour

- `backend/workers/tasks.py`: `CRAWL_FUNCTION = func(timed_job(crawl_website), timeout=get_settings().crawl_job_timeout_seconds)`. ARQ 0.28.0's `func()` builds a `Function`; `worker.py:574` uses `function.timeout_s` when set, falling back to the global `job_timeout`. `timed_job`'s `functools.wraps` preserves the `crawl_website` name ARQ dispatches on.
- Verified from the live registry: `crawl_website: explicit_timeout=3600 effective=3600`; `ping`, `process_document`, `process_website_documents`, `send_email` all `effective=600` (global). Dedicated timeout is finite (asserted `< inf` in tests).
- Non-crawl tasks are unchanged plain coroutines and inherit the global 600 s.

## Cancellation handling

- ARQ delivers `asyncio.CancelledError` (a `BaseException`) into the crawl when the per-task timeout expires; the existing `except Exception` handlers never see it (`worker.py:599`, `628-634`; job timeouts are hard failures, no retry).
- `_run_crawl_job_impl` now has `except asyncio.CancelledError:` (placed between `except InvalidUrlError` and `except Exception`) that awaits `_finalize_crawl_cancelled(...)` best-effort, then `raise` (re-raises the exact pending cancellation context so ARQ records the failure).
- The async context/`finally` cleanup (browser close, fetcher close) still runs during the unwind — asserted in tests.

## Terminal job state

- Job lands on `failed`, `active=False`, `completed_at` set, `pages_completed` = stored-page count, `pages_total` preserved, `error_message` = `"Crawl timed out after N seconds; pages stored=X"` (plus, when existing pages remain, `" Your existing knowledge base is still available."`). Whole value has no secrets/URLs/page content.

## Website state after timeout

- Existing pages > 0 → `WEBSITE_STATUS_READY`, `pages_indexed` = actual stored count (prior knowledge base survives a timed-out refresh; existing documents are never deleted).
- Zero pages stored → `WEBSITE_STATUS_FAILED`, `pages_indexed=0` (no invented knowledge is ever exposed).
- Either way the website leaves `crawling`, so `CrawlConflictError` no longer blocks a re-crawl.

## Partial progress behaviour

- Every page stored before the cancellation is preserved — never deleted, never re-stored by the terminalizer, and `pages_indexed` reflects the true count. No knowledge-ingestion handoff fires for a cancelled crawl (`enqueue_knowledge` is never called).

## Fencing behaviour

- FIND-02 single-terminator is reused: all side effects are gated behind `crawl_jobs.finish_if_active(...)`; a stale/re-delivered cancellation for an already-terminal job returns `won=False`, logs `crawl_terminal_skipped ... already_terminal`, and emits nothing (no duplicate event/audit/metric/website write). Website writes go through `update_if_crawl_owner` (owner-fenced); a lost race logs `crawl_website_write_fenced`.

## Observability

- `record_crawl_failed(reason="timeout")` → `CRAWL_FAILED_TOTAL` metric tagged `reason=timeout`.
- `crawl_events.publish_failed(job_id, error=...)` (SSE contract intact).
- `AuditLog` `AUDIT_CRAWL_FAILED` entry.
- Structured worker log `crawl_failed ... reason=timeout pages_stored=.. pages_total=.. elapsed_seconds=..` with safe `hostname`/`path` only (FIND-03: no full URLs, no secrets, no page content). Terminalization failures log `crawl_timeout_terminalization_failed` with `exc_info`. Normal success path and memory-guard path unchanged.

## Tests

5 new tests in `tests/test_crawl_worker.py` (all pass; run with `uv run pytest tests/test_crawl_worker.py -q` → 37 passed):

1. `test_worker_cancellation_terminalizes_job_with_partial_pages` — cancellation after 1 stored page → job `failed`/inactive, website `READY`/out of `crawling`, page preserved, no enqueue, cleanup ran.
2. `test_cancellation_emits_timeout_telemetry` — `record_crawl_failed(reason="timeout")`, `crawl_failed ... reason=timeout` log line, no full URLs (`first_error_url=` absent), safe host/path only.
3. `test_worker_cancellation_zero_pages_fails_website` — cancel before any page → website `FAILED`, no documents.
4. `test_crawl_cancel_terminal_write_is_fenced` — FIND-02 fence: second (stale) terminalization is a no-op.
5. `test_crawl_task_has_dedicated_timeout` — `CRAWL_FUNCTION` is an ARQ `Function`, name `crawl_website`, `timeout_s == crawl_job_timeout_seconds`, `> 600`, `< inf`; other tasks stay plain (global 600).

## Full suite

`uv run pytest tests/` — exit 0, full pass (no regressions). Note: warnings in `/tmp/opencode/full_suite.log` are pre-existing (fastapi/starlette deprecations, one gemini test RuntimeWarning) and unrelated to this change.

## mypy

`uv run mypy backend` — `Success: no issues found in 203 source files` (strict).

## Ruff

- `uv run ruff check backend/ tests/` — All checks passed.
- `uv run ruff format --check backend/ tests/` — All files formatted.
- `uv run ruff format` applied to the two files that required formatting (`backend/workers/jobs/crawl.py`, `tests/test_crawl_worker.py`).

## Docker audit

`bash scripts/check-production-docker.sh` — 9 passed, 0 failed — `RESULT: PASS`. `docker/compose.yml` and `docker/compose.prod.yml` are byte-identical to HEAD (worker sizing 1G/2.0 unchanged).

## Residual risks

- Cancellation can arrive between fetching/storing and the finish write; the best-effort terminalizer handles it under the active `CancelledError` (fenced), and a failed terminalization is logged but still re-raised — a job would only strand if the fence DB write itself is unreachable at that instant, which also breaks every other worker terminal path.
- A genuine hang inside a fetch can be cut at the per-task timeout mid-page; the page is simply not persisted (count reflects stored pages only).
- Choosing 3600 s is a trade-off: 100 min rogue ceiling is higher than the 10-min global. It is the right default for the site sizes served; deployments with consistently slower real crawls should raise it.

## Stale-job reaper status

NOT introduced in this change. FIND-08 is fully self-correcting via the timeout+terminalization (any timed-out crawl is left re-crawlable automatically, so a reaper is not required). A future reaper for pre-existing stranded jobs remains a tracked follow-up item, unchanged by this work.

## Git status

- `git status -sb`: `main...origin/main [ahead 8]`; 5 tracked files modified (above); untracked reports as above. Nothing staged.
- `git diff --check`: clean.
- `git diff --stat HEAD`: 5 files, +379/−2 — only the intended files.

## Commit

NONE — no commit was created and nothing was staged.

## Push

NONE — nothing was pushed.
