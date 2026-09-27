# Phase 17B — Mongo Queue Shadow Validation Report

- **Date:** 2026-09-25
- **Branch / HEAD:** `main` @ `d63deff` (unchanged — nothing committed, nothing pushed)
- **Scope:** validation only. **No cutover, no default change, no production traffic.**
- **Predecessor:** FIND-03 remediation complete (`docs/reports/FIND03_CRAWL_RESURRECTION_REMEDIATION.md`)

Every measurement below is labelled **[MEASURED]**, **[VERIFIED]**, **[CALCULATED]**,
**[INFERRED]** or **[NOT MEASURED]**. Readiness cells are `PASS` / `PARTIAL` / `FAIL` /
`NOT MEASURED`.

---

## 1. Verdict

**PARTIAL.** Two blockers remain (§28, §29). Neither is a queue-ownership defect: the
Mongo queue's claim, lease, fencing and retry semantics all survived adversarial
testing, and two genuine defects found *during* this phase (child split-brain, heartbeat
fence) were fixed and proven fixed. The blockers are (a) a mail-delivery idempotency
design that can silently suppress legitimate mail, and (b) a document-layer write that
has no stale-execution fencing. Both are named, reproducible, and have a recommended fix.

Production is **not** cut over and **must not** be cut over on the strength of this
report.

---

## 2. Environment

| Item | Value | Note |
|---|---|---|
| Host | shared Linux container, load average **4.5** [MEASURED] | not a quiet host; see §22 |
| Isolated mongod | `mongodb://127.0.0.1:27019`, single-node replica set `rs0` | dedicated, `--dbpath /tmp/opencode/find03-mongo` |
| Atlas | none | [NOT MEASURED] |
| Real providers | none contacted | no mail, no crawl, no embedding API call |

Load matters: the top CPU consumers during measurement were `opencode` (95.7%),
`agy` (33.9%) and `next-server` (14.2%). The measured `mongod` used **6.8%**. Absolute
latency numbers below are therefore inflated and are **not** comparable to Phase 17A's
idle-host figures.

---

## 3. Audit: every child enqueue path (the critical finding)

The brief asked for a parent → child → backend → tenant → job-id/dedup → retry graph
**before** changing anything. The graph:

```
API  (backend/api/deps.py)
 ├─ enqueue_crawl_website ──────────────► ARQ/Redis     [entry point, intentional]
 ├─ enqueue_email ─────────────────────► ARQ/Redis     [entry point, intentional]
 └─ enqueue_process_document ───────────► ARQ/Redis     [entry point, intentional]

worker crawl_website
 └─ process_website_documents ──────────► ARQ/Redis     ★ SPLIT-BRAIN
worker process_website_documents
 ├─ process_document (per document) ───► ARQ/Redis     ★ SPLIT-BRAIN
 └─ process_document (retry) ──────────► ARQ/Redis     ★ SPLIT-BRAIN
```

Three worker-side edges were hard-wired to ARQ/Redis. Under `QUEUE_BACKEND=mongo` the
parent job would land in Mongo while its children landed in Redis — two queues, one
logical unit of work, with no shared dedup, retry or lease.

**[MEASURED]** Proof before the fix (`/tmp/opencode/prove_split_brain.py`, real
production `process_website_documents`, real Mongo queue, ARQ patched to record):

```
parent execution backend : MONGO (…splitbrain_evidence.worker_jobs)
children -> REDIS/ARQ    : [('process_document', 'doc-1'), ('process_document', 'doc-2')]
children -> MONGO queue  : 0
RESULT: SPLIT-BRAIN CONFIRMED
```

### 3.1 Fix

A single narrow seam, `backend/queue/child.py`:

- `resolve_child_queue(ctx)` — returns the queue handle the *parent* was dispatched from;
- `resolve_child_tenant(ctx)` — returns that row's tenant.

`job_context()` now carries `queue` and `queue_tenant_id`; `MongoWorkerLoop` passes its
own adapter. A worker therefore enqueues children onto the backend it is already
running on, with the parent's tenant. `enqueue_*` API functions keep their raw-ARQ
behaviour for tenant-less request paths.

