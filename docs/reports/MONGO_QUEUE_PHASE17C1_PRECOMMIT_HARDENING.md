# MongoDB Queue — Phase 17C.1 Pre-Commit Hardening

**Date:** 2026-09-27
**Baseline HEAD:** `d63deff318ef62c45f14d3ebc83b082e96ecf158` *(unchanged — no commit, no push)*
**Scope:** the two production-relevant issues Phase 17C surfaced that are safe to fix before
committing, plus the evidence required to trust them.
**Verdict:** see [§20](#20-verdict).

Every number below is labelled. `[MEASURED]` = observed from the isolated local `mongod`.
`[VERIFIED]` = asserted by a test that was also falsified. `[CALCULATED]` = arithmetic on measured
inputs. `[INFERRED]` = reasoning from measured behaviour, not itself measured. `[NOT MEASURED]` =
explicitly not established here.

---

## 1. Scope

### 1.1 In scope

| # | Item | Outcome |
|---|------|---------|
| A | Claim-depth degradation | **Root-caused and bounded.** No safe narrow fix exists; the cheap candidate was measured and rejected. |
| B | Safe bounded terminal retention | **Fixed.** Terminal-only TTL index plus definition repair. |
| C | Tests and measurements | **Done.** 21 new tests, 2 falsification experiments, full gates. |

### 1.2 Explicitly out of scope, and left untouched

Atlas availability/configuration · replica-set failover · Railway sizing · real-worker Chromium
RSS · input validation · the email integration flake · Redis architecture · UI · billing · auth ·
unrelated Ruff cleanup · unrelated refactors.

ARQ remains the default backend; the Mongo queue remains explicit opt-in. No production endpoint
was contacted at any point in this phase. No deployment, cutover, commit or push was performed.

---

## 2. Baseline

| Item | Value |
|---|---|
| HEAD | `d63deff318ef62c45f14d3ebc83b082e96ecf158` `[VERIFIED]` |
| `git status --short` entries | 29 `[VERIFIED]` |
| Tracked diff | 18 files, 1679 insertions, 111 deletions `[VERIFIED]` |
| `git diff --check` | exit 0 `[VERIFIED]` |

The tracked diff is byte-for-byte the same as the Phase 17C baseline. **Phase 17C.1 modified no
tracked file.** All of this phase's changes live inside `backend/queue/`, which is untracked, so the
tracked diff is unchanged by construction. The pre-existing dirty tree was preserved in full: no
`reset`, `clean`, `restore`, `checkout --`, `stash`, `rebase`, `commit` or `push`.

---

## 3. Reproduction methodology

The Phase 17C harness was not reused for the claim sweep, because the question here is narrower and
needs the *real* query rather than a reconstruction of it.

`/tmp/opencode/c1_repro.py` (outside the repository, per spec §17) attaches a
`pymongo.monitoring.CommandListener` to the driver and records the exact `findAndModify` the claim
sends. That command is then replayed into `explain(..., verbosity="executionStats")`. Two properties
matter:

- **The tested query cannot drift.** The plan describes the production claim, because the plan is
  built from the command the production code emitted.
- **Explain and latency describe one state.** The explain runs against the same populated
  collection the benchmark drains, not a separate scratch collection.

`explain` of a `findAndModify` requires the `update` field to be present, so the captured update
pipeline is kept. Explain never executes it. `$db` is stripped because `Database.command` supplies
it and the server rejects a duplicate.

### 3.1 Two collection shapes

Phase 17C reported a single "depth" number. That conflated two different things, and separating them
is the main finding of this phase:

- **`backlog`** — N rows *all claimable*. This is the Phase 17C capacity shape and the worst case.
- **`history`** — N rows, 95% terminal and 5% claimable. What a long-lived deployment accumulates.

---

## 4. Before: measured claim behaviour

`[MEASURED]` 200 claims per point, single local `mongod 8.0.29` on loopback.

### 4.1 Backlog (all claimable)

| Depth | p50 ms | p95 ms | p99 ms | claims/s | `totalKeysExamined` | `totalDocsExamined` | SORT | IXSCAN | COLLSCAN |
|---|---|---|---|---|---|---|---|---|---|
| 100 | 1.980 | 11.301 | 23.274 | 285.2 | 100 | 99 | yes | yes | no |
| 1,000 | 4.201 | 13.569 | 22.823 | 187.6 | 1,000 | 999 | yes | yes | no |
| 10,000 | 26.077 | 54.934 | 119.701 | 33.5 | 10,001 | 10,000 | yes | yes | no |

### 4.2 History (95% terminal)

| Depth | p50 ms | p95 ms | p99 ms | claims/s | `totalKeysExamined` | `totalDocsExamined` |
|---|---|---|---|---|---|---|
| 100 | 7.644 | 8.255 | 8.255 | 173.5 | 5 | 4 |
| 1,000 | 1.553 | 13.375 | 15.338 | 335.0 | 50 | 49 |
| 10,000 | 3.909 | 14.756 | 23.170 | 194.8 | 500 | 499 |

---

## 5. Root cause — and a correction to Phase 17C

**Phase 17C attributed the degradation to collection "depth". That is wrong, and the correction
matters because it changes what is worth fixing.** `[MEASURED]`

At 10,000 rows the `backlog` shape examined **10,001 keys / 10,000 documents**, while the `history`
shape examined **500 keys / 499 documents** from the same 10,000-document collection. Claim cost
tracks the number of **claimable** rows, not the number of rows present. `[INFERRED]` Terminal
history is essentially free to the claim; a backlog is not.

The exact plan, from the captured command at `backlog_10000`:

```
UPDATE
└── SORT            sortPattern {run_at: 1, _id: 1}, type "default", memLimit 104857600, limitAmount 1
    └── FETCH      filter: {$expr: {$lt: ["$attempts", "$max_tries"]}}
        └── OR
            ├── FETCH  filter: {lease_expires_at: {$lte: now}}
            │   └── IXSCAN  status_1_run_at_1   bounds status ["running","running"]
            └── IXSCAN      status_1_run_at_1   bounds status [pending, retry_pending], run_at ≤ now
```

`[MEASURED]` Two structural facts explain the cost:

1. **The `SORT` is a full document sort, not a key sort.** It reports `type: "default"` with a
   100 MB `memLimit`, and `FETCH` sits *below* it. Documents are materialised and sorted before the
   first row can be chosen — which is why `totalDocsExamined` equals the whole backlog.
2. **The `FETCH` cannot be hoisted above the `SORT`,** because the attempt-budget predicate
   `{$expr: {$lt: ["$attempts", "$max_tries"]}}` compares two *fields*. No B-tree can answer a
   field-to-field comparison, so the server cannot know which documents survive without reading
   them.

The sort is required by the eligibility rule: the claim must return the globally earliest eligible
row across two disjoint status sets (`pending`/`retry_pending` ordered by `run_at`, and `running`
ordered by `lease_expires_at`). The server satisfies "earliest across both" with a merge, and the
merge is sorted.

The 10,000-row `backlog` numbers reproduce Phase 17C's capacity measurement almost exactly
(p50 26.077 ms / 33.5 claims/s here versus 25.481 ms / 33.4 claims/s there), which confirms this is
the same effect and not a new one. `[VERIFIED]`

---

## 6. Fix candidates evaluated

### 6.1 Partial index on `(run_at, _id)` restricted to claimable states — REJECTED

The obvious narrow fix: a partial index over `pending`/`retry_pending` so the pending branch is
served in `run_at` order with no sort.

`[MEASURED]` It does not work. Full sweep with the index installed:

| Depth (backlog) | p50 ms | p95 ms | p99 ms | claims/s | `totalKeysExamined` | SORT |
|---|---|---|---|---|---|---|
| 100 | 2.008 | 9.865 | 19.813 | 296.5 | 99 | yes |
| 1,000 | 4.784 | 9.536 | 13.835 | 193.5 | 999 | yes |
| 10,000 | 32.352 | 59.138 | 194.862 | 27.1 | 10,001 | yes |

`keys` is unchanged and `SORT` survives. The planner still builds an `OR` of two branches and still
merges them with a blocking sort; a third matching index does not remove the merge. The result is
slightly *worse* at 10,000 (27.1 vs 33.5 claims/s), though that specific delta is within run-to-run
noise. The decisive fact is that `totalKeysExamined` did not move.

**Rejected.** Adding it would buy a new index maintained on every claimable write, for no
measurable gain. `[INFERRED]`

### 6.2 Splitting the `$or` into two sequential claims — REJECTED on semantics

Claiming from the pending branch first and the expired-lease branch second would remove the merge
sort entirely. It is rejected because it **changes which job wins**: today the globally earliest
`(run_at, _id)` across both status sets wins, whereas a split would always prefer any pending job
over any crashed-lease job regardless of `run_at`. The brief forbids changing `run_at` ordering and
scheduling semantics, and crash recovery losing to fresh work is a real behavioural regression
(stalled jobs would wait behind a continuous arrival stream). It also doubles idle claim operations,
from 2,880 to 5,760 per worker per day. Still 30× below ARQ's 172,800, so the budget is not the
objection — ordering is. `[INFERRED]`

### 6.3 Derived claimability field — REJECTED on correctness risk

A maintained boolean (or an indexed equivalent) would make the attempt-budget predicate
index-eligible, hoisting `FETCH` above the `SORT` and eliminating the materialisation. It is
rejected because it introduces a drift-prone correctness invariant into the one predicate that
protects the attempt budget: if the derived value ever disagrees with `attempts < max_tries`, jobs
become either permanently unclaimable (lost work) or claimable past their attempt budget. It would
have to be maintained correctly in four places — the claim update pipeline, `complete_job`, both
branches of `fail_job`, and `retire_expired`. The existing `$expr` is self-computing and cannot
drift. `[INFERRED]`

**This is the option to revisit if backlog ever becomes a real problem, and it belongs in its own
phase with its own transition matrix — not in a pre-commit hardening pass.**

---

## 7. What was done about A instead

Claim throughput at a 10,000-row backlog is **33.4 claims/s** `[MEASURED]`. One worker needs
approximately one claim per `(job duration + poll delay)`. Even a one-second job needs 1 claim/s,
so there is roughly 30× headroom `[CALCULATED]`. Claim p99 at that depth is **114.6 ms**, about
**0.10%** of the 120 s lease `[CALCULATED]`. The heartbeat path is a single `_id`-keyed update and
does not traverse this plan at all, so lease renewal is unaffected by backlog `[INFERRED]`.

So the honest characterisation is a **scaling limit, not a defect**: real, characterised, bounded,
and not currently dangerous. A is therefore delivered as:

1. **A pinned invariant** — `backend/queue/tests/test_claim_query_plan.py` asserts the claim is
   never served by a `COLLSCAN` at any tested depth or shape, and that it *is* served by an index.
   This locks in the plan that is actually correct, and would catch the failure mode that would
   *matter* (a bad migration dropping `status_1_run_at_1` and silently turning the claim into a
   full collection walk).
2. **A pinned cost model** — examined counts are asserted to track the claimable backlog, so the
   Phase 17C "depth" framing cannot silently reappear.
3. **A falsified guarantee** — see [§15](#15-falsification).

---

## 8. The production change: terminal-only retention

This is the only production behaviour Phase 17C.1 changed. File: `backend/queue/mongo_adapter.py`.

### 8.1 The defect

Phase 17C's retention TTL was:

```python
if RETENTION_INDEX_NAME not in existing:
    await self._queue.collection.create_index(
        "finished_at", expireAfterSeconds=int(self._retention_days * 86_400),
        name=RETENTION_INDEX_NAME,
    )
```

Two problems `[VERIFIED]`:

1. **No terminal guard.** The index covered *every* row, so TTL eligibility rested entirely on the
   implicit invariant that `finished_at` is written only on a terminal transition. That invariant
   does hold today — `complete_job`, the dead branch of `fail_job`, and `retire_expired` are the
   only writers `[VERIFIED]` — but it is a convention, not a constraint. A future bug that
   populated `finished_at` early would start deleting live work, silently.
2. **A configuration change was silently ignored.** The index was created only if the *name* was
   absent. Re-deploying with a shorter window kept the old one, so retention could be shortened in
   config and never shrink in the database — an unbounded TTL surviving a decision to bound it.

### 8.2 The fix

- `RETENTION_PARTIAL_FILTER = {"status": {"$in": ["completed", "dead"]}}`, reusing
  `TERMINAL_STATUSES` from `backend/queue/mongo/models.py` so the policy and the status vocabulary
  cannot drift apart. A TTL monitor only ever considers documents *present in its index*, so a
  partial filter over terminal states makes deleting a non-terminal row structurally impossible
  rather than merely unlikely.
- `_ensure_retention_index()` **converges** on the intended definition instead of create-if-absent,
  comparing key pattern, `expireAfterSeconds` and `partialFilterExpression`, and rebuilding on
  mismatch.

**The default is unchanged.** `mongo_queue_retention_days` is still `0.0` and retention is still off
until explicitly configured `[VERIFIED]`. Hardening the mechanism deliberately does not flip the
deployment posture Phase 16 left `UNDECIDED`; enabling retention stays an explicit decision.

### 8.3 A bug found in the fix itself

The first implementation compared the installed index key against `{"finished_at": 1}`. This driver
reports the key as a **list of tuples**, `[("finished_at", 1)]`, so the comparison never matched and
`ensure_indexes()` would have dropped and rebuilt the retention index on *every startup* — a window
with no TTL guard at all, on every deploy. Caught by a test asserting `ensure_indexes` is idempotent
once the definition is already correct. Fixed with `_index_key()`, which normalises both shapes. This
is exactly the kind of silent-wrong behaviour the idempotency test exists to catch. `[VERIFIED]`

---

## 9. Before / after retention

`[MEASURED]` 5,000 terminal + 5,000 active rows, measured after an admin `fsync` (this local
`mongod` does not checkpoint on its own and reports pre-insert sizes until forced).

| | Partial (new) | Plain (pre-17C.1) |
|---|---|---|
| Installed `partialFilterExpression` | `{"status": {"$in": ["completed","dead"]}}` | absent |
| Retention index bytes | 40,960 | 57,344 |
| Expected index entries | 5,000 (terminal only) | 10,000 (all rows) |
| Ratio | 0.714 | 1.0 |

The partial index is smaller, consistent with holding only terminal rows. The ratio is 0.714 rather
than 0.5 because at this scale both indexes are a handful of WiredTiger pages and page granularity
dominates; the direction is what the measurement supports, not the exact ratio. `[INFERRED]`

### 9.1 Write cost

`[MEASURED]` 5 repetitions, alternating variants to remove run-order bias:

| | samples (ms/doc) | median |
|---|---|---|
| Partial, terminal-only | 0.0245, 0.0443, 0.0368, 0.0288, 0.0464 | 0.0368 |
| Plain, unfiltered | 0.0299, 0.0367, 0.0284, 0.0394, 0.0321 | 0.0321 |

**No measurable difference** — the ranges overlap almost completely and the medians differ by less
than the within-group spread. This is what theory predicts: skipping 5,000 of 10,000 index entries
is far below the noise floor of this machine at ~0.03 ms/doc. The structural claim (non-terminal
rows generate no index maintenance) holds by construction; the *magnitude* is `[NOT MEASURED]` on
hardware this noisy.

### 9.2 Claim impact: none, by construction

A partial index over terminal states contains no claimable row, so no claimable row's index entry
moves. The post-change sweep confirms byte-identical examined counts:

| Depth (backlog) | `totalKeysExamined` before | after | `totalDocsExamined` before | after |
|---|---|---|---|---|
| 100 | 100 | 100 | 99 | 99 |
| 1,000 | 1,000 | 1,000 | 999 | 999 |
| 10,000 | 10,001 | 10,001 | 10,000 | 10,000 |

`[VERIFIED]` `backend/queue/mongo/store.py` is byte-identical to its Phase 17C state (mtime
2026-09-25, untouched). The claim implementation did not change in this phase.

---

## 10. Scheduling semantics preserved

Unchanged and asserted `[VERIFIED]`:

- Eligibility is still exactly `pending`/`retry_pending` with `run_at <= now`, **or** `running` with
  `lease_expires_at <= now`, **and** `attempts < max_tries`.
- Ordering is still `(run_at: 1, _id: 1)`.
- The attempt budget is still enforced by the self-computing `$expr`, not by derived state.
- Claim remains a single atomic `find_one_and_update`.
- No index was added, removed, or altered on the claim path.
- Lease duration, heartbeat, backoff, and poll schedule are untouched.
- `retire_expired` behaviour is unchanged.

---

## 11. State classification and retention safety matrix

`[VERIFIED]` by `test_retention_partial_filter_classifies_every_job_state`, which inserts a row per
state carrying a **1-year-stale `finished_at`** — the worst case, and what an invariant bug would
produce — and asserts the partial filter's decision.

| State | Inside TTL index | Deletable by retention | Rationale |
|---|---|---|---|
| `pending` | no | **no** | Includes jobs scheduled arbitrarily far in the future. A future `run_at` is not staleness. |
| `retry_pending` | no | **no** | Waiting on backoff; still legitimately owed work. |
| `running` | no | **no** | An expired lease is *ambiguous*, not proof of death. The previous owner may still be alive and about to report. |
| `completed` | yes | yes | Terminal, outcome recorded. |
| `dead` | yes | yes | Terminal, attempt budget spent. |

Two dedicated tests cover the cases most likely to be argued about:

- `test_retention_never_reaches_a_job_scheduled_in_the_future` — a `pending` job 30 days out.
- `test_retention_never_reaches_a_live_lease_even_if_lease_looks_stale` — a `running` job whose
  lease expired a year ago. The server genuinely cannot distinguish this from a dead worker, which
  is precisely why `running` is excluded from the filter entirely rather than filtered on the lease
  timestamp.

Both assert `count_documents(RETENTION_PARTIAL_FILTER) == 0` on a collection that also holds
terminal rows, so they are not vacuous.

---

## 12. `email_deliveries` separation

Untouched. No file under `backend/repositories/email_delivery_repository.py` or
`backend/queue/mail_idempotency.py` was modified in this phase `[VERIFIED]`.

Retention on the queue collection is physically incapable of touching email delivery state: it is a
separate collection with its own schema, and the queue TTL index is scoped to the queue collection
only. The `delivery_id` duplicate-prevention key, provider idempotency key, expiry window,
accepted-terminal and unknown outcomes, and execution fencing are all unchanged. `[VERIFIED]` The
`test_email_delivery_repository.py` suite passes as part of the full gate.

---

## 13. Concurrency and fencing

`[VERIFIED]` Pre-existing suite, now strengthened:

| Invariant | Count | Status |
|---|---|---|
| Stale completion successes | 0 across 200 races (`ITERATIONS=100` × 2 outcomes) | pass |
| Stale failure successes | 0 across 200 races | pass |
| Stale heartbeat/renew successes | 0 across 100 steps | pass |
| Reclaim vs heartbeat, 25 iterations | exactly one owner | pass |
| **Duplicate claims, 120 jobs × 8 concurrent workers** | **0** | pass (new) |
| Lost jobs, same run | **0** — 120 claims for 120 jobs | pass (new) |
| Concurrent reclaim bumps `execution_version` to 2 exactly | 20 jobs × 6 workers | pass (new) |

The two new tests run workers through `asyncio.gather` with no orchestration, so contention is
whatever the event loop and the server produce. They assert the invariant, not the interleaving.

Also re-run green: `test_find03_crawl_resurrection.py` (FIND-03),
`test_child_enqueue_split_brain.py` (child-backend enqueue split-brain), `test_crawl_staging.py`
(winner-only), `test_document_redelivery.py` (CAS/checksum/cross-tenant),
`test_shadow_no_duplicate_side_effects.py` (shadow no-side-effects), `test_worker_loop.py` (WK-01).
`[VERIFIED]`

---

## 14. Regressions

- `scripts/check-backend.sh` — **exit 0**: Ruff clean, mypy clean, **2768 passed, 12 skipped,
  3 warnings** `[VERIFIED]`
- `scripts/check-input-validation.sh` — **21/22, exit 1** `[VERIFIED]`

The single failure is `UsageMetricOut.metric not using MetricName Literal`
(`backend/schemas/billing.py:60`). **Pre-existing and unrelated** — that file is unmodified in
`git status` and was not touched by this phase. The brief explicitly excludes input validation and
the known-unrelated failure gate. **Recorded, not fixed.** `[VERIFIED]`

3 consecutive runs of the concurrency-sensitive suites, each with random ordering enabled:

| Run | Result |
|---|---|
| 1 | 300 passed, 1 skipped |
| 2 | 300 passed, 1 skipped |
| 3 | 300 passed, 1 skipped |

The skip is the environment guard for the isolated `mongod`, which was reachable for all three runs.

---

## 15. Falsification

Two experiments, because a green test proves nothing unless it can go red.

### 15.1 The plan guard detects a real regression

Dropping every index but `_id_` and re-explaining `[MEASURED]`:

| | stages | `totalKeysExamined` | `totalDocsExamined` |
|---|---|---|---|
| With indexes | `FETCH, IXSCAN, OR, SORT, UPDATE` | 2,000 | 2,000 |
| Indexes dropped | `COLLSCAN, SORT, UPDATE` | 0 | 2,000 |

The test fails as intended. During this exercise a **latent flaw in the new test itself** was
found: an unparseable plan yields an empty stage set, which would make `assert "COLLSCAN" not in
stages` pass *vacuously*. `_explain_claim` now asserts the top-level `UPDATE` stage is present, so
an unreadable plan is a hard failure rather than a silent pass. `[VERIFIED]`

### 15.2 The duplicate-ownership test detects a non-atomic claim

Replacing the atomic `find_one_and_update` with a deliberate read-then-write `[MEASURED]`, same
workload:

```
NON-ATOMIC claim: claims=573 unique=120 duplicates=453
```

The test fails as intended. The workload is genuinely contended, so a real regression in claim
atomicity cannot pass silently. `[VERIFIED]`

---

## 16. Tests added

21 new tests, all green.

| File | Before | After | Added |
|---|---|---|---|
| `backend/queue/tests/test_mongo_adapter.py` | 51 | 63 | +12 |
| `backend/queue/tests/test_claim_query_plan.py` | — | 7 | +7 (new file) |
| `backend/queue/tests/test_ownership_races.py` | 14 | 16 | +2 |

---

## 17. Limitations — what is NOT established

Stated plainly, because the gap between this and production readiness is large.

- **Safe Atlas M0 runtime: `[NOT MEASURED]`.** The only configured Atlas target is production, and
  contacting it is out of bounds. Every number in this report is from a loopback `mongod 8.0.29`
  with a 0.25 GB WiredTiger cache, no replica set, and no real network. WiredTiger cache eviction
  under genuine M0 memory pressure is unmeasured.
- **Replica-set failover: `[NOT MEASURED]`.** Election behaviour, `retryWrites` during primary
  stepdown, and cursor behaviour across a topology change are untested. This is a single standalone
  node.
- **Representative worker RSS: `[NOT MEASURED]`.** No real worker ran, so the Phase 17C CPU/RSS
  figures remain lower bounds, not measurements of the deployed process.
- **Index size ratio: partially `[NOT MEASURED]`.** The 0.714 figure is page-granularity dominated
  at this scale; the direction is solid, the exact ratio is not.
- **Write-cost delta: `[NOT MEASURED]`.** Below the noise floor of this machine (§9.1).
- **TTL deletion timing: `[NOT MEASURED]`.** The safety argument is structural (partial index
  membership), not a timing observation. The TTL monitor runs on a ~60 s cycle, so a
  wait-for-deletion test would be slow and flaky; it was not written, deliberately.
- **$indexStats entry counts: `[NOT MEASURED]`.** This server build does not populate `entries`.
  Selectivity is evidenced by byte size and by the per-state tests instead.
- **The email integration flake did not reproduce** in this phase's runs. It remains open and
  out of scope.

---

## 18. Exact files changed by Phase 17C.1

Production code — **1 file**:

| File | Change |
|---|---|
| `backend/queue/mongo_adapter.py` | Added `RETENTION_PARTIAL_FILTER`, `_index_key()`, `_retention_index_matches()`, `_ensure_retention_index()`; rewrote `ensure_indexes()`; exported `RETENTION_PARTIAL_FILTER` |

Tests — **3 files**:

| File | Change |
|---|---|
| `backend/queue/tests/test_claim_query_plan.py` | **New.** 7 plan/cost-model guards, query captured from the driver |
| `backend/queue/tests/test_mongo_adapter.py` | +12 retention terminal-safety, repair and idempotency tests |
| `backend/queue/tests/test_ownership_races.py` | +2 concurrent drain and concurrent reclaim tests |

Explicitly **not** modified: `backend/queue/mongo/store.py` (the claim), `backend/queue/mongo/models.py`,
`backend/queue/mongo/config.py`, `backend/core/*`, `backend/workers/*`, `backend/repositories/*`,
`backend/schemas/*`, all `tests/*`, all prior `scripts/`, and the Phase 17C harness and report.

Measurement scripts live **outside** the repository in `/tmp/opencode/` (`c1_repro.py`, `c1_after.py`,
`c1_falsify.py`, `c1_falsify_dup.py`, `probe_idxstats.py`) per the brief's instruction not to add
throwaway scripts to the tree. No temporary artifact was added to the repository.

---

## 19. Operational guidance

1. **Retention is still off.** `mongo_queue_retention_days` remains `0.0`. Enabling it is a
   deliberate deployment decision, and this phase deliberately does not make it. When it is enabled,
   the terminal-only guard is structural, not conventional.
2. **Watch the backlog, not the collection size.** The claim's cost is a function of claimable rows.
   A monitor on pending + retryable + running is the meaningful signal; total row count is not, once
   retention is enabled.
3. **The claim plan is now a pinned invariant.** If a future migration drops
   `status_1_run_at_1`, `test_claim_query_plan.py` will fail rather than let the claim silently
   become a full collection walk.
4. **Do not add the partial `(run_at, _id)` claim index.** It was measured and does nothing
   (§6.1). Adding it on the assumption that it should help is the most likely wrong turn here.
5. **If backlog ever becomes real**, the correct lever is §6.3 in its own phase, with a transition
   matrix for the derived field — not a query rewrite during a hardening pass.

---

## 20. Verdict

Both in-scope items are resolved to the standard the brief set.

**A — claim depth:** root-caused with `executionStats`, the Phase 17C attribution corrected from
"collection depth" to "claimable backlog", the cheap fix measured and rejected on evidence, and the
remaining options rejected on documented semantic and correctness grounds. Bounded with evidence
(33.4 claims/s and 114.6 ms p99 at a 10,000-row backlog, against ~1 claim/s of need and a 120 s
lease), and the correct plan pinned by falsified tests.

**B — retention:** the actual production fix. Terminal deletion is now structurally impossible for
every non-terminal state including the ambiguous ones, a silently-ignored retention configuration
change is repaired, the default is unchanged, and a bug in the fix itself was caught by the
idempotency test.

**C — tests and measurements:** 21 new tests, two falsification experiments, 3 consecutive
concurrency-sensitive green runs, full backend gate green, the one known-unrelated failure recorded.

**This verdict is about the safety of the pre-commit change set. It is not a production-readiness
statement.** Safe Atlas M0 runtime remains `[NOT MEASURED]`, replica-set failover remains
`[NOT MEASURED]`, and representative worker RSS remains `[NOT MEASURED]`. The Mongo queue remains
explicit opt-in with ARQ as the default backend, and nothing here authorises enabling it in
production.

# PHASE 17C.1 PASS — READY FOR PRE-COMMIT REVIEW

NO COMMIT.
NO PUSH.
