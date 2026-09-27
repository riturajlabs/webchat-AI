# FIND-03 — Crawl Job Terminal-State Resurrection: Remediation Report

- **Date:** 2026-09-25
- **Branch / HEAD at time of writing:** `d63deff318ef62c45f14d3ebc83b082e96ecf158` (unchanged; no commit made)
- **Scope:** Targeted remediation of FIND-03 only. Phase 17B redelivery/fan-out validation, the shadow harness, performance reruns, and Phase 17C were intentionally **not** started.
- **Status:** FIXED and validated.

---

## 1. Summary

A duplicate crawl execution (redelivery, or reclaim after a queue lease expiry) could resurrect an
already-terminal `crawl_jobs` row and then win a **second** terminal transition, re-running every
winner-gated side effect: document purge, website write, audit row, `crawl_pages` rollup, usage
event, and knowledge fan-out.

The root cause was a single unfenced write. `MongoCrawlJobRepository.update()` performed an
unconditional whole-document `replace_one` filtered only by `(_id, tenant_id)`. A stale in-memory
snapshot whose status was still active therefore rolled a terminal row back to active, after which
`finish_if_active()` — the atomic ownership token — succeeded a second time.

The fix fences the write on the **stored** row's status, making terminal states monotonic at the
persistence boundary rather than by caller convention.

| | Before | After |
|---|---|---|
| Terminal row can be reopened by a stale active snapshot | Yes | **No** |
| `update()` return type | `None` | `bool` (rejection is observable) |
| Fake vs. Mongo semantics | Divergent (fake aliased objects) | **Parity** |
| Winner-gated effects under a reclaim | Duplicated | **Exactly once** |
| Blocked-refresh suffix persisted to the row | No (silent bug) | **Yes** |

---

## 2. Root cause

`backend/repositories/crawl_job_repository.py` — `update()`:

```python
# BEFORE
await self._collection.replace_one(
    {"_id": job.id, "tenant_id": job.tenant_id}, job.to_doc()
)
```

The filter asserted identity and tenancy but never the lifecycle state. Sequence:

1. Attempt A claims the job, holds an in-memory `CrawlJob` with an **active** status.
2. A's lease expires; attempt B reclaims (guarded by queue `execution_version`).
3. B wins `finish_if_active()` and runs every winner-gated effect.
4. A resumes and calls `update()` with its stale active snapshot → the row flips back to active.
5. A's `finish_if_active()` now matches again → **A wins a second terminator** and repeats every
   side effect in step 3.

Queue `execution_version` fencing cannot prevent this: it guards the **queue** row, not the
`crawl_jobs` collection, and the domain write happens before the worker closes the queue row.

---

## 3. Call-site audit (completed before changing code)

Every call to `CrawlJobRepository.update()` in the codebase:

| # | Site | Expected stored status | Disposition |
|---|---|---|---|
| 1 | `backend/workers/jobs/crawl.py` — `pending` → `running` | active | Fenced; **rejection now returns early** |
| 2 | `backend/workers/jobs/crawl.py` — `on_progress` callback | active | Fenced; **rejected progress is dropped** |
| 3 | `backend/workers/jobs/crawl.py` — `running` → `processing` | active | Fenced; **rejection now returns early** |
| 4 | `backend/workers/jobs/crawl.py` — exception retry path | active | Fenced; **rejection logged** |
| 5 | `tests/test_crawl_worker.py:121`, `:139` | active | Legitimate (sets terminal state on an active row) |

No other production caller, admin override, service, or background task writes `CrawlJob`. The other
writers are `create()` (insert), `delete()` (delete), and `finish_if_active()` (already atomic and
correctly scoped by `_id`, `tenant_id`, **and** active status). No second method could perform the
same resurrection.

---

## 4. State machine

Derived from `backend/models/crawl_job.py` (verified, not assumed):

- **Active:** `pending`, `running`, `processing` (`CRAWL_ACTIVE_STATUSES`)
- **Terminal:** `completed`, `failed` (`CRAWL_STATUSES - CRAWL_ACTIVE_STATUSES`)