**[MEASURED]** Proof after the fix, same script: `children -> REDIS/ARQ: []`,
`children -> MONGO queue: 2`.

**[VERIFIED]** Permanent regression: `backend/queue/tests/test_child_enqueue_split_brain.py`
(14 tests) — child backend, tenant propagation, crawl fan-out, deferred retry,
cross-tenant isolation, API-entry-point fallback, hostile `queue` handle, loop-published
queue.

---

## 4. The heartbeat fence (second real defect, found and fixed here)

`MongoQueue.renew_lease` filtered on `locked_by` only, while `complete_job` /
`fail_job` filtered on `_owner_filter` (identity **+** `execution_version`). Identity
alone is insufficient in one reachable case: **a worker reclaiming its own expired job
under the same worker id.** `locked_by` is unchanged across that reclaim, so a stale
execution could keep extending the *new* execution's lease. Because the stale execution
can no longer complete (its version is stale), the job would sit with a live lease and
no owner able to finish it — a permanent stall.

Fix: `execution_version` threaded through `renew_lease` → adapter → `WorkerQueue`
protocol → `MongoWorkerLoop._heartbeat_loop`, and added to the filter when supplied. The
`lease_expires_at > now` condition is retained, so an expired lease still cannot be
resurrected.

**[VERIFIED]** Falsifiability — the two new tests were run against the *old* filter and
both failed (`stale execution renewed its lease 1 time(s)`); with the fix, 14/14 pass.

---

## 5. Document redelivery (100 required iterations, 100 delivered)

`backend/queue/tests/test_document_redelivery.py`, 15 tests, real `KnowledgeProcessor`
and real `MongoQueueAdapter`, AI provider faked.

| Property | Result |
|---|---|
| Same-checksum redelivery suppressed, no duplicate provider call, no duplicate usage | **PASS** [VERIFIED] |
| Real queue claim → reclaim → version-complete; stale A rejected, B wins | **PASS** [VERIFIED] |
| Usage rollup not duplicated across a same-checksum redelivery | **PASS** [VERIFIED] |
| Changed checksum X→Y processed, old chunks replaced, no rollback | **PASS** [VERIFIED] |
| Stale `run_id` rejected before any work | **PASS** [VERIFIED] |
| Cross-tenant documents never touched | **PASS** [VERIFIED] |
| Dual execution (concurrent and across a real lease expiry) never rolls the checksum back | **PASS** [VERIFIED] |
| Fan-out: one child per eligible document; deleted website → none | **PASS** [VERIFIED] |
| Parent fan-out redelivery repeats children by design (children are idempotent) | **PASS** [VERIFIED] |
| **Stale document snapshot write** | **PARTIAL** — see §28 |

---

## 6. Ownership races — the required 100 iterations

`backend/queue/tests/test_ownership_races.py`. Fully deterministic: every store call
accepts an injected `now`, so lease expiry is driven by an explicit clock, not by
sleeping.

| Measurement | Required | Result |
|---|---|---|
| Stale completion successes | 0 | **0** [MEASURED] |
| Stale failure successes | 0 | **0** [MEASURED] |
| Stale heartbeat successes | 0 | **0** [MEASURED] |

- 100 iterations × {complete, fail} winner paths, each racing stale `complete` /
  `fail` / `renew_lease` against the live owner — totals 0 / 0 / 0.
- Boundary: heartbeat 1 s before expiry succeeds and extends; **at exactly
  `lease_expires_at` it is refused**; 1 µs earlier it succeeds.
- Ownership requires identity **and** version: right-version/wrong-worker,
  right-worker/wrong-version and replayed-version all refused.
- `retire_expired` leaves a live lease alone.
- Same-worker reclaim: 100 stale renewals move the deadline **zero** times (§4).

---

## 7. Backend selection and unsafe configuration

`backend/queue/tests/test_backend_selection_and_config.py` (27 tests).

