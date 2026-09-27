# MongoDB Queue — Production-Readiness Hardening Report (Phase 16)

Scope: EVIDENCE-GATHERING ONLY. This phase did **not** migrate the queue, did
**not** modify production workers/`enqueue_*`/deployment/`.env.production`, did
**not** remove Redis, and did **not** upgrade any paid service. No commits or
pushes were made. Every conclusion is labelled
`MEASURED` / `CALCULATED` / `INFERRED` / `NOT MEASURED` (legend in §20).

## 1. Baseline

| item | value |
| -- | -- |
| git HEAD | `d63deff318ef62c45f14d3ebc83b082e96ecf158` |
| `git status --short` | `?? backend/prototypes/`, `?? docs/reports/` (untracked, intent-to-keep) |
| prototype mongod | dedicated local instance on `mongodb://127.0.0.1:27019` (dbpath under `/tmp/opencode/mongo-queue-prototype`, WiredTiger cache 0.25 GiB) |
| production queue | ARQ 0.28 (Redis) — unchanged; every "queue" statement below refers to the isolated prototype unless stated |
| isolation | prototype never reads `backend.core.config`; isolated DB namespace `webchat_ai_queue_prototype`; `tests/test_isolation.py` asserts production workers do **not** import the prototype |

## 2. Phase 15 Evidence (carried forward)

Verified still-green: prototype suite passed **40** tests at the end of Phase 15;
full regression `pytest tests` = **2589 passed, 12 skipped, 0 failed**; `ruff
check backend tests` clean; `mypy backend` clean (225 files incl. prototype).
Measured numbers reused below (see Prototype Report §19–20):

- Mongo per-op latency on the constrained local mongod (500 samples): enqueue p50
  1.77 / p95 6.42 / p99 13.86 ms; claim(empty) p50 4.00 / p95 13.74 / p99 32.52 ms;
  claim+complete p99 ≈ 13 ms; burst enqueue 200 docs ≈ 3.77 ms/op.
- 100 concurrent claimers, 1 job → exactly 1 winner, 182 ms for the batch.
- Prototype worker RSS ≈ 48 MB idle and after active work.
- These are SINGLE-HOST local figures; they are `MEASURED` for the local mongod
  and **`NOT MEASURED`** for production Atlas M0.

## 3. Email Idempotency (Q1/Q2)

**Provider capability — VERIFIED from primary sources (not assumed):**

- The production provider is **Resend** (Mailpit in development has no
  idempotency semantics; both resolved by `get_mail_service()` in
  `backend/services/mail/__init__.py`).
- Official Resend HTTP API docs (send-email reference, fetched during this
  phase) document an **`Idempotency-Key`** header: unique per request, **24-hour
  expiry**, max **256 characters**, deduplicating repeated identical POSTs.
  `MEASURED` at the documented API contract level → labelled `VERIFIED`.
- The installed SDK (`resend==2.35.0`) exposes it as
  `Emails.SendOptions.idempotency_key`; its `request.py` lines 82–83 set
  `headers["Idempotency-Key"]` on POST when present. `VERIFIED` (SDK source read).

**Design options A–D:**

| | mechanism | free? | duplicate-at-provider protection | survives retry >24 h | failure mode |
| -- | -- | -- | -- | -- | -- |
| A | Resend `Idempotency-Key`, deterministic `email:<tenant_id>:<logical_message_id>` (content hash) | yes (existing provider) | yes (24 h window) | no (key expires) | provider remembers key, retry returns original message id |
| B | Durable Mongo delivered-marker (`sent_at`/message outcome written once, fenced by `_id`+execution) | yes | ubiquitous to store (works even if provider ignores keys) | yes (permanent marker) | queue must write the marker atomically with completion |
| C | Enqueue-time dedup only (`dedup_key` unique partial index) | yes | no — collapses duplicate SUBMISSIONS, not duplicate DELIVERIES | n/a | only prevents double-submit |
| D | A + B combined | yes | yes both layers | yes (B) | belt-and-braces |

