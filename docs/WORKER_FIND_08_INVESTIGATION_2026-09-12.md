# FIND-08 Investigation — Single Global ARQ `job_timeout=600` vs Large/Slow Crawls

- Date: 2026-09-12
- Status: **STILL VALID** (verified, impact materially worse than recorded)
- Priority: P2
- Audit baseline: `docs/WORKER_COMPREHENSIVE_PRODUCTION_AUDIT_2026-09-12.md` §5 FIND-08 (lines 143-149) plus adjacent FIND-09..FIND-12.
- HEAD at investigation: `3f49f3f` (`main`, 8 commits ahead of `origin/main`).

## Canonical finding

> **FIND-08 (P2) — Single global ARQ `job_timeout=600` vs large/slow crawls.**
>
> - File:line: `workers/app.py:77` (now `backend/workers/app.py:125`, unchanged since the project-foundation commit `6ae84cf`).
> - Problem: `job_timeout=600` applies to every task including `crawl_website`. A pathological site: 50 pages × (30 s nav timeout + retries + browser fallback 30 s) can exceed 10 min → ARQ cancels mid-crawl regardless of progress.
> - Impact: spurious failed-at-final-attempt crawls with partial pages stored (harmless, self-heals on re-crawl, but user-facing "crawl failed").
> - Root cause: single timeout for heterogeneous jobs.
> - Fix: per-task timeouts or raise the crawl timeout with a **cancellation-aware** crawl loop (see FIND-09); keep the 30 s per-page bound.
> - Risk: raising the bound alone trades stuck-job protection for long-running rogues → combine with page/total-completion bookkeeping. Effort: M.

## Code path traced (entry → affected behavior)

1. `backend/workers/app.py:125` — `job_timeout = 600` on `WorkerSettings`; `functions = tasks.TASKS` (`app.py:120`) where every task is registered bare, so ARQ `Function.timeout_s is None` for all and every job inherits the single global `job_timeout_s = 600` (`arq/worker.py:574`: `timeout_s = self.job_timeout_s if function.timeout_s is None else function.timeout_s`). ARQ **0.28.0** (pyproject `arq>=0.26`).
2. `backend/workers/tasks.py` — `TASKS = [ping, timed_job(send_email), timed_job(crawl_website), timed_job(process_document), timed_job(process_website_documents)]`. The `timed_job` wrapper preserves the coroutine name (`functools.wraps`) and adds no timeout; the registry comment still lists a `finalize_crawl` task that is **never registered** — there is no post-crawl finalize path anywhere (`grep finalize_crawl` matches only the comment).
3. `backend/workers/jobs/crawl.py:131` `crawl_website(ctx, crawl_job_id)` → `_run_crawl_job` → `_run_crawl_job_impl` sets `job.status = PROCESSING` (line 296-298), then `session.run()` (line 304) inside `async with crawl_semaphore()`.
4. Per-page timing budget (all bounded by `crawl_navigation_timeout_ms=30000`, `config.py:339`):
   - HTTP attempt 1: wall-clock deadline 30 s (`http_first.py:269-312` `fetch_http_page`).
   - Retryable failure → bounded HTTP retry (delay backoff 1→5 s, Retry-After capped 30 s, `crawl_http_max_attempts=2`) → HTTP attempt 2 (up to 30 s).
   - Browser fallback exactly once: `page.goto(timeout=30000)` (`browser.py:161`) + `page.content()`.
   - Plus robots.txt crawl-delay sleeps (`crawler.py:302-303`), extraction/clean CPU, and a Mongo upsert per page.
   - **Worst case per page ≈ 30 + 5 + 30 + 30 ≈ 95 s.** 50 pages ≈ 79 min. Even success-only "slow but working" sites exceed the cliff at ≈ 12 s/page average (600 s ÷ 50).