- Default is `queue_backend="arq"`, `mongo_queue_enabled=False`; the default selects
  `ArqQueueAdapter`. **[VERIFIED]**
- The default path never imports `backend.prototypes` (checked in a **subprocess**, so
  the import table is real). **[VERIFIED]**
- Constructing an adapter dials nothing. **[VERIFIED]**
- Mongo requires **both** flags; production requires an explicit queue database; the
  queue database may not equal the application database. **[VERIFIED]**
- 13 incoherent configurations rejected with specific messages (bad backend, negative
  retention, `max_tries < 1`, bad result policy, non-positive lease, heartbeat ≥ lease,
  empty/non-positive poll schedule). **No unsafe value silently falls back to ARQ.**
  **[VERIFIED]**

---

## 8. Redis consumers preserved

Non-queue Redis consumers are untouched and keep working under the Mongo queue: cache,
rate limiting, provider health, crawl-progress pub/sub. All still read the same
`get_redis` singleton; `redis_url` / `redis_prefix` remain configured. **The only
queue-dependent Redis consumer is the ARQ worker, and it stays on ARQ in production.**
**[VERIFIED]**

---

## 9. Shadow mode isolation

`test_shadow.py` (metadata-only, existing) plus the new
`backend/queue/tests/test_shadow_no_duplicate_side_effects.py` (10 tests) against the
**real** store:

- A full sweep of all 5 registered submissions leaves every row `pending`, `attempts=0`,
  `locked_by=None`, `started_at=None`, `finished_at=None`, `result=None`, `last_error=None`.
  **[MEASURED]**
- **Inverse control:** those same rows *are* claimable, so "nothing executed" is
  evidence of isolation, not of inert stubs. **[VERIFIED]**
- `claim` / `renew_lease` / `complete_job` / `fail_job` / `retire_expired` are trapped on
  the live instance; a shadow pass reaches none. **[VERIFIED]**
- A mismatched envelope is **loud** (both values reported, `UNEXPLAINED`) and **inert**
  (the primary is unaffected, the row is unchanged), and reports no payload values.
  **[VERIFIED]**

---

## 10. Envelope parity

All 5 registered jobs: **no unexplained differences** (harness, §11 and
`test_envelope_parity.py`). Corrupting either side is always detected — wrong timeout,
wrong function, lost payload key, changed payload *value* — so the comparator can fail.

---

## 11. Harness — `scripts/queue_shadow_validation.py`

```
endpoint        : 127.0.0.1 (loopback=True, consent=default)
collection      : webchat_ai_queue_shadow_validation.shadow_envelopes  (dropped on exit)
registry complete: True
jobs mirrored   : 5      jobs executed : none      no side effects : True
VERDICT: PASS - no unexplained differences
```

Safety, tested by `tests/test_queue_shadow_validation_harness.py` (19 tests):

- reads **no** environment URI — a stray `MONGO_URI` cannot aim it;
- only loopback runs unattended; any other host must be named in `--allow-host`, and the
  consent string is recorded in the artifact;
- `*.mongodb.net`, `prod*`, `production*`, `atlas*` unnamed → refused with that reason;
- naming one host does not unlock another;
- ambiguous SRV defaults are surfaced as notes, not silently inherited;
- collection and database dropped on exit; exit 1 on mismatch, 2 on safety refusal.

The harness is **falsifiable**: with the Mongo side's timeout corrupted it reports
`all_match: false` and exits 1.

---

## 12. Performance (measured on a loaded host)

`scripts/queue_perf_probe.py`, isolated mongod, 200 jobs per run, 3 runs each at 4 and
8 workers — **6 runs, 1200 claims**.

| Measurement | 4 workers (min–max) | 8 workers (min–max) |
|---|---|---|
| Duplicate claims | **0, 0, 0** | **0, 0, 0** |
| Unique claims | 200 / 200 / 200 | 200 / 200 / 200 |
| Throughput (jobs/s) | 75.5 – 158.8 | 107.5 – 141.5 |
| p50 | 6.25 – 10.54 ms | 8.72 – 12.61 ms |
| p95 | 12.44 – 34.46 ms | 24.79 – 55.79 ms |
| p99 | 15.86 – 57.76 ms | 31.29 – 157.07 ms |
| Document size | 346 B pending / 378 B running | same |
| Idle ops/worker/day | ARQ 172,800 → Mongo 2,880 (**60×** [CALCULATED]) | same |