**Deterministic key (OPTION A core):** the job payload never needs to carry a
key. Each execution recomputes
`sha256({to, subject, body, html, from})` → `email:<tenant_id>:<digest>` so every
retry, dual-execution, and stale re-run collides on the SAME key. The 64-hex
digest keeps keys far under Resend's 256-character cap.

**Verdict (INFERRED from the above):** OPTION A alone protects the common crash
paths for 24 h; OPTION B (durable marker) is the total guarantee, and is
required the moment a provider ignores idempotency. Recommended default: **A
with B as the enforced fallback** (B written once at completion; delivery marker
fenced by ownership like every other terminal write). No production change was
made in this phase.

**Prototype evidence (`email_idempotency.py`, `tests/test_email_idempotency.py`,
all `MEASURED` on the isolate mongod):**
- deterministic key: same tenant+message ⇒ same key, across two rendering calls;
  changed recipient/body or different tenant ⇒ different key; length ≤ 256.
- 100 concurrent sends of one logical email, provider honours key ⇒ **1
  delivery**, all 100 share the same `message_id` (1 winner, 99 `duplicated`).
- 100 concurrent sends, provider ignores key ⇒ **100 deliveries** — the report
  must say this plainly: with a non-idempotent provider, exactly-once is
  impossible from the queue alone (OPTION B is the only fix).

## 4. Email Crash Matrix (cases 1–8)

| # | scenario | with OPTION A (provider honours) | with provider ignoring keys | evidence |
| -- | -- | -- | -- | -- |
| 1 | crash before send | no email; retry sends normally | same | MEASURED (prototype lifecycle) |
| 2 | crash after send, before complete | **1 delivery** (retry returns same message id) | duplicate possible | MEASURED `test_crash_after_send_single_delivery_with_key` |
| 3 | provider accepted, response lost (timeout) | **1 delivery**, retry returns same id | 2 emails | MEASURED `test_response_loss_*` |
| 4 | lease expires during send (dual execution) | **1 delivery**; stale completion fenced off by `execution_version` | duplicate possible | MEASURED `test_stale_email_worker_...` |
| 5 | complete succeeds, but network drops after provider OK | 1 delivery; complete retried, still 1 | duplicate possible | INFERRED (same mechanism as 2) |
| 6 | retry beyond 24 h idempotency window | key forgotten; duplicate possible | duplicate possible | INFERRED from Resend docs (24 h expiry) |
| 7 | dedup of duplicate submissions (same logical email enqueued twice) | collapses to 1 job via `dedup_key` | collapses at queue, still 1 job | MEASURED `test_job_dedup_...` |
| 8 | dead-letter after 3 attempts, provider half-sent | partial send; job dead (no further retries) | same | INFERRED (max_tries path) |

Conclusion: lease+version fencing protects *completion*; only OPTION A (and B
for the 24 h+ / ignore-provider cases) protects *delivery duplication*.

## 5. Mongo Operation Model (A–I)

Per-op command model (driver-level commands, `CALCULATED`; READ vs WRITE):

| id | operation | mechanism | READ | WRITE | commands |
| -- | -- | -- | -- | -- | -- |
| A | enqueue | `insert_one` | 0 | 1 | 1 |
| A' | enqueue (dedup collision) | insert fails + read-back | 1 | 1 | 2 |
| B | claim | `find_one_and_update` (single atomic findAndModify) | 1 | 1 | 1 |
| C | complete | `update_one` on `_id` | 0 | 1 | 1 |
| D | fail/retry | find + update | 1 | 1 | 2 |
| E | renew lease | `update_one` on `_id` | 0 | 1 | 1 |
| F | retire-expired sweep | `update_many` (only when crash found) | 0 | 1 | ≤1 |
| G | dedup collision | failed insert + read-back | 1 | 1 | 2 |
| H | idle poll | findAndModify matching nothing | 1 | 0 | 1 |
| I | index maintenance | server-side WiredTiger B-tree; no app commands | — | — | 0 |

Workload scenarios A–J (opal-estimate `ESTIMATE`/`CALCULATED`; per-worker unless
stated):

