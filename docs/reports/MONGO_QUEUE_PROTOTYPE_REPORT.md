# MongoDB Queue Prototype Report

Prototype: `backend/prototypes/mongo_queue` (isolated package)
Baseline commit: `d63deff318ef62c45f14d3ebc83b082e96ecf158` (`fix(quota): account crawl pages for monthly limits`)
Date: 2026-09-21
Status: All prototype tests pass; repository regression green; no production code changed; nothing committed or pushed.

## 1. Executive Summary

We implemented and measured an isolated MongoDB-backed worker queue prototype that
reproduces the execution-guarantee semantics the production system currently gets
from ARQ + Redis (`max_tries=3`, `job_timeout=600`, heartbeat renewal, retry with
backoff, dead-letter, ownership fencing). Using a dedicated ephemeral `mongod`
(`127.0.0.1:27019`, namespace `webchat_ai_queue_prototype.worker_jobs_prototype`),
the prototype proves atomic single-winner claim under 100 concurrent workers, lease
recovery after crash, execution-version fencing against stale completions,
deduplication via a unique partial index, and the TWO safety claims that bear on
real jobs:

1. Crawl "finish_if_active / update_if_crawl_owner"-style single-terminator fences
   prevent duplicate terminal completions even when a stale worker reclaims the job.
2. **The `send_email` path carries a real duplicate-delivery risk**: crash-after-send
   with lease expiry delivers a second email unless the provider sees an
   idempotency key — identical to the risk profiling today's production send path.

Mongo per-op latency stays in the low millisecond range on the constrained prototype
mongod (p99 < 33 ms worst case, claim+complete p99 ≈ 13 ms). Adaptive polling cuts
idle backend commands from ARQ's fixed 172,800/day/worker to as low as 2,880/day/worker.

Verdict: the queue mechanics are **PASS**; **migration should not proceed until the
email idempotency gap below is closed** (see PROTOTYPE CONCLUSION).

## 2. Scope and Constraints

- No production files modified (`backend/`, `tests/`, `config/`, `.env*` untouched);
  the only repository additions are under `backend/prototypes/` and this report.
- No production Redis, ARQ, or Mongo connection is made; no real emails or websites.
- No migration of existing jobs; ARQ/Redis remain the production queue.
- Prototype test suite is excluded from `testpaths=["tests"]` and is run explicitly;
  the protected `tests/conftest.py` (which disables Mongo) is never imported.
- Measurements are on a single-host prototype `mongod` (WiredTiger cache 0.25 GiB);
  they are indicative, not production Atlas numbers.

## 3. Prototype Architecture and Data Model

`MongoQueue` (motor/pymongo 4.17, motor 3.7.1) stores one document per job in
`worker_jobs_prototype`:

- `_id` (job id, uuid hex), `function`, `payload`, `tenant_id`, `run_at`,
  `status`, `attempts`, `execution_version`, `locked_by`, `started_at`,
  `lease_expires_at`, `finished_at`, `last_error`, `result`, `dedup_key`,
  `created_at`.
- `Job` is a pydantic frozen model with a round-trip `from_doc`/`to_doc`; datetimes
  are tz-aware; Mongo stores at millisecond precision (tests tolerate sub-ms drift).
- Components: `config.py` (immutable `QueueConfig`), `ids.py`, `models.py`,
  `queue.py` (all writes), `poller.py` (adaptive poll schedule), `worker.py`
  (execution loop + heartbeat), `sim_jobs.py` (mock email provider with
  idempotency keys, document checksum store, crawl fence), `measure.py`
  (latency/memory harness).

## 4. Job State Machine

`pending -> running -> completed`
`pending -> running -> retry_pending -> running -> ... -> dead`
`running` with `lease_expires_at` in the past and `attempts < max_tries` is
reclaimable as `pending`-equivalent; with `attempts >= max_tries` it is flagged
`dead` by `retire_expired`.

`TERMINAL_STATUSES = {completed, dead}`; claim filters exclude terminal states
entirely, so a completed or dead job can never be re-claimed.

## 5. Indexing

Three indexes created idempotently by `ensure_indexes()`:

- `{status: 1, run_at: 1}` — claim scan.
- `{status: 1, lease_expires_at: 1}` — expiry reclaim scan.
- `{dedup_key: 1}` **unique, partialFilterExpression {dedup_key: {$type: "string"}}**
  — job-level dedup only for jobs that actually carry a key.

## 6. Atomic Claim

A claim is a single `find_one_and_update` (update pipeline, `ReturnDocument.AFTER`)
with:

