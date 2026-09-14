# Worker Comprehensive Production Audit — 2026-09-12

**Scope:** Background worker (`python -m backend.workers`, ARQ) — crawl, knowledge/embedding, and email pipelines, plus the Redis/Mongo infra they consume, sized for the stated Railway worker target of **2 vCPU / 1 GiB RAM**.
**Method:** Read-only code audit (no source/config/test/dependency changes). Evidence is file:line citations. Item provable from the tree is marked **VERIFIED**; anything needing observability we do not have today is marked **THEORETICAL / NEEDS RUNTIME VALIDATION**.
**Baseline:** HEAD `6d7129a` (`feat: fix mobile layout overflow and responsiveness`), branch `main`, working tree clean except an unrelated untracked `MOBILE_REVIEW_REPORT.md` (user artifact, intentionally untouched).

---

## 1. Executive Summary

The worker is a **PRODUCTION-READY WITH WARNINGS** deployment _for the currently configured single-replica, 1 GiB Railway shape_. The crawl/embedding design is unusually defensive: HTTP-first fetching keeps Chromium out of the memory path for static/SSR sites, every network hop is SSRF re-validated with fresh DNS (DNS-rebinding safe), robots.txt is honoured, page sizes are capped end-to-end (5 MB HTML / 200 KB cleaned text), the embedding pipeline is fenced to a single provider identity (BUG-1) with a process-wide concurrency pacer, and retry/failure state transitions are explicit and deterministic.

The main residual risk is **memory visibility**: the only RSS guard (`crawler._current_rss_mb`, `ru_maxrss` of `RUSAGE_SELF`) measures the Python process only, is **disabled by default** (`crawl_max_rss_mb = 0`), and is therefore blind to the one component that can blow the 1 GiB budget — the Chromium subprocess tree. On a 1 GiB container the arithmetic fits comfortably for the HTTP-first path and for small JS fallbacks, but the pathological JS-heavy page case cannot be detected or mitigated in-process today (needs runtime validation).

Findings: **0 P0, 2 P1, 7 P2, 5 P3.** No confirmed security, tenant-isolation, data-corruption, or deterministic-crash defects. The P1 items are: (1) the memory guard's blind spot + default-disable, and (2) the absence of a crawl single-flight lock, which is safe today at one replica but becomes a correctness risk the moment the worker is scaled horizontally (all process-local gates — crawl semaphore, browser lock, embedding pacer, embedding-run guard — become per-process).

---

## 2. Worker Architecture Map (VERIFIED)

```
python -m backend.workers               backend/workers/__main__.py:15
  └→ ARQ CLI → backend.workers.app.WorkerSettings
        workers/app.py:69-79  functions= TASKS, max_tries=3, job_timeout=600,
                              keep_result=3600, max_jobs=10, RedisSettings.from_dsn
        on_startup (app.py:30-44): ctx["embedding_client"] (single primary
             provider via build_ingestion_embedding_client), ctx["embedding_provider_health"]
             (ProviderHealthStore(redis))
        on_shutdown (app.py:54-66): close_browser → MongoDB.close → close_redis,
             each isolated + idempotent
        TASKS (workers/tasks.py:32-37): ping, send_email, crawl_website,
             process_document, process_website_documents (all but ping wrapped
             in timed_job — opt-in via PERF_TIMING_LOG_ENABLED, timing.py:46-77)
```

Pipeline stages and their files:

| Stage             | File(s)                                                                                                                          | Notes                                                                                                                                                                                      |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Crawl job         | `workers/jobs/crawl.py`                                                                                                          | enqueue fast-path (`enqueue_crawl_website`), state machine `queued→ready→completed/failed`, usage, audit, cache invalidation, knowledge handoff, `_purge_removed_documents` reconciliation |
| Frontier & engine | `ingestion/crawler.py`                                                                                                           | BFS + priority heap (`priority.py`), caps (pages/depth), robots, per-page SSRF, content checksum (Phase 5), blocked-page early stop                                                        |
| HTTP-first fetch  | `ingestion/http_first.py`                                                                                                        | httpx streaming, truncation, 20-redirect SSRF-validated hops, content-type gate, JS-shell verdict                                                                                          |
| Browser fallback  | `ingestion/browser.py`                                                                                                           | one shared lazy Chromium (asyncio.Lock), process-wide `crawl_semaphore`, per-job isolated contexts, SSRF on nav + redirects                                                                |
| Extraction/clean  | `ingestion/extractor.py`, `cleaner.py`                                                                                           | same-origin link extraction, boilerplate cleaning                                                                                                                                          |
| Knowledge job     | `workers/jobs/knowledge.py`, `knowledge/processor.py`                                                                            | document retry schedule (5s→30s→180s), run-id fencing, per-doc fan-out                                                                                                                     |
| Embedding         | `knowledge/embedding.py`                                                                                                         | batched (32), jittered backoff, Retry-After capped, process-wide pacer, embedding-identity compatibility                                                                                   |
| Chunking/quality  | `knowledge/chunker.py`, `corpus_quality.py`                                                                                      | token counts, quality gates                                                                                                                                                                |
| Infra             | `core/config.py`, `core/database.py`, `core/redis.py`, `core/cache.py`, `core/crawl_events.py`, `services/ai/provider_health.py` | settings, Mongo, Redis, cache, pub/sub events, provider health                                                                                                                             |