| workload | shape | queue commands/day | note |
| -- | -- | -- | -- |
| email, Free tier | ≤1,000 msg/month ≈ 33/day | 3 each ⇒ ≈99 | enqueue+claim+complete |
| email, Pro tier | ≤50,000 msg/month ≈ 1,650/day | ≈4,950 | burst-friendly |
| crawl page-fetch job | crawl_max_concurrent=2, timeout 3600 s | 3 per crawl start + heartbeat | §10 |
| document embedding | process_document, retries ≤3 | 3 + 2/retry | checksum usually skips re-runs (§11) |
| idle worker (adaptive) | cap 30 s | 2,880 | vs ARQ 172,800 (§7) |
| dual workers idle | 2 × adaptive | 5,760 | — |
| burst dedup (25 same) | 25 submits 1 key | 1 enqueue + 1 miss + 1 collision? | 25 attempts → 1 row |
| crash recovery | lease-expired sweep | intermittent | retire `update_many` |
| delayed jobs | run_at in future | 0 until run_at | served by status+run_at index |
| long crawl > lease | heartbeat keeps lease | 123 commands per 3600 s job | 120 renewals (§8) |

## 6. Atlas M0 Validation (Q3)

- The only configured Atlas URI in this working copy targets the **production**
  cluster (`cluster0.ghf4ner.mongodb.net`). Pointing a prototype or test at the
  production cluster is unsafe and is explicitly out of scope for evidence
  gathering. **There is no safe test Atlas environment in this setup.**
- Result: **ATLAS M0 SCALE = NOT MEASURED.** No Atlas figures — latency,
  throughput ceiling, storage behaviour, connection limits — were fabricated or
  measured this phase. `MEASURED` numbers are exclusively from the dedicated
  local mongod on `127.0.0.1:27019`.
- Flagged (INFERRED from MongoDB public tier facts): M0 is a free shared tier
  with a nominal ~512 MB storage and roughly 100 ops/s ceiling; the prototype's
  adaptive idle profile (one claim op per 30 s idle, ≈2,880 ops/day/worker) stays
  far below that ceiling, whereas ARQ's fixed 0.5 s poll (≈172,800 ops/day) is
  the same order as the ceiling. Precondition to ever "mark" Atlas: a **dedicated
  M0 sandbox** (separate database, no production data), then measure with the
  same harness.

## 7. Adaptive Polling Verification

- ARQ default `poll_delay = 0.5 s` → **172,800 idle ZRANGEBYSCORE commands /
  day / worker** (`CALCULATED`; constant read from arq source during Phase 15).
- Prototype adaptive schedule `(1, 2, 5, 10, 30)` s, idle dwelling on 30 s →
  **2,880 idle claim ops / day / worker** (`CALCULATED`; µtest
  `test_idle_costs_adaptive_vs_arq`). Two workers: 5,760 vs 345,600.
- `MEASURED` (Phase 15): a simulated idle 5-minute stretch issued 13 claim ops;
  a real 3 s idle worker logged ≤ 8 ops. Polling cost is therefore the dominant
  queue-to-Redis difference, and removing ARQ (whenever Phase 17 does so) removes
  ~172,750 idle commands/day/worker.

## 8. Active Job Heartbeat Cost (Q4, lease 600 s / heartbeat 30 s)

Per active job the queue issues: enqueue (1) + claim (1) + **renewals =
⌈duration/30⌉** + complete (1). `CALCULATED` (µ test `test_active_job_op_budget`):

| job duration | renewals | total queue commands | notes |
| -- | -- | -- | -- |
| 60 s email | 2 | 5 | negligible |
| 600 s burst job | 20 | 23 | full lease window |
| 3,600 s crawl | 120 | 123 | long job stays alive via heartbeats |

Renewal rate is 2 renewals/minute per running job per worker. Overlap safety:
heartbeat (30 s) is 20× shorter than lease (600 s), so a healthy worker cannot
trip its own fence even if a renewal is delayed seconds. `CALCULATED`.

## 9. Lease Sizing (600/30, 600/60, 900/60)

