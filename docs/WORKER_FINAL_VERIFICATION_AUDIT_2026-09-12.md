# Worker Final Verification Audit

- Status: **READ-ONLY VERIFICATION** — no source, test, config, Docker or doc changes made; nothing committed or pushed; working tree left exactly as found.
- Current HEAD: `d024f2a` (`fix: add dedicated crawl job timeout`)
- Branch: `main` (up to date with `origin/main`; 117 commits; tags v0.11.5, v0.6-rag-complete, v0.7-dashboard-complete, v0.8-widget-sdk-complete, v1.0.0)
- Date: 2026-09-12

---

## 1. Executive summary

The worker system (ARQ jobs → crawler → knowledge pipeline) was re-verified end-to-end at HEAD `d024f2a` against the five required checks. **All five pass:** pytest 2466 collected / 0 failures / 0 errors / 12 skipped (exit 0), mypy clean on 203 source files, ruff check clean, ruff format clean on 363 files, and `scripts/check-production-docker.sh` reports 9/9 PASS.

Previous findings were re-confirmed against the current tree:

- **FIND-02** (crawl single-flight) — implemented: unique partial index `(tenant_id, website_id, active)` + `finish_if_active` single-terminator + `update_if_crawl_owner` fencing (`crawl_job_repository.py:107-143`, `website_repository.py:149-170`).
- **FIND-03** (worker logging) — implemented: shared JSON logging, `request_id`/`tenant_id` ContextVars per job, sensitive-data filter, secret-safe URL logging (`workers/app.py:70-76`, `workers/jobs/log_context.py`, `crawl_failure.py:safe_url_parts`).
- **FIND-05** (no-sandbox) — the **committed** template is fixed (`crawl_no_sandbox` default `False`, `.env.production.example:387 = false`, `compose.yml:232 = false`) and the browser emits WARNING telemetry when no-sandbox is forced (`browser.py:68-76`). **However the real, gitignored `.env.production` still sets `CRAWL_NO_SANDBOX=true` (line 418)** — see FIND-12.
- **FIND-06** (worker sizing) — pinned: `compose.prod.yml:71` memory 1G / cpus 2.0, boot-time resource-cap logging (`workers/app.py:38-59`), and the size check is enforced by `check-production-docker.sh [3/8]`.
- **FIND-08** (crawl timeout) — **FIXED at HEAD**: `crawl_website` is registered with its own finite timeout `crawl_job_timeout_seconds=3600` (`workers/tasks.py:43-46`, `config.py:355`) and the timeout path terminalizes the job via `_finalize_crawl_cancelled` (`workers/jobs/crawl.py:632-653, 740-847`), with dedicated tests (`tests/test_crawl_worker.py:1025-1148`).
- **FIND-07** (robots fail-closed) — verified `robots.py` + `crawler._fetch_robots` deny-all default on policy-unavailable, with operator escape hatch `CRAWL_ROBOTS_FAIL_OPEN` (posture false).

**Two configuration drift findings remain against the deployed production environment** (not the codebase): effective crawl concurrency and embedding-batch concurrency are **2 / 2** in the real `.env.production` while the committed template, compose defaults, and the Railway memory validation all pin **1 / 1** (FIND-11); and `CRAWL_NO_SANDBOX=true` is still forced in the real env against the fixed committed posture (FIND-12). Both are P2 (hardening) — they change risk headroom, not correctness.

There are no P0 or P1 blockers. The implementation is safe to freeze.

## 2. Current HEAD

`d024f2a` — the FINd-08 fix commit. Direct parents confirmed in the log:

- `d024f2a fix: add dedicated crawl job timeout` (HEAD)
- `3f49f3f fix: enable Chromium sandbox by default` (FIND-05 committed fix)
- `9b64519 fix: pin production worker resource sizing` (FIND-06 commit)

Working tree: **clean** (only pre-existing untracked investigation reports and `MOBILE_REVIEW_REPORT.md` remain; nothing modified; nothing staged). All existing audit/investigation docs were read and preserved as-is.

