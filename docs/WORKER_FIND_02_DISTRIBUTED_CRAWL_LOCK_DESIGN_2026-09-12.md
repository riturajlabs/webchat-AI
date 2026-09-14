# FIND-02 — No crawl-job single-flight / distributed website crawl lock: design report

Date: 2026-09-12
Head: `e93aca5 fix: finalize embedding runs after knowledge processing`
Scope: READ-ONLY architecture investigation + concrete implementation plan. **Nothing here is implemented yet.**

---

## 0. Executive summary

| Question                        | Answer                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **FIND-02 severity**            | **Medium (P2).** Not a data-loss or security issue; a latent correctness + scaling issue.                                                                                                                                                                                                                                                                                                                                                                 |
| **Current production blocker?** | **No.** The current deployment runs a single worker replica with the per-process crawl semaphore serializing browser work, so no two same-website crawls can _overlap_ today.                                                                                                                                                                                                                                                                             |
| **Single-replica safety**       | Safe from overlap, **not** safe from duplicates. Two simultaneous `POST /websites/{id}/crawl` calls can both pass the `find_active_for_website()` pre-check (TOCTOU), creating two active `crawl_jobs` for the same website. With `crawl_max_concurrent=2` even one worker runs them concurrently; with the deployed `crawl_max_concurrent=1` they run serially but still both crawl, both increment usage, both audit, and both overwrite website state. |
| **Multi-replica risk**          | Duplicate same-website crawls run concurrently (duplicate work, racing status writes, double `crawl_pages` rollup, duplicated audit/knowledge-pass handoff). Same-website `crawl_jobs` are not fenced anywhere except the TOCTOU pre-check.                                                                                                                                                                                                               |
| **Recommended design**          | **Option C: ARQ deterministic `_job_id` (idempotent re-enqueue) + MongoDB conditional/fenced state writes.** A Redis lease is evaluated and **rejected as redundant** once the Mongo fence exists.                                                                                                                                                                                                                                                        |
| **Infrastructure added**        | One unique partial index on `crawl_jobs` (+ an `active` boolean field) and fenced terminal writes. No transactions, no new services.                                                                                                                                                                                                                                                                                                                      |

The core insight: the only place a duplicate same-website crawl can enter the system is the **crawl-job insert** in `start_crawl`. Make that insert atomic (unique partial index) and exactly one active crawl job can ever exist per `(tenant_id, website_id)`; ARQ already guarantees that one job id runs on at most one worker at a time (per-job `in_progress` lease). A per-website **Redis lease then adds nothing** for duplicate prevention — and its own TTL/renewal/Redis-outage semantics would only reintroduce the failure modes it claims to fix.

---

## 1. Current flow trace

### 1.1 End-to-end trace

```
POST /api/websites/{id}/crawl                      websites.py:187 start_website_crawl
  │  crawl_limiter (30/hr, IP-scoped)             deps.py:782
  ▼
CrawlService.start_crawl                           crawl_service.py:63
  ├─ websites.find_by_id(tenant, website)          crawl_service.py:76   (None → 404)
  ├─ crawl_jobs.find_active_for_website(...)       crawl_service.py:79   ★ TOCTOU pre-check
  │     └── plain find_one(tenant, website, status ∈ pending/running/processing)
  ├─ usage.check_limit(documents)                  crawl_service.py:84
  ├─ usage.check_limit(crawl_pages)                crawl_service.py:85   (reads usage_events; see §5)
  ├─ CrawlJob.new(...)                             crawl_service.py:87
  ├─ crawl_jobs.create(job)                        crawl_service.py:88   ★ unconditional insert
  ├─ audit create AUDIT_CRAWL_STARTED              crawl_service.py:89
  ├─ enqueue_crawl_website(job.id)                 crawl_service.py:98
  │     └── arq.enqueue_job("crawl_website", id)   crawl.py:118          ★ no _job_id → no dedup
  └─ website.status = CRAWLING; websites.update()  crawl_service.py:100-102  ★ unconditional replace
      ▼  (ARQ queue runs the job on the worker)
crawl_website(ctx, crawl_job_id)                   crawl.py:121
  └─ _run_crawl_job_impl
     ├─ crawl_jobs.find_by_id_any(id)              crawl.py:199   (None → skip)
     ├─ status ∉ ACTIVE → skip                     crawl.py:203
     ├─ websites.find_by_id(tenant, website)       crawl.py:207   (None → job failed)
     ├─ job.status = running; crawl_jobs.update()  crawl.py:216-219  ★ unconditional replace
     ├─ publish_started / record_crawl_started     crawl.py:220-221
     ├─ job.status = processing; update()          crawl.py:267-269
     ├─ CrawlSession.run(seed_url=website.url)     crawler.py:189
     │     BFS walk, robots.txt, SSRF guard, fetch → extract → clean → checksum
     │     documents.upsert(document)              crawler.py:372 (idempotent, unique key)
     │     on_progress → crawl_jobs.update()       crawl.py:229-238 (unconditional replace)
     ├─ _purge_removed_documents(...)              crawl.py:393 (best-effort)
     ├─ terminal success:
     │     job.status = completed; update()        crawl.py:404-408  ★ unconditional replace
     │     website.status = READY; update()        crawl.py:413-420  ★ unconditional replace
     │     audit AUDIT_CRAWL_COMPLETED             crawl.py:421
     │     usage.increment(crawl_pages=stored)     crawl.py:424-429  ★ atomic $inc, not app-idempotent
     │     enqueue_process_website_documents       crawl.py:430-435  (embedding_run fences the actual pass)
     │     cache invalidation (best-effort)        crawl.py:439-449
     ├─ terminal failure paths:
     │     job.status = failed; update()           crawl.py:279-294 / 487-491 / 513-517
     │     website.status = READY|FAILED; update() crawl.py:299-311 / 493-495 / 519-521
     │     audit AUDIT_CRAWL_FAILED                crawl.py:313 / 496 / 522
     └─ transient failure: re-raise                crawl.py:557 (ARQ retries, max_tries=3)
         ▼  (post-crawl handoff)
enqueue_process_website_documents(website_id)      knowledge.py:67
  └─ process_website_documents → embedding_run fence (FIND-05) — already single-flight, untouched.
```