**[MEASURED]** The safety-relevant claim — *zero duplicate claims under concurrency* —
held in **6/6** runs, 1200/1200 claims unique. That is the invariant, and it is
load-independent.

**[NOT MEASURED] / NOT COMPARABLE:** absolute latency vs Phase 17A (p50 1.45 / p95 5.32
ms, 392 jobs/s). The host carried load average 4.5 from unrelated processes, and
throughput varied 2.1× run to run. Claiming either parity or regression from this data
would be wrong. Real numbers need a quiet host and, for production relevance, Atlas —
which is unavailable here.

---

## 13. Retention

No TTL index is enabled by default; `retention_days` remains unset. Document sizes are
346/378 B, so M0-class storage is not a constraint. Retention is **undecided** and
deliberately not resolved in this phase. **[NOT MEASURED]**

---

## 14. Atlas M0

**NOT MEASURED.** No sandbox credentials, no paid cluster, and no free tier was used.
Network RTT (10–50 ms/round trip) would dominate the localhost figures above, so the
Atlas cost profile is genuinely unknown, not merely unmeasured.

---

## 15. Full regression

| Suite | Result |
|---|---|
| `tests/ backend/` (full) | **3057 passed, 13 skipped, 0 failed** [MEASURED] |
| `backend/queue/tests` | **414 passed, 1 skipped** [MEASURED] |
| `ruff check` (backend, tests, scripts) | clean [MEASURED] |
| `mypy` | clean, 43 source files [MEASURED] |
| `scripts/check-input-validation.sh` | 21/22 — same single pre-existing failure, `UsageMetricOut.metric not using MetricName Literal`, unrelated to this phase [MEASURED] |
| Determinism, 3 consecutive runs of the new suites | identical results [MEASURED] |

All 13 skips are environment-gated (E2E stack, API keys, live Mongo, RAG benchmark) plus
one intentional Mongo-specific skip inherited from FIND-03.

---

## 16. No cutover

`queue_backend = "arq"` and `mongo_queue_enabled = False` are unchanged. No `.env`,
compose, or deployment file was touched. `backend/workers/tasks.py` changed only in how
coroutines are *named* (`REGISTERED_*` bindings) so the registry can resolve them — the
ARQ dispatch names and the worker shape are unchanged. **[VERIFIED]**

---

## 17. Forensic review of the dirty tree

13 modified tracked files, 7 untracked paths. Classification: 9 files are queue-phase
work (config, `tasks.py`, mail base/providers, crawl, email, knowledge, fakes, and 2
test files); 3 pre-existing unrelated modifications were left untouched
(`core/privacy.py`, `services/auth/auth_service.py`, and the `test_config.py` additions);
FIND-03's changes to `crawl_job_repository.py`, `crawl.py` and `test_crawl_purge_safety.py`
are preserved and were re-validated, not redone. Nothing destructive was run; nothing
was committed or pushed.

---

## 18. Readiness matrix