## 3. Scope

Verified (read-only, from source + committed config in this tree):

- Task registry and ARQ worker (`backend/workers/app.py`, `tasks.py`, `timing.py`, `jobs/*`)
- Crawler pipeline (`services/ingestion/{crawler,http_first,browser,ssrf_guard,crawl_memory,crawl_failure,extractor,cleaner,priority}.py`, `utils/{url_validator,robots}.py`)
- Knowledge pipeline (`services/knowledge/{processor,embedding,chunker}.py`, `ai/registry.py`, `services/ai/provider_health.py`)
- Persistence and tenant isolation (`repositories/*`, `repositories/vector/*`, `models/*`)
- Container/deployment shape (`docker/Dockerfile.worker`, `docker/compose.yml`, `docker/compose.prod.yml`, `.env.production.example`, `scripts/check-production-docker.sh`)
- The five required verification commands (Section 11)
- Real production env deltas (`.env.production`, gitignored) versus the committed posture (Sections 9, 12)

Not verified (out of scope / unavailable): live Railway runtime state, live Mongo/Redis data, live worker boot logs. BN caught in Section 13.

## 4. Architecture verification

- Entrypoint: `python -m backend.workers` (`Dockerfile.worker:73`); ARQ `WorkerSettings` at `workers/app.py:117-127` (`functions = tasks.TASKS`, `job_timeout = 600`, `max_jobs = 10`, `keep_result = 3600`).
- Task registry (`workers/tasks.py:48-54`): `ping`, `timed_job(send_email)`, `CRAWL_FUNCTION`, `timed_job(process_document)`, `timed_job(process_website_documents)`.
- Startup binds shared embedding client + embedding provider-health store (`app.py:62-91`); shutdown closes browser, Mongo, Redis each idempotently and independently (`app.py:102-114`).
- Job `ctx` correlation via `request_id_var`/`tenant_id_var` with finally-reset; `timed_job` logs `worker_job` records with queue-wait + duration when `PERF_TIMING_LOG_ENABLED=true`.
- Tenant data flow: ARQ payloads carry no tenant claims; worker resolves ownership from stored documents (`find_by_id_any`), then everything downstream is tenant-scoped (00-AI-Development-Rules §7).
- No stray/missing registry entries: the stale `finalize_crawl` reference noted in the FIND-08 investigation is **only a comment** (`tasks.py:8`) — no unregistered task is dispatched.

## 5. Crawler verification

- BFS crawl engine with caps (`crawl_max_pages=50`, `crawl_max_depth=3`), seeded priority paths (band 1), content-score frontier ordering (band 2), URL normalization (fragment/tracking-param stripping), SHA-256 document checksum (`crawler.py`).
- Robots.txt: fetched through the same SSRF-guarded fetcher; absent robots (404/410) → allow; policy-unavailable → deny-all (fail-closed) unless `CRAWL_ROBOTS_FAIL_OPEN=true` (`crawler.py:441-475`). Crawl-delay honoured between fetches.
- Page size caps: `crawl_max_html_bytes` (browser truncates, crawler skips still-oversized), `crawl_max_content_bytes` (stored-text cap). Too-thin pages stored as failed documents with "Insufficient content" (`crawler.py:368-371`).
- HTTP-first hybrid (`http_first.py`): plain `httpx` fetch, BOM/charset decode, streamed truncation, media sniffing, redirect hop validation through the guard (≤20), one browser fallback per URL; JS-shell verdict only for large shell-marked pages with little meaningful text (`judge_http_content`). Retryable-status set excludes 403 (`crawl_failure.py:56`); Retry-After honoured but capped at `crawl_retry_max_wait_seconds=30`.
- Browser path (`browser.py`): single shared Chromium per process with launch lock, per-job context, route-level SSRF guard on `**/*`, per-job context close; whole browser closed on worker shutdown. Semaphore `crawl_max_concurrent` bounds concurrent crawls (`browser.py:44-49`; used at `crawl.py:304`).
- Memory guard (`crawl_memory.py` + `crawler.py:417-439`): container-aware (cgroup v2 → v1 → /proc tree), fails open when unmeasurable, raises recoverable `CrawlMemoryGuardError` when ceiling configured. **Ceiling default 0 = disabled** (`config.py:378`).
- Egress hardening: `record_crawl_*` metrics + classified `CrawlJobError`s (fixed enum), per-host blocked/rate-limited early stop, `safe_url_parts` logging everywhere URLs are emitted (`crawl_failure.py:103-113`).