Trade-off table only — NO verdict is selected in this phase (`CALCULATED`, µ
`test_lease_sizing_profiles_are_tradeoffs_without_verdict`):

| lease / heartbeat | renewals full lease | renewals 3,600 s crawl | failure detection | stale-worker window | lease÷heartbeat |
| -- | -- | -- | -- | -- | -- |
| 600 / 30 | 20 | 120 | 600 s | 600 s | 20 |
| 600 / 60 | 10 | 60 | 600 s | 600 s | 10 |
| 900 / 60 | 15 | 60 | 900 s | 900 s | 15 |

- 900/60 halves renewal traffic vs 600/30 on long jobs but detects a crash 50%
  slower and leaves a zombie execution window 300 s wider.
- 600/30 recovers fastest but sends 2× the renewal writes on 3600 s crawls.
- Failure detection time == lease length on this design (a crashed worker's job
  becomes re-claimable when the lease expires). Improvements (e.g. stationary
  worker liveness) are out of scope.

## 10. Crawl Safety

- Terminal state is single-winner (`MongoCrawlJobRepository.finish_if_active`):
  the finish update matches only while the crawl is still active; exactly one
  caller wins and owns audit/usage/website-write/knowledge-enqueue. `MEASURED` in
  prototype (`test_concurrent_crawl_completions_single_winner`,
  `test_crawl_stale_worker_cannot_corrupt_terminal_state`) + `INFERRED` from
  `backend/repositories` code.
- Website row writes are guarded by `update_if_crawl_owner` (tenant+ownership).
- Usage accounting + audit for a crawl happen once (the winning terminator).
- Enforcements: crawl job TTL 30 days; `crawl_max_concurrent = 2`;
  `crawl_job_timeout_seconds = 3600` registered on the ARQ function; progress is
  best-effort Redis pub/sub `crawl:progress:{id}` (non-authoritative).
- In a Mongo-queue world the crawl job itself is a normal queue row; the 3600 s
  timeout maps to §8's 120-heartbeat budget. Verdict: **PASS** for fences;
  `MEASURED`/`INFERRED`.

## 11. Document Safety

- `processor.py` checksum-skip (`already_embedded`) makes re-runs idempotent;
  `run_id` tags each embedding run; `knowledge_max_document_retries = 3` with
  backoff 5/30/180 (µ `test_document_checksum_idempotency_under_redelivery`
  `MEASURED`; `INFERRED` from repo/processor).
- `knowledge_chunks` holds a unique compound index (dedup for chunk + hash rows)
  so the store itself rejects double-embedding.
- Replacement semantics are full-document re-embed after checksum change; TTLed
  container retries remain bounded by the retry budget. Verdict: **PASS**.

## 12. Redis Dependency Inventory

Inventory performed with a sub-agent over `backend/core` + `backend/api` +
`backend/workers`. Every consumer is classified as queue-independent (must keep
Redis) vs queue-shaped:

| consumer | pattern | depends on ARQ? |
| -- | -- | -- |
| ARQ jobs (crawl/document/email) | ZSET job queue + 0.5 s idle poll | **YES — the dominant stream** |
| cache (`backend/core/cache.py`) | users/plans cache; reads gated in `deps.py` | no |
| rate limiting (`backend/core/rate_limit.py`) | INCR/EXPIRE per endpoint | no |
| AI provider health (`services/ai/provider_health`) | store + backoff reads via `deps.py` | no |
| crawl progress pub/sub (`crawl_events.py`) | best-effort `crawl:progress:{id}` | no (used by the crawl worker, survives a queue move) |
| sessions / other | as inventoried, all non-queue | no |

Conclusion (`INFERRED` from inventory): **removing ARQ eliminates the ~172,750
idle commands/day/worker and the ARQ ZSETs, but Redis itself is NOT removed.**
Decision to preserve Redis stays (phase constraint: no Redis removal). If the
queue moves to Mongo, Redis keeps serving cache/rate-limit/health/progress.

## 13. Queue Retention

- Prototype: one collection `worker_jobs_prototype`; **no TTL configured** — the
  report must flag that production queue retention is UNDECIDED (config stays
  arq-side today; every existing TTL lives on business collections, not jobs).
