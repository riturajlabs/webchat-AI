# Worker Memory Guard — FIND-01 (INGEST-04) Fix — 2026-09-12

**Status:** FIXED (implementation) · 1 GiB Railway budget: **NOT RUNTIME-VALIDATED** · produced alongside `docs/WORKER_COMPREHENSIVE_PRODUCTION_AUDIT_2026-09-12.md`

## 1. Current problem

The historical INGEST-04 guard read the **Python process's _peak_ RSS**:

```python
resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
```

The crawler's JS fallback runs **headless Chromium**, which spawns child
subprocesses (browser, renderer, GPU, utility) inside the _same container
cgroup_. Because `RUSAGE_SELF` only counts the calling process, the guard was
blind to the worker's dominant memory consumer. Measured on the dev host (see
§8): while Chromium + helpers held **≈ 478 MiB**, the old guard measured
**≈ 65 MiB** and never tripped. A JavaScript-heavy or pathological site could
therefore OOM the 1 GiB Railway worker while the guard reported a healthy
Python RSS.

Worse, the old trigger only `break`ed the crawl loop silently: no dedicated
error type, no worker metric/log differentiation, and the ceiling was
documented as "worker RSS" while the real budget is the whole container.

## 2. Root cause

- **Wrong measurement target:** single-process `RUSAGE_SELF` vs. container
  reality (cgroup, with Chromium as children).
- **Wrong semantics:** "Python peak RSS" did not map to the deployment's 1 GiB
  _container_ budget (Python + shared Chromium + page cache + Redis).
- **Silent failure mode:** `break` left no trace distinguishable from a normal
  short crawl in metrics/logs.

## 3. Implementation

New module `backend/services/ingestion/crawl_memory.py`:

- `measure_memory()` → `MemoryMeasurement(source, current_bytes, limit_bytes,
python_rss_bytes, processes)`; **never raises** (contract: fail open).
- Source priority: **cgroup v2 → cgroup v1 → process tree** → else
  `source="unavailable"` with `current_bytes=None`.
- `memory.max == "max"` → `limit_bytes=None` (unbounded / unknown).
- `current_rss_mb()` → footprint in MiB, or `0` when unmeasurable (guard
  fails open then).

`backend/services/ingestion/crawler.py`:

- `_current_rss_mb()` now forwards to `current_rss_mb()` — the **whole worker
  footprint**, not Python peak. (`import resource` removed.)
- New recoverable `CrawlMemoryGuardError(current_mb, ceiling_mb, source,
limit_mb)` — raised **instead of** silently continuing.
- Loop-top trigger raises it, sets `memory_pressure_aborted`, records an
  error, and logs `memory_guard_triggered current_mb=… ceiling_mb=… source=…
limit_mb=… tenant=… website=… pages_stored=…`.
- `_over_memory_ceiling()`: ceiling `0` (default) disables the check; an
  unmeasurable footprint **fails open** with one warning per crawl.

Worker `backend/workers/jobs/crawl.py`:

- `record_crawl_failed(reason="memory_guard")` + structured warning log for
  guard aborts (distinct from generic `reason="exception"`).
- ARQ retry semantics are unchanged: the guard stays recoverable, retries up
  to `max_tries`, and the final attempt marks the job/website **failed**
  (existing handler).

`backend/core/config.py`:

- Comment for `crawl_max_rss_mb` rewritten (meaning = whole worker/container
  footprint; keep disabled until runtime-validated). **Default stays `0`.**

Exported via `backend.services.ingestion`.

## 4. cgroup detection strategy

1. Plain mount path: `/sys/fs/cgroup/memory.current` (v2) or
   `/sys/fs/cgroup/memory/memory.usage_in_bytes` (v1).
2. Else parse `/proc/self/cgroup`:
   - `0::/relative/path` → **v2** delegated path (k8s/cri, systemd scopes).
   - `<i>:memory:/relative/path` → **v1** memory controller path (docker).
   - Handles reset paths (e.g. `/init.scope`, `/docker/<id>`).
3. No Railway-specific hard-coding; portable across hosts.

## 5. process-tree fallback

Used only when no memory controller is readable. Sums `VmRSS` over the Python
process **and every descendant** via BFS:

- Parentage from `/proc/<pid>/stat` (ppid parsed after the last `)` of comm).
- RSS from `VmRSS:` in `/proc/<pid>/status`.
- **Race/cycle-safe:** a `visited` set prevents double counting under
  reparenting races; a missing/unreadable `stat`/`status` (process vanished)
  is skipped, never fatal.
- Exactly this descent is what makes Chromium (browser + renderer + GPU +
  helpers) visible when no cgroup is mounted.

## 6. Guard semantics

- Ceiling = **worker/container footprint**: cgroup current (v2/v1) when a
  memory controller is mounted, else summed Python + Chromium RSS.