---

## 3. Deployment Model (VERIFIED)

- **Container:** `docker/Dockerfile.worker` — `ghcr.io/astral-sh/uv:python3.13-bookworm-slim`, `playwright install --with-deps chromium`, non-root `appuser`, exec-form `CMD ["python", "-m", "backend.workers"]` (Dockerfile.worker:73) → python is PID 1 and receives signals directly.
- **Runtime sizing:** stated target is Railway 2 vCPU / 1 GiB. The in-repo evidence for the 1 GiB figure is prose only: `docs/CRAWL_EGRESS_HARDENING.md:99` ("1 GiB") and `config.py:363-366`/`.env.production.example:329-331,363-365` comments. Compose pins **2 GiB / 2 CPU** (`docker/compose.yml:446-450`, `compose.prod.yml:58-62`) — not the Railway budget. No `railway.toml`/Procfile exists.
- **Production-config critical values** (`.env.production.example`): `CRAWL_MAX_CONCURRENT=1` (:365), `CRAWL_HTTP_FIRST=true` (:374), `EMBEDDING_MAX_CONCURRENT_BATCHES=1` (:331), `CRAWL_NO_SANDBOX=true` (:370).

---

## 4. Current Strengths (all VERIFIED)

1. **SSRF is enforced at the network boundary on every hop.** `SsrFGuard.validate_async` runs before every navigation start (`crawler.py:158`, `http_first.py:313`, `browser.py:123`) **and again on every redirect target** (`http_first.py:357`, `browser.py:240`), rejecting literal IPs, blocked ports, internal hostnames, and any host whose _any_ A/AAAA record lands in a blocked range (`ssrf_guard.py:39-82`). Resolution is deliberately uncached in the live path (`ssrf_guard.py:99-121`) so DNS-rebinding attacks are closed. IPv4-mapped IPv6 is unmasked before range checks (`ssrf_guard.py:141-142`).
2. **HTTP-first architecture is the 1 GiB story.** Static/SSR pages are fetched with httpx and never touch Chromium (`http_first.py`, `crawl_http_first=true`). Browser fallback only for pages judged JS shells (`judge_http_content`, thresholds in `config.py:368-379`).
3. **Embedding identity is fenced (BUG-1 closed).** `ctx["embedding_client"]` is a single-primary-provider client (`app.py:33-40`), retries resume in the SAME embedding space via run-id fencing (`knowledge.py:143-148`), and `ensure_embedding_compatibility` guards dimension/space changes (`embedding.py:25`). No process can write foreign-space vectors mid-corpus.
4. **Embedding concurrency is a process-wide pacer**, not per-call (module-global `_pacer`, `embedding.py:93-100`) → `EMBEDDING_MAX_CONCURRENT_BATCHES` stays a true bound even with `max_jobs=10` in-flight knowledge jobs.
5. **Crawl concurrency and browser lifecycle are governed by process-wide gates:** `crawl_semaphore()` (browser.py:44-49) and a lazy shared-launch asyncio.Lock (browser.py:61); per-job isolated browser contexts.
6. **Response/storage caps end-to-end:** HTML streamed and truncated at 5 MB (`http_first.py:366-372`, `browser.py:119`), cleaned text capped at 200 KB (`config.py:344`), navigation hard-timeout 30 s wrapping the entire redirect chain (`http_first.py:312`), `_MAX_REDIRECTS=20` both paths (`http_first.py:47`).
7. **Deterministic failure classification.** `InvalidUrlError` (seed not crawlable) → immediate permanent failure with no retry burn (`crawl.py:481-502`); all other exceptions retry under ARQ `max_tries=3` and only the final attempt stamps `failed` + events + audit (`crawl.py:503-529`). 403 is never retried over HTTP (spec falls straight to browser); Retry-After is capped at 30 s (`config.py:389`).
8. **robots.txt is actually used:** parsed (`utils/robots.py`), fetched through the same SSRF-guarded fetcher (`crawler.py:376-384`), per-path `is_allowed` (crawler.py:243), crawl-delay honoured (`crawler.py:248-251`).
9. **Tenant isolation is largely sound:** all document paths read tenant ownership from the job/doc and scope writes accordingly; admin `list_any`/`count_any` are route-guarded (ADR-006); cache prefixes are `{tenant}:{website}:` (`crawl.py:439-441`).
10. **Idempotent re-crawl:** SHA-256 content checksums drive incremental updates (Phase 5), `_purge_removed_documents` reconciles deletions, cache invalidation is best-effort and never fails a crawl (`crawl.py:437-447`).
11. **Graceful shutdown verified:** independent idempotent closers for browser/Mongo/Redis (`app.py:46-66`), covered by `tests/test_worker_shutdown.py`.
12. **Best-effort side-effects are isolated:** usage records, knowledge handoff enqueue, cache invalidation are wrapped so a dependent-outage cannot fail the crawl (`crawl.py:420-447`).

---

## 5. Critical Findings

### P0 — none found