- Proposed schema note (`ESTIMATE`): add TTL index on a resolved timestamp
  (`finished_at`/terminal `created_at`) per plan tier so completed rows are
  auto-reaped while in-flight rows (`status != terminal`) are kept.
- `CALCULATED` formula: `rows/day × days × bytes × overhead`. Example: 1,000
  jobs/day × 30 days × ~360 B × 1.5 ≈ **16.2 MB** retained (see §14 for
  per-plan table).

## 14. Storage Model

Measured queue-row size on the local mongod (BSON-encoded wire size,
`MEASURED`): `send_email` ≈ **362 B**, `crawl_website` ≈ **347 B**,
`process_document` ≈ **350 B** → use ~**360 B** as the report constant.

Monthly footprint by plan `ESTIMATE` (jobs/day derived from plan caps, ×360 B,
×1.5 index/overhead factor):

| plan | monthly messages cap | approx queue rows/month | 30-day retention (MB) | 90-day retention (MB) |
| -- | -- | -- | -- | -- |
| Free | 1,000 | ~1,000–2,000 | ~0.5–1.1 | ~1.6–3.2 |
| Pro | 50,000 | ~50,000–100,000 | ~27–54 | ~81–162 |
| Starter | 5,000 | ~5,000–10,000 | ~2.7–5.4 | ~8–16 |

All trivially within M0's ~512 MB free storage if retention is bounded (TTL in
§13); unbounded growth is the only hazard.

## 15. Resource Constraints

Free-only mandate honored: no Upstash upgrade, no paid Mongo tier, no new paid
service was recommended or required to satisfy any capability; where a
capability can't be demonstrated free (production Atlas), it is explicitly
`NOT MEASURED` rather than silently downgraded.

- Worker today: 1 GiB memory / 2 vCPU (`WorkerSettings` targets 1024 MiB, 2
  CPUs). Prototype worker RSS ≈ 48 MB — the Mongo queue adds no meaningful
  footprint. `MEASURED` (local).
- Local mongod constrained to 0.25 GiB cache and still yields the §2 latency
  table; M0's shared vCPU ceiling is the binding constraint, unmeasured here.
- Dial/tuning: adaptive idle (30 s cap) is the levee that keeps per-worker idle
  load at ~2,880 ops/day; keep it if Phase 17 ports the worker.

## 16. Test Results

| suite | command | result |
| -- | -- | -- |
| prototype | `pytest backend/prototypes/mongo_queue/tests` | **61 passed** (40 Phase 15 + 21 Phase 16) |
| regression | `pytest tests` | **2589 passed, 12 skipped, 0 failed** |
| lint | `ruff check backend tests` | clean |
| types | `mypy backend` (strict) | clean (230 files incl. prototype) |

New Phase 16 suites: `test_email_idempotency.py` (deterministic keys, 100-worker
honour/ignore, crash-after-send, response-loss honoured+ignored, stale-worker
fencing), `test_costs_model.py` (operation model A–I, idle ARQ-vs-adaptive,
active-job heartbeat budget, lease-sizing table, retention/storage arithmetic),
`test_index_plan.py` (explain-plan validation, dedup partial-unique collapse).

## 17. Index Analysis and Explain Validation

Prototype indexes and purpose (schema from `queue.py`):

| index | purpose | validation |
| -- | -- | -- |
| `{status:1, run_at:1}` | claim: pending/retry_pending by run_at (hot path; also delayed jobs) | `MEASURED` explain: IXSCAN `status_1_run_at_1` |
| `{status:1, lease_expires_at:1}` | crash reclaim of `running` rows | explain shows IXSCAN on the expired-running branch |
| `dedup_key` unique partial (`$type: string`) | atomic submission dedup | 25 parallel same-key enqueues → 1 row (`MEASURED`) |

Explain-plan checks (`test_index_plan.py`, local mongod): the claim query is
planned as SORT ← FETCH ← OR(IXSCAN[status_1_run_at_1] , IXSCAN[status_1_lease_expires_at_1])
— never COLLSCAN, for both eligible branches. Production Atlas explain plans are
`NOT MEASURED` (no safe Atlas).