### 1.2 Every place a duplicate concurrent crawl could race

1. **`crawl_service.py:79` `find_active_for_website` is a TOCTOU read** — two concurrent requests both see "no active job".
2. **`crawl_service.py:88` `crawl_jobs.create` is an unconditional `insert_one`** — there is no unique constraint preventing two active jobs for one website (`backend/core/database.py:350-353`: plain `tenant_id`, `website_id`, `(tenant_id, status)`, TTL indexes only).
3. **`crawl.py:118` enqueue has no `_job_id`** — ARQ dedup is off; a duplicate job row in Mongo is always processed.
4. **`crawl.py:216-219` / `267-269` running/processing transitions are unconditional `replace_one`** — two attempts of the same job both "start".
5. **`crawl.py:404-408`, `279-294`, `487-491`, `513-517` terminal `crawl_jobs.update()` are unconditional `replace_one`** — a stale/late attempt can overwrite a newer attempt's terminal state (regression `completed` → `failed` or vice versa).
6. **`crawl.py:413-420`, `299-311`, `493-495`, `519-521` website terminal writes are unconditional `replace_one`** — last-writer-wins across any overlapping attempts, **and the replace has no `status != deleted` filter, so a mid-crawl website deletion can be visually resurrected** (see J in §6).
7. **`crawl.py:424-429` usage increment is non-idempotent at the app level** (atomic `$inc` prevents lost updates but not double-counting).
8. **`crawl.py:430-435` knowledge handoff** — double-enqueued; safe only because the embedding `embedding_run` fence (FIND-05) dedupes the actual embedding pass.
9. **Progress updates (`crawl.py:229-238`)** — benign last-writer; no fencing needed.

---

## 2. ARQ options — verified against the installed version

Installed: **arq 0.28.0** (`.venv/lib/python3.13/site-packages/arq`). Facts below are from that source, not assumed.

### 2.1 Deterministic `_job_id` + enqueue deduplication

`ArqRedis.enqueue_job(..., _job_id=...)` (`connections.py:120-181`):

- `job_id = _job_id or uuid4().hex`.
- Dedup is a WATCH/MULTI transaction on `arq:job:<job_id>`: if `arq:job:<job_id>` **or** `arq:result:<job_id>` exists → returns `None` (no-op). Otherwise writes the job and zadds to the queue.
- `arq:job:*` key TTL default = `score - enqueue_time + expires_extra_ms` (1 day, `constants.py`, `connections.py:170`).
- On **finish**, `arq:job:<id>` is deleted and `arq:result:<id>` is set with TTL = `keep_result` (`worker.py:700-704`). This repo sets `keep_result = 3600` (`workers/app.py:92`).

Consequences:

- A deterministic `_job_id` gives **idempotent re-enqueue of the _same logical job_**: a client-retried request (or a partial enqueue) cannot create a second queue entry for the same job id.
- Dedup window = while queued/running **+ `keep_result` (1 h)** after finishing. This is why the design must keep the deterministic id **scoped to the crawl job id** (`crawl:{crawl_job_id}`), **not** a static website key: a static `crawl:{tenant}:{website}` key would silently swallow legitimate manual re-crawls for up to 1 h after every completed crawl.
- With `_job_id = crawl:{crawl_job_id}` the dedup is harmless: re-enqueueing the same completed job id later re-runs `crawl_website` → loads the job → status `completed` ∉ `CRAWL_ACTIVE_STATUSES` → skip (`crawl.py:203`).

### 2.2 Execution lease (per-job, built in)

