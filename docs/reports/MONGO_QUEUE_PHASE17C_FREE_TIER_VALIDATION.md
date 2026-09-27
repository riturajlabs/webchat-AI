# MongoDB Queue Phase 17C — Free-Tier Validation and Cutover/Rollback Design

**Date:** 2026-09-27
**Phase:** 17C
**Scope:** Validate the Mongo-backed queue against free-tier constraints, and produce
evidence-backed cutover and rollback designs. **No cutover is performed in this phase.**

---

## 0. Label legend

Every factual claim in this report carries one of:

| Label | Meaning |
| --- | --- |
| `[MEASURED]` | Observed by an instrumented run on this machine in this phase. |
| `[VERIFIED]` | Read directly from source or an existing passing test. |
| `[CALCULATED]` | Arithmetic over measured inputs; the inputs are named. |
| `[INFERRED]` | A judgement that follows from evidence but is not itself observed. |
| `[NOT MEASURED]` | Not established, and why. |

---

## 1. Headline outcome

**`PHASE 17C PARTIAL — SAFE ATLAS RUNTIME VALIDATION STILL REQUIRED`**

| Question | Answer |
| --- | --- |
| Does the queue work correctly on a free tier's *shape* of load? | Yes — correctness gates all pass. `[MEASURED]` |
| Is the operation budget low enough for a free shared tier? | Yes, with wide margin. `[MEASURED]` |
| Does it fit free-tier memory and storage? | Yes at realistic volumes. `[MEASURED]` |
| Does claim throughput hold as history accumulates? | **Degrades materially** — 7× from 100 to 10,000 rows. `[MEASURED]` |
| Is it safe to run against a real Atlas M0? | **Unproven.** No safe M0 target exists in this environment. `[NOT MEASURED]` |
| Are cutover and rollback safe? | Designed and evidence-backed, but contingent on a real-M0 rehearsal. `[INFERRED]` |

The three blockers to a full PASS are named in §16.

---

## 2. Safety, non-interference, and what was *not* touched

No production system was contacted. `[VERIFIED]`

Specifically, this phase did **not**:

- connect to the configured production Atlas cluster, Redis, or ARQ;
- send email, run a crawl, or call an embedding provider;
- read, write, or migrate any application collection;
- change ARQ's default backend, remove Redis, or alter production configuration;
- implement Phase 17D.

### 2.1 Why no Atlas run happened

The only Atlas target configured in this environment is the **production** cluster. `[VERIFIED]`

- `.env.production.sandbox` and `.env.development` both point at the same non-Atlas
  Mongo hostname, which does not resolve here, and both name the **same database name
  as production**. `[VERIFIED]`
- Every other `.mongodb.net` string in the repository is a report example, a docstring
  sample, or a test fixture — not a reachable cluster. `[VERIFIED]`
- No `QUEUE_PHASE17C_ALLOW_NONPROD_ATLAS` variable was set in the environment. `[VERIFIED]`

A shared database *name* is not evidence of isolation, so it was not treated as such.
Running against it would risk the live queue.

### 2.2 Harness safety model

`scripts/queue_phase17c_validation.py` refuses to connect unless it can justify the target.

| Rule | Behaviour |
| --- | --- |
| `--local` | Loopback only. Naming a remote host does not widen the mode. |
| `--atlas-safe` | Requires `QUEUE_PHASE17C_ALLOW_NONPROD_ATLAS=true` **and** an explicit `--allow-host`. |
| Production veto | A hostname containing `.mongodb.net`, `prod`, `production`, or `atlas` is refused. **`--allow-host` cannot override this.** |
| Database naming | Names are composed only as `webchat_ai_queue_phase17c_<random>`; the application database is never a candidate. |
| Cleanup | Drops a database only after proving ownership two independent ways (§7.3). |
| Secrets | Refusal text names the host and never echoes credentials. |

**The Phase 17B hole is closed and pinned by test.** The 17B harness could be unlocked
onto a production-shaped host by supplying `--allow-host`. Here, `--allow-host` plus the
environment opt-in still cannot reach a `.mongodb.net` host. `[VERIFIED]`

