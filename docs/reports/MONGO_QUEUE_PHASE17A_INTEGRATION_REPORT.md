# Phase 17A — WorkerQueue Integration Report (MongoDB Queue, **no cutover**)

**Status:** integration complete, **ARQ remains the production queue**.
**Scope of this report:** the `WorkerQueue` interface, the two adapters behind it, the
opt-in Mongo worker, the ARQ-parity semantics, the measurements, and what is
deliberately *not* done yet.

---

## A–R summary

| | Item | State | Evidence |
|---|---|---|---|
| **A** | `WorkerQueue` interface with no storage concepts | Done | `backend/queue/protocol.py`, `test_protocol.py` |
| **B** | ARQ adapter reproduces today's enqueue call shapes | Done | `backend/queue/arq_adapter.py`, `test_protocol.py` |
| **C** | Mongo storage engine promoted from the prototype | Done | `backend/queue/mongo/` |
| **D** | **Fencing bug fixed** (prototype read-then-write terminal write) | Done | `store.fail_job`, `test_fail_is_refused_for_a_fenced_worker_and_leaves_the_row_alone` |
| **E** | Closed function registry, no dynamic import | Done | `backend/queue/registry.py`, `test_registry.py` |
| **F** | Payload contracts matching production signatures | Done | `registry.validate_payload`, `test_registry.py` |
| **G** | Every Mongo job carries a tenant | Done (stricter than the protocol) | `MissingTenantError`, `test_enqueue_requires_a_tenant` |
| **H** | Job context reproduces ARQ's injected keys | Done | `protocol.job_context`, `test_job_context_reproduces_arq_injected_keys` |
| **I** | **ARQ retry/timeout semantics measured, not assumed** | Done | `scripts/queue_arq_probe.py`, `test_retry_policy.py` |
| **J** | Mongo worker loop with the measured mapping | Done | `backend/queue/worker.py`, `test_worker_loop.py` |
| **K** | Lease heartbeat + reclaim | Done | `store.renew_lease`, `test_heartbeat_*` |
| **L** | Crash recovery (`retire_expired`) | Done | `test_retire_expired_*` |
| **M** | Deterministic mail idempotency keys | Done (helper only) | `backend/queue/mail_idempotency.py`, `test_mail_idempotency.py` |
| **N** | Metadata-only shadow comparison | Done | `backend/queue/shadow.py`, `test_shadow.py` |
| **O** | Backend selection, opt-in gating, DB isolation | Done | `backend/queue/factory.py`, `test_selection.py` |
| **P** | Performance measured | Done | `scripts/queue_perf_probe.py`, §Performance |
| **Q** | Security audit | Done, 1 pre-existing unrelated failure | §Security |
| **R** | Production cutover, queue migration, real traffic | **NOT DONE — out of scope** | §Not done |

---

## 1. Production queue contract (read from the code, not assumed)

`backend/workers/app.py` `WorkerSettings`:

| Setting | Value | Phase 17A consequence |
|---|---|---|
| `max_tries` | `3` | Reachable **only** by ARQ's explicit retry paths — see §8. |
| `job_timeout` | `600` | Default per-function timeout. |
| `crawl_job_timeout_seconds` | `3600` | `crawl_website` is registered as an `arq.Function` with its own timeout (FIND-08). **Not unified.** |
| `keep_result` | `3600` | Result retention only. |
| `retry_jobs` | default (`True`) | Enables `Retry`/`RetryJob` handling. |

Enqueue call shapes reproduced verbatim by `ArqQueueAdapter`:

| Site | Shape |
|---|---|
| `enqueue_crawl_website` | `enqueue_job("crawl_website", crawl_job_id, _job_id=f"crawl:{id}")` |
| `enqueue_email` | `enqueue_job("send_email", payload)` |
| `enqueue_process_document_deferred` | `enqueue_job("process_document", document_id, run_id, _defer_by=N)` |
| `enqueue_process_website_documents` | `enqueue_job("process_website_documents", website_id)` |