`worker.py:436-476` (`start_jobs`):

- Before starting a job the worker does a WATCH/MULTI on `arq:in-progress:<job_id>`: if it exists (another worker started it), or the job is not in the queue zset / not yet due → **skip**. Otherwise it `psetex` the key with `in_progress_timeout_s` and runs the job.
- `in_progress_timeout_s = max(function timeout_s or job_timeout_s across all functions) + 10` (`worker.py:277`). This repo `job_timeout = 600` (`app.py:91`) → **610 s**.
- The zset entry is **not** removed when the job starts; it is removed only in `finish_job` (`worker.py:706`).

### 2.3 Retry behavior

- `max_tries = 3` (`app.py:90`); transient failures re-raise (`crawl.py:557`), ARQ increments `arq:retry:<job_id>` and re-delivers. On the final try the worker records `failed` (`crawl.py:512-522`).
- `job_timeout = 600` s: `asyncio.wait_for(task, 600)` cancels an over-long crawl (`worker.py:595-604`); it is then treated as a failure and retried per `max_tries`.

### 2.4 What happens after a worker crash

- The job id stays in the queue zset; `arq:in-progress:<id>` expires after ~610 s; then **any** worker (including the restarted one) picks it up again via `zrangebyscore` (`worker.py:391-393`). The Mongo job remains `active` (pending/running/processing), so the re-delivered run resumes normally. **ARQ leases are per _job id_, not per _website_.**

### 2.5 Old job still queued/running when a new one is enqueued

- With a **job-scoped** `_job_id`: a _new_ crawl job (new id) enqueues and runs regardless — which is exactly right ("does not block legitimate manual retries").
- Only the _same_ job id is deduped while queued/running/finished-<1 h.
- If a job's `arq:job:*` key expires (< 1 day) without the job ever completing, the **Mongo** job remains active → `find_active_for_website` blocks new crawls until the TTL index (30 days) or manual cleanup. This stale-blocking hazard is **pre-existing** and independent of the chosen design (§11).

### 2.6 Is ARQ alone sufficient?

**No.** ARQ guarantees single-execution of one _job id_ and idempotent re-enqueue of one _job id_. It does **not** prevent two _different_ job rows for the same website from both running (the very duplicate `start_crawl` race). So "ARQ deterministic `_job_id` only" (Option A) cannot be the sole fix — the website-level single-flight must live in the Mongo write (Option C).

---

## 3. Is a Redis per-website lease necessary?

### 3.1 Design (for completeness, since the option was requested)

A hypothetical `crawl:lease:{tenant_id}:{website_id}` key held by the winning crawler:

- **Key format:** `crawl:lease:{tenant_id}:{website_id}` — tenant isolation is built into the key namespace.
- **Acquisition:** `SET key <token> NX EX <ttl>` where `token = crawl_job_id` and `ttl ≈ crawl_max_duration`.
- **Renewal:** periodic `PEXPIRE` guarded by token ownership → requires compare-and-delete, so **Lua** or WATCH/MULTI. `SET NX EX` alone is sufficient for _acquisition_ but not for _renewal/release_ (a renewal without ownership check could extend a dead owner's lease; a release without ownership check could free another owner's lease).
- **Release:** Lua `if GET(key) == token then DEL(key) end` (atomic compare-and-delete).
- **Crash recovery:** TTL expiry reopens the lease; an old owner that resumes after expiry is a "zombie" and must be tolerated (fail-open) or fenced out.
- **Redis unavailable:** acquisition fails → either refuse the crawl (fail-closed) or proceed (fail-open).
- **Race conditions:** TTL expiry vs renewal heartbeat (renewal must beat TTL by a margin); zombie-owner overlap after expiry; clock skew doesn't matter (Redis TTL is server-side).

**Lease lifetime:** keeping it for the _entire crawl_ is required to prevent same-website overlap; an enqueue/start-time-only lease leaves the whole crawl window unprotected unless the Mongo fence exists anyway.

**Fail-open vs fail-closed for this app:** crawls are best-effort, page upserts are idempotent, and the pipeline philosophy is "never fail the crawl for a Redis hiccup" (`crawl.py:630-631`, `crawl_events.py:47-48`). _If_ a lease were the only guard, **fail-open is safer for availability** but risks duplicate run + double usage rollup; **fail-closed is safer for accounting** but turns a Redis outage into a total crawl outage. Either way, both failure modes are strictly worse than what a Mongo write fence gives us.

### 3.2 Verdict

**Not required.** Once the crawl-job insert is fenced (Option C), at most one active `crawl_jobs` row exists per website, so at most one crawler run can ever execute — the lease is decorative. It would add: a renewal heartbeat loop, a Lua compare-and-delete, Redis-outage semantics, and a zombie-owner window after TTL expiry — a _new_ class of failure modes, with **zero added correctness** over the Mongo fence. Redis already exists in the stack, so "no new infrastructure" is not the objection; the objection is purely that the lease solves a problem the Mongo fence has already eliminated. It is noted as the enabling mechanism _if_ future ops wants stale-active override (§11), but is not recommended now.

