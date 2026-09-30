# Queue Backend Cutover & Rollback Runbook

**Scope.** Moving the worker queue between the two supported backends:

| Backend                            | Storage                                      | Consumer entrypoint                      |
| ---------------------------------- | -------------------------------------------- | ---------------------------------------- |
| `arq` (current production default) | Redis (`arq:queue` and friends)              | `python -m backend.workers` (ARQ)        |
| `mongo` (opt-in)                   | MongoDB `MONGODB_QUEUE_DATABASE.worker_jobs` | `python -m backend.workers` (Mongo loop) |

**Authority.** This runbook describes a _quiesced_ cutover. There is no
cross-backend migration, and none is authorised. Read
[`../reports/MONGO_QUEUE_PHASE18A_ROUTING_AND_WORKER_LIFECYCLE.md`](../reports/MONGO_QUEUE_PHASE18A_ROUTING_AND_WORKER_LIFECYCLE.md)
for how the backend is selected.

---

## 1. The invariant

> **Never flip `QUEUE_BACKEND` while the other backend holds unresolved work.**

A cutover changes only which backend the worker _consumes from_. It does not
move jobs. Anything sitting on the non-consumed side is stranded — it will
neither run nor be visible to the new backend.

Phase 18B's rollback drill measured exactly this: a Mongo `pending` job and a
crashed `running` job both survived an ARQ flip untouched, and afterwards new
enqueues went to a different backend than the stranded rows.

Consequences:

- There is **no** "flip and let the other side catch up" mode.
- There is **no** automatic migration, and adding one is out of scope.
- Quiescing is the operator's job: stop producers, drain, then flip.

---

## 2. Terminal-state policy

Statuses come from `backend/queue/mongo/models.py`. There are exactly five, and
only three of them are non-terminal:

| Status          | Terminal? | Meaning                                                    | Blocks a cutover? |
| --------------- | --------- | ---------------------------------------------------------- | ----------------- |
| `pending`       | no        | claimable, not yet leased                                  | **yes**           |
| `running`       | no        | leased by a live worker                                    | **yes**           |
| `retry_pending` | no        | waiting out a backoff, will be retried                     | **yes**           |
| `completed`     | yes       | succeeded; result retained per `MONGO_QUEUE_RESULT_POLICY` | no                |
| `dead`          | yes       | retries exhausted or non-retryable failure                 | no (see below)    |

Rules that follow from that table:

- **Terminal is absorbing.** A `completed` or `dead` row is never re-opened by
  the worker. `dead` is only reachable from a fenced write, and `retry_pending`
  only from a fenced write with retries left.
- **`dead` is history, not backlog.** A cutover does not block on `dead` rows —
  they will not run again. But they are the queue's failure ledger: a cluster of
  new `dead` rows is a real incident, and the gate's `GO` does not mean the
  backlog is healthy. Count them before and after every flip.
- **Non-terminal is absorbing in the other direction.** A non-terminal row on the
  side that is about to stop being consumed is stranded work. That is the whole
  reason the gate exists.
- **ARQ has no equivalent of `dead`.** When an ARQ job exhausts its retries the
  exception surfaces inside the worker and leaves no terminal record; ARQ also
  TTLs results, so `completed` cannot be counted. The gate reports those two
  states as `n/a` (untracked), never as `0`.

### Backlog invariant

Before any cutover, for **both** sides:

```
non_terminal = pending + running + retry_pending   ==   0
```

plus a deliberate human decision about the terminal history:

```
dead_before == dead_after        (nothing new died during the drain)
```

A non-zero `dead` count is not a blocker, but a _rising_ one during a drain
means the workload is failing and the flip will not help.

---

## 3. Pre-cutover gate

```bash
# ARQ -> Mongo (the intended production cutover)
python scripts/queue_cutover_gate.py --from arq --to mongo

# Mongo -> ARQ (rollback)
python scripts/queue_cutover_gate.py --from mongo --to arq

# machine-readable
python scripts/queue_cutover_gate.py --from arq --to mongo --json
```

The gate reads the endpoints from the **same environment variables the worker
uses** (`MONGODB_URI`, `MONGODB_QUEUE_DATABASE`, `MONGODB_QUEUE_COLLECTION`,
`REDIS_URL`, `QUEUE_BACKEND`), so it inspects what a deployed worker would use.