No verifiable security, cross-tenant, data-corruption, or crash-by-default defects were found. Candidate items (vector replace non-atomicity, workers with no log filters) were assessed and are P2, not P0, because each converges on retry and never leaks cross-tenant data.

### P1

**FIND-01 (P1) — Memory guard is blind to Chromium and disabled by default.**

- Component: crawler memory protection / 1 GiB posture.
- File:line: `ingestion/crawler.py:48-51` (`_current_rss_mb` → `resource.getrusage(RUSAGE_SELF).ru_maxrss`), `config.py:352-355` (`crawl_max_rss_mb: int = 0` = disabled).
- Problem: the only RSS check in the worker measures the **Python process peak RSS only**. Chromium runs as a child subprocess; `RUSAGE_SELF` excludes it. And with `crawl_max_rss_mb = 0` the check is off even for Python.
- Root cause: designed when `ru_maxrss` was the available signal; no cgroup or process-tree accounting; disabled default preserves "current behaviour".
- Production impact: on the 1 GiB Railway worker, a JS-heavy crawl exercising the browser fallback can push Chromium past the budget with **no in-process tripwire** → Railway OOM-kills the container mid-crawl. The crawl job is retried (ARQ) up to 3 attempts, each starting a fresh browser, so the outcome is repeated OOM + partial page sets, not corruption.
- Reproduction / evidence: code path proven (VERIFIED); memory behaviour **THEORETICAL / NEEDS RUNTIME VALIDATION** — no cgroup reading, no `/proc` tree scan, no OOM observation yet.
- Recommended fix (two phases): (a) read cgroup v2 `memory.current`/`memory.max` when present, falling back to a `/proc/<pid>/status VmRSS` scan summed across the Chromium subprocess tree; (b) treat `crawl_max_rss_mb` as the process-TREE ceiling and abort with an explicit `CRAWL_MAX_RSS` classification. Optionally set a sane non-zero default for the Railway shape.
- Risk of fix: an over-tight ceiling could abort legitimate crawls → choose ceiling from measured idle+peak baseline first.
- Effort: S (cgroup read) but requires a runtime measurement pass before choosing the value.

**FIND-02 (P1) — No crawl job single-flight lock; all gates are process-local.**

- Component: queue correctness at ≥2 replicas or overlapping retries.
- File:line: `workers/app.py:69-79` (no per-queue worker identity / distributed lock); `browser.py:44-49` & `embedding.py:93-100` (process-wide, not cluster-wide); `workers/jobs/crawl.py:428-479` (status writes are read-modify-write on the job doc).
- Problem: the crawl semaphore, browser launch lock, embedding pacer, and embedding-run guard are all **per-process**. Today Railway runs a single worker replica, so they are global in practice — but the moment the worker is scaled to 2+ replicas (or if the same job-id is ever enqueued twice via retry/backpressure replay), two `crawl_website` executions of the same website can run concurrently: duplicate HTTP traffic, double usage `$inc`, and racing `job.status`/`website.status` writes.
- Root cause: virtual-concurrency ambitions assumed one worker process (ADR-002 era).
- Production impact: currently **THEORETICAL / NEEDS RUNTIME VALIDATION** (single replica). At 2 replicas: duplicate crawls double egress and usage counters; worst case a race marks the website `ready` twice.
- Recommended fix: (a) document a hard "1 worker replica" invariant (or enforce via a Redis `set(nx)` job-lease); (b) before scaling, make status transitions conditional updates (`update_many({'status': RUNNING}, ...)`) so the second executor loses the race deterministically.
- Risk of fix: low; a lease adds a Redis dependency on the crawl path (currently none — Redis outage is fully graceful for crawls).
- Effort: M (conditional updates) or S (documented invariant).

### P2

**FIND-03 (P2) — Worker never configures structured logging / sensitive-data filtering.**

- File:line: `workers/app.py:30-44`, `workers/__main__.py` (no `configure_logging()`, no `attach_sensitive_data_filter()`, no metrics-log collector). The API does (`core/logging.py:133-142`); the worker does not.
- Problem: worker logs use Python's default formatting (no JSON, no `request_id`/`tenant_id` envelopes), and SensitiveDataFilter (token/secret/bearer scrub) is absent. Several worker paths log full URLs (`browser.py` `url=%s` lines flagged during this audit; most crawl logs already use `safe_url_parts`).
- Impact: a crawled page whose URL embeds a query token, or an embedding provider error echoing credentials, can land verbatim in worker logs; and incident triage lacks the structured request/tenant context the API enjoys.
- Root cause: logging bootstrap not wired into the worker startup.
- Fix: call the shared logging bootstrap (JSON formatter + sensitive filter) in `startup()`; replace remaining full-URL log calls with `safe_url_parts`.
- Risk: low. Effort: S.

**FIND-04 (P2) — Vector replacement is delete-then-insert (non-atomic).**

- File:line: document/vector repositories (delete current chunks, then insert new) — flagged in the repositories audit; see `repositories/vector/` and `services/knowledge/processor.py` replace path.
- Problem: a crash or Mongo error between delete and insert leaves the document with **zero or partial chunks** until the next retry; retrieval in that window misses the doc.
- Impact: transient retrieval misses on re-ingest; self-heals on retry (idempotent checksum). No corruption; no cross-tenant risk.
- Fix options: (a) transactional delete+insert when the driver/sharding allows; (b) write-new → remove-old with a generation/`vector_version` field so readers keep the old set until the new set is complete. Option (b) fits the current doc model.
- Risk: (b) is low. Effort: M.