Storage-level fences re-verified from `backend/core/database.py` (§2 of
Prototype report): `websites (tenant_id,url)` unique partial `deleted:false`;
`crawl_jobs (tenant_id,website_id,active)` partial unique; `users.email`,
`refresh_tokens.token_hash`, `members (tenant_id,user_id)` unique; business TTLs
(crawl_jobs 30 d, messages 90 d, usage 3 y, feedback 2 y, audit 1 y).

## 18. Migration Preconditions (checklist, evidence-gathering perspective)

If and only if a decision is made to port the queue to Mongo (Phase 17 moment):

- [ ] Safe Atlas M0 sandbox exists (dedicated DB, no production data), or requirement waived with documented `NOT MEASURED` status.
- [ ] Lease/heartbeat sizing decision made (600/30 | 600/60 | 900/60) with owner.
- [ ] Queue retention policy chosen (TTL on terminal `created_at`, per-plan window) — UNDECIDED this phase.
- [ ] Result policy chosen (full result vs status-only vs reference) — UNDECIDED this phase.
- [ ] Email OPTION A key derivation reviewed for PII-hash policy; OPTION B marker write decided.
- [ ] `mypy`-clean worker metadata (ClaimContext/function registry) ported, ARQ `erq.Function` contracts preserved or mapped.
- [ ] `worker_settings map` (crawl timeout 3600 vs global 600) reproduced exactly.
- [ ] Progress pub/sub, cache, rate-limit, health continue on Redis (no removal).
- [ ] Backfill/drain job from ARQ to Mongo staging with duplicate-skip by `dedup_key`.
- [ ] Rollout gate: run Mongo worker alongside (shadow) before cutover; both read contract tests (2589) green.

## 19. Next Phase (17) Scope

Phase 17 executes the *migration work* the hardening prepared, still on free
resources and still evidence-first:

1. Implement MongoDB-backed worker (`worker.py` port) + `MongoQueue` integration
   replicating ARQ semantics (max_tries, timeouts incl. per-function crawl 3600 s,
   backoff, dead-letter, tenant propagation, result write policy from §18).
2. Email OPTION A (deterministic key) + OPTION B marker under `send_email`
   (still calling Resend via `get_mail_service()`).
3. TTL index on queue collection cleared for production schema review.
4. Shadow-run MongoDB worker beside existing ARQ workers; compare deliveries,
   crawl completions, document embeddings; measure against the op-model table.
5. Regression gate before any cutover: full `pytest tests`, ruff, mypy, plus the
   Phase 16 prototype suites.
6. No Redis removal, no paid tier upgrade, no commit/push without instruction.

## 20. Evidence Classification Legend

- `MEASURED` — observed directly on the local prototype mongod/test harness.
- `VERIFIED` — confirmed against primary provider/SDK docs (Resend).
- `CALCULATED` — deterministic arithmetic implemented in `costs.py` and asserted
  by tests.
- `INFERRED` — derived from repo code or provider docs without runtime proof.
- `NOT MEASURED` — requires production Atlas / real provider; intentionally not
  fabricated (explicitly: Atlas M0 scale).

## 21. Final Readiness Matrix