| Exit | Verdict   | Meaning                                                        |
| ---- | --------- | -------------------------------------------------------------- |
| `0`  | `GO`      | both sides were inspected and both have zero non-terminal jobs |
| `1`  | `NO-GO`   | work is stranded, or the request is not a real cutover         |
| `2`  | `UNKNOWN` | something could not be determined — **never treated as clear** |

`UNKNOWN` is the important one. If the gate cannot inspect a side, it does **not**
assume that side is empty; an unreachable broker and an empty broker produce
different verdicts, and only the second may exit 0.

Safety properties of the script:

- **Read-only.** Only `PING`, `ZCARD`, `ZCOUNT`, `HLEN`, `SCARD` and Mongo
  `ping` / `count_documents`. It cannot enqueue, claim, lease, retry, delete,
  repair or migrate. `tests/test_queue_cutover_gate.py` asserts no mutating verb
  appears in the source.
- **No hardcoded endpoint.** Nothing is baked in; unset variables are an error.
- **No silent localhost fallback.** The application defaults `MONGODB_URI` /
  `REDIS_URL` to localhost; the gate deliberately does not inherit that default,
  so an unset variable can never quietly point the check at a throwaway instance
  and report `GO`.
- **Credentials redacted.** Output is `scheme://***@host:port/db`. Passwords in
  the userinfo _and_ in the query string are removed.
- **No auto-migration.** The gate reports; a human changes the environment.

### Cutover procedure

1. **Stop producers.** Scale the API to zero workers (or set a maintenance
   window) so nothing new is enqueued. The queue must stay empty, not just small.
2. **Let the source drain.** Watch the gate until it reports `GO`. Do not proceed
   on a `NO-GO` you intend to "clean up later" — each cleanup is a manual,
   per-job decision.
3. **Record the baseline.**
   ```bash
   python scripts/queue_cutover_gate.py --from arq --to mongo --json > /tmp/pre-cutover.json
   ```
   Keep the per-status counts, including `dead`.
4. **Flip the variable.** Set `QUEUE_BACKEND=mongo` in Railway (worker service).
   If `MONGO_QUEUE_ENABLED` is not already `true`, set it — the app refuses to
   start the Mongo consumer otherwise.
5. **Roll the worker.** One replica first. Watch `worker_health` logs: they must
   report `queue_backend=mongo` and probe the queue store, **not** Redis.
6. **Verify.** Re-run the gate; both sides should still be `0`. Confirm the
   worker logs a healthy start and that no `arq:*` key is being touched.
7. **Roll the rest**, then re-enable the API.

### Rollback

Same gate, opposite direction, and the same quiescing rules:

```bash
python scripts/queue_cutover_gate.py --from mongo --to arq
```

`NO-GO` / `UNKNOWN` means **do not flip**. Investigate the non-terminal rows
first. A `--from` that does not match the live `QUEUE_BACKEND` is rejected as
`UNKNOWN`, so you cannot accidentally gate (and then flip) the wrong pair.

---

## 4. Job-type rollback behaviour

Execution is **at-least-once** in both backends. A lease that expires under a
killed worker is reclaimed and re-run, so any rollback may re-execute a job
that had already started. What stops that from double-applying effects is a
per-job-type fence — each of which is listed here with the exact risk it leaves
behind.

### `crawl_website`

- **Fence.** FIND-02 "single-terminator": only the attempt that wins the
  terminal CAS writes a terminal website state; losers hit
  `crawl_website_write_fenced` and drop their writes. Progress writes from a
  losing attempt are discarded in favour of the winner's counters. The
  winner-gated knowledge fan-out is built per execution, so only the winner
  enqueues child ingestion jobs.
- **Terminal monotonicity.** A website row already terminal is never reopened;
  a stale attempt cannot write back over it.
- **Risk left.** Fetching and parsing are re-done (wasted provider spend, more
  crawl budget). Child ingestion jobs may be enqueued twice, which is why they
  carry the same dedup/CAS fences. Provider HTTP calls are _not_ idempotent —
  a re-run re-issues them.
- **Re-drive.** Do not bulk re-drive crawl jobs. Inspect the website row first;
  a terminal-monotonic row needs no work, and a non-terminal one is already
  being reclaimed by the queue's own lease logic.

### `send_email`

- **Fence.** `delivery_id` is minted **once** at enqueue and persisted. Each
  attempt claims the row keyed by `delivery_id` before sending, and the provider
  call carries a derived `idempotency_key`.
- **Accepted vs unknown.** A delivery recorded `accepted` is never sent again. An
  attempt whose provider response was lost is recorded `unknown` and is only
  retried inside the provider's deduplication window; beyond it, an `unknown`
  delivery is treated as possibly-delivered.