ARQ injects **exactly** `job_id`, `job_try`, `enqueue_time`, `score`
(verified against `arq.worker.Worker.run_job`, arq 0.28). `crawl_website` reads
`ctx.get("max_tries", 3)` in its inner runner, so it **always** observes its
literal fallback of 3 under ARQ. `protocol.job_context` supplies `max_tries=3`
so the Mongo path observes the same value.

---

## 2. The interface

`backend/queue/protocol.py` names queue *semantics*
(`enqueue`/`claim`/`heartbeat`/`complete`/`fail`/`retire_expired`/`ping`) and never
storage. Verified by `test_job_context_does_not_leak_queue_storage_concepts`,
which greps the built context for `zset`, `zrange`, `arq:job`, `in_progress`,
`retry_key`.

`ArqQueueAdapter` implements the **producer** half and raises
`BackendNotSupportedError` for `claim`/`heartbeat`/`complete`/`fail`/
`retire_expired` — ARQ owns consumption, and pretending otherwise would be a lie.
`MongoQueueAdapter` implements the full contract.

**The tenant is deliberately absent from the job context.** Production jobs derive
their tenant from the authoritative domain row (`crawl_website` sets
`tenant_id_var` from the crawl job document). Injecting the queue row's copy would
be a *less* trusted value and could mask a mismatch, so the queue row's
`tenant_id` is carried for observability and enforcement only
(`test_context_does_not_carry_the_queue_row_tenant`).

---

## 3. Mongo storage engine and the fencing fix

Promoted from the Phase 15/16 prototype with one behavioural change.

**The prototype bug.** `fail_job` read the job unconditionally to decide
retry-vs-dead and then wrote on `{"_id": ...}` alone. A worker that lost its lease
between that read and the write could still mark a **live, reclaimed** job
terminal — a second worker's in-flight job silently dead-lettered.

**The fix.** The read and the write share **one** filter
(`_id` + `status: running` + `locked_by` + `execution_version`):

```python
fence = self._owner_filter(job_id, worker_id, execution_version)
job = await self.get(job_id, fence)          # read under the fence
...
result = await self._collection.update_one(fence, update)   # write under the same fence
return target if result.matched_count == 1 else "not_owned"
```

A fenced worker matches nothing and cannot write. Regression test:
`test_fail_is_refused_for_a_fenced_worker_and_leaves_the_row_alone` — the row stays
`running` with `last_error is None`, belonging to the worker that actually owns it.

Claim is a **single** atomic `find_one_and_update` with an update pipeline
(`attempts`, `execution_version` incremented in the same server round-trip); there
is no find-then-update window. `attempts < max_tries` is enforced **inside** the
claim filter via `$expr`, so an exhausted job can never be reclaimed.

Indexes: `{status, run_at}` (hot claim path), `{status, lease_expires_at}`
(claim + crash recovery), and a **partial unique** `dedup_key` index so key-less
jobs never collide with each other.

---

## 4. Deduplication: the two backends disagree, deliberately

| | ARQ | Mongo |
|---|---|---|
| Mechanism | `_job_id` string | unique partial index on `dedup_key` |
| Duplicate signal | `enqueue_job` returns `None` | returns the **existing** id |
| Window | `keep_result` (3600 s) | until the row is deleted / TTL'd |

`ArqQueueAdapter` raises `DuplicateJobError` when ARQ returns `None` rather than
fabricating an id (`test_arq_enqueue_reports_arq_own_deduplication`,
FIND-02). A bare `dedup_key` is namespaced (`process_document:d1`) so it cannot
collide with a crawl's `crawl:` keyspace. The differing windows are a real
behavioural difference and a Phase 17B decision.

---

## 5. Tenant enforcement