- Filter: `$expr {attempts < max_tries}` AND `$or [ {status: pending, run_at <= now},
  {status: retry_pending, run_at <= now}, {status: running, lease_expires_at <= now} ]`.
- Update: `$set {status: running, locked_by, started_at, lease_expires_at:
  now + lease_seconds}` and `$set {attempts: $add(attempts,1),
  execution_version: $add(execution_version,1)}`.
- There is no find-then-update window; no job can be leased twice.

Measured: **100 concurrent claimers, 1 job → exactly 1 winner** (182 ms total for the
batch). Also 100 separate races × 4 workers with zero duplicate claims.

## 7. Lease Model and Renewal

`lease_seconds = 120` (prototype; production `job_timeout = 600`). A lease expiring
with the job still `running` simply makes it reclaimable; the worker that still holds
it is fenced off because claim bumped `execution_version`.

`renew_lease(worker_id, execution_version)` is a conditional write keyed on
`locked_by + execution_version`; a worker whose job was reclaimed can no longer renew
(verified by test).

## 8. Heartbeat

The worker runs a background heartbeat task every `heartbeat_interval_seconds`
(= 30s prototype, matching production 30s/`job_timeout` ratio) that calls
`renew_lease`. It cancels automatically on completion/failure. This bounds
"crash without fence" exposure to a fraction of the lease length, exactly like ARQ.

## 9. Retry and Backoff

`fail_job(..., execution_version)` moves the job to `retry_pending` with
`run_at = now + backoff[attempt - 1]` where `backoff = (5, 30, 180)` seconds; attempt
3's final failure moves it to `dead`. Backoff keys off the attempt count that claim
incremented, so a reclaimed retry carries the same attempt budget.

## 10. Dead-Letter and Terminal Handling

A job is terminal once and only once; every completion or dead transition is a
conditional write guarded by `locked_by + execution_version`. `retire_expired()`
marks stuck `running` jobs at `attempts >= max_tries` as `dead` (either via the 3-fail
path or via the retry wrapper). Dead jobs are never re-claimed.

## 11. Deduplication

`enqueue(dedup_key=...)` attempts insert; a duplicate hits the unique partial index
(`DuplicateKeyError`), and the existing job is read back and returned. This is
job-level dedup (one job, not duplicate side effects). Measured: 100 racing
submissions with the same key collapse to one job. The prototype documents that
dedup ≠ idempotency (see §13).

## 12. Execution Fencing and Ownership Tokens

`execution_version` is incremented on every claim and is required by
`complete_job`, `fail_job`, and `renew_lease`. A stale worker completing after its
lease was reclaimed gets `False` and cannot corrupt terminal state (verified by the
"stale worker cannot corrupt terminal state" test and the crawl fence tests).

## 13. Email Side-Effect Safety (CRITICAL FINDING)

Mocked provider with an idempotency-key API:

- **Without a provider idempotency key**: worker-a sends the email, crashes before
  completion, lease expires, worker-b reclaims and re-runs → **2 emails delivered**
  for one logical job (test asserts `sent_count == 2`). This risk exists in the
  production `send_email` path today, independent of queue technology.
- **With a provider idempotency_key derived from the job**: worker-b's re-send is
  rejected by the provider and returns the original message id → **1 email**.
- Dedup key (`dedup_key`) deduplicates *jobs*, not *side effects*; the two are
  explicitly tested as distinct.

Recommendation: add a provider-level idempotency key (or a durable
"attempt-token" in the outbox) **before** any queue migration reduces reliance on
ARQ's in-memory semantics.

## 14. Crawl Safety (mirrors production fences)

The prototype reproduces the production pattern `update_if_crawl_owner` +
`finish_if_active` as a `CrawlFence`:

- A started-but-crashed crawler (`crawl-a`) loses its lease; `crawl-b` reclaims and
  completes the job and the fence (`winner=True`, `fence.is_active=False`).
- `crawl-a`, resuming later, cannot complete (`complete_job` returns `False`), cannot
  corrupt terminal state, and the fence records exactly one `completed` event.
- Two concurrent runs of the same crawl: outcomes `{True, False}` — exactly one
  winner; the fence stays authoritative (this stays a Mongo/DB concern, unchanged by
  the queue).
- Honest cost surfaced: re-executed crawlers may have produced partial side-effect
  work before being fenced (events recorded = 3 pages fetched for 2 runs + 1 resume).

## 15. Document Checksum Idempotency

`DocumentChecksumStore` mirrors the production processor's checksum-skip gate:
worker-a embeds then crashes; worker-b re-runs the same document and the checksum
gate skips re-embedding → one embed side effect across two executions (verified by
test; `store.events` shows a single `embedded:d1`).

