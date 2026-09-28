# Phase 18A — Producer Routing, Mongo Worker Lifecycle, and Backend-Aware Health

- **Date:** 2026-09-28
- **Branch / HEAD:** `main` @ `4852612da02dd79c4bde494dc6016ac5e8e01488` (unchanged — nothing committed, nothing pushed, no deploy)
- **Scope:** make the queue backend a _routing_ decision end to end. **No cutover, no default change, no production traffic, no `MONGO_QUEUE_ENABLED` flip.**
- **Predecessors:** Phase 17B.1 blocker remediation (`docs/reports/MONGO_QUEUE_PHASE17B1_BLOCKER_REMEDIATION.md`), Phase 17C/17C.1 hardening, FIND-03 remediation.

Every measurement is labelled **[MEASURED]**, **[VERIFIED]**, **[CALCULATED]**,
**[INFERRED]** or **[NOT MEASURED]**.

---

## 1. Verdict

> **PHASE 18A PASS — ROUTING COMPLETE, STILL NOT CUT OVER**
>
> Scoped strictly to routing, worker lifecycle and health. This authorizes **no**
> deployment and **no** cutover (§24).

An independent implementation review of this diff returned
**PHASE 18A REVIEW PARTIAL — FIXES REQUIRED BEFORE COMMIT** — one CI blocker
(`ruff format --check .` failing on this report's own code blocks) plus factual
corrections to the duplicate, cache-close, Redis and test-count wording. The
implementation itself was accepted; the documentation corrections and the format fix
are recorded in §27.

**PASS.** 42 Phase 18A tests (40 in new test files, 2 added to existing files) and the
full backend suite are green (§21), and the five load-bearing mechanisms of this phase
are each proven falsifiable by experiment (§22) — reverting any of them makes a named test
fail, so the suite measures the mechanism and not the absence of a symptom.

What Phase 18A establishes:

- **Every producer goes through one seam.** `enqueue_email`, `enqueue_crawl_website`,
  `enqueue_process_document`, `enqueue_process_document_deferred` and
  `enqueue_process_website_documents` no longer call `ArqRedis` directly; they call
  `backend.queue.runtime.enqueue_worker_job`, which binds a process-scoped
  `WorkerQueue` from the configured backend. One place decides ARQ vs Mongo.
- **The ARQ wire format is wire-compatible for all currently reachable producer
  inputs.** The payload is a dict at the seam and `backend.queue.registry.args_from_payload`
  maps it back to the positional args the previous direct calls produced (§6), and the
  `_job_id` keyword is reproduced exactly. Jobs already sitting in production Redis keep
  working, because the handler signatures accept the old positional form and the new one
  identically. The one deliberate divergence — `_defer_by` for a non-positive delay — is
  unreachable today and documented in §6.
- **Mongo mode fails loud, never silent.** An opt-in Mongo deployment that cannot resolve
  a job's authoritative tenant raises `UnresolvedTenantError` at the producer boundary
  instead of enqueueing unattributable work; an unknown `QUEUE_BACKEND` refuses to start a
  consumer; a mixed-case value can no longer drift into ARQ.
- **Crash recovery is scheduled, not hoped for.** The Mongo worker sweeps expired leases
  once at boot and then on a bounded cadence, so a dead worker never strands work until
  another deploy (§10).
- **The container healthcheck follows the backend.** `python -m backend.workers.health`
  pings Redis under ARQ and the queue store under Mongo, so cutting over the queue does
  not leave behind a probe that can never pass (§14).

What this phase does **not** establish: cutover readiness. No shadow run, no soak, no
load test, no production-shaped exercise of the Mongo consumer was performed (§23).

---

## 2. Environment

| Item                                     | Value                                                                  | Label                |
| ---------------------------------------- | ---------------------------------------------------------------------- | -------------------- |
| HEAD before / after                      | `4852612da02dd79c4bde494dc6016ac5e8e01488`                             | VERIFIED (identical) |
| Branch                                   | `main`                                                                 | VERIFIED             |
| Working tree                             | 25 changed paths (18 modified, 7 new), uncommitted                     | VERIFIED             |
| Python                                   | 3.13.14                                                                | MEASURED             |
| MongoDB                                  | isolated prototype `mongod` on `127.0.0.1:27019` (real, not simulated) | MEASURED             |
| Redis                                    | **not running** locally; every producer/entrypoint test uses a double  | MEASURED             |
| Full phase suite                         | `3448 passed, 14 skipped, 3 warnings` in 457.50 s, coverage `92.74%`   | MEASURED             |
| `scripts/check-backend.sh`               | `2811 passed, 12 skipped` in 237.27 s, exit 0                          | MEASURED             |
| `mypy backend`                           | no issues in 274 source files                                          | MEASURED             |
| `ruff check .` / `ruff format --check .` | pass / every file formatted, **after** the remediation in §27          | MEASURED             |

No `.env.production` was read. No provider, embedding or crawl network call was made. The
only Docker interaction was read-only (`docker ps`, `docker logs`, `docker inspect`) on the
developer's local stack, to check whether the running worker image was healthy (§19).

---

## 3. The gap this phase closes

Phase 17B built the Mongo adapter, the loop and the child-enqueue split-brain guard, and
left exactly one seam open. The producers still reached for ARQ:

```
crawl service ─► enqueue_crawl_website ─► _arq_redis().enqueue_job(...) ─► Redis
```

Consequences that followed from that, all of which are now closed:

| Consequence                                                                                     | Closed by                    | §   |
| ----------------------------------------------------------------------------------------------- | ---------------------------- | --- |
| Setting `QUEUE_BACKEND=mongo` did nothing for API-process enqueues                              | `runtime.enqueue_worker_job` | 5   |
| Mongo rows had no tenant attribution, because ARQ has nowhere to put one                        | producer tenant resolution   | 7   |
| The container healthcheck was hard-wired to Redis, so a Mongo deployment could never be healthy | `backend.workers.health`     | 14  |
| `python -m backend.workers` could only ever start ARQ                                           | backend-aware entrypoint     | 13  |
| A worker killed mid-job left a lease stranded until the next deploy                             | boot + periodic sweep        | 10  |
| The Mongo worker had no per-process services to hand its jobs                                   | `app_context`                | 16  |
| `QUEUE_BACKEND=MONGO` validated as an opt-in and then built ARQ                                 | normalization                | 17  |

---

## 4. Design rules held throughout

- **ARQ is the default and stays the default.** `QUEUE_BACKEND` is unset in the local
  worker container [VERIFIED] and the ARQ path is the one the deployment uses.
- **Mongo stays opt-in behind two flags.** `Settings` already requires
  `MONGO_QUEUE_ENABLED=true` for a Mongo opt-in; this phase adds no third way in.
- **No split of the job bodies.** The same production coroutines
  (`crawl_website`, `send_email`, `process_document`, `process_website_documents`) run on
  both backends. Phase 18A changed _where_ a job is submitted, never _what_ runs.
- **No domain-row lookup under ARQ.** The tenant resolvers run only when
  `mongo_backend_selected()` is true, so production's enqueue path adds zero queries
  [VERIFIED in `backend/queue/runtime.py::producer_tenant`].
- **No service-layer or dependency changes.** `backend/api/deps.py`, the service producer
  signatures, and the dependency set are untouched (git diff shows no such file).

---

## 5. The producer seam: `backend/queue/runtime.py`

New module, 42 statements, **100% covered** [MEASURED].

| Symbol                     | Role                                                                                                                |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `get_worker_queue()`       | Returns the process `WorkerQueue`, building it on first use and caching it in a module global.                      |
| `reset_worker_queue()`     | Drops the cache without closing (tests, in-process restarts).                                                       |
| `close_worker_queue()`     | Best-effort close; never raises; unconditionally clears the cache.                                                  |
| `enqueue_worker_job(...)`  | The single submit path; converts `DuplicateJobError` into `None`.                                                   |
| `producer_tenant(resolve)` | `""` under ARQ (no lookup); under Mongo, calls the resolver, strips, and raises `UnresolvedTenantError` when empty. |
| `mongo_backend_selected()` | Normalized backend check, matching `Settings`' own validation.                                                      |

Two properties are deliberate and tested:

- **Fail-soft shutdown, fail-hard submit.** A queue that cannot be closed must not stop
  the API process from finishing its other cleanup
  (`test_closing_a_broken_worker_queue_never_raises`), but a job whose tenant cannot be
  attributed is refused (§7).
- **The cache swap is unconditional and no stronger guarantee is claimed.** Swapping the
  global to `None` protects _future_ producers: one that arrives after the swap rebuilds
  a fresh adapter instead of enqueueing onto a closed one. A producer that had already
  taken the adapter reference _before_ the swap can still race the shutdown and enqueue
  onto a closing ARQ pool. In practice Uvicorn drains in-flight requests before the
  lifespan shutdown runs, so that window is empty on the API path; it is still a real race,
  and Phase 18A accepts it rather than adding a lock around every enqueue. Reviewed and
  accepted for Phase 18A [VERIFIED by reading `close_worker_queue`; see §23.8].

`backend/queue/__init__.py` was deliberately **not** modified: the ARQ path must not drag
in the Mongo store, which `test_arq_backend_never_imports_the_mongo_store` enforces
[MEASURED, passing].

---

## 6. Producer rewiring, and why the ARQ envelope did not change

Each producer now submits a dict payload; `args_from_payload` converts it back to the
exact positional args the old direct call produced. Measured ARQ call shapes, from the
new `test_producer_routing.py` and the pre-existing `test_envelope_parity.py`:

| Producer                                               | Before                                                         | After (positional args and keywords)                          |
| ------------------------------------------------------ | -------------------------------------------------------------- | ------------------------------------------------------------- |
| `enqueue_crawl_website(id)`                            | `enqueue_job("crawl_website", id, _job_id=f"crawl:{id}")`      | same                                                          |
| `enqueue_email(msg)`                                   | `enqueue_job("send_email", msg.to_payload())`                  | same                                                          |
| `enqueue_process_document(id, run_id)`                 | `enqueue_job("process_document", id, run_id)`                  | same                                                          |
| `enqueue_process_document_deferred(id, run_id, delay)` | `enqueue_job("process_document", id, run_id, _defer_by=delay)` | same for `delay > 0`; `_defer_by` is omitted for `delay <= 0` |
| `enqueue_process_website_documents(id)`                | `enqueue_job("process_website_documents", id)`                 | same                                                          |

[VERIFIED] for all five: `args_from_payload` (`backend/queue/registry.py:101`) handles
`send_email` as `(dict(payload),)` and everything else as
`tuple(payload.get(name) for name in JOB_ARGUMENTS[function])`, and the dedup/`_defer_by`
keywords are rebuilt by `ArqQueueAdapter.enqueue` itself.

**Exact scope of the compatibility claim — "wire-compatible for all currently reachable
producer inputs", not "byte-for-byte unchanged".** Positional arguments match, `_job_id`
behaviour matches (including job-scoped `crawl:<id>`, so FIND-02's single-flight window is
preserved), and deferred behaviour matches for positive delays. The one divergence:
`ArqQueueAdapter.enqueue` adds `_defer_by` only when `defer_by > 0`, so a **non-positive**
delay is submitted with the keyword omitted rather than explicitly sent as `0`. ARQ treats
both forms as "run immediately", so the behaviour is identical; the emitted keyword set
is not. The only production caller of the deferred path is the knowledge processor's
backoff schedule (`knowledge_retry_base_delay_seconds * factor**attempt`, i.e. 5s/30s/180s
at the defaults — all positive), so this edge is **not currently reachable**.

**Jobs already in production Redis keep running.** The handler signatures
(`crawl_website(ctx, crawl_job_id)`, `process_document(ctx, document_id, run_id=None)`,
`send_email(ctx, payload)`, `process_website_documents(ctx, website_id)`) accept the old
positional form unchanged [VERIFIED by reading the signatures].

The `_arq_redis()` helpers remain in all three modules, marked as legacy and kept
importable for tests and ops tooling. No producer calls them any more
[VERIFIED — `rg` finds no call sites]. The split-brain guard's docstring was corrected to
stop claiming the API-process path still uses them.

---

## 7. Tenant attribution (the reason Mongo needs a resolver)

Mongo rows are tenant-scoped, so a submission with no tenant is unowned work that nobody
can list, cancel or account for. The adapter rejects it; the producers therefore supply it
from the authoritative domain row:

| Producer | Authoritative source                                              | Resolver                   |
| -------- | ----------------------------------------------------------------- | -------------------------- |
| crawl    | the `CrawlJob` row the service just created                       | `_resolve_crawl_tenant`    |
| document | the `Document` row                                                | `_resolve_document_tenant` |
| website  | the `Website` row                                                 | `_resolve_website_tenant`  |
| email    | `message.tenant_id`, set by `message.for_tenant` at the call site | none needed                |

`UnresolvedTenantError` (new, `backend/queue/errors.py`) is raised when the row is missing
or carries no tenant. It propagates to the caller — the API request that triggered the
crawl fails loudly instead of enqueueing an orphan. It is **never** swallowed into an ARQ
fallback and never fabricates a scope [VERIFIED by reading `producer_tenant`].

Email is deliberately different: its tenant is known at submission time from the
authenticated request, and an email with an empty tenant is rejected by
`MongoQueueAdapter` itself with `MissingTenantError` [MEASURED — asserted in
`test_producer_routing.py`].

---

## 8. Duplicate suppression: invisible to producers on both backends

The two backends signal a duplicate **differently**, and the seam does not flatten that
difference. Stated precisely, because the earlier version of this section got it wrong:

- **Mongo:** the store's atomic upsert hits the unique `dedup_key` index;
  `MongoQueue.store.enqueue` catches `DuplicateKeyError`, re-reads the canonical row and
  **returns the existing job id** (`backend/queue/mongo/store.py:174-181`).
  `MongoQueueAdapter.enqueue` documents this as "signals the _existing_ id rather than
  raising". No `DuplicateJobError` is raised, and `enqueue_worker_job` returns that id
  rather than `None`.
- **ARQ:** ARQ itself declines the enqueue and returns `None`; the adapter converts that
  into `DuplicateJobError`, which `enqueue_worker_job` catches and turns into `None` — the
  same `None` the producers saw before Phase 18A.

**Externally observed producer behaviour is unchanged either way.** All five producers
keep their `-> None` signatures and discard the return value, so a duplicate submission is
invisible to callers: no exception, no signature change, no extra work executed. What
changed is only the internal return value of the seam under Mongo (existing id instead of
`None`), which no production caller reads. `test_a_new_job_id_still_enqueues_after_a_duplicate`
asserts a _different_ job id still enqueues, so the dedup key remains job-scoped per
FIND-02; `test_arq_duplicate_suppression_is_still_a_silent_no_op` pins the ARQ `None`
path [MEASURED].

---

## 9. The Mongo worker process: `backend/workers/mongo.py`

New module, 84 statements, 89% covered [MEASURED]; the uncovered lines are the
`if __name__` guard, the non-POSIX signal-handler fallback, and one `SystemExit` message
branch (see §23).

It is the cousin of `backend.workers.app`: same job coroutines, same logging
configuration, same `_log_resource_caps`, but hosted on `MongoWorkerLoop`.

Two fail-loud gates before any work is consumed
(`test_mongo_worker_refuses_to_run_under_the_arq_backend`,
`test_mongo_worker_refuses_a_non_mongo_adapter`):

1. `QUEUE_BACKEND` must normalize to `mongo` — otherwise exit with an explicit message.
2. `get_queue()` must actually return a `MongoQueueAdapter` — a factory that produced
   something else is a configuration bug, and this process must not consume it.

Then: `ensure_indexes()` **before** any claim (a brand-new queue database has no
claim/scan index and no worker may race one), the boot sweep, the two concurrent loops,
and a resilient shutdown.

Process-level services are built once, not per job:

```python
{
    "app_name": settings.app_name,
    "embedding_client": build_ingestion_embedding_client(),
    "embedding_provider_health": ProviderHealthStore(get_redis()),
}
```

This preserves the Phase 9 / ADR-009 rule that a process never switches embedding spaces
mid-corpus, and keeps embedding-provider health separate from generation health.

---

## 10. Crash recovery: boot sweep plus a bounded cadence

| Guarantee                                                            | Mechanism                                     | Test                                                                                                          |
| -------------------------------------------------------------------- | --------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| A worker killed on its final attempt does not strand work            | `_retire_initial` runs before the first claim | `test_boot_recovers_a_crashed_job_before_serving_and_shuts_down` (asserts the real row reached `STATUS_DEAD`) |
| The sweep keeps running _while serving_                              | `_retire_loop` gathered with the poll loop    | `test_the_recovery_sweep_keeps_running_after_boot`                                                            |
| A store hiccup degrades the cadence, never crashes the worker        | `except Exception` → `logger.warning`         | `test_retire_loop_survives_a_failing_sweep`, `test_retire_initial_survives_a_failing_sweep`                   |
| A pending or terminal row is never retired                           | adapter-side status/attempt filters           | `test_retire_expired_ignores_unclaimed_rows`, `..._ignores_finished_rows`                                     |
| A row with attempts left goes back to the queue, not the dead-letter | adapter                                       | `test_retire_expired_never_touches_work_with_attempts_left`                                                   |
| A crash on the final attempt is dead-lettered with its reason        | adapter                                       | `test_retire_expired_retires_a_crash_on_the_final_attempt`                                                    |
| A job cannot retire a row that is legitimately waiting to retry      | adapter                                       | `test_a_job_cannot_retire_a_retry_pending_row`                                                                |

Cadence: `max(mongo_queue_heartbeat_seconds, 5.0)`, with the floor exposed as
`_RETIRE_INTERVAL_FLOOR_SECONDS` so a test can drive the cadence without a 5-second wait.
One indexed query per tick; never a busy loop.

---

## 11. Signals and shutdown

- SIGINT/SIGTERM set a single `asyncio.Event`; the poll loop and the sweep loop both stop,
  and the handlers are removed on the way out [VERIFIED in `_run`].
- `_shutdown()` releases the Playwright browser, the shared `MongoDB` client and the
  shared Redis client **independently**: a failing closer is logged and the next one still
  runs (`test_shutdown_releases_everything_even_when_one_close_fails`).
- The API process gained the same treatment: `backend/main.py`'s lifespan now closes the
  worker queue **first** (its ARQ adapter owns a Redis pool that must be released before
  the shared client), and the ordering is pinned by
  `test_lifespan_closes_the_worker_queue_before_redis`.

---

## 12. The Redis-outage guarantee (queue broker only — not full Redis independence)

A Mongo-mode **worker** must boot and keep running its jobs when Redis is unavailable,
because Mongo queue mode removes Redis as the worker's **queue broker**.

**This does not mean Redis can be removed from the application.** Redis remains a
first-class dependency for non-queue functionality:

| Consumer of Redis                              | Behaviour when Redis is down                          |
| ---------------------------------------------- | ----------------------------------------------------- |
| API rate limiting                              | fails closed — requests are rejected (503)            |
| API quota accounting                           | unavailable                                           |
| API widget cache / cached reads                | unavailable                                           |
| API crawl SSE (`crawl_events.subscribe`)       | live progress events stop; the snapshot still renders |
| Worker crawl cache invalidation                | best-effort; logged, not fatal                        |
| Worker crawl progress publishing               | best-effort; logged, not fatal                        |
| Worker provider health (`ProviderHealthStore`) | fail-open; logged, not fatal                          |

Only the last three are worker-side and all are non-fatal, so crawl / email / knowledge
jobs still execute — **degraded**, without live progress events or cache coherence. The
API is _not_ fully functional without Redis.

`build_ingestion_embedding_client()` and `ProviderHealthStore(get_redis())` open no socket
at construction, so boot itself is unaffected. Pinned by
`test_the_worker_context_carries_the_shared_process_services`, which hands the boot path a
Redis double whose `ping`/`get` record every call and asserts `pings == []`.

[MEASURED] The local machine has no Redis on `127.0.0.1:6379`, and the whole Mongo worker
suite passes — the guarantee is exercised by construction, not by a mock returning canned
values.

### 12.1 Cutover safety note — `REDIS_URL` stays

Phase 18A does **not** authorize deleting, unsetting or disabling `REDIS_URL`, and no
Phase 18A change reads less of Redis than before. Mongo queue cutover means:

```
ARQ queue traffic            ->  Mongo queue
```

It does **not** mean:

```
entire application Redis    ->  removed
```

The initial cutover **must** keep `REDIS_URL` configured (including its credentials),
because the API's rate limiter, quota accounting, widget cache and crawl SSE all still
depend on it. Anyone reading "Mongo mode needs no Redis" must read this table with it.
(One stale sentence asserting otherwise survives in the `backend/workers/health.py` module
docstring; correcting code comments is outside this report-only remediation — tracked in
§23.10.)

---

## 13. Backend-aware entrypoint: `python -m backend.workers`

```python
backend = settings.queue_backend.strip().lower()
if backend == "arq":
    sys.exit(cli(["backend.workers.app.WorkerSettings"], ...))
if backend == "mongo":
    sys.exit(run_worker())
raise SystemExit(f"Unknown QUEUE_BACKEND={settings.queue_backend!r}; ...")
```

Imports are lazy per branch, so the ARQ path never imports the Mongo consumer and the
Mongo path does not import the ARQ CLI. 11 tests in
`tests/test_worker_backend_entrypoints.py` cover the default ARQ route (asserting the exact
`cli()` arguments and `prog_name`), the Mongo route, case-insensitive matching, the
refusal, and the health module's exit codes.

---

## 14. Backend-aware healthcheck: `python -m backend.workers.health`

Replaces the Dockerfile's inline `redis.ping()` command. Under ARQ it pings the shared
Redis client — the same check as before, including authenticated `REDIS_URL`. Under Mongo
it pings the queue store and **never touches Redis**, and it reports unhealthy (rather
than probing a broker this process does not consume) if the factory hands back a
non-Mongo adapter.

The probe is read-only: it never enqueues, claims or mutates queue state, so a 30-second
interval cannot consume or duplicate work. It closes the shared Mongo client it opened, so
the check exits cleanly. Exit `0` healthy, `1` unhealthy or errored — a probe must never
traceback-crash the container health machinery.

Dockerfile now uses exec form (`CMD ["python", "-m", "backend.workers.health"]`), which is
immune to shell quoting, and a test asserts the old inline Redis ping is gone — a
Redis-only probe would fail a Mongo deployment forever.

---

## 15. Worker context injection

`MongoWorkerLoop` gained `app_context`, merged **beneath** the job context:

```python
ctx = {**self._app_context, **job_context(job, ...)}
```

Job-sourced keys always win, so a job can never spoof a reserved key
(`test_app_context_is_merged_under_the_job_context` proves both directions). The
Phase 17B split-brain guard is preserved: the job still receives the very queue it is
executing on, so child enqueues stay on the parent's backend.

---

## 16. Case-insensitive backend normalization

`Settings` validates `QUEUE_BACKEND` case-insensitively, which made `QUEUE_BACKEND=MONGO`
a _valid opt-in_ that the factory and the entrypoint then compared raw — serving ARQ to a
process that believed it had opted into Mongo. Both now normalize with
`.strip().lower()`. Falsified in §22.

---

## 17. Test inventory (42 Phase 18A tests: 40 in new files, 2 added to existing files)

**Precise accounting** — 40 of the 42 tests live in newly created test files; the other 2
were added to files that already existed. They are all Phase 18A tests, but calling all 42
"new tests" would misstate the diff.

**New files (40 tests):**

| File                                            | Tests | Covers                                                                                                                                                                              |
| ----------------------------------------------- | ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/queue/tests/test_producer_routing.py`  | 14    | ARQ envelopes, Mongo tenant attribution, missing-tenant fail-loud, missing-row fail-loud, ARQ duplicate → `None`, email tenant rules, `producer_tenant` behavior, best-effort close |
| `backend/queue/tests/test_worker_retirement.py` | 15    | retirement semantics, boot recovery, periodic cadence, sweep outage tolerance, `_run` wiring and fail-loud gates, signal-free shutdown, app-context sharing                         |
| `tests/test_worker_backend_entrypoints.py`      | 11    | entrypoint routing ×4, health ×5, exit codes, Dockerfile probe                                                                                                                      |

**Added to existing files (2 tests, 1 each):** the factory normalization regression
(`test_backend_selection_and_config.py`) and the lifespan close-ordering test
(`test_lifespan.py`). Plus the sweep-cadence test counted above.

**Adjusted, not added, in existing files:** `test_crawl_single_flight.py` and
`test_email_idempotency_integration.py` now patch `ArqQueueAdapter._arq_redis` (the seam
that actually builds a client) instead of the module helpers, and their fake ARQ now
returns a job object like real ARQ, because the adapter reads `job.job_id` and raises
`DuplicateJobError` on `None`. `backend/queue/tests/conftest.py` gained an autouse
`reset_worker_queue()` so the process-scoped cache cannot leak between tests.

---

## 18. Determinism work (two flakes found, both fixed)

A green suite that is green by luck is not a gate. Two timing artifacts were found and
removed:

1. **`test_dual_execution_and_stale_completion_is_fenced`** used fixed sleeps to stage a
   lease expiry. Replaced with event gating and a poll-until-expired wait; **6 consecutive
   focused runs green** [MEASURED].
2. **`test_find03_a_reclaimed_attempt_cannot_duplicate_any_winner_effect`** (pre-existing)
   failed **once in the first full-suite run and never again**. The cause was a fixed
   `sleep(LEASE_SECONDS + 0.1)` against a deliberately short 0.4s lease: on an idle box it
   passes, under load it can lose the race. Replaced all five such waits with
   `_await_lease_expiry`, which reads the row's real `lease_expires_at` and polls.
   Verified: 5 consecutive runs green, plus one run under 6× CPU contention [MEASURED].

Also fixed during this phase: the new retirement test initially passed alone but failed in
the full suite because it claimed the wrong row (two rows shared a collection and a
score). Split into two independent tests rather than papering over the ordering with a
sleep — the failure was order-dependence, not timing.

---

## 19. Two environment observations (neither is a Phase 18A defect)

1. **The local dev stack's worker container is crash-looping**, and it is _not_ caused by
   this phase. The failing frame is `backend/workers/app.py:40` →
   `build_ingestion_embedding_client()` raising `ProviderConfigurationError`, because
   `GEMINI_API_KEY`, `JINA_API_KEY` and `COHERE_API_KEY` are all present but **empty** in
   the container while `EMBEDDING_PROVIDER_ORDER=["gemini","jina","cohere"]` requires one
   [VERIFIED via `docker inspect`]. The entrypoint itself worked correctly: the logs show
   it routing to `arq backend.workers.app.WorkerSettings`, i.e. the new backend-aware
   branch behaved exactly as designed under the default backend. No key was injected and
   no container was restarted — out of scope.
2. **The prototype-import guard was narrowed, deliberately.** It previously failed on the
   bare substring `mongo_queue`, which Phase 18A makes correct production code
   (`MONGO_QUEUE_*` settings, `backend.queue.mongo_adapter`, `backend.workers.mongo`). The
   guard now checks the prototype's actual _import path_ (`prototypes`), which still
   catches any import of the prototype package and no longer fails on correct code. The
   reason is recorded in the test's docstring so the next reader does not "restore" it.

---

## 20. Read-only interaction with the running deployment

The only live-system interaction was read-only inspection of the developer's local stack
(`docker ps`, `docker logs webchat-worker`, `docker inspect` — no restart, no config
change, no deploy) to determine whether the new worker image was healthy. Findings are in
§19. No production system was contacted. No migration, index build or flag flip was
performed against any non-local database.

---

## 21. Gate results (all MEASURED)

```
$ uv run ruff check .
All checks passed!

$ uv run ruff format --check .
498 files already formatted                  # after the §27 remediation; this
                                            # report itself used to fail this gate

$ uv run mypy backend
Success: no issues found in 274 source files

$ uv run pytest --cov=backend --cov-report=term-missing --cov-fail-under=85
2811 passed, 12 skipped, 3 warnings in 187.41s
Required test coverage of 85% reached. Total coverage: 85.46%

$ uv run pytest --cov=backend --cov-report=term-missing --cov-fail-under=85 \
      tests backend/queue/tests backend/prototypes/mongo_queue/tests
3448 passed, 14 skipped, 3 warnings in 457.50s
Required test coverage of 85% reached. Total coverage: 92.74%

$ ./scripts/check-backend.sh
2811 passed, 12 skipped, 3 warnings in 237.27s   (exit 0)
```

**Note on the two pytest commands.** The 2811-test run is the _exact_ CI gate and
`check-backend.sh`; neither passes a path, and `pyproject.toml` sets
`testpaths = ["tests"]`, so both collect only `tests/`. The 3448-test run adds the Mongo
queue and prototype suites explicitly, which is how the new consumer code is actually
exercised and how the 92.74% figure is reached. The two gates measuring different things
is itself a follow-up (§23.11). The Mongo queue suites need the isolated prototype
`mongod` on `127.0.0.1:27019`; without it they **skip** rather than fail, so a green
focused run must be read together with its pass count.

Per-module coverage for the code this phase added or changed [MEASURED]:

| Module                              | Coverage         | Uncovered                            |
| ----------------------------------- | ---------------- | ------------------------------------ |
| `backend/queue/runtime.py`          | **100%** (42/42) | —                                    |
| `backend/queue/factory.py`          | **100%** (30/30) | —                                    |
| `backend/queue/worker.py`           | 97% (109)        | 3 defensive lines                    |
| `backend/queue/arq_adapter.py`      | 97% (63)         | consumer-only stubs                  |
| `backend/workers/health.py`         | 97% (34)         | `if __name__` guard                  |
| `backend/workers/__main__.py`       | 93% (14)         | `if __name__` guard                  |
| `backend/workers/mongo.py`          | 89% (84)         | 102-104, 134-135, 178, 198-201 (§23) |
| `backend/workers/jobs/knowledge.py` | 89% (98)         | pre-existing fan-out paths           |
| `backend/workers/jobs/crawl.py`     | 91% (347)        | pre-existing fetch/parse paths       |
| `backend/workers/jobs/email.py`     | 92% (98)         | pre-existing send paths              |

`backend/workers/mongo.py` residual lines, stated precisely: 102-104 is the
`except (NotImplementedError, RuntimeError)` fallback when a platform cannot install a
signal handler; 134-135 the `remove_signal_handler` fallback; 178 the sweep's
`retired` log line; 198-201 the `run_worker()` body (`configure_logging` +
`asyncio.run`) — it is exercised through `__main__.main()` in the entrypoint test with
`run_worker` patched, because running the real one would open a browser and connect to a
queue. The `SystemExit` fail-loud gates are covered.

---

## 22. Falsification: each mechanism is load-bearing, proven by experiment

Every claim below was tested by reverting the mechanism in the working tree, running the
named test, and restoring. All were restored and re-verified green.

| Mechanism reverted                                 | Test                                                           | Observed                                                   |
| -------------------------------------------------- | -------------------------------------------------------------- | ---------------------------------------------------------- |
| `factory` normalization (`.strip().lower()` → raw) | `test_the_factory_matches_the_backend_name_case_insensitively` | **FAILED** — a `MONGO` value produced an ARQ adapter       |
| Entrypoint normalization                           | `test_the_backend_name_is_matched_case_insensitively`          | **FAILED** — a `MONGO` value started the ARQ worker        |
| Health probe's Mongo branch (forced ARQ probe)     | `test_health_pings_the_queue_under_mongo_and_never_redis`      | **FAILED** — the probe touched Redis under Mongo mode      |
| Periodic sweep removed from `_run`                 | `test_the_recovery_sweep_keeps_running_after_boot`             | **FAILED** — `sweeps == [0]`, i.e. only the boot sweep ran |
| `app_context` merge removed                        | `test_app_context_is_merged_under_the_job_context`             | **FAILED** — the job saw no shared services                |

The fifth row is the one that mattered most: before it was added, the boot-recovery test
still passed with the periodic sweep unwired, because the boot sweep alone recovered that
row. The gap was found by falsification, not by reading, and the test was added to close
it.

---

## 23. Residual risk and what is NOT measured

Stated plainly, because the honest list is the useful one:

- **[NOT MEASURED] Cutover.** No shadow comparison, no dual-backend soak, no load test, no
  production-shaped exercise of the Mongo consumer. Phase 17B/17C evidence covers the
  adapter and the loop; this phase covers the seam around them.
- **[NOT MEASURED] Real signals in a container.** SIGINT/SIGTERM handling is implemented
  and the handler install/remove fallbacks are code-reviewed, but no test sends a real
  signal to a running Mongo worker. Doing so requires a live queue database and a
  Playwright-capable image; it belongs to a cutover rehearsal, not to this phase.
- **[NOT MEASURED] Multi-worker contention on the periodic sweep.** The sweep is a single
  indexed query with no lock, so two workers sweeping concurrently is safe by design
  (retirement is idempotent) but not load-tested here.
- **[PARTIAL] `workers/mongo.py` coverage at 89%** — see §21 for the exact residual lines.
  All of them are platform fallbacks or the `run_worker()` wrapper body.
- **Not covered by design:** `close_browser` really closing a Playwright browser (covered
  by a double), and the embedding client's own construction.
- **Pre-existing, untouched:** `docker/Dockerfile.worker`'s embedding-provider startup
  requirement (§19.1). Fixing it means deciding how the dev stack obtains provider
  credentials — a separate decision, deliberately not made here.
- **[INFERRED] Blast radius of the seam change.** The producers' call sites are unchanged
  (`rg` confirms no service calls the new seam directly), so the seam is reached only
  through these five producers. Services keep their existing interfaces, so no API-layer
  change can reach a different submit path.

### 23.1 – 23.10 NON-BLOCKING / FOLLOW-UP (recorded by the independent review, not fixed here)

None of these blocks the commit candidate. They are recorded so the next reader inherits
the known edges rather than rediscovering them.

| #     | NON-BLOCKING / FOLLOW-UP                                                                                                                                                                                                                                                                                                                                             | Why it is acceptable for Phase 18A                                                                                                                                                                                                                                                  |
| ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 23.1  | **Soft-deleted website can enqueue one redundant job.** `_resolve_website_tenant` uses `find_by_id_any`, which does not filter `status == deleted`, so a soft-deleted website still resolves a tenant and produces a queue row.                                                                                                                                      | `Website` is the only soft-deletable entity of the three resolver sources (crawl jobs and documents have no deleted state), and `processor.py:159/733` already no-ops a deleted website. Impact is one redundant queue row, not wrong work.                                         |
| 23.2  | **Mongo health probe inherits the 30s server-selection timeout** (`mongodb_server_selection_timeout_ms`) while the Docker `HEALTHCHECK` timeout is 5s.                                                                                                                                                                                                               | Fail-closed and self-healing: a slow-but-healthy primary is reported unhealthy until it recovers. Tightening the selection timeout (or probing a faster endpoint) is a follow-up.                                                                                                   |
| 23.3  | **Mongo SIGTERM drains the current job** rather than cancelling it ARQ-style; the loop checks the stop event between polls.                                                                                                                                                                                                                                          | The heartbeat keeps the lease alive while draining, and a forced kill recovers through lease expiry plus `execution_version` fencing, so the guarantee stays at-least-once. A cutover rehearsal should measure the platform grace period against the longest crawl.                 |
| 23.4  | **`_run` gathers the poll loop and the sweep loop without `return_exceptions`** (`backend/workers/mongo.py:115`).                                                                                                                                                                                                                                                    | If the poll loop raises, the retire task is not cancelled and can briefly outlive `_shutdown()`, surfacing as a logged warning during an already-failing shutdown. Cosmetic; worth `return_exceptions=True` in a later pass.                                                        |
| 23.5  | **No true concurrent multi-worker retirement load test.** Concurrency safety is argued from the atomic per-document `update_many` filter, not exercised.                                                                                                                                                                                                             | The filter predicates are mutually exclusive (attempts `<` max for reclaim, `>=` max for retire) and retirement never increments attempts, so a second sweep cannot double-count. Belongs to a cutover rehearsal.                                                                   |
| 23.6  | **No real-Redis ARQ wire test.** The new routing tests use a recording `ArqRedis` double and assert the call shape, not a live Redis round-trip.                                                                                                                                                                                                                     | The pre-existing envelope-parity tests plus the manual `git show HEAD` comparison cover the argument reconstruction. A live-wire test would be a nice belt-and-braces addition.                                                                                                     |
| 23.7  | **The prototype import guard does not scan every backend path** — its roots are `backend/workers`, `backend/api`, `backend/services`, `backend/repositories`, not `backend/queue`.                                                                                                                                                                                   | Narrowing the match to `prototypes` was still correct, and no production module imports the prototype today (`rg` over non-test code finds only the ops script `scripts/queue_shadow_validation.py`). A future regression inside `backend/queue` would not be caught automatically. |
| 23.8  | **The process-scoped queue close is not race-free** (§5) — a producer holding the adapter reference can race shutdown.                                                                                                                                                                                                                                               | Uvicorn drains requests before lifespan shutdown, and no lock is added around the enqueue hot path. Accepted explicitly; no stronger guarantee is claimed.                                                                                                                          |
| 23.9  | **`MONGO_QUEUE_LEASE_SECONDS` (120s default) is a new tuning parameter** with no production-shaped soak behind it.                                                                                                                                                                                                                                                   | Safe by construction: an over-short lease yields redundant at-least-once re-execution, never loss, and the heartbeat cadence bounds the exposure. Tune during the cutover rehearsal.                                                                                                |
| 23.10 | **One stale sentence in a code comment**: `backend/workers/health.py`'s module docstring still says "ARQ may be switched off entirely", which reads as if Redis could be removed. §12.1 is the accurate statement.                                                                                                                                                   | Comment-only, and the healthcheck's _behaviour_ is correct — it probes only the selected broker. Correcting code comments is outside this report-only remediation.                                                                                                                  |
| 23.11 | **The CI coverage gate runs with a thin margin.** Because `testpaths = ["tests"]` (§21), the exact CI command measures `85.46%` against the `--cov-fail-under=85` threshold, and the new consumer modules are largely uncovered _in that run_ (`backend/workers/mongo.py` shows 31%) because their suite lives in `backend/queue/tests/`, which CI does not collect. | Currently green, verified. The phase's own suite raises the total to 92.74% when the queue and prototype directories are included. Worth raising `testpaths` (or the threshold) so the queue consumer's coverage is actually gated by CI.                                           |

---

## 24. What this PASS does and does not authorize

This report authorizes **no deployment and no cutover**, and specifically does not
authorize removing `REDIS_URL` (§12.1). It establishes that the backend is a routing
decision made in exactly one place, that the ARQ wire format stays wire-compatible for all
currently reachable producer inputs, that Mongo mode fails loud where it cannot attribute
work, that crash recovery is scheduled, and that the suite would catch the return of any
of those properties.

It does **not** establish that the Mongo backend is production-ready. That claim requires
the cutover rehearsal Phase 17B/17C left open (shadow equivalence under load, soak, and a
rollback drill), none of which this phase performed.

---

## 25. Reproduction

```bash
# gates
uv run ruff format --check .
uv run ruff check .
uv run mypy backend
uv run pytest --cov=backend --cov-report=term-missing --cov-fail-under=85 \
  tests backend/queue/tests backend/prototypes/mongo_queue/tests
./scripts/check-backend.sh

# the Mongo queue suites need the isolated prototype mongod on 127.0.0.1:27019
uv run pytest backend/queue/tests/test_worker_retirement.py -v
uv run pytest backend/queue/tests/test_producer_routing.py -v
uv run pytest tests/test_worker_backend_entrypoints.py -v

# timing-sensitive suites, proven repeatable
for i in 1 2 3 4 5; do
  uv run pytest backend/queue/tests/test_crawl_staging.py \
                backend/queue/tests/test_worker_loop.py
done
```

Do not add a second `-q`: `pyproject.toml` already sets `addopts = "-q"`, and `-qq` makes
pytest omit the final count line, so a passing run looks like it produced no results.

---

## 26. Appendix — file manifest

**New (6 code files + this report):**

| File                                                                | Purpose                                                                                                 |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `backend/queue/runtime.py`                                          | The producer seam: process-scoped binding, close, tenant resolution, duplicate suppression              |
| `backend/workers/mongo.py`                                          | The opt-in Mongo consumer: fail-loud gates, indexes, boot + periodic sweep, signals, resilient shutdown |
| `backend/workers/health.py`                                         | Backend-aware health probe (Docker `HEALTHCHECK`)                                                       |
| `backend/queue/tests/test_producer_routing.py`                      | 14 producer/routing tests                                                                               |
| `backend/queue/tests/test_worker_retirement.py`                     | 15 retirement/lifecycle tests                                                                           |
| `tests/test_worker_backend_entrypoints.py`                          | 11 entrypoint/health/Dockerfile tests                                                                   |
| `docs/reports/MONGO_QUEUE_PHASE18A_ROUTING_AND_WORKER_LIFECYCLE.md` | This report                                                                                             |

**Modified (18):** `backend/queue/errors.py` (`UnresolvedTenantError`),
`backend/queue/factory.py` (normalization), `backend/queue/worker.py` (`app_context`),
`backend/workers/__main__.py` (backend-aware branch), `backend/workers/jobs/{crawl,email,knowledge}.py`
(seam), `backend/main.py` (lifespan close), `docker/Dockerfile.worker` (healthcheck),
`backend/prototypes/mongo_queue/tests/test_isolation.py` (guard narrowed, §19.2),
`backend/queue/tests/conftest.py` (autouse cache reset),
`backend/queue/tests/test_{backend_selection_and_config,child_enqueue_split_brain,crawl_staging,email_idempotency_integration,worker_loop}.py`,
`tests/test_{crawl_single_flight,lifespan}.py`.

---

## 27. Remediation record (documentation + format only)

An independent review of the Phase 18A diff returned **PHASE 18A REVIEW PARTIAL — FIXES
REQUIRED BEFORE COMMIT**: the implementation was accepted, but this report contained one
CI blocker and several factual overstatements. This revision is a **report-only**
remediation — no production code, test, Dockerfile, config or dependency was touched, and
nothing was committed, pushed or deployed.

| Review finding                                                                                                                                                                                                 | Resolution                                                                                                                                                                                                                                        |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **BLOCKER-1** — `uv run ruff format --check .` exited 1 because Ruff formats the Python fenced code blocks in this report (ruff 0.16.2, `uv.lock`-pinned; `.github/workflows/ci.yml:61` runs the same command) | Fixed by running `uv run ruff format` on this file. `ruff format --check .` is green.                                                                                                                                                             |
| Duplicate semantics described as "Mongo → `DuplicateJobError` → returns `None`"                                                                                                                                | §8 rewritten: Mongo resolves a duplicate to the **existing job id** (`store.enqueue` catches `DuplicateKeyError` and re-reads the row); only ARQ yields `None`. Producers ignore the return value, so externally observed behaviour is unchanged. |
| "race-free" queue-cache close                                                                                                                                                                                  | §5 rewritten: the `None` swap protects _future_ producers; a producer already holding the adapter can race shutdown; Uvicorn normally drains first; accepted for Phase 18A, no locking added, no stronger guarantee claimed. Tracked as §23.8.    |
| Implied Redis could be switched off after cutover                                                                                                                                                              | §12 rewritten with a per-consumer table, plus a new §12.1 cutover safety note: `REDIS_URL` **must** stay configured, and Mongo cutover means _ARQ queue traffic → Mongo queue_, not _application Redis → removed_. §24 repeats it.                |
| "42 new tests"                                                                                                                                                                                                 | §17 retitled and rewritten: 40 tests in new test files, 2 added to existing files, 42 Phase 18A tests total.                                                                                                                                      |
| "byte-for-byte unchanged" ARQ wire                                                                                                                                                                             | §1/§6 replaced with "wire-compatible for all currently reachable producer inputs", documenting the `_defer_by <= 0` omission and that the only production deferred caller uses positive delays, so the edge is unreachable.                       |
| Residual risks not recorded                                                                                                                                                                                    | §23.1–§23.10 added, all labelled NON-BLOCKING / FOLLOW-UP.                                                                                                                                                                                        |
| §21 implied its 3448-test run was the CI gate                                                                                                                                                                  | Corrected: CI and `check-backend.sh` run `uv run pytest` with `testpaths = ["tests"]`; the other two suite directories are passed explicitly.                                                                                                     |
| §2/§21 reported `ruff format --check .` as already passing                                                                                                                                                     | Reworded as measured **after** this remediation.                                                                                                                                                                                                  |
| §26 manifest omitted the report from the new-file list                                                                                                                                                         | Report added to the manifest.                                                                                                                                                                                                                     |

Post-remediation verification is recorded in the remediation report itself; the
implementation files listed in §26 are byte-identical to what the review accepted.