There is **no** `cancelled` status; the cancellation path finalizes as `failed`. Tests derive the
terminal set from the model rather than hardcoding it, and assert it is exactly
`{completed, failed}` so a future status addition fails loudly.

Terminal irreversibility is already the model's stated intent (`active is False` on terminal,
a partial unique index in `backend/core/database.py`, and `finish_if_active`).

---

## 5. The fix

**`MongoCrawlJobRepository.update()`** — one atomic statement, no read-before-write:

```python
result = await self._collection.replace_one(
    {
        "_id": job.id,
        "tenant_id": job.tenant_id,
        "status": {"$in": sorted(CRAWL_ACTIVE_STATUSES)},
    },
    job.to_doc(),
)
return result.matched_count > 0
```

- The filter stays scoped by `_id` **and** `tenant_id`, so cross-tenant writes remain impossible.
- `matched_count == 0` means the row was missing, terminal, or foreign-tenant → `False`.
- The Protocol signature changed from `async def update(self, job) -> None` to `-> bool`.

**Precise semantics (deliberate, documented in the docstring):** the fence constrains the **stored**
row, not the incoming object. An active row may still be transitioned to a terminal status through
`update()`; only a row that is **already** terminal is immutable via this method. This preserves the
two legitimate call sites in `tests/test_crawl_worker.py` that use `update()` to set a terminal state
on an active row. All winner-gated terminal transitions must still go through `finish_if_active()`,
which remains the atomic ownership token.

**Worker call sites** now observe rejection:
- `running` / `processing` transitions: log `crawl_update_rejected reason=not_active` and return
  immediately, **before** crawling and **before** the winner-gated block.
- Progress callback: drop the write, log at debug, keep crawling (progress is best-effort).
- Retry path: log at debug; nothing to gate on.

---

## 6. Fake / Mongo parity

`tests/fakes.py` — `FakeCrawlJobRepository.update()` was rewritten to mirror Mongo exactly:

- rejects unknown IDs and foreign tenants,
- rejects when the **stored** row's status is not active,
- stores `job.model_copy(deep=True)` (a whole-document replace, matching `replace_one`),
- returns a `bool`.

This mattered: the old fake stored the caller's object **by reference**, which silently masked a
latent production bug — see §10. The `test_find03_crawl_resurrection.py` suite is parameterized over
both implementations, so either one drifting fails the build.

---

## 7. Tests

### 7.1 `backend/queue/tests/test_find03_crawl_resurrection.py` — 26 passed, 1 skipped

Parameterized over `fake` and `mongo`. The single skip is deliberate: the fake has no query filter to
introspect, so `test_the_write_filter_is_scoped_by_id_and_tenant[fake]` cannot apply.

Covers: every real terminal status (`completed`, `failed`); a terminal row cannot be reopened by a
stale active snapshot; the winner's fields survive verbatim; a legitimate active update still lands;
the whole `CRAWL_ACTIVE_STATUSES` set can still be written; cross-tenant writes are impossible
against both `_id` and `tenant_id`; repeated progress writes after terminalization are rejected;
the write filter itself is fenced; the 100-iteration races; and 100 alternating
winner/stale-writer orderings.

### 7.2 `backend/queue/tests/test_crawl_staging.py` — 29 passed

The full reproduced sequence, end to end on the real job body: A claims and takes an active
snapshot → A's lease expires → B reclaims and completes → A resumes and is rejected. Asserts A
cannot win a second terminator, and that the audit row, `crawl_pages` rollup, usage event, knowledge
fan-out, stored pages, and website terminal state are each **exactly once** and that A's stale
snapshot cannot rewind the winner's counters.

Also parameterized over `completed` **and** `failed` (neither terminal status is special-cased), and
a test asserting the losing attempt bails out at the `running` transition — i.e. the early exit is
wired, not merely the repository.