## 6. Embedding / knowledge verification

- `process_website_documents` fans a website's documents out per-document; website is locked to one embedding provider before fan-out (`processor.py:173-199`); fan-out fences run through atomic `acquire_embedding_run` / `finalize_embedding_run` (`website_repository.py:172-232`); stale jobs carrying a non-running `run_id` are skipped.
- `process_document`: checksum-skip when unchanged and chunks already stored (`processor.py:236-241`); insufficient-content → permanent failure; temporary `EmbeddingError` → document-level exponential retry 5s/30s/180s via deferred ARQ job (`workers/jobs/knowledge.py:55-64`), `rate_limited` (429) recorded non-terminally; permanent provider-config failures quarantine instead of switching embedding spaces (`registry.py:244-299`).
- Embedding client (`embedding.py`): `google.genai` async, `output_dimensionality` enforcement, per-batch retries with Retry-After/hint/backoff (429/5xx retryable; 4xx permanent), process-wide pacer `embedding_max_concurrent_batches` bounds in-flight batches, in-memory text→vector memo (cap 1024) avoids re-billing on retries, usage hook into daily rollup.
- Identity safety: chunks carry provider/model/dimensions/version; ingestion refuses mixed-identity corpora (`has_incompatible_identity` quarantine); `$vectorSearch` pre-filters on tenant+website+identity and re-asserts per chunk; brute-force cosine fallback with dimension-skew reporting (`repositories/vector/mongodb.py`).
- Cache invalidation after stored chunks: retrieval/lexical prefix deletion in both crawl and knowledge paths, best-effort.

## 7. Security / tenant verification

- SSRF: registration-time hostname/IP/port checks (`url_validator.py`) + per-navigation, per-redirect, per-route async fresh-DNS re-validation blocking any A/AAAA record in private/loopback/link-local/metadata ranges and all blocked ports (`ssrf_guard.py`); browser route guard aborts content not validated.
- Tenant isolation: every repository method tenant-scoped except worker-internal `find_by_id_any` (ownership read from stored data) and the admin surface (`list_any`/`count_any`, admin-role-gated only).
- Secrets hygiene: keys config-only (never logged/returned); URL logging via hostname+path only; `SensitiveDataFilter` attached in worker startup (`app.py:71`); audit actions carried only as enum + tenant.
- Prod validators: Mongo/Redis credentials required, `DEBUG`/`ENABLE_DOCS` fail-fast in production (`config.py:972+`).
- Docker hardening (verified by script, Section 11): non-root `appuser`, `cap_drop ALL`, `no-new-privileges`, read-only root fs + tmpfs (prod), no env-file copies, no privileged containers, bounded logs.

## 8. ARQ / job verification

- Timeout contract **verified**: `crawl_website` uses per-task `timeout=crawl_job_timeout_seconds` (3600 s); every other task inherits global 600 s (`workers/tasks.py:43-46`, `app.py:125`).
- Cancellation contract verified: `asyncio.CancelledError` (BaseException) is caught in `crawl.py:632-653` and terminalizes through `_finalize_crawl_cancelled` (single-terminator fenced, partial pages preserved, no knowledge handoff, website re-crawlable). Tests: `test_worker_cancellation_terminalizes_job_with_partial_pages`, `test_cancellation_emits_timeout_telemetry`, `test_worker_cancellation_zero_pages_fails_website`, `test_crawl_cancel_terminal_write_is_fenced`.
- Retry model: ARQ `max_tries=3`; only the final attempt writes permanent failure side effects (website, audit, metric); `InvalidUrlError` fails fast with no retry (`crawl.py:577-631`).
- Single-flight: enqueue uses job-scoped `_job_id="crawl:{id}"` so `keep_result` dedup can never suppress a new manual crawl (`crawl.py:117-129`); the partial unique index is the atomic gate (`create` raises `CrawlConflictError` on duplicates).
- Terminal ownership: only the winner of `finish_if_active` runs side effects (event, website write, audit, usage rollup, knowledge handoff, cache invalidation); `update_if_crawl_owner` prevents writes regressing a newer owner or resurrecting a deleted website.