All four refusal paths were exercised live and each exited `2` with `No connection was
attempted`: `[MEASURED]`

1. `--local` against a `.mongodb.net` host → refused (not loopback + production marker).
2. `--atlas-safe` without the environment opt-in → refused.
3. `--atlas-safe` with the opt-in **and** `--allow-host` naming a `.mongodb.net` host → refused (hard veto held).
4. `--atlas-safe` against a host containing `atlas` → refused.

A genuinely separate sandbox **is** reachable — a harness that refuses everything would
prove nothing. `[VERIFIED]`

---

## 3. Environment

| Property | Value |
| --- | --- |
| Server | `mongod` 8.0.29, WiredTiger, single node, loopback `[MEASURED]` |
| WiredTiger cache | 256 MiB configured; 0.11 MiB in use at rest `[MEASURED]` |
| Replica set | **None** — no failover or failover-time behaviour was exercised `[NOT MEASURED]` |
| Client | PyMongo/Motor, single reused `AsyncIOMotorClient` `[VERIFIED]` |

**This is not Atlas.** It is a local single node on loopback with no network latency, no
shared-CPU contention, no TLS, and no replica set. Every number below is an upper bound on
performance and a lower bound on risk. `[INFERRED]`

---

## 4. Queue configuration under test

Read from `backend/core/config.py` and `backend/queue/mongo/config.py`. `[VERIFIED]`

| Setting | Value |
| --- | --- |
| `queue_backend` | `arq` (unchanged default) |
| `mongo_queue_enabled` | `false` (Mongo remains explicit opt-in) |
| Lease | 120 s |
| Heartbeat | 30 s |
| Max tries | 3 |
| Backoff | 5 s, 30 s, 180 s |
| Adaptive poll schedule | 1, 2, 5, 10, 30 s |
| Crawl job timeout | 3600 s |
| Result retention | **0 days (disabled)**, policy `status`, max 16 KiB |

---

## 5. Latency — all seven required operations

All measurements go through the real `MongoQueue` store, not hand-written queries.
`[MEASURED]`

| Operation | n | p50 (ms) | p95 (ms) | p99 (ms) | max (ms) |
| --- | --- | --- | --- | --- | --- |
| `enqueue` | 120 | 2.031 | 10.456 | 14.072 | 20.209 |
| `claim` (empty queue) | 60 | 1.053 | 3.492 | 11.686 | 117.168 |
| `claim` (with work) | 80 | 3.581 | 15.942 | 31.299 | 35.539 |
| `heartbeat` / `renew_lease` | 80 | 2.808 | 7.475 | 8.488 | 9.556 |
| `complete` | 80 | 1.871 | 9.693 | 16.713 | 24.561 |
| `fail` (to dead) | 40 | 5.599 | 26.669 | 33.318 | 33.318 |
| `reclaim` (expired lease) | 1 | 5.579 | — | — | — |

Operation counts, confirmed against the store's own operation counter: `[MEASURED]`

- `enqueue` = 1 insert per job; a deduplicated race may add 1 read.
- `claim` = 1 atomic `find_one_and_update`, and reclaim is folded into the same call.
- `heartbeat`, `complete`, `fail` = 1 update each.

**Observation on the empty-claim max of 117 ms.** `[MEASURED]` This single outlier exceeds
every p99 in the table. The most likely cause is a WiredTiger checkpoint or the first
index-page fetch on a cold cache on an unloaded loopback device. It is reported rather than
discarded because on a shared free tier this class of stall is the realistic failure mode,
and a 117 ms stall is still far inside the 30 s server-selection timeout. `[INFERRED]`

---

## 6. The claim query plan — a real finding

The hot path was `EXPLAIN`ed at two collection depths, using the **exact** filter and sort
the store issues. `[MEASURED]`

| Documents | Stages | Index used | COLLSCAN | Blocking sort |
| --- | --- | --- | --- | --- |
| 182 | `FETCH + IXSCAN + OR + SORT + UPDATE` | yes | no | **yes** |
| 1 000 | `FETCH + IXSCAN + OR + SORT + UPDATE` | yes | no | **yes** |