- Exceeded → `CrawlMemoryGuardError` → crawl stops; `CrawlSession.run()`'s
  `finally` still closes the fetcher, so the per-job browser **context** is
  released; worker re-raises (ARQ retry) and the final attempt FAILs the job.
- Never `InvalidUrlError`; never silent continue; never kills processes (the
  worker or Chromium directly).
- Unmeasurable → fail open with a logged warning (a container without a
  readable cgroup or `/proc` never wedges the crawler).

## 7. Test coverage

`tests/test_crawl_memory.py` — 20 behaviour-oriented tests (fake cgroup/proc
trees via injected `cgroup_root`/`proc_root`/`self_pid`):

1. cgroup v2 current + limit parsing.
2. v2 `memory.max = max` → no limit.
3. v2 delegated path via `/proc/self/cgroup`.
4. cgroup v1 current + limit.
5. v1 controller path via `/proc/self/cgroup` (docker-style).
6. v2 unreadable → degrades to v1 (fail-open chain).
7. **v1 membership wins over the mount root** (strict-review P2 fix): node root
   60 GiB vs. process's `2:memory:/docker/deadbeef` 300 MiB → measures 300 MiB.
8. **v2 membership wins over the mount root**: deeper `0::/container/deadbeef`
   cgroup measured instead of the broader root scope (strict-review P2 fix).
9. malformed cgroup bytes → fall through to process tree.
10. missing cgroup files + empty proc → `unavailable`.
11. unreadable `memory.current` → `unavailable` (no crash).
12. process tree sums worker + Chromium children incl. descendants.
13. descendants beyond one level included.
14. reparenting/self-parent race → no double count, no hang.
15. process vanishing mid-scan → skipped, not fatal.
16. empty process tree → `unavailable`.
17. cgroup source preferred over process tree.
18. hostile roots → `unavailable`, never a raise.
19. MiB wrapper `current_rss_mb() == 0` when unavailable.
20. MiB wrapper reports correct cgroup footprint, rounded down to MiB.

`tests/test_crawler.py` (updated):

- `test_raises_when_memory_ceiling_exceeded` — raises `CrawlMemoryGuardError`
  (was silent break), carries `current_mb`/`ceiling_mb`/`source`,
  `memory_pressure_aborted=True`, **fetcher still closed**, error recorded.
- `test_memory_guard_fails_open_when_unmeasurable` — an unreadable footprint
  never wedges/interrupts the crawl.
- `test_memory_ceiling_disabled_by_default` — `crawl_max_rss_mb=0` unchanged.

`tests/test_crawl_worker.py` (added):

- memory-guard abort on try 1 re-raises so ARQ retries (job stays active,
  no `AUDIT_CRAWL_FAILED`, no website failure, fetcher closed).
- memory-guard on the final retry marks job/website **failed** with an
  error message naming `CrawlMemoryGuardError`.

## 8. Runtime measurements (dev host, 2026-09-12)

Host: Linux, cgroup v2 unified, `/proc/self/cgroup = 0::/init.scope`
(delegated path — exercised §4), `memory.max = max` (unbounded). The cgroup
`current` column reflects the **host/init.scope**, which contains more than
this worker, so it is **not** a valid Railway budget read-out; the
process-tree columns are the worker-relevant side-by-side.

| Scenario                       | source    | tree MiB | python MiB | procs | cgroup current MiB | notes                                   |
| ------------------------------ | --------- | -------: | ---------: | ----: | -----------------: | --------------------------------------- |
| idle (python only)             | cgroup_v2 |      ~66 |        ~66 |     1 |          ~950–1075 | scope noise                             |
| HTTP-first fetch (example.com) | cgroup_v2 |      ~73 |        ~73 |     1 |              ~1027 | +~2 MiB per fetch                       |
| HTTP-first fetch ×2            | cgroup_v2 |      ~73 |        ~73 |     1 |              ~1028 | client reused                           |
| Browser JS-shell fetch         | cgroup_v2 |  **545** |        ~69 |     7 |              ~1251 | Chromium ≈ **477** MiB                  |
| After `fetcher.close()`        | cgroup_v2 |     ~545 |        ~69 |     7 |              ~1242 | context closed; shared browser persists |
| +120 MiB Python alloc          | cgroup_v2 |  ~176 py |       ~176 |     1 |              ~1321 | footprint tracks growth                 |

Key empirical finding: **`BrowserPageFetcher.close()` closes the per-job
browser _context_ (`browser.py:216`); the shared Chromium instance persists
across jobs until worker shutdown (`close_browser()`)**. So once a job uses
JS, the standing worker footprint includes resident Chromium (~480 MiB here),
and the guard correctly sees it (the old `ru_maxrss` guard never could).

End-to-end guard trigger with the **real** reader (dev host, ceiling 200 MiB):