Every Mongo job must carry a non-empty `tenant_id`; an empty one raises
`MissingTenantError` at the producer boundary. Rationale: a row with no tenant
could never be read back through a tenant-scoped query
(`MongoQueueAdapter.get_for_tenant`), so it would be unobservable work nobody can
cancel or audit. This is **stricter than the `WorkerQueue` protocol default**,
which the ARQ adapter keeps as `""` because ARQ has no tenant-scoped read path to
protect. A payload that *asserts* its own `tenant_id` cannot override the
submission's (`test_claim_returns_the_owner_tenant_not_a_payload_tenant`).

---

## 6. Safe dispatch (no dynamic import, no `eval`)

`registry.py` is a closed literal table. `resolve()` dispatches on explicit `if`
branches; the function name is only ever a dict key and an equality test. No name
is ever formatted into an import path. An unknown name is rejected at the producer
boundary (`UnknownFunctionError`) and, if a poisoned/hand-edited row ever reached a
consumer, dead-lettered without execution.

`test_registry_contains_no_dynamic_import_concatenation` greps the module for
`importlib`, `__import__`, `eval(`, `exec(`, `getattr(tasks,`.

`resolve()` returns the **same objects ARQ dispatches** — the `timed_job` wrappers
are included, so the Mongo path keeps the Phase 12.1 timing instrumentation
(`test_resolve_returns_the_same_object_arq_dispatches`,
`test_resolve_keeps_the_timed_job_instrumentation`).

---

## 7. Result and retention policy (was UNDECIDED in Phase 16)

**Measurement:** no code anywhere in the repository reads an ARQ `JobResult` or
`arq:result` key. Storing a result body would grow every queue document and widen
the blast radius of a queue-collection exposure for no consumer.

- Default `MONGO_QUEUE_RESULT_POLICY=status` → the result is **discarded**;
  status and reference semantics only (`test_status_policy_drops_the_result_body`).
- `full` → ARQ `keep_result` parity, size-clamped at
  `MONGO_QUEUE_MAX_RESULT_BYTES`, over-large results stored as
  `{"__truncated__": true, "bytes": N}`.
- Retention is **off by default** (`retention_days = 0` → no TTL index is
  installed). Phase 16 left the policy UNDECIDED, so Phase 17A makes it
  configurable and never installs a TTL implicitly
  (`test_retention_ttl_index_is_absent_by_default`).

---

## 8. Retry and timeout semantics — measured, not assumed

`scripts/queue_arq_probe.py` runs a real `arq.worker.Worker` with the production
`WorkerSettings` shape against an isolated Redis and counts executions.
Reproduce with `python scripts/queue_arq_probe.py --json`:

```json
{ "arq_version": "0.28.0", "max_tries": 3, "job_timeout": 600,
  "keep_result": 3600,
  "results": { "ordinary": 1, "cancelled": 3, "timeout": 1 } }
```

| Raised inside the job | Executions | ARQ outcome | Mongo `fail(retry=…)` |
|---|---|---|---|
| success | 1 | completed | `complete()` |
| **ordinary exception** | **1** | dead | `False` → dead |
| **job timeout** | **1** | dead | `False` → dead |
| `arq.worker.Retry` / `RetryJob` | 3 | dead after `max_tries` | `True` → retry, retry, dead |
| job-raised `asyncio.CancelledError` | 3 | dead after `max_tries` | `True` → retry, retry, dead |

**The two rows that matter.** Under arq 0.28, `max_tries=3` is *unreachable* for
an ordinary exception or a job timeout. If the Mongo backend "helpfully" retried
them, a failing crawl would run three times — tripling provider spend, crawl load
and quota consumption versus production. The Mongo worker loop deliberately
dead-letters both on the first attempt.

`backend/queue/worker.py` encodes exactly this table, and
`test_retry_policy.py` asserts it through the real loop against the real store.
The live ARQ measurement is re-run by
`test_arq_worker_agrees_with_the_mongo_mapping` (in a **subprocess**: `arq.worker.Worker`
owns its event loop and shutdown, so driving it inside the test's loop is
unreliable) so the table cannot silently drift from the installed arq version.