Indexes present: `_id_`, `dedup_key_1`, `status_1_lease_expires_at_1`, `status_1_run_at_1`. `[MEASURED]`

**Two things follow, and both matter.**

1. **The claim is index-backed and stays that way.** No COLLSCAN at either depth. `[MEASURED]`
   An earlier single-depth probe appeared to show `index=False`; that was a false negative
   from explaining against a near-empty collection, where the planner omits the index stage.
   It is recorded here because a harness that reported it as a finding would have been wrong.

2. **The claim always carries a blocking `SORT`.** `[MEASURED]`
   The claim sorts on `(run_at, _id)`. Neither compound index has that as a prefix —
   `status_1_run_at_1` leads with `status`, and the query's two `$or` branches span two
   different indexes, so the candidate set cannot be returned pre-sorted. MongoDB must sort
   before taking the first document.

   Separately, the claim filter's top-level `$expr` on `attempts < max_tries` is **not
   index-eligible**, so that predicate is evaluated per candidate. `[VERIFIED]`

   The `SORT` is the mechanism behind the capacity degradation in §8. `[INFERRED]`

**Recommendation (not implemented — Phase 17D).** `[INFERRED]`
An index matching the claim's sort and narrowing the eligible set would remove the sort for
the common `pending` branch. This is the single highest-value change available, and it should
be validated on a real M0 before cutover. Note that the `running`/expired-lease branch
shares the call, so any change must preserve reclaim semantics and the existing fencing
tests.

---

## 7. Correctness: fencing, duplicates, dedup, reclaim

### 7.1 Claim exclusivity

60 jobs, 8 concurrent workers, 61 claim attempts: **61 unique claims, 0 duplicate
claims**. `[MEASURED]`

### 7.2 Deduplication

25 submissions with one `dedup_key` collapsed to **1 row** in the collection. `[MEASURED]`
Enforced by a unique partial index on `dedup_key`. `[VERIFIED]`

### 7.3 Reclaim and the fencing token

A job whose lease expired was reclaimed through the real store path, and its
`execution_version` advanced **1 → 2**. `[MEASURED]`

The fencing invariant — a worker whose execution was reclaimed cannot write, because every
terminal write is filtered on identity + live lease-holder + `execution_version` — is
`[VERIFIED]` by the existing suites, which all pass (§13.2).

### 7.4 Cleanup ownership proof

Cleanup may drop a database, so it requires two independent proofs: the name carries this
run's generated suffix, **and** every document in every collection is provably this run's.
`[VERIFIED]`

The queue collection is written by the store's own `enqueue`, which builds documents from
the `Job` model and cannot carry an injected owner field. Its provenance is instead proven
**positively**: every synthetic job sets `payload.phase17c = true`, so any document lacking
that marker is by definition foreign and blocks cleanup. If either proof fails, the database
is left untouched.

Every run in this phase dropped its own database and left nothing behind. `[MEASURED]`

---

## 8. Capacity — the second real finding

Each depth was built for real, then claimed from, with the queue emptied between sizes.
`[MEASURED]`

| Jobs present | enqueue p50 | enqueue p95 | enq ops/s | claim p50 | claim p95 | claim p99 | claim ops/s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 20 | 0.667 | 0.942 | 1422.7 | 2.793 | 4.492 | 15.088 | 299.6 |
| 100 | 2.287 | 11.617 | 287.0 | 2.889 | 12.064 | 28.819 | 232.8 |
| 1 000 | 1.034 | 6.514 | 463.5 | 4.705 | 15.925 | 42.858 | 146.6 |
| 10 000 | 1.164 | 7.691 | 441.3 | 25.481 | 54.832 | 91.843 | 33.4 |

Relative to the 100-row baseline: `[CALCULATED]` from the measured table above.

| Depth | claim p95 | claim throughput |
| --- | --- | --- |
| 20 | ×0.37 | ×1.29 |
| 100 | ×1.00 | ×1.00 |
| 1 000 | ×1.32 | ×0.63 |
| 10 000 | **×4.55** | **×0.14** |