```
memory_guard_triggered current_mb=1075 ceiling_mb=200 source=cgroup_v2 limit_mb=unset ...
CrawlMemoryGuardError: current_mb=1075 ceiling_mb=200 source=cgroup_v2 limit_mb=None
fetcher closed: True | memory_pressure_aborted: True | pages stored: 0
```

## 9. 1 GiB budget analysis (before / after)

| Row (worker)                    | Before (old guard visibility) | After (full footprint)                  | 1 GiB verdict                        |
| ------------------------------- | ----------------------------- | --------------------------------------- | ------------------------------------ |
| idle                            | python ~1 MiB (peak)          | ~66 MiB                                 | SAFE (measured)                      |
| HTTP-first only crawl           | ~1 MiB                        | ~73 MiB                                 | SAFE (measured)                      |
| JS/browser crawl                | ~65–176 MiB (blind to Chrome) | ~545 MiB (Chrome ≈ 478)                 | SAFE WITH CONDITIONS                 |
| large page (5 MB cap, deep DOM) | not measured                  | not measured locally                    | NOT YET VALIDATED                    |
| embedding phase                 | n/a (separate phase)          | not run (needs provider creds)          | THEORETICAL                          |
| Railway 1 GiB container         | guard could not help          | Python 66–75 + resident Chrome ~480–650 | **NEEDS RAILWAY RUNTIME VALIDATION** |

Verdict on 1 GiB: a full-footprint guard gives real visibility; measured
worker components (~545 MiB on the dev host) fit with headroom, but the
figure is host-specific and **not** proven on Railway. **Do not enable a hard
ceiling blindly.**

## 10. Limitations

- cgroup `current` can include page-cache attribution and scope noise on
  shared hosts (see host readings above). Fine when the limit is
  per-container (Railway), single-tenant worker.
- The shared browser stays resident between jobs — the ceiling must budget a
  standing Chromium once any job used JS.
- `memory.max = max` provides no kernel limit; the guard then relies on the
  configured `crawl_max_rss_mb`.
- cgroupless/seccomp-restricted environments fall back to `/proc`; if
  neighbour-process `status` is unreadable there, the guard fails open.
- Sampling is at page granularity (loop top); a single fetch's spike is
  judged at the next page boundary, so the ceiling should be set with
  headroom.

## 11. Railway validation status

- **Not yet validated on Railway.** This report's measurements come from the
  dev host (§8).
- Suggested Railway validation: run one worker job against a JS-heavy site
  with `measure_memory` logging (`source`, `current_bytes`, `memory.max`);
  read `/proc/self/cgroup` on Railway to confirm the v2 path; if peak stays
  clearly under 1 GiB, set `crawl_max_rss_mb` (e.g. 900 MiB) with ~20%
  headroom. Until then `crawl_max_rss_mb` remains `0` (disabled).

## 12. Regression results (2026-09-12)

- Tests: full suite **green — 0 failed** (this run: 2369 passed, 12
  environment-dependent skipped), incl. 20 new memory + updated crawler +
  2 new worker tests.
- Coverage: **89.90%** (CI gate 85%).
- `mypy backend`: clean (strict).
- `ruff check backend tests`: clean; `ruff format --check`: clean.
- `git diff --check`: clean.
- Invariants preserved: HTTP-first crawler + targeted browser fallback,
  `crawl_max_concurrent=1`, `embedding_max_concurrent_batches=1`, 5 MB HTML /
  200 KB text caps, 30 s nav timeout, 20-redirect cap, SSRF per hop + redirect
  hops, embedding identity fencing, graceful shutdown, tenant isolation,
  ARQ retry semantics — none modified.

## 13. Recommended next steps

1. Run the §11 Railway validation; record `source`/`current`/`max` during an
   idle + JS-heavy crawl; then set `crawl_max_rss_mb` for the worker env.
2. (Future, out of scope) Idle-TTL / reaping for the shared browser
   (`close_browser()` only runs at shutdown) to reclaim ~480 MiB between jobs.
3. (Unaddressed P1) **FIND-02** — single-flight lock — remains for a
   separate workstream; do not conflate with this fix.

## Verdict

| Question                     | Answer                                                                                                                                                                                                                                                                                     |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| FIND-01 fixed?               | **YES** — whole-container footprint (cgroup v2 → v1 → process tree incl. Chromium), dedicated recoverable `CrawlMemoryGuardError`, worker integration, fail-open safety, 20 + updated + worker tests, live-validated on a cgroup v2 host and against `proc` fallback with a real Chromium. |
| 1 GiB runtime-validated?     | **NO** — dev-host measurements only; THEORETICAL / **NEEDS RAILWAY RUNTIME VALIDATION**.                                                                                                                                                                                                   |
| Enable hard ceiling in prod? | **NOT until Railway validation**; default `crawl_max_rss_mb = 0` (disabled) retained.                                                                                                                                                                                                      |
| Remaining risk               | unvalidated Railway numbers; resident shared Chromium (~480 MiB); page-granularity sampling.                                                                                                                                                                                               |