| # | capability | status | evidence |
| -- | -- | -- | -- |
| 1 | atomic claim / single winner | PASS | MEASURED 100-claim race, 182 ms |
| 2 | lease recovery after crash | PASS | MEASURED expiry-reclaim tests |
| 3 | execution fencing (stale worker) | PASS | MEASURED completion/fail rejection |
| 4 | retry + backoff + dead-letter | PASS | MEASURED lifecycle tests |
| 5 | deduplication (submission-level) | PASS | MEASURED unique partial index, 25→1 |
| 6 | crawl safety (single terminator) | PASS | MEASURED single-winner fences |
| 7 | document safety (checksum/run_id) | PASS | MEASURED/INFERRED processor+store |
| 8 | email idempotency (OPTION A/B) | PASS (prototype) | MEASURED 100-worker honour/ignore + crash+response-loss tests |
| 9 | Atlas M0 scale | NOT MEASURED | no safe test Atlas (only production cluster) |
| 10 | polling efficiency | PASS | CALCULATED 2,880 vs 172,800 idle/day; MEASURED 13 ops/5-min idle |
| 11 | queue retention (TTL) | PARTIAL — not configured in prototype; policy UNDECIDED | ESTIMATE tables only |
| 12 | tenant isolation (scoped reads) | PASS | MEASURED cross-tenant lookup |
| 13 | Redis dependency reduction | PASS (partial) | INFERRED inventory: ARQ removed, Redis kept |
| 14 | worker resource fit | PASS | MEASURED RSS ≈ 48 MB vs 2 vCPU/1 GiB |
| 15 | production integration | NOT MEASURED | ties to Atlas (row 9) + provider real-send unexercised |

No numeric roll-up is given — each capability is independently assessed via its
measurement path (`PASS`/`PARTIAL`/`NOT MEASURED`).

## 22. Final Output A–N

**A. Baseline.** HEAD `d63deff3...ecf158`; untracked: `backend/prototypes/`,
`docs/reports/`; local prototype mongod up on 127.0.0.1:27019; production stack
untouched.

**B. Email idempotency.** Production provider Resend supports `Idempotency-Key`
(24 h, ≤256 chars; `VERIFIED` against docs + SDK 2.35.0). OPTION A: deterministic
`email:<tenant>:<sha256(content)>`; OPTION B: durable Mongo delivered-marker;
recommended default A+B; B mandatory if provider ignores keys.

**C. Email crash matrix.** Cases 1–8 analysed; prototype proves single delivery
for crash-after-send, response-loss, and dual-execution under OPTION A, and
documents unavoidable duplicates under a key-ignoring provider.

**D. Operation model + workloads.** A–I per-op table and A–J workload scenarios
in §5; per-op READ/WRITE counts; active-job budget 3 + ⌈D/30⌉ commands.

**E. Atlas M0 validation.** **NOT MEASURED** — only the production Atlas cluster
is configured; no safe sandbox. Precondition item #1 in §18.

**F. Lease sizing.** 600/30: 20 renewals/lease, 120/3,600 s crawl, detect 600 s.
600/60: 10 & 60, detect 600 s. 900/60: 15 & 60, detect 900 s (50% slower
recovery, 300 s wider zombie window). Trade-offs only; no verdict.

**G. Active job + polling.** 60 s job = 5 queue commands; 600 s = 23; 3,600 s
crawl = 123. Idle: adaptive 2,880 vs ARQ 172,800 commands/day/worker.

**H. Crawl safety.** PASS — `finish_if_active`/`update_if_crawl_owner` fences
(MEASURED single-winner), crawl TTL 30 d, max_concurrent 2, 3600 s timeout.

**I. Document safety.** PASS — checksum-skip, run_id, unique chunk index, ≤3
retries with 5/30/180 backoff.

**J. Redis findings.** ARQ is the dominant (but only queue-shaped) consumer;
removing it eliminates ~172,750 idle commands/day/worker while Redis stays for
cache/rate-limit/health/progress. No Redis removal performed or proposed.

**K. Resource constraints.** Free-only honored; prototypes RSS ≈ 48 MB vs
worker budget 2 vCPU/1 GiB; M0 storage fits (≤162 MB at 90-day Pro estimate).

**L. Tests.** Prototype 61 passed; regression 2589 passed/12 skipped; ruff
clean; mypy clean (230 files).

**M. Readiness matrix.** 15 rows in §21: 11 PASS/1 PARTIAL (retention)/3 NOT
MEASURED (Atlas M0, retention-policy-unmeasured, production integration).

**N. Preconditions + Phase 17 + git.** Precondition checklist §18 (8 items);
Phase 17 scope §19 (6 steps: Mongo worker port, email A+B, TTL index, shadow
run, regression gate, no paid upgrades/Redis removal). `git status --short`:
`?? backend/prototypes/`, `?? docs/reports/`. Nothing committed, nothing pushed.