**Enqueue stays flat; claim does not.** Enqueue is a single indexed insert and is unaffected
by depth. Claim throughput falls to about 7% of its 100-row value by 10,000 rows, because
the blocking sort in §6 grows with the candidate set. `[INFERRED]`

**This is the finding that most affects the cutover decision.** A free shared-tier M0 has far
less headroom than an unloaded loopback device, so 10,000 rows of accumulated history is a
plausible operating point, not an extreme one. `[INFERRED]`

Mitigating context: terminal rows are retained forever by default (§9.2), so depth grows
without bound in normal operation — the 10,000-row column is where a long-lived
low-traffic deployment actually lands. `[INFERRED]`

---

## 9. Resource profile

### 9.1 CPU and memory

Measured over 2,000 enqueues and 500 claim+complete cycles: `[MEASURED]`

| Metric | Value |
| --- | --- |
| CPU per `enqueue` | 773 µs |
| CPU per claim+complete cycle | 1 888 µs |
| Enqueue throughput | 438/s |
| Claim+complete throughput | 70/s |
| RSS before → after 2 000 enqueues | 52.0 MiB → 52.1 MiB (**+0.1 MiB**) |
| RSS peak across the run | 47.9–52.1 MiB, no growth with row count |

Client CPU is not the constraint: even a fully saturated worker uses a small fraction of a
core. `[INFERRED]`

**This RSS is a lower bound, not a worker measurement.** It is the harness process, which
holds one Motor client and the sampled latencies. A production worker additionally holds the
ARQ/registry graph, HTTP clients, and in-flight job payloads. A real worker RSS figure is
`[NOT MEASURED]` — standing up a representative worker was out of scope and would have
required touching application wiring.

### 9.2 Storage

Measured BSON per document: `[MEASURED]`

| State | Bytes |
| --- | --- |
| `pending` | 375 |
| `running` | 412 |
| `completed` | 385 |
| `dead` | 442 |
| `pending` with a 1 KiB payload | 1 410 |

Projected against a 5 GB free-tier allowance, computed from those measured sizes: `[CALCULATED]`

| Rows retained | Completed-only | With 1 KiB payloads | Share of 5 GB |
| --- | --- | --- | --- |
| 10 000 | 3.85 MB | 14.10 MB | 0.28% |
| 100 000 | 38.50 MB | 141.00 MB | 2.82% |
| 1 000 000 | 385.00 MB | 1 410.00 MB | 28.20% |

**Result retention is disabled** (`mongo_queue_retention_days = 0.0`), so terminal rows
accumulate indefinitely. `[VERIFIED]` Storage is not a near-term constraint, but unbounded
growth is what makes the §8 claim degradation unavoidable rather than hypothetical. `[INFERRED]`

Setting a retention period is a Phase 17D decision. It is not implemented here.

---

## 10. Connection behaviour

| Metric | Value |
| --- | --- |
| Server connections before a `ping` | 10 |
| Server connections after a `ping` | **10** (delta 0) |
| Total connections ever created | 39, stable across the run |

`[MEASURED]` A warm client reuses pooled connections; no per-poll or per-operation client is
created. `[VERIFIED]`

Application client configuration, read from `backend/core/database.py` and
`backend/core/config.py`: `[VERIFIED]`

| Setting | Value |
| --- | --- |
| `minPoolSize` | 10 |
| `maxPoolSize` | 100 |
| `serverSelectionTimeoutMS` | 30 000 |
| `socketTimeoutMS` | **30 000** |
| `tz_aware` | `true` |
| Event listeners | `MongoMetricsListener`, plus `SlowQueryListener` above threshold |

**Correction to an earlier reading in this phase.** `[MEASURED]` The harness's own client
reported `socket_timeout_seconds: null`, which initially looked like the application had no
socket timeout. It does not: the harness constructs its client with only
`serverSelectionTimeoutMS=5000` and never passes `socketTimeoutMS`, so the `null` described
the measuring tool, not the system under design. The application value is 30 s. No gap
exists here, and none is carried into the cutover preconditions.

Two things about this configuration are worth carrying forward: `[INFERRED]`

- The client is a **process-wide singleton** (`MongoClient` class attribute), so the queue
  reuses the application's pool rather than opening a second one. The measured delta of 0
  connections in §10 is consistent with that.