---

## 4. MongoDB state transitions — which writes need fencing

### 4.1 `crawl_jobs` writes

| Write                          | Location                                            | Unconditional today? | Fencing needed?                          | Fence                                                                                                                                                                                     |
| ------------------------------ | --------------------------------------------------- | -------------------- | ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `create` (insert)              | `crawl_job_repository.py:53`; service `:88`         | Yes                  | **YES — this is THE single-flight gate** | Unique partial index `(tenant_id, website_id, active)` on `active: true`; duplicate → `CrawlConflictError`                                                                                |
| running/processing transitions | `crawl.py:216-219`, `:267-269`                      | Yes                  | Low (defense-in-depth)                   | Optional atomic `claim_start` (`{_id, tenant_id, status ∈ ACTIVE}` → `running`)                                                                                                           |
| terminal `completed`/`failed`  | `crawl.py:404-408`, `279-294`, `487-491`, `513-517` | Yes                  | **YES**                                  | New `finish_if_active(job_id, tenant_id, terminal_status, …)`: `find_one_and_update({_id, tenant_id, status ∈ ACTIVE} → terminal)` returns whether _this_ attempt won (single-terminator) |
| progress (`pages_*`)           | `crawl.py:229-238`                                  | Yes                  | No                                       | Last-writer is harmless                                                                                                                                                                   |

The **single-terminator** on terminal writes is what makes every later side effect (audit, usage, website write, knowledge enqueue) exactly-once _per crawl job_: only the attempt that returned `matched=True` proceeds with side effects.

### 4.2 `websites` writes

| Write                      | Location                                            | Fencing needed?             | Fence                                                                                                                                                     |
| -------------------------- | --------------------------------------------------- | --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `start_crawl` → `CRAWLING` | `crawl_service.py:100-102`                          | Yes (also record ownership) | Add `website.crawl_job_id = job.id` in this same replace                                                                                                  |
| Terminal `READY`/`FAILED`  | `crawl.py:413-420`, `299-311`, `493-495`, `519-521` | **YES**                     | New `update_if_crawl_owner(tenant_id, website_id, crawl_job_id, website)`: replace only when `{_id, tenant_id, status ≠ deleted, crawl_job_id == job.id}` |

The website fence (a) stops a stale/older attempt from overwriting a newer job's terminal website state, and (b) **prevents resurrecting a soft-deleted website** — today `websites.update()` is `replace_one({_id, tenant_id}, …)` (`website_repository.py:140-143`) with **no `deleted`/`status` filter**, so a mid-crawl deletion is overwritten back to `READY` with `deleted: false`.

### 4.3 Writes that do **not** need fencing

- `documents.upsert` — already idempotent via the unique `(tenant_id, website_id, url)` index (`document_repository.py:61-81`).
- `usage_records.increment` — atomic `$inc`; the _duplicate_ is prevented higher up (single-terminator), not by changing the increment.
- Cache invalidation, crawl-event pub/sub, audit rows (guarded by the single-terminator).
- Website **reads / non-crawl** updates (`update_website`, `delete`, `acquire_embedding_run`) — unchanged; the new `crawl_job_id` field is only _written_ by `start_crawl` and only _checked_ by the worker's terminal write.

---

## 5. Usage accounting

### 5.1 Inventory

| Accounting                  | Mechanism                                                                          | Idempotent?                    | Duplicate-crawl effect                                                                                                                                                                          |
| --------------------------- | ---------------------------------------------------------------------------------- | ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Page storage                | `documents.upsert`, unique `(tenant, website, url)`                                | **Idempotent**                 | No duplicate `documents` rows; re-crawl replaces content                                                                                                                                        |
| Daily `crawl_pages` rollup  | `usage_records` `$inc` (`usage_record_repository.py:95-121`, ADR-005 §5.5)         | Atomic, **not app-idempotent** | Two completing attempts → **double-count** `crawl_pages` (no lost update, but 2×)                                                                                                               |
| Monthly `crawl_pages` limit | `check_limit(crawl_pages)` reads `usage_events` sums (`usage_service.py:155-184`)  | Read-only                      | N/A today — **nothing records a `crawl_pages` usage_event** (only check; ADR-005 §5.5: counter "remains reserved"), so the monthly cap is currently unenforced. Adjacent finding, out of scope. |
| `documents` limit           | `check_limit(documents)` reads live `documents.count` (`usage_service.py:226-227`) | Read-only                      | Not corrupted by duplicates (count is live)                                                                                                                                                     |
| Audit events                | one `AUDIT_CRAWL_*` per job                                                        | Not app-idempotent             | Duplicate jobs → duplicate `CRAWL_STARTED`/`COMPLETED` rows; fixed by the insert fence + single-terminator                                                                                      |