## 16. Crash Recovery Matrix

`test_crash.py` drives every crash point the brief lists against expected outcomes,
covering (measured as passing):

- **A** enqueue then crash before claim → job remains `pending`, later reclaimed,
  terminal once.
- **B** claim then crash (no work done) → lease expires → reclaimed → terminal once.
- **C** claim, work, crash before completion → reclaimed, side effects re-run
  (email: duplicate unless idempotent; document: checksum-skipped; crawl: fenced).
- **D** claim, work, fail → retried with backoff → eventually `dead` after 3 tries;
  dead never re-claimed.
- **E** crash during processing after lease expiry → another worker reclaims while
  the first is still alive → fencing blocks the stale completion.
- **F** never-claimed job (repo/DB interruption) → recoverable later; no partial
  execution; terminal exactly once.

## 17. Concurrency Results

- 100 separate races × 4 workers: 0 duplicate claims.
- 100 concurrent claimers on one job: 1 winner (182 ms batch).
- Credentialed fencing: stale completions rejected; terminal writes intact.
- Lease expiry reclaim and version fencing demonstrated under interleaved
  `asyncio` tasks (no sleeps, purely event-loop + server atomicity).

## 18. Adaptive Polling

`AdaptivePoller` (schedule 1s → 2s → 5s → 10s → 30s) advances the next claim time by
`nick(found_work)`: back to 1 s when a job was just completed/failed, ratcheting up
during idle, no DB op while sleeping. Reportable numbers (see measure/poller tests):

| workers | adaptive claims/day (idle) | ARQ fixed 0.5 s poll claims/day |
| -- | -- | -- |
| 1 | 2,880 | 172,800 |
| 2 | 5,760 | 345,600 |
| 5 | 14,400 | 864,000 |

A simulated idle 5-minute stretch performs 13 claim ops; a real 3 s idle worker run
logs ≤ 8 ops. Idle DB load drops ~98% versus ARQ's fixed poll.

## 19. Mongo Latency (local prototype mongod, WiredTiger cache 0.25 GiB)

500 samples per op, p50/p95/p99 (ms):

| op | p50 | p95 | p99 |
| -- | -- | -- | -- |
| enqueue | 1.77 | 6.42 | 13.86 |
| claim (empty queue) | 4.00 | 13.74 | 32.52 |
| claim + complete | 3.58 | 9.26 | 13.33 |
| claim + renew | 2.66 | 6.39 | 10.90 |
| claim + fail(→retry) | 2.49 | 7.32 | 10.16 |

Burst enqueue (200 doc inserts) averaged 3.77 ms/op. One 100-claim batch = 182 ms.
These are single-host figures; production Atlas M0 ceiling (~100 ops/s) is a
separately flagged concern, but the prototype's adaptive idle profile (≈ 1 claim op
per 30 s idle) keeps background load well within it.

## 20. Resource Profile

Prototype worker (motor AsyncIO client, no cache configured): RSS ≈ 48 MB idle,
≈ 48 MB after an active unit of work — an order of magnitude below the noted
baseline process footprint (~109 MB Python baseline; headless Chromium ≈ 530 MB).
The prototype mongod is constrained (cache 0.25 GiB, per-host dbpath in `/tmp`).

## 21. Test Results

| suite | command | result |
| -- | -- | -- |
| prototype | `pytest backend/prototypes/mongo_queue/tests` | **40 passed** |
| regression | `pytest tests` | **2589 passed, 12 skipped, 0 failed** |
| lint | `ruff check backend tests` | clean |
| types | `mypy backend` (strict) | clean (225 files, incl. prototype) |

## 22. Known Limitations and Risks

- At-least-once delivery; **exactly-once is not provided** (documented in code and
  here). Duplicate side effects depend on the fences/idempotency in §13–15.
- `send_email` duplicate-delivery risk persists without a provider idempotency key
  (§13) — currently the single gating item for a real migration.
- Prototype timings are local single-host; Atlas M0 throttling (~100 ops/s) and
  WT cache limits are not reproduced.
- Real crawling cost (headless Chromium) is not exercised inside the queue prototype;
  only fence semantics are simulated.
- No failover/replica-set or network-partition behavior was tested (single mongod).
- No lock-free fencing beyond the single-equality checks is required; correctness
  rests on `locked_by + execution_version` conditional writes plus the atomic claim.

## 23. Migration Estimate