Two implementation details worth recording:

- `asyncio.TimeoutError` **is** the builtin `TimeoutError` in Python ≥3.11, so the
  loop distinguishes the two ARQ outcomes by
  `isinstance(exc, asyncio.CancelledError)`, not by type name.
- The crawl's domain row is **already** finalised by `crawl_website`'s own
  `CancelledError` handler *before* `asyncio.wait_for` raises, so the queue's
  terminal transition does not double-handle it.

**Backoff is not an ARQ behaviour.** ARQ applies no backoff to its own retry
paths (`RetryJob` simply re-queues for the next ~0.5 s poll). The
5 / 30 / 180 s schedule in `QueueConfig` is the **knowledge-domain** schedule
(`knowledge_retry_base_delay=5.0` × factor `6.0`), which is a different mechanism
and must not be described as ARQ parity.

**No production job raises `Retry`/`RetryJob`**
(`test_no_production_job_raises_an_arq_retry_exception`); deferred document
processing is scheduled *inside* the job via
`enqueue_process_document_deferred`. The rows that carry real production traffic
are therefore success, ordinary exception and timeout.

---

## 9. Mail idempotency (deterministic keys)

Duplicate-delivery risk is queue-independent: a crash **after** the provider
accepted a send but **before** the queue completion is written causes a second
delivery on re-run. Only the provider can fix this, via an idempotency key.

`backend/queue/mail_idempotency.py` computes
`email:<tenant_id>:sha256(canonical content)` where the canonical content is
exactly the `EmailMessage.to_payload()` fields (`to`, `subject`, `text`, `html`).
Properties, each tested:

- **Deterministic** — the same logical mail always yields the same key, so any
  re-delivery collides. No timestamp, no random value, no secret.
- **Tenant-scoped** — one tenant's key can never suppress another tenant's mail.
- **Content-sensitive** — a changed recipient, subject or body yields a new key.
- **Order-independent** — `json.dumps(sort_keys=True)`, so dict insertion order
  cannot change the key.
- **Bounded** — asserted against Resend's 256-character maximum (Phase 16,
  verified), so an over-long tenant id fails at the call site rather than at the
  provider.
- **Log-safe** — `redact_key()` strips the tenant segment, because the key embeds a
  tenant identifier and the repo rules forbid logging customer-identifying values.

**Scope limit (important):** this is the integration abstraction only. It sends
nothing and imports no provider SDK.
`backend/workers/jobs/email.py` is **deliberately unmodified** in Phase 17A — see
§Not done. Production adoption is a Phase 17B change.

---

## 10. Shadow mode is metadata-only, on purpose

Executing the same job through both queues would double-send email, double-crawl,
double-bill embeddings and double-count usage. So `backend/queue/shadow.py` asks
both backends only how they *would describe* the same submission — function,
tenant, dedup key and payload **key set** (never payload values, which are message
bodies) — and reports any disagreement.

It issues **no queue operation at all**:
`test_shadow_issues_no_queue_operations` passes doubles whose every verb raises if
called. `shadow_plan()` defaults to covering every registered function so a sweep
is exhaustive rather than sampling whatever happened to be enqueued.

---

## 11. Selection, gating and connection isolation

- `QUEUE_BACKEND` defaults to `arq`. `mongo` requires **both**
  `QUEUE_BACKEND=mongo` **and** `MONGO_QUEUE_ENABLED=true`, enforced twice (at
  `Settings` construction and again in `get_queue`) so a half-configured
  deployment fails at boot, not at the first enqueue.
- Production additionally requires an explicit `MONGO_QUEUE_DATABASE`, and
  `queue_database_name()` refuses the application database outright.
- The queue reuses the application's existing `MongoDB` client and pool — a second
  unmanaged client would double the connection count against the server-side limit
  and silently opt out of command monitoring and slow-query logging
  (`test_queue_reuses_the_application_mongo_client`).