Strict concurrent assertions were **restored**, not weakened: exactly one terminal winner, one
purge, one website write, one audit, one `crawl_pages` event, one fan-out, one completion publish —
all under real `asyncio.gather` concurrency. Every test file was verified to pass **5/5 repeated
runs** for determinism.

### 7.3 Race volume

Two dedicated tests, each looping 100 times per implementation (400 race executions total):
one where the stale writer always attempts first, and one where the winner always commits first.

---

## 8. Control experiment — the tests provably catch the bug

To prove the suite detects the original defect rather than merely passing, the production
`update()` was **temporarily reverted** to the unfenced version and the suites re-run:

| Suite | With fix | Reverted to defective `update()` |
|---|---|---|
| `test_find03_crawl_resurrection.py` | 26 passed, 1 skipped | **9 failed**, 17 passed, 1 skipped |
| `test_crawl_staging.py` | 29 passed | 29 passed |

The 9 failures include the 100-iteration race tests, the direct resurrection tests for both terminal
statuses, and the filter-shape test. The fix was then restored and re-verified.

`test_crawl_staging.py` staying green is expected and correct: it exercises orchestration through
the (fixed) fake, whereas `test_find03_crawl_resurrection.py` is what pins the real Mongo
implementation. The two files are complementary, and the fake/mongo parameterization guarantees
neither implementation can regress alone.

---

## 9. Full regression results

Environment: isolated MongoDB **8.0.29** on `127.0.0.1:27019` (replica set `rs0`, **PRIMARY**),
Redis **7.0.15** on `127.0.0.1:27029`. The application MongoDB on port `27017` was not touched. No
production ARQ, email provider, crawl, embedding, billing, or Atlas interaction occurred.

| Command | Result |
|---|---|
| `pytest backend/queue/tests` | **318 tests — 0 failures, 1 skipped** |
| `pytest backend/prototypes/mongo_queue/tests` | **62 tests — 0 failures** |
| `pytest tests` | **2612 tests — 0 failures, 0 errors, 12 skipped** |
| `pytest backend/queue/tests/test_find03_crawl_resurrection.py` | 26 passed, 1 skipped |
| `pytest backend/queue/tests/test_crawl_staging.py` | 29 passed (5/5 deterministic) |
| `ruff check .` | All checks passed |
| `mypy backend` | Success — no issues in **261** source files |
| `bash scripts/check-backend.sh` | **exit 0** — 2600 passed, 12 skipped |
| `bash scripts/check-input-validation.sh` | exit 1 — **21/22**, the one known pre-existing failure |

The single `check-input-validation.sh` failure is
`✗ UsageMetricOut.metric not using MetricName Literal` in `backend/schemas/billing.py`. It is
**pre-existing, unrelated to FIND-03, and was deliberately not fixed** (no FIND-03 file touches
billing). It reproduces independently of this work.

---

## 10. Latent production bug found and fixed

Making the fake faithful (§6) exposed a real defect that the old reference-aliasing fake had been
hiding for the lifetime of the suite.

**The bug:** on a blocked-refresh or timed-out refresh that left an existing knowledge base, the
worker computed the user-facing suffix *"…Your existing knowledge base is still available."* and
assigned it to `job.error_message` **after** `finish_if_active()` had already persisted the row.
There was no second `update()` call — the enrichment was in-memory only. In production
(`replace_one` serialises) **the stored row kept the short message and the reassurance never
reached the user**, who polls the crawl job to see why it failed. The existing test
`test_worker_blocked_refresh_preserves_knowledge_base` passed only because the old fake stored the
worker's object by reference, making the later in-memory mutation visible in the "stored" row.

**The fix:** the surviving page count is now read *before* the terminator (a pure read, safe outside
the winner gate) and the final message is composed into the single atomic `finish_if_active()` call.
No post-terminal write is required. Applied to both affected paths: the zero-page/blocked path and
the timeout/cancellation path. All mutating side effects remain strictly behind the winner gate.

This is the only behaviour change beyond the fence itself, it was **required** by the fence (the old
code depended on an impossible-to-fence post-terminal write), and it is covered by the existing
regression test, which now genuinely passes.