**FIND-05 (P2) — `CRAWL_NO_SANDBOX=true` in the production template contradicts the code policy.**

- File:line: `.env.production.example:370` sets `CRAWL_NO_SANDBOX=true`; `config.py:347-351` documents sandbox-on as the production posture and says no-sandbox is "never the default".
- Problem: the shipped production config runs Chromium with the sandbox disabled inside a non-root container.
- Impact: defence-in-depth loss if a crawled hostile page exploits a Chromium rendering bug (browser runs untrusted web content by design). This is exactly the crawler's threat model.
- Fix: re-derive at deploy time whether the Railway container truly cannot sandbox (user namespaces); if it can, ship `CRAWL_NO_SANDBOX=false`. At minimum, add an explicit comment + runtime warning when no-sandbox is enabled.
- Risk: if the runtime genuinely refuses sandboxing, disabling it may be the only option — hence "validate, don't blindly revert". Effort: S.

**FIND-06 (P2) — Deployment sizing drift: 2 GiB/2 CPU in compose vs 1 GiB target; no railway.toml.**

- File:line: `docker/compose.yml:446-450`, `compose.prod.yml:58-62` (2 GiB / 2 CPU); 1 GiB only in prose (`docs/CRAWL_EGRESS_HARDENING.md:99`, config comments); no `railway.toml`.
- Problem: nothing in the repo pins the 1 GiB Railway budget; local/staging runs at 2 GiB hide OOM pressure that will only appear in production.
- Fix: add a `railway.toml` (worker service memory limit) and/or a compose overrides file matching the production shape; add a boot-time check that logs the effective caps.
- Risk: low. Effort: S.

**FIND-07 (P2) — robots.txt fetch failure fails OPEN (allow_all).**

- File:line: `ingestion/crawler.py:376-384` — on fetch/parse error returns `RobotsTxt.allow_all()`.
- Problem: if robots fetching fails transiently, the crawler proceeds unconstrained by the site's robots policy for the whole crawl.
- Impact: polite-crawl compliance + egress risk on hosts that enforce policy; no security impact.
- Fix: fail-closed is the standard alternative — treat robots-unavailable as "crawl the seed only" or defer. Setting depends on product posture.
- Risk: fail-closed would make crawls of flaky-hosting sites almost always empty; needs an escape hatch. Effort: S-M.

**FIND-08 (P2) — Single global ARQ `job_timeout=600` vs large/slow crawls.**

- File:line: `workers/app.py:77`.
- Problem: `job_timeout=600` applies to every task including `crawl_website`. A pathological site: 50 pages × (30 s nav timeout + retries + browser fallback 30 s) can exceed 10 min → ARQ cancels mid-crawl regardless of progress.
- Impact: spurious failed-at-final-attempt crawls with partial pages stored (harmless, self-heals on re-crawl, but user-facing "crawl failed").
- Root cause: single timeout for heterogeneous jobs.
- Fix: per-task timeouts or raise the crawl timeout with a **cancellation-aware** crawl loop (see FIND-09); keep the 30 s per-page bound.
- Risk: raising the bound alone trades stuck-job protection for long-running rogues → combine with page/total-completion bookkeeping. Effort: M.

### P3