- `MongoQueueAdapter` is exported lazily via `__getattr__`, so the ARQ default path
  never imports motor/pymongo
  (`test_arq_backend_never_imports_the_mongo_store`).
- `.env.production` was **not** modified. No production job was rewired to use
  `get_queue`; the adapters are reachable only by explicit call.

---

## 12. Performance (measured)

`scripts/queue_perf_probe.py` against the isolated mongod
(`mongodb://127.0.0.1:27019`), 200 jobs, 4 workers:

| Measurement | Result |
|---|---|
| Claim latency p50 / p95 / p99 | **1.45 / 5.32 / 24.3 ms** |
| Throughput, 4 concurrent workers | **392 jobs/s** |
| **Duplicate claims** | **0** (200 jobs, 200 unique claims) |
| Idle claim ops/worker/day — ARQ | **172,800** (fixed 0.5 s poll) |
| Idle claim ops/worker/day — Mongo | **2,880** (1→2→5→10→30 s cap) |
| Idle cost reduction | **60×** |
| Stored document | **346 B** pending / **378 B** running |

The zero duplicate claims under concurrency is the atomic-claim claim, measured
rather than asserted.

**Honest caveats.** These are localhost numbers on a throwaway single-node mongod.
A real Atlas deployment adds network RTT (often 10–50 ms per round trip), which
would dominate the p50 and shift the whole cost profile; the 30 s idle cap exists
precisely so that per-claim latency is not on the critical path when idle. The
claim is **one** round trip, versus ARQ's Lua script plus separate string-key
reads, so the Mongo path trades latency for a lower idle command count — the right
trade only if the queue is bursty, which is why the poll schedule is configurable
rather than hard-coded.

---

## 13. Security

| Check | Result |
|---|---|
| `scripts/check-secrets.sh` | **PASS** — no secrets in tracked files |
| `scripts/check-backend.sh` | **PASS** — ruff (repo-wide) + mypy (255 files) + 2600 tests |
| `scripts/check-database-security.sh` | **PASS** |
| `scripts/check-observability.sh` | **PASS** — 22/22 |
| `scripts/check-input-validation.sh` | 21/22 — 1 failure, **pre-existing and unrelated** |

The single input-validation failure is
`UsageMetricOut.metric not using MetricName Literal` in
`backend/schemas/billing.py`, a file this phase does not touch (`git status`
shows only `backend/core/config.py`, `backend/workers/tasks.py`,
`tests/test_config.py` modified). It is recorded, not fixed — out of scope.

Security properties of the new code:

- **No dynamic execution** — closed registry; no `importlib`, `eval`, `exec`, or
  name-to-path interpolation.
- **Tenant isolation** — every Mongo job is tenant-attributed; reads are
  tenant-scoped; a cross-tenant read returns `None`.
- **Fenced writes** — no unfenced state transition exists; `fail_job` cannot
  dead-letter another worker's live job.
- **No credential in the queue** — payloads are id-only; the queue collection holds
  no tokens, API keys or PII beyond the tenant id and the mail body already used
  by the existing email job.
- **Log hygiene** — worker logs carry job id, function, worker id and attempt, not
  payload values; `redact_key()` keeps tenant ids out of mail-key logs.
- **No secret logged** by either probe script; both target localhost/isolated
  instances only and take their target from an argument, never from
  `REDIS_URL`/`MONGODB_URI` in the environment.

---

## 14. Test results

| Suite | Result |
|---|---|
| `backend/queue/tests` | **185 passed** |
| `backend/prototypes/mongo_queue/tests` | **62 passed** |
| both together (collision check) | **247 passed** |
| `pytest tests` (full regression) | **2600 passed, 12 skipped** in 104.6 s — matches the Phase 17A baseline |
| `ruff check .` | **All checks passed** |
| `mypy backend` | **Success: no issues in 255 source files** |