### 5.2Conclusion

The only **non-idempotent counter a duplicate crawl can inflate is the daily `usage_records.crawl_pages` rollup** (plus duplicate audit/history rows). Documents are never duplicated (unique upsert). With Option C, a duplicate job row cannot be created and a duplicate completion cannot be recorded (single-terminator), so all accounting becomes exactly-once per crawl job without changing any counter code.

---

## 6. Failure / crash matrix (behavior under Option C)

| #   | Scenario                                                | Behavior today                                                                                                                                                                                                 | Behavior under Option C                                                                                                                                       |
| --- | ------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A   | Two identical requests simultaneously                   | Both pass `find_active_for_website` → two jobs → (sem=1: serial; sem=2: concurrent) duplicate crawl + double usage                                                                                             | Atomic insert fence: one wins, one gets `409 CrawlConflictError`; exactly one job/enqueue                                                                     |
| B   | Two API requests enqueue same website                   | Same as A (crawl_limiter 30/hr only narrows the window)                                                                                                                                                        | Same as A — void after fence                                                                                                                                  |
| C   | Worker A starts crawl, worker B gets duplicate job      | Impossible today (only one job id is enqueued once) — but if two job rows existed, both run                                                                                                                    | Can't exist; the same job id also cannot run twice (ARQ `in_progress` lease, `worker.py:450-476`)                                                             |
| D   | Worker A crashes mid-crawl                              | Job left active; ARQ re-delivers after ~610 s (zset + in-progress expiry); run resumes                                                                                                                         | Same re-delivery; all fences make the re-run safe (single-terminator, website owner fence); no duplication                                                    |
| E   | Worker A loses Redis during crawl                       | Progress pub/sub best-effort; ARQ may time out/cancel → retry; overlap possible at Mongo                                                                                                                       | Retry overlaps guarded: status fence ≈ exactly one terminal writer; website fence; usage/audit recorded only by the terminal winner                           |
| F   | Redis restarts while crawl active                       | Redis client retry/backoff; job continues or is re-delivered                                                                                                                                                   | Same as E                                                                                                                                                     |
| G   | Worker A finishes but crashes before "releasing a lock" | No app lock with Option C; terminal Mongo writes already committed → re-delivery loads `completed` → skip (`crawl.py:203`)                                                                                     | Same — nothing to release; safe                                                                                                                               |
| H   | Crawl retry after `job_timeout` (600 s)                 | ARQ cancels → retry (max_tries=3) → final try marks `failed`                                                                                                                                                   | Same; final `failed` goes through `finish_if_active`; website write fenced; abort does not delete docs or re-enqueue knowledge                                |
| I   | Old crawl finishes after newer crawl started            | Possible when a stale attempt resumes; unconditional replaces regress website/job state                                                                                                                        | Blocked: unique active-job fence prevents two _jobs_; `crawl_job_id` website fence + status fence stop a _stale attempt_ writing after a newer attempt        |
| J   | Website deleted mid-crawl                               | **Resurrection bug**: `websites.update()` replaces `{_id, tenant_id}` with no `deleted` filter, so the running crawl can set a soft-deleted website back to `READY` (and re-insert documents after the purge). | Website terminal writes fenced on `status ≠ deleted` → no resurrect; a later re-entry finds `website is None` (`crawl.py:207-214`) and fails the job properly |
| K   | Manual retry while a crawl is active                    | `409` via `find_active_for_website`                                                                                                                                                                            | Same UX; now race-free                                                                                                                                        |
| L   | Two replicas process different jobs for same website    | Both run (duplicate work, races)                                                                                                                                                                               | Impossible — one active job row exists; also the same job id cannot run twice (ARQ lease)                                                                     |

---

## 7. Comparison of designs