- **Risk left.** This is the highest-consequence job type under at-least-once.
  Re-running an `unknown` delivery after the provider window can double-send.
  **Never bulk re-drive email jobs**, and never re-drive an `accepted` one.
- **Untracked sends.** A message with no `delivery_id` logs
  `email_delivery_untracked` and has no fence at all — a re-run re-sends. Treat
  that log line as a defect to fix, not noise to ignore.

### `process_document` / `process_website_documents`

- **Fence.** Document writes go through the embedding-identity lock and a
  compare-and-swap, so a stale attempt cannot overwrite a newer embedding.
- **Risk left.** Embedding calls may be re-issued, which costs provider quota
  and can produce a second vector. The identity lock prevents the _stale_ result
  from being persisted, but it does not prevent the spend.
- **Re-drive.** Safe to re-drive per document, but prefer draining the queue's
  own retry path over manual re-enqueue, so `attempts` / `max_tries` accounting
  stays honest.

### General rule

Re-drive nothing by default. If a job must be re-driven, re-drive it **once**,
by id, and record that you did. There is no bulk re-drive tooling in this
codebase, and adding one is not authorised.

---

## 5. Redis incident recovery (rate limiting, not queueing)

The login `503 "Rate limiter is temporarily unavailable"` seen in production is
a **Redis** incident on the _rate limiter_ path, and is **separate** from the
queue cutover above. It is also deliberately **fail-closed**: when Redis is
unavailable, requests are rejected rather than served unlimited.

Redis is load-bearing well beyond ARQ. In rough order of criticality:

1. **Rate limiting** (`backend/api/deps.py`, 19 limiters) — auth, login, API and
   widget abuse protection. Fails closed.
2. **Tenant quota** (`backend/core/quota.py`) — AI spend protection. Fails
   closed.
3. **RAG cache** (`backend/workers/jobs/knowledge.py`) — cache-only, degrades
   to recompute.
4. **Crawl event pub/sub** (`backend/core/crawl_events.py`, and the crawl job's
   Redis cache) — progress signalling, degrades to polling.

`backend/core/redis.py` sets **no** `socket_timeout` / `socket_connect_timeout`.
Against a blackholed (rather than refused) endpoint, commands can block for the
driver's own default, which is why failures have been observed in two distinct
modes: a fast refusal for a dead host, and a hang for a silently dropped
connection. The worker healthcheck is now bounded (see
`backend/workers/health.py`) but application code paths are not.

### Free-tier recovery options

In rough order of preference, all of which preserve fail-closed rate limiting:

1. **Wait for the provider's quota window to reset.** Free Redis tiers cap
   commands per day/month; the reset is the fix, and it costs nothing.
2. **Move to another Redis endpoint on a free tier** that is compatible with
   the current client (RESP/TLS as the app expects). Update `REDIS_URL`; no code
   change, no limit weakening.
3. **Reduce commands per request** — trim cache churn or raise cache TTLs so the
   same workload fits inside the existing quota.
4. **Paid plan.** A real option if the free tier cannot carry the traffic, and
   the honest answer to "the free tier is not enough" — not a default.

**What is not an option:** disabling, raising or fail-opening the rate limiters
to make the `503` disappear. That trades a visible availability symptom for an
unbounded abuse and AI-spend exposure. If Redis is genuinely unavailable, the
system is correct to refuse the request.

### Diagnosing

```bash
# is it a refusal or a hang?
uv run python -c "import asyncio,redis; print(asyncio.run(redis.asyncio.Redis.from_url('$REDIS_URL').ping()))"

# how much of the quota is gone?
redis-cli -u "$REDIS_URL" info commandstats | head

# the queue side of the same Redis (for cutover work, not for rate limiting)
python scripts/queue_cutover_gate.py --from arq --to mongo
```

---

## 6. Shutdown behaviour (why `docker stop` behaves the way it does)

The Mongo worker polls with an interruptible wait (`backend/queue/worker.py`,
`_sleep_or_stop`): the poll sleep races `stop_event.wait()`, so SIGTERM ends an
idle sleep immediately instead of after a full poll interval. On SIGTERM the
handler is **not** cancelled — a job in flight keeps running and keeps
heart-beating its lease, so it completes cleanly or is reclaimed after the
lease expires and fenced by `execution_version`.

This is why the production compose/Dockerfile grace period must exceed the
longest job, not the poll interval. See the Phase 18C report for the measured
drain and `docker stop` numbers.