The pre-existing test-module basename collision
(`backend/queue/tests/test_email_idempotency.py` vs the prototype's identically
named file) is resolved: the integration suite's file is
`test_mail_idempotency.py`, so both suites now collect in one run.

Baseline defects found and fixed in the pre-existing Phase 17A scaffolding:
the production package imported `backend.prototypes`; the prototype-derived
`fail_job` had the unfenced terminal write; `types.py`/`functions.py` did not match
the required API; `mypy` had 4 errors and `ruff` 1 (import order).

---

## 15. Not done — deliberately

None of the following was performed, and each is a Phase 17B decision:

- **No production cutover.** `QUEUE_BACKEND=arq`; no job routes to Mongo.
- **No queue migration.** No Redis queue data was read, converted or written.
- **No queue drain, no real job execution.** Every test injects a fake handler;
  no email was sent, no site crawled, no embedding computed, no provider called.
- **`backend/workers/jobs/email.py` is unmodified** — the idempotency key is
  computed and tested, but not yet passed to Resend. Adopting it needs a provider
  sandbox to verify suppression actually occurs.
- **No real-provider verification** of the 24 h / 256-char Resend key semantics
  (carried from Phase 16 as VERIFIED-against-docs, not VERIFIED-in-sandbox).
- **No Atlas measurement.** All figures are localhost/isolated.
- **Retention TTL left off** (Phase 16 UNDECIDED) and the **result policy left at
  `status`** — both are now configuration, not code, so either can change without
  a code change.
- **Observability for the Mongo worker** (queue depth, dead-letter count) is not
  yet wired into `check-observability.sh`'s metrics.

---

## 16. How to reproduce

```bash
# isolated infrastructure (never production)
mongod --dbpath /tmp/opencode/mongo-queue-prototype --port 27019 \
       --bind_ip 127.0.0.1 --fork --logpath /tmp/opencode/mongo-queue-prototype/mongod.log
redis-server 127.0.0.1:27029 --port 27029

# suites
.venv/bin/python -m pytest backend/queue/tests backend/prototypes/mongo_queue/tests
.venv/bin/python -m pytest tests
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy backend

# measurements
.venv/bin/python scripts/queue_arq_probe.py --json     # ARQ semantics
.venv/bin/python scripts/queue_perf_probe.py --json    # cost and latency

# gates
bash scripts/check-backend.sh
```

---

## 17. Files

**New — interface and adapters**
`backend/queue/__init__.py`, `protocol.py`, `errors.py`, `registry.py`,
`arq_adapter.py`, `mongo_adapter.py`, `factory.py`, `worker.py`,
`mail_idempotency.py`, `shadow.py`

**New — Mongo storage engine**
`backend/queue/mongo/__init__.py`, `ids.py`, `config.py`, `models.py`, `store.py`, `poller.py`

**New — tests** (185)
`backend/queue/tests/conftest.py`, `test_protocol.py`, `test_registry.py`,
`test_mongo_adapter.py`, `test_retry_policy.py`, `test_worker_loop.py`,
`test_selection.py`, `test_mail_idempotency.py`, `test_shadow.py`

**New — measurement scripts**
`scripts/queue_arq_probe.py`, `scripts/queue_perf_probe.py`

**Modified**
`backend/workers/tasks.py` (exports the `REGISTERED_*` callables the registry
resolves, so the Mongo path dispatches the identical, already-instrumented
objects), `backend/core/config.py` (result policy + lease/heartbeat/poll
validation), `tests/test_config.py` (pre-existing Phase 17A config tests).

**Removed**
`backend/queue/types.py`, `backend/queue/functions.py` (superseded by
`protocol.py` + `registry.py`), `backend/queue/tests/test_email_idempotency.py`
(renamed to `test_mail_idempotency.py` to resolve the prototype basename
collision).

**Untouched**
`backend/prototypes/mongo_queue/` remains the Phase 15/16 evidence, still passing
(62 tests), and is imported by no production code.