| Dimension                     | A: ARQ `_job_id` only                                             | B: Redis lease only                                                              | C: ARQ `_job_id` + Mongo fencing                                                   | D: Redis lease + Mongo fencing                         | E: Redis lease + `_job_id` + Mongo fencing |
| ----------------------------- | ----------------------------------------------------------------- | -------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------ | ------------------------------------------ |
| Correctness (duplicates)      | **Fails** — dedups only the _same_ job id; two job rows still run | Cross-replica duplicate prevention only _while_ lease is held; TTL/zombie window | **Passes** — atomic insert = one active job/website; ARQ lease = one execution/job | Passes (Mongo fence is the guarantor; lease redundant) | Passes (same)                              |
| Crash recovery                | Via ARQ `in-progress` re-delivery                                 | Lease TTL reopens; zombie owner risk                                             | Via ARQ re-delivery + fenced re-entry                                              | Lease + ARQ re-delivery                                | Same                                       |
| Duplicate prevention strength | Weak (single job id)                                              | Medium (best-effort; zombie window; Redis outage)                                | **Strong** (Mongo is the source of truth)                                          | Strong (redundant)                                     | Strong (redundant)                         |
| Implementation complexity     | Trivial (1 line)                                                  | High (renewal loop, Lua CAS, outage semantics)                                   | **Low** (1 index + 2 fenced repo methods + a few call sites)                       | High+Low                                               | High+Low+1 line                            |
| Redis dependency              | Already required by ARQ                                           | Lease adds new keys/Lua/outage handling                                          | **Unchanged** (ARQ only)                                                           | New lease keys                                         | New lease keys                             |
| Mongo dependency              | Unchanged                                                         | Unchanged                                                                        | **1 unique partial index + fenced writes, no transactions**                        | Same                                                   | Same                                       |
| Operational risk              | Stale duplicate jobs still possible                               | Lease expiry/zombie + Redis outage = crawl availability decisions                | **Lowest** — stale active is the only residual (pre-existing, §11)                 | Low + lease op risk                                    | Low + lease op risk                        |
| Suitability for WebChat AI    | Not suitable alone                                                | Over-engineered; introduces its own failure modes                                | **Best fit** — smallest change, no new infra                                       | More moving parts for zero added correctness           | Same as D                                  |
| Implement now?                | Only the `_job_id` piece, as part of C                            | **No**                                                                           | **Yes (recommended)**                                                              | No                                                     | No                                         |

**Rejected alternatives:** Redis lease (B/D/E) — redundant once the Mongo insert fence exists, and it introduces TTL/zombie/Redis-outage failure modes with no correctness gain. Mongo **transactions** — rejected because the fence needs only one atomic special write (unique index), no multi-document transaction. A static per-website ARQ `_job_id` — rejected because its 1 h `keep_result` dedup window silently swallows legitimate manual re-crawls.

---

## 8. Recommendation

**Option C: ARQ deterministic `_job_id` (idempotent re-enqueue) + MongoDB conditional/fenced state writes.**

Why it meets every requirement:

- **Preserves current behavior / works with one replica** — the common path is byte-for-byte the same; fences only fire on a genuine duplicate or stale attempt; all existing worker/service tests stay green.
- **Safe with multiple replicas** — the unique partial index makes the crawl-job insert atomic, so only one active job per website can ever exist; ARQ's per-job `in_progress` lease makes the same job id execute on exactly one worker; fenced terminal/website writes make overlaps harmless.
- **Handles worker crashes** — ARQ re-delivery (zset + `in-progress` TTL, ~610 s) is preserved; the fenced re-entry and single-terminator make the re-run idempotent.
- **No Mongo transactions** — only `find_one_and_update` + one unique index.
- **No unnecessary infrastructure** — nothing new beyond one index and one boolean field; no Redis lease keys.
- **Preserves tenant isolation** — fence key is `(tenant_id, website_id)`; the unique index is per-tenant.
- **Does not break ARQ retries** — `max_tries=3`, `job_timeout=600` untouched; the worker still re-raises for transient failures and only terminal transitions go through the fence.
- **Does not block legitimate manual retries** — `_job_id` is job-scoped (`crawl:{job_id}`), so a _new_ job always enqueues; a re-crawl after completion is never swallowed by ARQ dedup.

---

## 9. Implementation plan (file-by-file)

### 9.1 `backend/models/crawl_job.py`

- **Current:** `CrawlJob` has `status`, no single-flight marker.
- **Change:** add `active: bool = True` (participates in `to_doc`/`from_doc` automatically; `extra="allow"` already tolerates legacy docs).
- **Why:** a partial unique index needs an equality-filtered boolean; `active` mirrors `status ∈ CRAWL_ACTIVE_STATUSES` and is flipped `False` on terminal.
- **Race addressed:** concurrent active-job creation.

### 9.2 `backend/core/database.py` (`MongoDatabase.init_indexes`, near `:350-353`)

- **Current:** plain `tenant_id`, `website_id`, `(tenant_id, status)` indexes on `crawl_jobs`.
- **Change:**
  1. Idempotent backfill: `update_many({status: {$in: ACTIVE}}, {$set: {active: True}})` and `update_many({status: {$nin: ACTIVE}}, {$set: {active: False}})`.
  2. `db["crawl_jobs"].create_index([("tenant_id", 1), ("website_id", 1), ("active", 1)], unique=True, partialFilterExpression={"active": True})`.
- **Why:** the atomic single-flight gate.
- **Race addressed:** the `start_crawl` TOCTOU — the second simultaneous insert hits `DuplicateKeyError` instead of both succeeding.

### 9.3 `backend/repositories/crawl_job_repository.py`