5. ARQ enforcement (`arq/worker.py:599`): `result = await asyncio.wait_for(task, timeout_s)` → on timeout it **cancels the crawl coroutine** (`CancelledError`) and raises `asyncio.TimeoutError` to the worker, which marks the job failed-with-timeout (`worker.py:628-634`, `finish=True`, `jobs_failed += 1`) and **does not retry** (a timeout is neither `Retry`, `CancelledError`, nor `RetryJob`).

## Is it still valid, fixed, or materially changed?

**STILL VALID — and the recorded impact is materially worse than the audit stated.**

Verified against HEAD `3f49f3f`:

- `job_timeout = 600` is unchanged and untouched since `6ae84cf` (the project-foundation commit); no post-audit commit (`9123adb` FIND-01, `3c3616c`, `3d78866` FIND-02, `3b60478` FIND-03, `e93aca5` embedding finalization, `b0c4ff4` FIND-07, `9b64519` FIND-06, `3f49f3f` FIND-05) touched it or added a per-task override. No settings knob exists for a crawl-job timeout.
- `crawl_navigation_timeout_ms=30000` is still the only per-page cap; nothing bounds the total crawl wall-clock on the worker side.

**Discrepancy with the audit's impact statement (verified, did not copy):**

- The audit projected "failed-at-final-attempt crawls … self-heals on re-crawl". That is **incorrect** for the shipped code:
  - `CancelledError` is a `BaseException`; every handler in `_run_crawl_job_impl` is `except Exception` (`crawl.py:576`, `:631`) and there is **no `except CancelledError`/`except BaseException`** anywhere in the crawl path or the worker. A timeout cancels the coroutine with **no terminal write**: `finish_if_active` is never called.
  - The `crawl_jobs` document is left in `processing` with `active=True` (`crawl.py:296-298` set status, `find_one_and_update` fenced terminal writer never runs), and the `websites` document stays `crawling` (`crawl_service.py:112`).
  - `CrawlService.start_crawl` → `find_active_for_website` returns the stranded active row (`crawl_job_repository.py:90-99`) → **`CrawlConflictError`** → **a manual re-crawl is blocked indefinitely**.
  - There is **no reaper, requeue, cron reset, finalize task, or admin reset action** anywhere (admin surface `admin.py:557` `GET /api/admin/crawl-jobs` is read-only monitoring; `delete_by_website` only fires on website deletion). Nothing recovers the stranded pair.
  - Result: the job/site pair is **permanently stuck** until an operator deletes the website, with partial pages stored but **never embedded** (no `enqueue_knowledge` on a cancelled run).

## Root cause

Two compounding defects, both present at audit baseline:

1. **Single global timeout for heterogeneous tasks** (`app.py:125`): the email/ping/knowledge tasks and the long-running `crawl_website` share one 600 s budget. The crawler's worst-case bound (≈ 79 min for 50 pathological pages) is an order of magnitude above the budget, and even an average 12 s/page successful crawl scrapes it.
2. **No cancellation handling in the crawl loop** (`crawl.py`, cross-ref FIND-09): on `CancelledError` the job and website documents are left in non-terminal, non-recoverable states; ARQ's own failure bookkeeping and the app's crawl-job document diverge (ARQ sees "failed/timeout", Mongo still shows `active`).

## Production impact