- **FIND-09 (P3)** — No explicit cancellation handler: if ARQ cancels a crawl mid-flight, the job doc may be left in a transient status until the next attempt; no partial-progress write. (Test gap: `test_crawl_worker.py` lacks a cancel test.) Fix: write partial progress on `asyncio.CancelledError`. Effort: M.
- **FIND-10 (P3)** — `PERF_TIMING_LOG_ENABLED=false` in production (`.env.production.example:47`) disables the only queue-wait/execution timing records (`timing.py:46-77`); recommend enabling (cheap, structured) for ops. Effort: S.
- **FIND-11 (P3)** — `keep_result = 3600` (app.py:78) retains every job result an hour; under high fan-out (`process_document` per document) this grows Redis. Consider lowering or pruning long-tail queues. Effort: S.
- **FIND-12 (P3)** — `max_jobs=10` allows up to 10 concurrent in-flight jobs; with `crawl_max_concurrent=1` and the embedding pacer this is memory-safe, but a burst of 10 knowledge jobs each with large docs (200 KB) transiently multiplies parsed/tokenized text in RAM. Not a failure today; note for the 1 GiB ceiling. Effort: S (document, don't change).
- **FIND-13 (P3)** — Mongo `MONGODB_MIN_POOL_SIZE=10` (`.env.production.example:139`) opens 10 connections in a 1 GiB worker; the async driver's connections are cheap but this is over-provisioned for a single consumer. Effort: S.

---

## 6. Memory Analysis — 1 GiB Railway Worker

Model uses optimistic-baseline + worst-case-with-tripwire reasoning. Figures are estimates for the referenced components; **needs runtime validation**.

| Component                                            | Typical         | Peak (pathological)         | Notes                                                                                                     |
| ---------------------------------------------------- | --------------- | --------------------------- | --------------------------------------------------------------------------------------------------------- |
| Python + deps (uv, ARQ, httpx, motor, playwright py) | ~100–150 MB     | ~200 MB                     | Q3/Q4 interpreter + import surface of this stack                                                          |
| Mongo driver pool (min 10)                           | ~15–25 MB       | same                        | async, no threads per conn                                                                                |
| HTTP-first page fetch                                | <10 MB          | 5 MB html cap + 200 KB text | streamed, truncated                                                                                       |
| Embedding batch (32 texts, pacer=1)                  | <5 MB transient | ~15 MB                      | response 32×1024 floats ≈ 130 KB; tokens/tokenizers dominate                                              |
| Knowledge job in-flight (≤10 jobs)                   | ~20 MB          | ~100 MB                     | 200 KB text/document parsed + tokenized per concurrent job                                                |
| **Chromium (browser fallback only)**                 | ~180–250 MB     | **~400 MB**                 | one instance + one context (concurrency=1); complex JS pages balloon — **outside `ru_maxrss` visibility** |
| **Total**                                            | **~350–450 MB** | **~700–800 MB**             | fits 1 GiB with headroom today; pathological case untracked (FIND-01)                                     |

**Conclusions (VERIFIED where code-bound, ESTIMATED for RAM):**

- With CRAWL_MAX_CONCURRENT=1, CRAWL_HTTP_FIRST=true and EMBEDDING_MAX_CONCURRENT_BATCHES=1 (the committed production values), the worker **fits comfortably in 1 GiB** for realistic crawls: static/SSR pages never launch Chromium.
- The un-guarded edge is exactly the case the architecture exists to avoid: a JS-shell page that forces the shared browser. One context at a time bounds it to ~400 MB worst-case — still under budget — but nothing in-process can confirm or react to it (FIND-01). cgroup-aware reading makes the guard real at near-zero cost.
- OOM consequences are **retryable**: fresh browser per attempt, job fails permanently only after 3 attempts, partial page sets self-heal on re-crawl.

**Recommendation:** keep the 3 production flags; add cgroup-aware tree-RSS guard; validate with a soak crawl of a JS-heavy site before going live.

---

## 7. Concurrency (VERIFIED)

| Gate                | Scope                             | Value                                          | Where                                  |
| ------------------- | --------------------------------- | ---------------------------------------------- | -------------------------------------- |
| `crawl_semaphore`   | process-wide                      | `crawl_max_concurrent` (1 in prod)             | `browser.py:44-49`                     |
| Browser launch      | process-wide asyncio.Lock         | lazy single instance                           | `browser.py:61`                        |
| Embedding pacer     | process-wide (module global)      | `embedding_max_concurrent_batches` (1 in prod) | `embedding.py:93-100`                  |
| ARQ max_jobs        | process-wide                      | 10                                             | `app.py:78`                            |
| Embedding-run guard | per-corpus via Redis/Mongo atomic | —                                              | `processor.py` `acquire_embedding_run` |

All are correct for a single worker process. The crawl path is serialized to one in-flight crawl; the embedding path is serialized to one in-flight batch **cluster-wide only while one replica exists** (→ FIND-02 at scale). `max_jobs=10` is safe for memory because the two expensive paths are individually capped.

---

## 8. Crawler (VERIFIED)

- Frontier: BFS with priority heap seeded by `crawl_priority_url_paths` (`priority.py`), caps `crawl_max_pages=50`, `crawl_max_depth=3` (config.py:337-338).
- Per-page pipeline: robots gate → SSRF validate → HTTP-first fetch → verdict (content/JS-shell) → browser fallback only if needed → extract → clean → checksum (Phase 5) → store.
- Bounded error handling: `_MAX_RECORDED_ERRORS=50`; blocked-host early stop at `crawl_max_blocked_pages_per_host=10` (config.py:397); insufficient-content gate `INSUFFICIENT_CONTENT_REASON` aligns with `knowledge_min_content_chars=100` (config.py:334).
- Crawl-delay honoured (crawler.py:248-251); same-origin extraction (extractor.py:107) rejects `data:`/`javascript:`.

---

## 9. Browser (VERIFIED)

- Single lazy shared Chromium per process, serialized launch, per-job isolated contexts, html truncated at cap, SSRF on initial nav (browser.py:123) and redirects (browser.py:240).
- `CRAWL_NO_SANDBOX` contradiction flagged (FIND-05). User agent is the declared `WebChatAI-Crawler/1.0` (config.py:346).

---

## 10. Embedding (VERIFIED)

- Batch size 32, per-batch exponential backoff with full jitter (`embedding.py:510-522`), Retry-After honoured and capped via the document-level schedule; provider-status parsing from GenAI SDK + httpx exceptions (`embedding.py:110-129`).
- Permanent failures (config errors) do not burn backoff (`embedding.py:440-447`).
- In-memory memo bounded at 1024 entries (embedding.py:38); embedding identity lock (BUG-1); dimensions enforced (config.py:214/344).

---

## 11. Redis

- Role: ARQ broker (queue + deferred zset + results), crawl events, cache (tenant-prefixed `RedisCacheStore`), provider health store, embedding-run guard, pacing, spend/rate limits.
- Resilient by construction: every crawl-side Redis touch is best-effort (`crawl.py:435-447`); embedding guard failure → safety pause, not corruption.
- Deferral correctness: `process_document` retries use zset `_defer_by` (`knowledge.py:54-63`) with jitter (`random.uniform`, :146) — avoids thundering herd.
- **THEORETICAL / NEEDS RUNTIME VALIDATION:** no Redis failure-injection tests exist (gap in §15) — the graceful-side paths are code-visible but unproven under drop.

## 12. Mongo

- Singleton `MongoDB`, connected through `motor`, `serverSelectionTimeoutMS=30000`, `socketTimeoutMS=30000`, min/max pool 10/100 (config.py:150-151; example 139-141).
- Async driver in an event loop: no blocking; backpressure is bounded by per-op timeouts.
- Vector replace non-atomicity flagged (FIND-04). `_purge_removed_documents` (crawl.py:532+) reconciles stale docs — good convergence net.

---

## 13. Security / SSRF (VERIFIED)

- Three layers: (1) registration-time `url_validator` (blocked IPs/ports/hostnames, `BLOCKED_PORTS`, `ALLOWED_SCHEMES`), (2) network-boundary `SsrFGuard` with live uncached DNS + any-record blocked-range rejection (ssrf_guard.py:99-121), IPv4-mapped-IPv6 unmask (:141-142), (3) redirect-hop re-validation on both fetch paths (http_first.py:357, browser.py:240) with `_MAX_REDIRECTS=20` matching Chromium's own abort.
- Query-param `safe_url_parts` logging in most crawl logs (crawler.py:325-331, http_first.py:519-567, jobs/crawl.py:320-341). Residual full-URL logs → FIND-03.

---

## 14. Tenant Isolation (VERIFIED + flagged)

- Crawl/knowledge repos resolve the owning `tenant_id` from the job/document and scope writes; cross-tenant reads go through `find_by_id_any`/`list_any` helpers documented as worker-internal (UUID4 job/doc ids) — VERIFIED, with `list_any`/`count_any` additionally role-guarded at the route (ADR-006).
- Cache invalidation prefixes are `{tenant}:{website}:` (crawl.py:439-441). Vector replace and status writes are tenant-scoped by construction.
- **No cross-tenant write path was found.** FIND-02 is the only related risk (race at scale, not cross-tenant spill).

---

## 15. Retry / Idempotency (VERIFIED)

| Path               | Policy                                                                                           | Idempotency                                                                                         |
| ------------------ | ------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------- |
| `crawl_website`    | ARQ `max_tries=3`; transient re-raise, final → `failed`; `InvalidUrlError` → immediate permanent | per-page upsert by (tenant, website, url) + content checksum; `_purge_removed_documents` reconciles |
| HTTP fetch         | `crawl_http_max_attempts=2`; 403 never retried; Retry-After capped 30 s; backoff 1→5 s           | —                                                                                                   |
| `process_document` | doc-level schedule 5s→30s→180s with jitter, same run-id                                          | `acquire_embedding_run` atomic guard + checksum skip                                                |
| Embedding batch    | per-batch backoff + jitter; config errors permanent                                              | batched, memo-guarded                                                                               |
| Email              | ARQ retries                                                                                      | — (idempotency N/A, transient only)                                                                 |

---

## 16. Cancellation / Shutdown (VERIFIED partial)

- Graceful `on_shutdown`: browser → Mongo → Redis, separately idempotent (`app.py:46-66`), covered by `tests/test_worker_shutdown.py`.
- **Gap (FIND-09):** no cancellation handler inside a crawl; ARQ job_timeout cancel leaves no partial-progress write.
- Signals: exec-form CMD → python is PID 1; ARQ's signal handling stops job pickup and drains in-flight.

---

## 17. Observability (VERIFIED + findings)

- Metrics: counters recorded in-process; API exposes a metrics route (`api/routes/metrics.py`); **the worker has no exporter** — worker metrics are invisible unless log-collector ingestion is configured (it is not, FIND-03).
- Timing: queue-wait + duration structured records exist (`timing.py`) but are off by default in prod (FIND-10).
- IDs: `request_id_var`/`tenant_id_var` (logging.py:24,30) exist but are only useful with the JSON formatter, which the worker never enables (FIND-03).

---

## 18. Timeout / Bound Matrix (VERIFIED)

| Bound                            | Value                       | Config                                  |
| -------------------------------- | --------------------------- | --------------------------------------- |
| ARQ job timeout (all tasks)      | 600 s                       | app.py:77                               |
| ARQ retries                      | 3                           | app.py:76                               |
| Keep job result                  | 3600 s                      | app.py:78                               |
| ARQ concurrent jobs              | 10                          | app.py:79                               |
| Page navigation                  | 30 s (incl. redirect chain) | config.py:339, http_first.py:312        |
| Redirects                        | 20 (both paths)             | http_first.py:47                        |
| HTML cap / text cap              | 5 MB / 200 KB               | config.py:342,344                       |
| HTTP retries / Retry-After cap   | 2 / 30 s                    | config.py:386,389                       |
| Embedding batch                  | 32 texts                    | config.py:306                           |
| Embedding request                | 10 s                        | config.py:314; prod tok 60 s AI timeout |
| Embedding retry base/backoff cap | 300 ms / base·2^n           | embedding.py:220,304                    |
| Mongo selection/socket           | 30 s / 30 s                 | config.py:150-151                       |
| Knowledge doc retry              | 5s→30s→180s                 | processor.py:16                         |

---

## 19. Failure-Scenario Matrix (A–X)

| ID  | Scenario                                           | Behaviour (verified where possible)                                            | Outcome                                                  | Sev            |
| --- | -------------------------------------------------- | ------------------------------------------------------------------------------ | -------------------------------------------------------- | -------------- |
| A   | Mongo down at crawl start                          | job re-raises → ARQ retry; final → `failed`+event+audit                        | Deterministic fail, user-visible                         | P2             |
| B   | Mongo down mid-crawl                               | page/store raises; retried; partial pages persisted                            | Self-heal on retry                                       | P2             |
| C   | Redis down (broker)                                | enqueue fails fast at API edge; in-flight continues                            | Queue stalls, no data loss                               | P2             |
| D   | Redis down (cache/events/health)                   | best-effort paths log+continue (crawl.py:435-447)                              | Crawl succeeds w/o events                                | P2             |
| E   | Embedding 429/rate limit                           | Retry-After/backoff + doc-level schedule, jittered                             | Converges                                                | P3             |
| F   | Embedding provider down                            | backoff till budget; quarantine via identity lock                              | Doc stuck until provider recovers; no wrong-space writes | P2             |
| G   | Embedding config/permanent error                   | `ProviderConfigurationError` permanent, no backoff burn (embedding.py:440-447) | Doc failed cleanly                                       | P3             |
| H   | Chromium crash mid-nav                             | per-job context; exception → retry; browser relaunch                           | Self-heal                                                | P2             |
| I   | Chromium OOM on 1 GiB                              | UNDETECTABLE in-process (FIND-01) → container OOM-kill                         | Repeated OOM; job fails after 3 tries                    | **P1**         |
| J   | HTTP 403                                           | no HTTP retry; straight to browser fallback                                    | Faster, correct                                          | P3             |
| K   | HTTP 5xx/timeout                                   | retries up to 2, backoff ≤5 s, then browser                                    | Converges                                                | P3             |
| L   | Very slow page                                     | 30 s overall cap (incl. redirects)                                             | Skip, classified recoverable                             | P3             |
| M   | Redirect loop/superset                             | `_MAX_REDIRECTS=20`                                                            | Fail classified, no hang                                 | P3             |
| N   | SSRF (private IP, blocked port, rebinding)         | refused pre-connect, fresh DNS each hop                                        | Blocked, safe                                            | P0-grade → N/A |
| O   | Invalid seed URL                                   | immediate permanent, no retries (crawl.py:481-502)                             | Deterministic                                            | P3             |
| P   | robots.txt unavailable                             | allow_all **fail-OPEN** (crawler.py:376-384)                                   | Crawls anyway (FIND-07)                                  | P2             |
| Q   | JS-shell page on HTTP path                         | verdict → browser fallback (config.py:368-379)                                 | Correct path                                             | P3             |
| R   | Oversized page body                                | truncated at cap (http_first.py:366-372)                                       | Bounded memory                                           | P3             |
| S   | Duplicate crawl (retry overlap)                    | no single-flight (FIND-02) — safe today, races at scale                        | THEORETICAL                                              | P1             |
| T   | ARQ job_timeout fires mid-crawl                    | task cancelled; partial pages kept; no cancel handler                          | Spurious fail for large slow sites                       | P2             |
| U   | Embedding run guard contention (2 docs, 1 website) | atomic acquire; second defers                                                  | Ordered                                                  | P3             |
| V   | Vector delete-then-insert crash window             | zero/partial chunks until retry (FIND-04)                                      | Transient retrieval miss                                 | P2             |
| W   | Email delivery failure                             | ARQ retries (send_email)                                                       | Retried                                                  | P3             |
| X   | Graceful shutdown mid-knowledge-job                | on_shutdown idempotent; ARQ drains in-flight                                   | Clean (test_worker_shutdown)                             | P3             |

---

## 20. Test-Coverage Matrix

Suite: root `tests/` (150 files), hermetic (conftest stubs Mongo; no real Chromium/Redis/Mongo/network). Worker-relevant files: `test_crawl_worker.py` (924 ln), `test_knowledge_worker.py`, `test_worker_shutdown.py`, `test_crawl_events.py`, `test_browser_lock.py`, `test_db_cache_resilience.py`, `test_crawler.py`, `test_http_first_crawler.py`, `test_crawl_egress_hardening.py`, `test_embedding_fallback.py`, `test_ingestion_embedding_identity.py`, `test_reingest_website_corpus.py`, `test_vector_mongodb.py`, `test_corpus_quality.py`, `test_crawl_service.py`, `test_crawl_api.py`, `test_knowledge_api.py`.

| Area                          | Coverage                         | Gaps (P3 unless noted)                                                                                          |
| ----------------------------- | -------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Crawl state machine / retries | Good (worker + http_first)       | No explicit ARQ-cancel test (FIND-09)                                                                           |
| SSRF                          | Good + egress hardening          | No IPv6/redirect-target SSRF tests (`test_http_first_crawler` covers much of redirect validation; IPv6 missing) |
| Browser lifecycle             | Lock test exists                 | No browser-crash-mid-context test                                                                               |
| Redis resilience              | `test_db_cache_resilience.py`    | No Redis-down failure-injection                                                                                 |
| Mongo resilience              | Partial                          | No Mongo-drop test                                                                                              |
| Memory pressure               | None                             | No RSS/abort test (FIND-01)                                                                                     |
| Cancellation                  | Shutdown test only               | No job-cancel test                                                                                              |
| Duplicate execution           | Reingest test covers idempotency | No duplicate-concurrent-crawl race test (FIND-02)                                                               |
| Queue explosion / sitemap     | Internal caps tested             | No sitemap/frontier-bomb test                                                                                   |

---

## 21. Performance Opportunities

- **P2-opt:** cache vector lookups/retrieval TTLs sized to 1 GiB (already conservative).
- **P3-opt:** broker-only Redis vs cache Redis separation would shrink production contention — not needed at current scale.
- **P3-opt:** `process_website_documents` fan-out enqueues one job per document; a batch API would cut queue depth (keep per-doc retry granularity).
- **P3-opt:** enable `PERF_TIMING_LOG_ENABLED` to surface queue-wait regressions before user impact.

---

## 22. Recommended Fix Order

1. Security/correctness: NONE required for go-live (P0/N-A items verified safe).
2. Reliability/memory: FIND-01 (cgroup-aware tree-RSS guard + measurement) — the only P1 with operational teeth.
3. Correctness at scale: FIND-02 (single-flight/conditional status updates) — cheap insurance, documents the single-replica invariant.
4. Data resilience: FIND-04 (write-new-then-swap vector replace) + FIND-07 (robots fail-closed policy decision).
5. Memory: FIND-06 (pin 1 GiB shape in repo), FIND-12 (document burst behaviour).
6. Performance: P3 opts above.
7. Observability: FIND-03 (worker logging bootstrap + `safe_url_parts`), FIND-10 (enable timing), FIND-05 (sandbox validation), FIND-11 (result retention).
8. Polish: FIND-08/FIND-09 (per-task timeout + cancel handler), FIND-13 (pool sizing).

---

## 23. Quick Wins (≤S effort, low risk)

1. Wire worker startup into the shared logging bootstrap (FIND-03).
2. Enable `PERF_TIMING_LOG_ENABLED` in production (FIND-10).
3. Add a `railway.toml`/compose override pinning 1 GiB + document single-replica invariant (FIND-02/FIND-06).
4. Lower `keep_result` or prune (FIND-11).
5. Reduce `MONGODB_MIN_POOL_SIZE` for the worker (FIND-13).
6. Re-validate + comment `CRAWL_NO_SANDBOX` (FIND-05).

---

## 24. High-Risk Areas (must not regress)

- **SSRF guard placement** (initial + redirect hops, uncached DNS) — never move validation inside the browser/omit hop checks.
- **Embedding-identity fencing** (BUG-1) — never allow a second embedding space mid-corpus; the run-id threading and `acquire_embedding_run` guard are load-bearing.
- **The three production memory flags** — `CRAWL_MAX_CONCURRENT=1`, `CRAWL_HTTP_FIRST=true`, `EMBEDDING_MAX_CONCURRENT_BATCHES=1` on the 1 GiB shape.
- **HTTP-first verdict thresholds** — mis-tuning `crawl_http_min_content_words`/`js_shell_min_bytes` flips pages to the 400 MB Chromium path and breaks the memory story.

---

## 25. What Should NOT Be Changed

- `Resource.getrusage`-style guard: keep but ADD tree/cgroup awareness (don't remove the existing tripwire).
- The delete-then-insert vector path's semantics (keep, but make generation-swap safe).
- Robots/Crawl-delay/Retry-After capping logic.
- The single-provider embedding client architecture (ADR-009 / BUG-1 design).
- Exec-form CMD / non-root appuser posture.
- Best-effort isolation of side-effects (usage/events/cache) from the crawl happy path.

---

## 26. Final Verdict

**PRODUCTION-READY WITH WARNINGS** for the current single-replica Railway 1 GiB deployment.

The worker is a defensively engineered, well-tested background pipeline. There are **no P0 findings and no verifiable security, isolation, or corruption defects**. The two P1 items are tractable and, notably, the largest one (memory visibility) is currently compensated by architecture (HTTP-first + concurrency caps) rather than instrumentation. The single most valuable follow-up before trusting the 1 GiB shape with _crawl-heavy real-world traffic_ is a **cgroup-aware, process-tree RSS guard backed by a short soak measurement** — everything else is polish.

---

_Read-only audit. No source, configuration, test, or dependency files were modified. Only this document was created. Baseline and finish state re-verified with `git status`/`git log` (clean except the pre-existing untracked `MOBILE_REVIEW_REPORT.md`)._