- **Current:** `create` = `insert_one`; `update` = `replace_one({_id, tenant_id})`; `find_active_for_website` = plain read.
- **Change:**
  1. `create`: catch `DuplicateKeyError` → raise `CrawlConflictError` (`core/errors.py`) and keep the failure branch at the **repository boundary** so the service and test fakes share the semantic.
  2. Add `async def finish_if_active(self, job_id: str, tenant_id: str, *, terminal_status: str, completed_at: datetime | None = None, **fields: Any) -> bool` → `find_one_and_update({"_id": job_id, "tenant_id": tenant_id, "status": {"$in": sorted(ACTIVE)}}, {"$set": {**fields, "status": terminal_status, "active": False, "completed_at": completed_at, "updated_at": now}}, return_document=AFTER)`; return `True` iff matched (single-terminator; also the owner-claim of all side effects).
  3. Optional (defense): `claim_start(job_id, tenant_id)` atomically `pending|running|processing → running`.
  4. Update `create`/`update` in the **Protocol** too.
- **Why:** makes the terminal transition atomic and ownership-bearing; keeps progress updates cheap and unfenced.
- **Race addressed:** two attempts both "winning" completion (I, E, H); duplicate active jobs (A, B, L).

### 9.4 `backend/workers/jobs/crawl.py`

- **Current:** activity as traced in §1.
- **Change:**
  1. `enqueue_crawl_website` (`:116-118`): `enqueue_job("crawl_website", crawl_job_id, _job_id=f"crawl:{crawl_job_id}")` — idempotent re-enqueue of the same job.
  2. Terminal **success** path (`:404-421`): replace the `job.status = completed; update()` block with `won = await crawl_jobs.finish_if_active(job.id, job.tenant_id, terminal_status=COMPLETED, completed_at=now, pages_completed=stored, pages_total=…, errors=session.errors, error_message=None)`; gate `websites` write (`readied` below), audit, `_record_crawl_pages`, `enqueue_knowledge`, and cache invalidation on `won`. Log + return unchanged when `won=False` (a newer attempt already finished).
  3. Terminal **failure** paths (zero-page `:279-294`, `InvalidUrlError` `:487-491`, final-retry `:513-517`): same `finish_if_active(..., terminal_status=FAILED, ...)` pattern; side effects (audit, `record_crawl_failed`, metrics, website write) gated on `won`.
  4. Website writes (`:413-420`, `:299-311`, `:493-495`, `:519-521`): switch to `websites.update_if_crawl_owner(tenant_id, website_id, job.id, website) -> bool`; if `False` (newer owner or deleted), log a warning and skip.
- **Why:** single-terminator for exactly-once side effects; website-owner fence for stale/deleted protection; job-scoped `_job_id` for idempotent enqueue.
- **Race addressed:** E/F (lens of overlaps), G, H, I, J.

### 9.5 `backend/models/website.py`

- **Change:** add `crawl_job_id: str | None = None` (last/current crawl that owns the terminal write; mirrors the embedding-run idiom already in this model).
- **Why:** ownership token for fencing website writes.

### 9.6 `backend/repositories/website_repository.py`

- **Change:** add `async def update_if_crawl_owner(self, tenant_id: str, website_id: str, crawl_job_id: str, website: Website) -> bool` → `replace_one({"_id": website_id, "tenant_id": tenant_id, "status": {"$ne": WEBSITE_STATUS_DELETED}, "crawl_job_id": crawl_job_id}, website.to_doc())`, return `matched_count > 0`. Add to Protocol.
- **Why:** prevents stale/deleted overwrites without touching the general `update` used by services/tests.
- **Race addressed:** J (deleted resurrect), I (old crawl regressing newer state).

### 9.7 `backend/services/crawl/crawl_service.py`