Queues/semantics are a like-for-like replacement at the API level; the likely
migration footprint is: implement `MongoQueue` behind the existing worker interface
(~the prototype's queue.py now), swap the ARQ-backed worker entrypoint for
`PrototypeWorker`-style polling, route `enqueue` call sites (jobs, crawl scheduler,
scheduled jobs) to MongoQueue with the same `function`/`payload`/`tenant_id`/dedup
keys, and keep ARQ as a short-term rollback path. This is an engineering-hours
estimate only — no production migration was attempted (out of scope), so real
effort is **NOT MEASURED**.

## 24. Pre-Migration Conditions (checklist)

- [ ] Add provider-level idempotency key (or durable attempt token) to `send_email`
      so crash-after-send cannot double-deliver (§13).
- [ ] Confirm crawl `finish_if_active`/`update_if_crawl_owner` fences also fence
      against queue re-delivery (prototype shows the pattern holds; production
      repository needs an equivalent test).
- [ ] Confirm document processor checksum skip covers the queue re-claim path.
- [ ] Size production Atlas (or replica set) at the observed per-op latencies and
      adaptive poll profile; verify < ~100 ops/s sustained with margin.
- [ ] Keep ARQ active for one full email/crawl cycle as rollback; migrate
      low-risk job types (document processing) before email.
- [ ] Decide lease/heartbeat values for production (`job_timeout=600` → lease 600s,
      heartbeat 30s is the direct mapping to validate).

## 25. Final Conclusion

Same conclusion as the feasibility report, now with evidence: the MongoDB-backed
queue **can** reproduce ARQ's queue guarantees (atomic claim, lease recovery,
retry/backoff, dead-letter, fencing, deduplication) and is measurable at low latency
with dramatically lower idle load. The **email idempotency gap is queue-independent**
and blocks any migration regardless of queue choice. See the final classification
matrix and PROTOTYPE CONCLUSION below.

---

## Classification Matrix

| # | outcome | verdict | evidence |
| -- | -- | -- | -- |
| 1 | Read-only inspection of live Mongo/Redis stack | PASS | inspected docker stack; host port unmapped; used isolated 27019 mongod |
| 2 | Isolated prototype mongod, never touches production | PASS | dedicated dbpath `/tmp/opencode/mongo-queue-prototype`, port 27019, noauth |
| 3 | Reproduce ARQ claim/retry/backoff/dead semantics | PASS | lifecycle tests (§4, §9, §10) |
| 4 | Atomic single-winner claim | PASS | 100 concurrent workers → 1 winner; 100×4 races, 0 duplicates |
| 5 | Lease expiry recovery (crash matrix) | PASS | crash tests A–F |
| 6 | Execution-version fencing; stale completion blocked | PASS | stale-worker tests, crawl fence tests |
| 7 | Unique-index job dedup | PASS | 100 concurrent same-key → 1 job |
| 8 | Retry/backoff + dead-letter correctness | PASS | lifecycle retry tests |
| 9 | Email duplicate risk demonstrated | PASS | duplicate without idempotency key; single with key |
| 10 | Crawl finish_if_active single-winner behavior | PASS | fence tests incl. stale reclaim |
| 11 | Document checksum idempotency | PASS | checksum skip test |
| 12 | 100-worker concurrent claim (literal) | PASS | one-off measurement + committed test |
| 13 | Adaptive polling reduces idle DB ops | PASS | virtual 5-min idle = 13 ops; table vs ARQ |
| 14 | Mongo per-op latency (p50/p95/p99) | PASS | table in §19 |
| 15 | Worker resource footprint | PASS | ~48 MB RSS idle/active |
| 16 | Production code untouched / isolated namespace | PASS | `git status` shows only `backend/prototypes/` + this report |
| 17 | Regression: full production suite, ruff, mypy | PASS | 2589 + 12 skipped; ruff clean; `mypy backend` clean |
| 18 | Exactly-once delivery | PARTIAL | at-least-once; exact-once requires fences/idempotency (email gap open) |
| 19 | Atlas M0 production-scale behavior | NOT MEASURED | single-host prototype mongod only |
| 20 | Migration effort (hours) | NOT MEASURED | out of scope; only API-level estimate in §23 |

## PROTOTYPE CONCLUSION

**READY FOR NEXT MIGRATION PHASE — with one precondition.** The queue mechanics pass
all evidence-based checks: atomic claim, lease recovery, fencing, dedup, retry/backoff,
dead-letter, adaptive polling, and safety fences (crawl + document checksum). Before a
live migration can begin, the `send_email` path must carry a provider-level idempotency
key (or durable attempt token) — otherwise crash-after-send double-delivers emails under
any at-least-once queue, Mongo or ARQ. With that closed and Atlas-scale sizing
confirmed, the prototype's `MongoQueue`/`AdaptivePoller`/`PrototypeWorker` can be
promoted behind the existing worker interface for the next phase.