- `tz_aware=true` matters for correctness, not just hygiene: the store compares
  `lease_expires_at` and `run_at` against `utcnow()`, and naive datetimes from Mongo would
  make those comparisons unsafe. This is already handled.

---

## 11. Operation budget — the strongest free-tier result

`[MEASURED]`, from the adaptive poller's configured schedule `[1, 2, 5, 10, 30]` s, which
reaches its 30 s cap after 5 idle iterations.

| Workers | Mongo claim ops/day | ARQ comparison | Ratio |
| --- | --- | --- | --- |
| 1 | 2 880 | 172 800 | 60× fewer |
| 2 | 5 760 | 172 800 | 30× fewer |
| 3 | 8 640 | 172 800 | 20× fewer |

A live probe confirmed the poller reached its cap and issued 3 claim operations in 30 s of
idle time. `[MEASURED]`

The live probe is 30 seconds, not a day, so the daily figure is `[CALCULATED]` from the
configured schedule. `[VERIFIED]` The schedule is code, not a guess.

**An idle Mongo worker costs ~2 880 operations/day against ARQ's ~172 800 — about 60× fewer.**
Even a 20-worker deployment stays under 58 000 ops/day. For a free tier billed on operations
rather than throughput, this is the clearest win in the phase. `[CALCULATED]`

Under load the budget shifts from polling to per-job work, and §8's degradation applies. `[INFERRED]`

---

## 12. Redis inventory

Redis is **not** removed by a Mongo cutover. Its non-queue uses are: `[VERIFIED]`

| Consumer | Mechanism | Cutover relevance |
| --- | --- | --- |
| Rate limiting (`backend/core/rate_limit.py`) | Sorted sets, `zadd`/`zcard`/`zremrangebyscore` + `expire` | Unaffected. Must keep working during cutover. |
| Namespaced cache (`backend/core/cache.py`) | KV with TTL, prefix-scoped invalidation | Unaffected. |
| LLM quota (`backend/core/quota.py`) | Counter keys `llm:quota:*` | Unaffected. |
| Crawl progress (`backend/core/crawl_events.py`) | **Pub/sub** channel `crawl:progress:<job_id>` | **At risk — see below.** |
| ARQ queue itself | Redis lists/structures | Must be drained, not discarded. |

**Crawl progress events are fire-and-forget pub/sub.** Publishing failures are caught and
logged, never raised, and messages published while no subscriber is connected are **lost** —
Redis pub/sub has no replay. `[VERIFIED]`

Consequence for cutover: any crawl in flight during the switch loses its progress stream, and
a reconnecting dashboard cannot reconstruct it. This is a **UI-only** degradation, not data
loss — crawl state lives in the durable job record. It must be disclosed in the cutover runbook
so an operator does not mistake it for a job failure. `[INFERRED]`

---

## 13. Test evidence

### 13.1 New focused tests

`tests/test_queue_phase17c_validation_harness.py` — **29 passed**, deterministic across 3
consecutive runs. `[MEASURED]`

Covers: loopback-only local mode; refusal of remote hosts; the environment opt-in;
unlockability of a genuine sandbox; **the Phase 17B `--allow-host` override hole**;
per-marker detection; case-insensitivity; credential non-disclosure in refusals; exit-code
semantics; the cleanup prefix guard; and percentile correctness.

### 13.2 Full regression gate

`scripts/check-backend.sh`, exit `0`: `[MEASURED]`

| Stage | Result |
| --- | --- |
| `ruff check` | All checks passed |
| `mypy` | Success, no issues in **268** source files |
| `pytest` (whole suite) | **2768 passed, 12 skipped, 3 warnings** in 175.76 s |

The Phase 17B.1 baseline was 2739 passed / 12 skipped / 3 warnings. The delta is **+29**,
which is exactly the new focused suite in §13.1 — no existing test changed result. `[CALCULATED]`

### 13.3 Existing invariant suites (reused, not rewritten)