---

## 11. Blast radius and migration notes

- **Protocol change:** `CrawlJobRepository.update` now returns `bool`. There are exactly **two**
  implementations in the codebase (`Mongo…`, `Fake…`), both updated.
- **Falsy-return hazard:** an implementation or test double returning `None` is falsy and therefore
  **fails closed** — the worker stops early rather than double-writing. That is the safe direction,
  but it is a silent behaviour change for any such adapter. One test double
  (`LosingJobsRepo` in `tests/test_crawl_purge_safety.py`) returned `None`; it was updated to honour
  the Protocol. A repo-wide audit found no other wrapper.
- **No schema migration.** The fence reuses the existing `crawl_jobs` collection; the partial unique
  index in `backend/core/database.py` is unchanged and is exercised directly by the tests.
- **No public API, response shape, or event-contract change.** The only user-visible effect is that
  the blocked/timeout failure message is now actually persisted (§10).

---

## 12. Verification that public behaviour is preserved

- Every previously passing test that was expected to keep passing does pass; the two initial
  regressions were investigated to root cause, not papered over, and both are now green.
- The success path, the zero-page path, the blocked path, the timeout path, the purge path, the
  single-flight path, the usage/accounting path, and the API surface were all exercised by the
  `tests/` suite (2612 tests, 0 failures).
- Repeated 5× and 3× runs of the concurrency-sensitive suites show no flakiness or ordering
  dependence.

---

## 13. Performance

No new query, index, round trip, or lock was introduced. `update()` remains a single
`replace_one`; the added cost is one integer comparison on an already-indexed field. The two
reorderings in §10 move an existing read earlier rather than adding work. No benchmark was
re-baselined (out of scope for this remediation).

---

## 14. Security and tenancy

- The write filter retains **both** `_id` and `tenant_id`, so a stale snapshot can never modify
  another tenant's row, and cannot modify any row at all once terminal.
- `finish_if_active()` was already fenced and is unchanged; it remains the sole ownership token for
  winner-gated side effects.
- Cross-tenant rejection is asserted directly for both the fake and the real Mongo repository.
- No secrets, credentials, or PII were introduced; no external service was contacted.

---

## 15. Final status and remaining risks

**FIND-03 is fixed.** Terminal crawl-job states are monotonic at the persistence boundary; the fake
and the Mongo implementation agree; and every winner-gated effect is exactly-once under a reclaim.

Remaining risks (none blocking this remediation):

1. **Active → active clobbering is still possible.** The fence constrains the *stored* row's status,
   not the exact expected status, so two concurrent *active* attempts can still overwrite each
   other's progress counters (last writer wins on `pages_completed`). This is not terminal
   resurrection and is out of FIND-03's scope, but it means progress counters are eventually
   consistent rather than monotonic. Tightening this to an exact expected-status CAS is a
   candidate follow-up.
2. **`update()` can still move an active row to terminal.** Deliberate, to preserve the two
   legitimate test call sites (§5), but it means a caller could in principle bypass
   `finish_if_active()` for a terminal transition. A lint rule or a deprecation of the
   terminal-transition use of `update()` would close this off later.
3. **Partial-unique-index migration.** Deployments must have run
   `_ensure_crawl_job_active_index` for the wider single-flight guarantee; the tests exercise the
   helper directly but production migration state was not verified here.
4. **Atlas validation still outstanding.** Only an isolated single-node replica set was used; no
   Atlas or production-cluster validation was performed.
5. **Broader Phase 17B blockers remain open** and were intentionally not touched: the hard-wired ARQ
   child enqueue in `backend/workers/jobs/knowledge.py` (split-brain risk during cutover) and the
   finite email-provider idempotency window.
6. **Pre-existing unrelated failure:** `UsageMetricOut.metric` is not a `MetricName` Literal
   (`check-input-validation.sh`, 21/22).

**Verdict: FIND-03 FIXED — READY TO RESUME PHASE 17B** (at the next user go-ahead; no Phase 17B work
was performed as part of this remediation).