| Capability | Status | Evidence |
|---|---|---|
| Atomic claim, no duplicate claims | **PASS** | §6, §12 (1200/1200) |
| Lease expiry + reclaim | **PASS** | §6 |
| Heartbeat boundary + fencing | **PASS** | §4, §6 (fixed here) |
| Stale owner cannot complete / fail / renew | **PASS** | §6 (0 / 0 / 0) |
| Retry / backoff / dead-letter | **PASS** | Phase 17A, re-run |
| Idempotent same-checksum redelivery | **PASS** | §5 |
| Changed-checksum replacement | **PASS** | §5 |
| Stale document snapshot write | **PARTIAL** | §28 |
| Child enqueue stays on the parent's backend | **PASS** | §3 (fixed here) |
| Tenant propagation to children | **PASS** | §3 |
| Cross-tenant isolation | **PASS** | §5, §3 |
| Envelope parity, 5 registered jobs | **PASS** | §10 |
| Shadow mode executes nothing | **PASS** | §9 |
| Harness safety + falsifiability | **PASS** | §11 |
| Default stays ARQ; Mongo opt-in only | **PASS** | §7, §16 |
| Unsafe config rejected, no silent fallback | **PASS** | §7 |
| Redis consumers preserved | **PASS** | §8 |
| **Email durable idempotency** | **FAIL** | §29 |
| Full regression green | **PASS** | §15 |
| Performance under production-representative load | **NOT MEASURED** | §12, §14 |
| Atlas M0 | **NOT MEASURED** | §14 |
| Retention / TTL policy | **NOT MEASURED** | §13 |
| Cutover approved | **FAIL** | §1, §29 |

---

## 19. Blocker A — email idempotency can suppress legitimate mail

`backend/queue/mail_idempotency.py` derives the provider key as
`sha256(tenant_id, to, subject, text, html)` — pure **content identity**. There is no
nonce and no job id.

**[VERIFIED]** Two genuinely separate sends of identical content to the same tenant
produce the **same** key:

```
same content, two separate sends -> same key?  True   email:t1:eddeb367cba2e696d7b
different content                -> different key? True
different tenant                 -> different key? True
```

Resend retains the key for **24 hours**. Within that window the second, *legitimate*
delivery is suppressed by the provider. Before this phase both would have been sent.
Silently dropped mail is a worse failure mode than a rare duplicate.

Two further exposures, same area:

- **No durable marker.** Nothing in Mongo records that a message was accepted, so
  protection outside the 24 h window is gone entirely (a dead-letter job re-queued days
  later double-sends).
- **No tenant → unkeyed.** `resolve_idempotency_key` returns `None` for a tenant-less
  message and sends unkeyed, logging the omission. Correct — a fabricated key could
  suppress a *different* message — but it is a duplicate exposure.

**Recommendation (needs a decision, not a patch):** make the key per-*delivery* rather
than per-*content* by folding the queue job id into it, and add a durable
`email_delivery` record written before the provider call. Per-delivery keeps reclaim
redelivery idempotent (a reclaim keeps the same row id) while restoring legitimate
repeats. This changes mail behaviour, so it should be a deliberate, tested change.

---

## 20. Blocker B — the document layer has no stale-write fencing

**[VERIFIED]** `test_a_stale_document_write_reopens_the_document_for_reprocessing`
asserts the gap rather than hiding it: a `Document` snapshot taken before an embedding
and written back afterwards resets `knowledge_checksum`, so the next delivery re-embeds.

The queue's `execution_version` fence prevents the stale *delivery* from completing, but
it cannot prevent a handler that is already mid-flight from writing a stale snapshot.
Correctness here currently rests entirely on queue-level fencing.

**Recommendation:** add `run_id`/version CAS to the document `upsert`, so a write from a
superseded execution is refused rather than reopening the document. This is a change to
`MongoDocumentRepository`, so it is out of scope for a validation phase.

---

## 21. Explicitly out of scope

- **Active-crawl progress last-writer-wins** (FIND-03 follow-up, §14). Non-blocking:
  concurrent active crawls on one job still race on `pages_completed`. Eventually
  consistent, not monotonic. Recorded, not redesigned.
- Retention policy, Atlas sizing, and any real cutover plan.

---

## 22. What would unblock a PASS

1. Decide the email key semantics (per-delivery + durable marker) and implement with
   tests covering the legitimate-repeat case.
2. Add version CAS to the document upsert, or formally accept queue-only fencing in
   writing.
3. Re-run the full gate and this harness.
4. For a performance claim, re-measure on a quiet host and, if budget allows, an Atlas
   sandbox.

**Bottom line:** the queue mechanics are in good shape and two real defects were fixed
and proven fixed. The two remaining blockers are both *downstream of the queue*, in mail
delivery and the document write path. Do not cut over until they are resolved.