## 9. Resource / Railway verification (1 GiB envelope)

- `Dockerfile.worker`: uv `python3.13-bookworm-slim`, `uv sync` retry loops, `playwright install --with-deps chromium`, PLAYWRIGHT_BROWSERS_PATH=/ms-playwright, uv cache cleaned, non-root `appuser`, Redis-ping healthcheck, `CMD python -m backend.workers`.
- Sizing: prod overlay worker = 1G memory / 2.0 CPU (`compose.prod.yml:71-72`), verified by check-production-docker.sh [3/8]. Base compose worker is 2G/2.0; the overlay is authoritative for production.
- Boot logs expose the effective memory shape against the 1 GiB / 2 vCPU target (`app.py:38-59`).
- **Effective production concurrency (REAL `.env.production`, gitignored): `CRAWL_MAX_CONCURRENT=2` (line 413), `EMBEDDING_MAX_CONCURRENT_BATCHES` unset → code default 2 (config.py:320). This contradicts both the committed posture (`CRAWL_MAX_CONCURRENT=1` `.env.production.example:376`, `EMBEDDING_MAX_CONCURRENT_BATCHES=1` `:331`, compose defaults `compose.yml:226/204`) and the Railway memory validation, which measured the 1 GiB envelope at **1×1**, worst JS peak 405 MiB (405/1024 = 40%, §5/§12 of `WORKER_MEMORY_GUARD_RAILWAY_VALIDATION_2026-09-12.md`).** See FIND-11.
- Memory guard: `CRAWL_MAX_RSS_MB` not present in `.env.production` → default 0 → guard disabled. This matches the documented policy (keep disabled until the ceiling is runtime-validated; `config.py:373-377`) and the validation doc's classification B ("needs more soak", ceiling NOT enabled).

## 10. Observability verification

- Structured logging: JSON in production (level from `ENVIRONMENT`/`LOG_LEVEL`/`DEBUG`), readable in dev; `request_id`/`tenant_id`/`job_id` on worker records (`core/logging.py`, `workers/jobs/*`).
- Metrics: dependency-free in-process registry, fixed label cardinality; crawl started/completed/failed, per-fetch-failure classification/status/method, memory-guard abort (`reason=memory_guard`), timeout terminalization (`reason=timeout`) (`core/metrics.py`).
- SSE live events: `crawl:progress:{job_id}` started/fetching/extracting/progress/completed/failed (`core/crawl_events.py`, wired in `crawl.py`).
- Timing: `worker_job` (queue-wait, duration, ok) and `chat_stage` records gated on `PERF_TIMING_LOG_ENABLED` (`timing.py`). Real `.env.production` sets it **true twice** (lines 49, 278) against the committed example's false — FIND-13.
- Failure surfacing: classified `CrawlJobError`s on the job document, safe user-facing reasons for blocked/rate-limited zero-page crawls, audit log entries on every terminal path, usage rollup for crawl pages + embeddings (best-effort, non-failing).

## 11. Test / static results (exact output)

| Check             | Command                                                 | Result                                                                                                                 |
| ----------------- | ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Tests             | `uv run pytest tests/ -q -p no:warnings --junitxml=...` | exit 0 — **2466 collected, 0 failures, 0 errors, 12 skipped**                                                          |
| Types             | `uv run mypy backend`                                   | `Success: no issues found in 203 source files`                                                                         |
| Lint              | `uv run ruff check backend/ tests/`                     | `All checks passed!`                                                                                                   |
| Format            | `uv run ruff format --check backend/ tests/`            | `363 files already formatted`                                                                                          |
| Docker prod audit | `bash scripts/check-production-docker.sh`               | 8/8 checks PASS + compose validation PASS → `Production Docker audit: 9 passed, 0 failed (of 9 checks)` `RESULT: PASS` |