- **User-facing**: the website spins in `crawling` / the job in `processing` forever; the dashboard cannot re-crawl (409 conflict); the site's previous knowledge base remains frozen until manual cleanup. Called out only by the admin crawl monitor if anyone is watching.
- **Data**: pages stored during the cancelled window are valid documents but are **not embedded** (no knowledge handoff), so they sit in the knowledge base as pending/never-embedded until a later successful crawl reconciles them.
- **Observability**: `record_crawl_failed` is only invoked from terminal paths (`crawl.py:375/619/688/702`); a timed-out crawl emits **no `crawl_failed` metric** (FIND-03 JSON logs do capture ARQ's `crawl_website failed, asyncio.TimeoutError` record). The failure is invisible to dashboards that key on the counter.
- **Confirmation of "harmless, self-heals" being false**: the audit's P2 severity assumption (partial pages stored harmlessly; re-crawl fixes it) does not hold — re-crawl is blocked, so issue recurrence actually **compounds** the stuck state per pathological site.

## Existing mitigation

None. There is no per-task timeout, no enqueue-side timeout override (`arq 0.28.0` has no `_job_timeout`), no cancellation handler, no stale-job reaper. `crawl_max_pages=50` and `crawl_max_concurrent=1` bound concurrency but not total wall-clock.

## Recommended remediation (smallest production-safe, matches audit "per-task timeouts or cancellation-aware loop")

Primary (matches the audit's fix and is a one-line structural change) — **per-task timeout via ARQ `Function`**:

- Register `crawl_website` (and optionally `process_document`) as `Function(..., timeout=...)` from `arq.worker`, so the global `job_timeout=600` no longer governs crawls and the other tasks keep their short protection (`arq/worker.py:52,69,94`).
- Set the crawl timeout from a new settings knob, e.g. `crawl_job_timeout_seconds` (env `CRAWL_JOB_TIMEOUT_SECONDS`), defaulting to a value sized for the _worst honest case_ (50 × 30 s nav + retries + fallback → ~79 min worst, ~15-20 min realistic slow) but below the pathological-rogue bound; keep `crawl_navigation_timeout_ms=30000` as the per-page bound exactly as the audit demands.
- Land it next to the other `CRAWL_*` knobs (`config.py:336-351`, `.env.production.example:353-397`) with a comment explaining the sizing math.

Required companion (do NOT ship the timeout alone — this is exactly the audit's "raise the bound alone trades stuck-job protection" warning): **cancellation + completion bookkeeping**:

- Wrap the `session.run()` window in a `CancelledError` handler that performs a best-effort terminal write (`finish_if_active(…, FAILED, error_message="Crawl timed out after N s, pages_stored=X")`, website to READY-when-partial, audit + `record_crawl_failed(reason="timeout")`), so a cancelled crawl lands in a terminal, re-crawlable state instead of stranding `active=True` (also resolves FIND-09's partial-progress write).
- Optionally raise the per-page-past-the-fallback logging so slow-but-working sites are visible (FIND-03 conscious; keep spotty).

Secondary (defense-in-depth, independent of the timeout): a **stale-crawl recovery** path (operator/admin reset endpoint or a worker-side periodic check that terminalizes `processing` jobs older than `job_timeout`), which also covers killed workers / crashes that never deliver a timeout at all. Effort S-M; ship with the issue or as a fast follow-up.

Minimal confidence test (matches audit "Test gap: `test_crawl_worker.py` lacks a cancel test"): add a test that runs `_run_crawl_job` with a fetcher that stalls past the worker timeout and asserts the job/website reach a terminal state with partial pages preserved.

## Alternatives considered

- **Raise the global `job_timeout` only**: rejected — applies the longer bound to email/knowledge tasks and leaves the stuck-state bug in place; directly contradicted by the audit's risk note.
- **Per-enqueue timeout**: not available in ARQ 0.28.0 (`enqueue_job` has only `_job_id`, `_defer`, etc.).
- **`cron`-based requeue of timed-out jobs**: adds ARQ cron complexity and re-runs from scratch (partial pages re-fetched); the terminal-write-on-cancel approach is simpler and preserves partial progress.
- **Embedding the partial pages on cancellation**: correct product behavior but larger scope (knowledge orchestration); note for follow-up, not required for the fix.

## Interaction with other findings

- **FIND-09 (P3)**: same root cause family; resolved by the same `CancelledError` terminal-write. The audit's fix order (§22 polish group) lists them together — "FIND-08/FIND-09 per-task timeout + cancel handler".
- **FIND-03 (P3)**: timed-out crawls are silent in metrics; the `CancelledError` path must emit `crawl_failed(reason=...)` + a structured log to close the observability gap.
- **FIND-02 (committed `3d78866`)**: use `finish_if_active` for the cancel-terminal write so a re-delivered duplicate cannot double-write side effects (single-terminator, same as the existing paths).
- **FIND-01 (committed `9123adb`) / `crawl_max_rss_mb`**: a memory-guard abort is recoverable/retryable; a timeout cancel today is not — after the fix both terminalize correctly.
- **FIND-11 (P3) `keep_result=3600` / FIND-12 (P3) `max_jobs=10`**: unaffected by the fix; a per-task `keep_result` could be set alongside for crawls only if desired (optional).

## Tests performed / evidence (read-only)

- `git log --all -S job_timeout -- backend/workers/app.py` → only `6ae84cf` (foundation) introduced it; no later commit changed it.
- `git log --oneline --all -- backend/workers/app.py` → app.py touched only by `3b60478` (logging), `9b64519` (FIND-06) since foundation; neither altered `job_timeout`.
- Read `arq/worker.py` (0.28.0): `Function` per-task `timeout` (line 52, 69, 94), global fallback (line 574), `asyncio.wait_for` cancel-on-timeout (line 599), non-retry of `asyncio.TimeoutError` (lines 610-634).
- Read `arq/connections.py`: no `_job_timeout` enqueue override exists.
- Read `crawl.py` `_run_crawl_job_impl`: only `except Exception` handlers; no `CancelledError`/`BaseException` catch anywhere in backend crawl/worker paths (`grep -rn "except.*CancelledError|except BaseException" backend` matches only `chat/rag_service.py` and `api/sse.py`).
- Read `crawl_job_repository.py`: `find_active_for_website` matches any active status; `finish_if_active` requires a fenced active row → stranded `processing` rows are perma-active.
- Read `crawl_service.py`, `admin.py`, `admin_service.py`, `tasks.py`: no reset/requeue/finalize/reaper; admin crawl surface is read-only.
- `tests/test_crawl_worker.py`: 32 tests, zero mentions of `CancelledError`/`job_timeout`/`wait_for` (the audit's "lacks a cancel test" is confirmed).
- Worst-case per-page budget recomputed from config (`crawl_navigation_timeout_ms=30000`, `crawl_http_max_attempts=2`, browser fallback exactly once).

## Files that would need modification IF implementation is approved

- `backend/workers/tasks.py` — register `crawl_website` as `Function(..., timeout=crawl_job_timeout_seconds)`.
- `backend/core/config.py` — add `crawl_job_timeout_seconds` (+ comment sizing math) in the crawl block.
- `.env.production.example` — document `CRAWL_JOB_TIMEOUT_SECONDS` default.
- `backend/workers/jobs/crawl.py` — `CancelledError` handler around `session.run()` doing a best-effort fenced terminal write (FIND-09) with partial-page metrics/logging.
- `tests/test_crawl_worker.py` — add a cancel/test-timeout test asserting terminal state + partial pages preserved.

## Residual risks

- Choose the crawl-timeout default against the real deployment baseline, not in isolation; the audit's 1 GiB plan and `crawl_max_concurrent=1` mean the ceiling's real victims are single-site rogues, so an upper bound with completion bookkeeping still needs to exist (the "stuck-job protection" the audit demands).
- The stale-recovery secondary path remains valuable even after the fix (worker kill, Mongo hiccup, `asyncio` cancel dropping a partially-written terminal update), so it should not be silently dropped.

## Verdict

**STILL VALID (P2)** — `job_timeout=600` governs `crawl_website` unchanged, cancelled runs strand the job/website pair in non-terminal, non-recoverable states (re-crawl blocked), and no mitigation exists at HEAD `3f49f3f`. The audit's "self-heals on re-crawl" assumption is disproven by the shipped code and should be corrected in any future audit revision.