- **Current:** `start_crawl` relies on TOCTOU pre-check; enqueues then replaces website (`:79-102`).
- **Change:** keep `find_active_for_website` as a _fast-path_ 409, but treat `CrawlConflictError` from `create` as authoritative; set `website.crawl_job_id = job.id` in the `CRAWLING` replace (`:100-102`).
- **Why:** the insert fence is the real gate; ownership recorded at enqueue time (matches the worker's later terminal write).
- **Race addressed:** A, B, K.

### 9.8 `tests/fakes.py`

- `FakeCrawlJobRepository`: `create` → raise `CrawlConflictError` on active (tenant, website); add `finish_if_active` (mirror predicate + `active=False`) and optional `claim_start`.
- `FakeWebsiteRepository`: add `update_if_crawl_owner` (mirror fence; refuse on deleted/foreign job id).
- `FakeCrawlEnv`/`build_crawl_env` (`tests/crawl_helpers.py`): unchanged (fakes absorb the new methods).

### 9.9 Out of scope (explicitly)

- No change to `embedding_run` fencing / knowledge single-flight (FIND-05 work already landed at `e93aca5`).
- No change to `documents.upsert`, `usage_records.increment`, cache, SSE, admin surfaces.
- No transactions, no Redis lease, no Lua scripts, no scheduled/automatic crawl.

---

## 10. Test plan

New file `tests/test_crawl_single_flight.py` (+ small additions to `test_crawl_service.py` / `test_crawl_worker.py`), mirrors of the embed-run lifecycle tests:

| Concern                         | Test                                                                                                                                                                                                                   |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Simultaneous enqueue            | `asyncio.gather` two `start_crawl` for the same website → exactly one wins, one raises `CrawlConflictError`; one job row; one enqueue; website `CRAWLING` once                                                         |
| Duplicate execution             | Re-invoke `_run_crawl_job_impl` for an already-`completed` job → `{"status": ...}` skip, no side effects                                                                                                               |
| Lock acquisition (insert gate)  | Repo-level: second active `create` for same `(tenant, website)` raises; after `finish_if_active(completed)`, `create` succeeds (lock released)                                                                         |
| Lock ownership                  | `finish_if_active` returns `True` once, then `False` for a second (stale) attempt; side effects only on the winner                                                                                                     |
| TTL / expiry                    | (no Redis lease) — cover `active` flag flip on terminal and re-acquire; assert the partial unique index is created by `init_indexes` (database init test)                                                              |
| Crash / retry                   | Worker final-retry marks `failed` through `finish_if_active` exactly once (extend `test_worker_final_retry_marks_failed`); re-delivery after crash leaves the run resumable                                            |
| Stale-owner release             | After a failed crawl, `start_crawl` is allowed again (existing `test_start_crawl_allows_new_job_after_completion` + active-flag variant)                                                                               |
| Redis failure                   | FakeARQ: enqueue with `_job_id` dedups re-enqueue of the same job id (second `enqueue_job` returns `None`) and **does not** dedup a _new_ job id (manual retry works)                                                  |
| Mongo fencing                   | `finish_if_active` no-ops once terminal; website `update_if_crawl_owner` refuses for foreign `crawl_job_id` / deleted website                                                                                          |
| Old crawl cannot overwrite new  | Start crawl J1, simulate newer owner J2 (`website.crawl_job_id = J2`), J1's terminal website write returns `False` and state stays J2's                                                                                |
| Tenant isolation                | Same `website_id` under two tenants → both allowed (unique key is per tenant)                                                                                                                                          |
| Usage accounting                | Two overlapping attempts: only the terminal winner increments `crawl_pages`; counter increments exactly once per completed job (extend `test_crawl_success_increments_crawl_pages` with a stale-attempt replay)        |
| Manual retry                    | Immediately after `completed`, `start_crawl` succeeds (no ARQ `keep_result` swallow) with a new job id                                                                                                                 |
| Existing single-worker behavior | Entire existing suite must pass unchanged: worker transitions, zero-page, purge, cache invalidation, SSE events, admin lists, tenant scoping, `_job_id` arg must be forward-compatible with the FakeArqRedis signature |

Gate: `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy backend` / `uv run pytest` (expected 2397 + new tests).

---

## 11. Remaining risks

1. **Stale active job blocks future crawls (pre-existing, unchanged).** If a worker dies permanently and ARQ's `arq:job:*` key expires (~1 day) before re-delivery, the Mongo `active` job blocks `start_crawl` for that website until the `crawl_jobs` TTL index (30 d) or manual cleanup. This exists identically today (a crashed worker already leaves a `pending` job behind). Recommendation for a follow-up: a maintenance script/ops runbook to release/re-run stale active crawl jobs (mirroring the embedding-run reset script added with FIND-05).
2. **`update_website` URL change during an active crawl** is not fenced by this design (out of FIND-02 scope): the crawl may finish and set `READY` with content crawled from the _old_ seed. Flagged for a future fence on `website.url`/`status` in the terminal write if desired.
3. **Monthly `crawl_pages` limit is not actually enforced** — no code records a `usage_event` for crawled pages (ADR-005 §5.5 reserves the counter). Adjacent gap, tracked separately from FIND-02.
4. **`finish_if_active`/`update_if_crawl_owner` add one round-trip each** on the terminal path — negligible.
5. Enqueue still has no durability guarantee end-to-end (enqueue failure after job insert leaves an active-but-never-run job). Pre-existing; ARQ re-opens the queue when Redis returns.

---

## Appendix A — rejected alternatives, condensed

- **Option A (ARQ `_job_id` only):** can only dedup the _same_ job id; the two-request TOCTOU creates _two different_ job ids that both run. Not sufficient.
- **Options B/D/E (Redis lease):** redundant once the Mongo insert fence exists; adds TTL/zombie/Redis-outage failure modes with no correctness gain. Fail-open vs fail-closed is decision-forcing where Mongo fencing is not.
- **Static per-website ARQ `_job_id`:** dedup window = run + `keep_result` (1 h) silently swallows manual re-crawls. Violates "does not block legitimate manual retries".
- **Mongo transactions / `$or`-upsert lock doc:** the unique partial index is simpler and race-free; upsert-with-`$or` inserts the query's non-operator fields (`_id` collisions, operator-field injection footguns) and needs no more correctness than one index.

---

_This document is a design report only. No source/test/config files were modified. Nothing was committed or pushed._