Warnings observed (non-failures): starlette/httpx `TestClient` deprecation notices and a per-request-cookie deprecation notice in `tests/test_crawl_api.py`, plus one `RuntimeWarning` (unawaited `asend`) in `tests/test_gemini_client.py:164`. No warnings in worker code.

## 12. Findings

### FIND-11 (P2) — Effective production concurrency (2/2) exceeds the validated-and-documented posture (1/1); memory guard disabled

- File/function: `.env.production` (gitignored) lines 413 (CRAWL_MAX_CONCURRENT=2) and absent EMBEDDING_MAX_CONCURRENT_BATCHES → `config.py:320/361` defaults (2/2). Contrast: `.env.production.example:331/376` (1/1), `docker/compose.yml:204/226` (1/1), and the Railway validation shape (§1 of `WORKER_MEMORY_GUARD_RAILWAY_VALIDATION_2026-09-12.md`).
- Evidence: config defaults `embedding_max_concurrent_batches: int = 2` (config.py:320) and `crawl_max_concurrent: int = 2` (config.py:361); validation doc measured worst JS crawl at **405 MiB / 1024 MiB (40%)** under 1×1; headroom under 1×1 was ≥60%.
- Impact: two concurrent JS-fallback crawls (worst-case fan-out on a JS-heavy site) would share one browser but each holds a context + page; worst observed single-crawl peak 405 MiB does not include deep-DOM/max-5MB pages or the embed phase (listed as unmeasured in §14 of the validation doc). At 2×2 that headroom is materially thinner (potentially well under the ≥20% guidance) inside the hard 1024 MiB cap, and no ceiling (`CRAWL_MAX_RSS_MB=0`) protects the worker. The memory guard fails open and crawls retry, so the blast radius is a failed crawl, not corruption.
- Reproducibility: deterministic configuration state — reproducible on Railway preview/deploy using `.env.production`; runtime peak must be measured (see mitigation).
- Existing mitigations: guard fails open + ARQ retries; semaphore bounds browser-driven crawls; HTTP-first keeps most crawls browser-free (~59 MiB).
- Recommendation: align the deployed env to the **validated 1×1 shape** (set `CRAWL_MAX_CONCURRENT=1`, `EMBEDDING_MAX_CONCURRENT_BATCHES=1` in the real env), **or** re-run the Railway browser-crawl soak at 2×2 before shipping; either way document the chosen value next to the validation doc. Keep `CRAWL_MAX_RSS_MB=0` until the soak yields a defensible ceiling with ≥20% headroom.
- Blocking: **No** (P2 hardening).

### FIND-12 (P2) — Real production env still forces `CRAWL_NO_SANDBOX=true`