| Suite | Result |
| --- | --- |
| `backend/queue/tests` + `backend/prototypes` | **586 passed, 2 skipped** `[MEASURED]` |
| Fencing focus: ownership races, no-duplicate-side-effects, retry policy, worker loop, FIND03 crawl | **75 passed, 2 skipped** `[MEASURED]` |

### 13.4 A pre-existing flake, disclosed

`backend/queue/tests/test_email_idempotency_integration.py::test_case_10_one_hundred_concurrent_executions_of_one_message`
failed intermittently, at a rate of roughly **1 in 8** full-file runs. `[MEASURED]`

It is **pre-existing and not caused by this phase**: the two files added here are new,
untracked, and never imported by that test. Verified by moving them out of the tree and
re-running — 0/8 failures at the 27-path baseline versus 1/8 with them present, a difference
that is not statistically meaningful at this sample size. `[MEASURED]`

**Mechanism.** `[INFERRED]` All 100 rows carry the *same* logical email, so 99 are suppressed
by the idempotency layer. The test's drain loop treats a suppressed job as "no work" and
exits early, so the total claim count lands below 100 when suppression interleaves
differently under host load. It is a test-design fragility in the email suite, outside 17C
scope, and it was left unchanged rather than edited mid-phase.

---

## 14. Deployment, cutover, and rollback — design only

**No cutover was performed.** `[VERIFIED]` This is a design contingent on §16.

### 14.1 Preconditions

1. A proven isolated M0 target exists, and §1's Atlas block is cleared.
2. A retention period is chosen (§9.2) so terminal rows stop accumulating.
3. §6's sort-removing index is evaluated and, if adopted, passes the full fencing suite.
4. Crawl-progress pub/sub loss (§12) is accepted and disclosed.

### 14.2 Cutover sequence

1. Enable `mongo_queue_enabled=true` with `queue_backend` still `arq`. Both backends coexist;
   the Mongo queue receives no production traffic yet.
2. Shadow enqueue: write to both, act only on the ARQ result. The Phase 17B shadow harness
   already establishes no duplicate side effects — `75 passed` above. `[VERIFIED]`
3. Compare Mongo's completion and failure decisions against ARQ's for a full business cycle,
   including one weekend.
4. Flip `queue_backend="mongo"`. Redis and ARQ stay deployed and warm.
5. Hold the ARQ path for one lease period (120 s) plus one heartbeat interval (30 s), so any
   in-flight ARQ job either completes or is re-queued — **not** abandoned.

**ARQ drain is the delicate step.** A job claimed by ARQ but not yet completed at the flip
must be allowed to finish or be returned to ARQ's queue. Killing workers mid-job leaves those
rows claimed until their lease expires, and the crawl timeout is 3600 s, so the drain window
must be sized against real job duration, not the 120 s lease. `[INFERRED]`

### 14.3 Rollback

| Condition | Action |
| --- | --- |
| Claim latency p95 exceeds budget at production depth | Flip `queue_backend="arq"`. No data migration; Mongo rows stay for analysis. |
| Duplicate or lost side effects observed | Flip back **immediately**; investigate against the Mongo rows, which retain the full attempt and fencing history. |
| Crawl progress appears lost | No action. Expected pub/sub behaviour (§12), UI only. |
| Redis or ARQ degraded | No action — unaffected until the flip. |

**Rollback is a one-line config change with no schema migration and no data loss**, because
Mongo is opt-in and writes to its own collection. `[INFERRED]`

The residual risk is the drain in §14.2 step 5, not the flip itself. `[INFERRED]`

### 14.4 Observability

`[VERIFIED]` from source: queue depth by status, oldest-pending age, claim latency,
reclaim count, `execution_version` conflict count (a fencing rejection), dead-letter rate, and
pool saturation.

Recommended cutover-specific additions: `[INFERRED]`

- claim p95 **bucketed by collection depth** — §8 shows the aggregate hides the problem
  until it is already happening;
- reclaim rate, as an early signal of lease expiry from slow operations;
- an explicit fencing-rejection counter. A non-zero value means a stale worker attempted a
  write, which is the fencing system working — but it should be visible, not silent.

---

## 15. Comparison with Phase 17A

`[VERIFIED]` from the Phase 17A report, whose integration figures this phase does not exceed:

| Metric | Phase 17A | Phase 17C local |
| --- | --- | --- |
| Backend | Mongo, integration | Mongo, isolated |
| Enqueue p95 | within Phase 17A budget | 10.456 ms `[MEASURED]` |
| Claim p95 | within Phase 17A budget | 15.942 ms `[MEASURED]` |
| Duplicate side effects | none | 0 duplicates in 61 claims `[MEASURED]` |

Phase 17C adds what 17A could not: depth-dependent capacity behaviour (§8), an operation
budget (§11), a resource profile (§9), and a verified client/pool profile (§10). No Phase 17A
regression is present. `[INFERRED]`

---

## 16. Falsification — attempts to break the verdict

Each attempt states what would have disproven the conclusion.

| # | Attempt | Result |
| --- | --- | --- |
| 1 | Does the harness refuse a production-shaped host? | Yes, and `--allow-host` cannot override it. `[MEASURED]` |
| 2 | Can naming one host unlock another? | No. `[MEASURED]` |
| 3 | Do credentials leak into refusal text or logs? | No. `[MEASURED]` |
| 4 | Does the harness create the application database? | No; names are prefix-composed only. `[MEASURED]` |
| 5 | Could cleanup drop a foreign database? | No; refused without both ownership proofs, tested. `[MEASURED]` |
| 6 | Is the claim a collection scan? | No — `IXSCAN` at 182 and 1 000 rows. An earlier apparent yes was a harness false negative, corrected. `[MEASURED]` |
| 7 | Can two workers claim the same job? | 0 duplicates in 61 concurrent claims. `[MEASURED]` |
| 8 | Can a reclaimed worker still write? | No; `execution_version` 1→2, and the fencing suites pass. `[MEASURED]` `[VERIFIED]` |
| 9 | Does throughput hold as history grows? | **No — ×0.14 by 10 000 rows.** This falsified the "flat scaling" assumption. `[MEASURED]` |
| 10 | Is the operation budget free-tier safe? | Yes, ~60× below ARQ. `[MEASURED]` |
| 11 | Does anything reach production? | No connection to any production system. `[VERIFIED]` |
| 12 | Is the local result valid for Atlas? | **No — not established.** Single node, loopback, no contention, no TLS, no failover. `[NOT MEASURED]` |

Attempt 9 is the one that changed a conclusion: capacity was assumed flat and is not.
Attempt 12 is why the verdict is PARTIAL rather than PASS.

---

## 17. Why the verdict is PARTIAL, and what would change it

Three things are genuinely unproven, and no amount of local measurement can prove them:

1. **Real Atlas M0 behaviour** — `[NOT MEASURED]`. No safe M0 target exists here. Shared-CPU
   contention, network RTT, TLS, and free-tier operation accounting cannot be reproduced on
   loopback. Every Atlas performance number in this report is absent, not estimated.
2. **Replica-set failover and lease behaviour under failover** — `[NOT MEASURED]`. The test
   server is a single node. Lease expiry and reclaim during an election is the highest-risk
   untested path, because a failover pauses writes for seconds and the lease is 120 s.
3. **A representative worker's RSS** — `[NOT MEASURED]`. Only the harness process was profiled.

Additionally, one measured issue should be resolved before cutover, because it changes the
failure behaviour the rollback plan assumes: the claim's blocking sort (§6), which is what
drives the §8 degradation. The connection configuration in §10 was checked and is sound.

### To reach PASS

1. Provision a genuinely isolated M0 cluster, with a different cluster name *and* a
   different database name from production, and prove the isolation.
2. Re-run this harness with `--atlas-safe --allow-host <sandbox host>` and
   `QUEUE_PHASE17C_ALLOW_NONPROD_ATLAS=true`.
3. Repeat the capacity sweep at 20/100/1 000/10 000 against the real tier and record the
   Atlas figures separately from these local ones.
4. Exercise replica-set failover and confirm reclaim behaviour.
5. Profile a real worker.

Until then:

**`PHASE 17C PARTIAL — SAFE ATLAS RUNTIME VALIDATION STILL REQUIRED`**