- File/function: `.env.production:418` (comment "Set false behind a non-root production image") vs the value `true`; code posture `config.py:363-367` (sandbox-on production default) and `compose.yml:228-232` (default false); committed example `:387` false (FIND-05's fix shipped only to the tracked posture).
- Evidence: browser launch appends `--no-sandbox` only when `crawl_no_sandbox` is true (`browser.py:68-69`) and now emits WARNING telemetry when forced (`browser.py:70-76`). The non-root runtime supports Chromium's user-namespace sandbox; `cap_drop ALL`/no-new-privileges remain in effect either way.
- Impact: if Railway genuinely cannot sandbox, this is the sanctioned escape hatch and the risk is accepted; otherwise, defense-in-depth is silently reduced on the exact attacker-controlled surface (JS-rendered pages) the crawler processes.
- Reproducibility: configuration state, deterministic.
- Existing mitigation: WARNING log at launch; layered container hardening (non-root, cap_drop ALL, no-new-privileges, read-only FS); only JS-fallback pages reach Chromium.
- Recommendation: perform the FIND-05-prescribed deploy-time user-namespace smoke test on Railway; if sandboxing works, set `CRAWL_NO_SANDBOX=false` in the real env; if not, keep true and record the decision (with the now-present WARNING visible in boot logs). FIND-05 doc's remediation steps 1–4 apply.
- Blocking: **No** (P2 defense-in-depth).

### FIND-13 (P3) — `PERF_TIMING_LOG_ENABLED=true` duplicated and enabled in the real production env

- File/function: `.env.production:49` and `.env.production:278` (duplicate) = `true`; `.env.production.example:47` = `false` (opted-out template).
- Evidence: `perf_timing_log_enabled: bool = False` default (`config.py:592`); `timing.py` emits `worker_job`/`chat_stage` records only when enabled.
- Impact: worker per-job timing logs (`queue_wait_ms`, `duration_ms`) are emitted on every job in production while the committed example keeps them off; the duplicate line invites future divergence. Log volume grows; no correctness impact.
- Reproducibility: configuration state, deterministic.
- Existing mitigation: none needed for safety; records carry no secrets (job id, timings only).
- Recommendation: decide the production intent — if timing telemetry is wanted, keep a single `PERF_TIMING_LOG_ENABLED=true` and update the example to match; if not, set false. At minimum remove the duplicate line.
- Blocking: **No** (P3 polish).

### Previously-open findings verified as CLOSED at HEAD `d024f2a`

- FIND-02 single-flight fencing, FIND-03 worker logging, FIND-05 committed template + browser WARNING, FIND-06 1 GiB/2 vCPU pin + boot caps log, FIND-07 robots fail-closed, and **FIND-08** (dedicated 3600 s crawl timeout + cancellation-safe terminalization) are all present and covered by passing tests (Sections 4–8, 11). No finding re-opened during this verification.

## 13. Residual risks

- **Category C (runtime unknowns).** Live Railway state was not reachable from this environment: worker boot logs, actual peak RSS in production, whether the platform blocks user namespaces, exact Railway replica sizing, and how `webchat-ai-production-7e84.up.railway.app`'s env maps to the local `.env.production` are unconfirmed. FIND-11/12 conclusions follow from the config in this tree.
- Memory guard remains disabled (consistent with documented policy) — worst-case 5 MB DOM + embed-phase memory is unmeasured; the validation doc's soak plan (browser crawl on a max-size/JS-heavy page, a multi-page site, and extended idle) is the committed path to a defensible ceiling.
- `CRAWL_MAX_RSS_MB` and Effective concurrency are runtime-env-owned values; nothing in CI pins the deployed `.env.production`. The docker audit script pins only the container-compose shape, not the Railway env.

## 14. Verdict

**STOP — WITH TRACKED FOLLOW-UPS (option B).**

No P0/P1 items exist in code, config, Docker, tests, or static checks. The three findings are P2/P3 configuration-drift items in the **deployed** env file (concurrency 2/2 vs validated 1/1; `CRAWL_NO_SANDBOX=true`; duplicated perf-timing flag), not implementations to change. Follow-ups are env hygiene + one Railway soak, tracked separately.

> Worker implementation can now be frozen. Remaining items are follow-up hardening, not blockers.

## 15. Recommended next project focus

1. **Railway env reconciliation (hardening, this repo's ops surface):** set the real env to the validated concurrency posture or re-soak at 2×2; run the FIND-05 sandbox smoke test; single-source the perf-timing flag.
2. **Memory-guard soak (per validation doc):** browser crawl against a max-size/deep-DOM page + multi-page site + extended idle at the chosen concurrency, then set `CRAWL_MAX_RSS_MB` with ≥20% headroom.
3. Next feature area (out of worker scope, proposes itself now complete): a distributed-multi-worker story is explicitly a follow-up design (FIND-02 lock design doc) and should not land pre-1.0 without a dedicated queue-locking pass.

---

_Read-only. Nothing in this audit modified source, tests, config, Docker files, or any existing report. New report only; git tree left as found._
