# WORKER ↔ FRONTEND INTEGRATION FORENSIC AUDIT

**Audit date:** 2026-09-13
**HEAD:** `d024f2ad605084b422c1791f12d4d078af97c979` (branch `main`)
**Mode:** READ-ONLY. No source, tests, Docker, env, or config modified. Only this report file exists.
**Evidence rule:** every finding below cites real source location, real state transition, real frontend consumer. No speculation is used inside CONFIRMED findings.

---

## 1. Executive Verdict

```
FRONTEND FIX REQUIRED
```

Worker ↔ API state transitions are correct and the widget chat stream path is clean, but the dashboard frontend renders Worker state incorrectly in three confirmed ways that reproduce the reported symptoms:

- "Ready" is displayed while embedding/knowledge processing is still running (field mismatch: `website.status` vs `website.knowledge_status`).
- Embedding progress is invisible on the crawl/sites/dashboard surfaces (dead SSE event path + progress bar cleared on job completion); only the Knowledge page shows it.
- Conversations list/detail never live-update (static React Query queries; no polling, no focus refetch).

Plus one confirmed presentation issue in the widget: answers ≥ 1200 chars are intentionally collapsed after streaming and read as "cut in the middle".

---

## 2. Actual Architecture

Real end-to-end flow, every hop traced to code:

```
USER action                     apps/dashboard: WebsiteCard → handleCrawl → startCrawl.mutateAsync
  →  POST /websites/{id}/crawl  apps/dashboard/src/features/websites/hooks.ts:useStartCrawl
  →  backend enqueue            backend/services/crawl/crawl_service.py:112 (website.status='crawling')
  →  ARQ job                    backend/workers/jobs/crawl.py (worker enqueues + executes task)
  →  crawl lifecycle            crawl.py:246 job='running'; 297 job='processing'; 342/602/672/793 fail; 491 'completed'
  →  website status writes      crawl.py:350/353 (fail path), 499, 801/804 (success/partial) — status='ready'/'failed'
  →  Mongo                      backend/models/website.py:73 (status), :86 (knowledge_status default 'none')
  →  embedding fan-out          backend/services/knowledge/processor.py:193 website.knowledge_status='processing' → 726 'ready' / 734,743 'failed'
  →  backend API response       backend/schemas/websites.py:31,39,59 WebsiteOut serializes status + knowledge_status
  →  React Query write          apps/dashboard: useWebsites fetch OR CrawlJobSync site-poll setQueryData
  →  component                  WebsiteCard / DashboardHome / KnowledgePage
  →  visible UI state
```

Parallel real-time paths:

- **Crawl SSE:** worker publishes `crawl.snapshot/started/fetching/extracting/progress/completed/failed` to channel `crawl:progress:{job_id}` (`backend/core/crawl_events.py`); backend streams them via `GET /crawl-jobs/{id}/stream` and closes the stream at the terminal event (`backend/api/routes/crawl_jobs.py:88,123`). Frontend consumes via `useCrawlProgress` (`features/websites/hooks.ts:178-205`, listeners: snapshot/started/progress/fetching/completed/failed) and mirrors SSE closure on terminal.
- **Crawl job poll:** `useCrawlJob` polls `GET /crawl-jobs/{id}` every 3 s while SSE is down and the job is non-terminal (fallback — also the accounting source for the progress bar).
- **Website poll:** `CrawlJobSync` polls `GET /websites/{id}` every 3 s (active or post-terminal until `knowledge_status ∈ {ready, failed}`) and mirrors the snapshot into the `['websites']` list cache.
- **Knowledge page poll:** `useKnowledgeDocuments` polls every 3 s while its summary has `pending + processing > 0` (`features/knowledge/hooks.ts`).
- **Conversations:** no poll, no SSE. `useConversations`/`useConversation` are mount-once queries.
- **Widget chat:** POST `/api/widget/v1/chat` fetch-stream; backend emits `event: sources|message|done|error` with 15 s heartbeat comments (`backend/api/sse.py:60-61`) and guaranteed terminal `done` (`backend/api/sse.py:130-197`); `apps/widget/src/core/sse.ts` parses; 45 s client stall watchdog (`widget/src/stream/client.ts`) vs backend 30 s per-call guard (`backend/core/config.py:456`).

API contract integrity (field name / type / serialization) verified intact: `WebsiteOut` (`schemas/websites.py:26-64`) ↔ `Website` (`features/websites/types.ts:9-28`); `CrawlJob` (`schemas/crawl_jobs.py`) ↔ `CrawlJob` (`types.ts:68-92`); `ConversationSummary/Detail` (`schemas/conversations.py:15-59`) ↔ `types.ts:7-53`). No mismatch.

---

## 3. Worker State Machine

Constants: `website.status` ∈ {pending, crawling, processing, ready, failed} (`models/website.py:45-47`, default `pending`:73). `crawl_job.status` ∈ {pending, running, processing, completed, failed} (`models/crawl_job.py:16-18`, default pending:56). `knowledge_status` ∈ {none, pending, processing, ready, failed, rate_limited} (`models/knowledge_chunk.py:20-31`); **website-level** `knowledge_status` is only ever assigned none/processing/ready/failed (below).

| Event                              | Field                       | Old                 | New               | File/Function                                                    | Persisted Where |
| ---------------------------------- | --------------------------- | ------------------- | ----------------- | ---------------------------------------------------------------- | --------------- |
| Website created                    | `website.status`            | —                   | `pending`         | `services/website/website_service.py:234`                        | Mongo           |
| Crawl enqueued/started             | `website.status`            | pending/crawling    | `crawling`        | `services/crawl/crawl_service.py:112`                            | Mongo           |
| Crawl task starts                  | `job.status`                | pending             | `running`         | `workers/jobs/crawl.py:246`                                      | Mongo           |
| Crawl in progress                  | `job.status`                | running             | `processing`      | `workers/jobs/crawl.py:297`                                      | Mongo           |
| Crawl OK (pages found)             | `job.status`                | processing          | `completed`       | `crawl.py:491`                                                   | Mongo           |
| Crawl OK                           | `website.status`            | crawling/processing | `ready`           | `crawl.py:499`                                                   | Mongo           |
| Crawl failed, 0 KB pages           | `website.status`            | crawling/processing | `failed`          | `crawl.py:350`, `607`, `677`, `801`                              | Mongo           |
| Crawl failed, existing KB survives | `website.status`            | —                   | `ready`           | `crawl.py:353`, `804`                                            | Mongo           |
| Crawl failed                       | `job.status`                | processing          | `failed`          | `crawl.py:342`, `602`, `672`, `793`                              | Mongo           |
| Embed fan-out (site)               | `website.knowledge_status`  | none                | `processing`      | `services/knowledge/processor.py:193`                            | Mongo           |
| Embed fan-out (doc)                | `document.knowledge_status` | —                   | `processing`      | `processor.py:243`                                               | Mongo           |
| Doc embed outcome                  | `document.knowledge_status` | (varies)            | status / `failed` | `processor.py:595`, `630`                                        | Mongo           |
| Embed hard-fail (crawl-time)       | `document.knowledge_status` | —                   | `failed`          | `services/ingestion/crawler.py:369`, `document_repository.py:96` | Mongo           |
| All docs embedded                  | `website.knowledge_status`  | processing          | `ready`           | `processor.py:726`                                               | Mongo           |
| All docs failed                    | `website.knowledge_status`  | processing          | `failed`          | `processor.py:734`, `743`                                        | Mongo           |

**Key structural fact:** `website.status` flips to `ready` when the **crawl** terminates (crawl.py:499/353/804) — embedding has not run yet. `website.knowledge_status` reaches `ready` only after **all documents are embedded** (processor.py:726). Between those two points, `status='ready'` AND `knowledge_status='processing'` coexist. Nothing marks a **cancelled** state in this codebase (no CANCELLED enum; abort surfaces as `failed`).

---

## 4. Frontend State Consumption

| Frontend UI                              | Data Source (hook)                                  | Field Used                                              | Refresh Mechanism                                         | Terminal Condition                         | Correct?                                   |
| ---------------------------------------- | --------------------------------------------------- | ------------------------------------------------------- | --------------------------------------------------------- | ------------------------------------------ | ------------------------------------------ |
| WebsiteCard StatusBadge                  | `useWebsites` (list) or `CrawlJobSync` poll         | `website.status`                                        | watcher 3s poll / page-mount                              | none (badge static per value)              | ✗ shows "ready" pre-embed                  |
| WebsiteCard KnowledgeBadge               | same                                                | `website.knowledge_status`                              | same                                                      | `ready`/`failed`                           | ✓                                          |
| DashboardHome "Ready" count              | `useWebsites`                                       | `status === 'ready'` (dashboard-home.tsx:93)            | static (only watcher while mounted)                       | —                                          | ✗ premature                                |
| DashboardHome checklist "Install widget" | `useWebsites`                                       | `status === 'ready'` (dashboard-home.tsx:139)           | static                                                    | —                                          | ✗ premature                                |
| CrawlStatusBanner                        | `useWebsites`                                       | `status === 'crawling'`                                 | static (watcher)                                          | never during embedding                     | ✗ nothing to show during embed             |
| CrawlJobProgressBar                      | `useCrawlProgress` SSE + `useCrawlJob`              | merged `status`                                         | SSE / 3s poll                                             | returns null when job `completed`/`failed` | ✗ embedding state unreachable              |
| CrawlActivityProvider/CrawlJobSync       | site list + `['crawl-job', id]` + `['website', id]` | `job.status`, `knowledge_status`                        | 3s polls; 1s terminal settle check; 60s embed-start grace | `finish()` on settle/grace                 | ⚠ 60s-grace gap (FINDING-5)                |
| KnowledgePage "Websites ready"           | `useWebsites`                                       | `knowledge_status === 'ready'` (knowledge-page.tsx:248) | static + documents 3s poll                                | —                                          | ✓ (disagrees with DashboardHome by design) |
| KnowledgePage documents                  | `useKnowledgeDocuments`                             | summary pending/processing                              | 3s poll while >0                                          | `0`                                        | ✓                                          |
| Conversations list                       | `useConversations`                                  | `ConversationSummary`                                   | **none** (mount/refetch-on-error only)                    | —                                          | ✗ stale (FINDING-3)                        |
| Conversation detail                      | `useConversation`                                   | `ConversationDetail`                                    | **none**                                                  | —                                          | ✗ stale (FINDING-3)                        |
| Dashboard stats (usage/conversations)    | `useUsage`, `useConversations({perPage:1})`         | counts                                                  | **none**                                                  | —                                          | ✗ stale (FINDING-6)                        |
| Widget chat bubbles                      | widget `Conversation` in-memory                     | full message deltas                                     | rAF                                                       | `done`/`error`/abort                       | ✓ (transport) + ✗ collapse (FINDING-4)     |

React Query defaults: `staleTime: 30_000`, `retry: 1`, `refetchOnWindowFocus: false` (`apps/dashboard/src/app/providers.tsx:20-23`).

---

## 5. Confirmed Findings

### FINDING-1 — P1 — Confirmed

**Symptom:** Website card and dashboard show "Ready" while the Worker is still embedding; Knowledge page shows "processing" for the same site.
**Actual evidence:** `backend/schemas/websites.py:31,39` serializes both `status` and `knowledge_status`; frontend `Website` type carries both (`features/websites/types.ts:14,22`). Consumers key on the wrong field:

- `dashboard-home.tsx:93` `ready = websites.filter(site => site.status === 'ready')`
- `dashboard-home.tsx:139` `done: websites.some(s => s.status === 'ready')` (onboarding "Install widget")
- `website-card.tsx:69` renders `StatusBadge` for `website.status`
  Knowledge page correctly uses `knowledge_status` (`knowledge-page.tsx:248`) → the two pages visibly disagree.
  **Root cause:** `website.status='ready'` is written at **crawl** termination (`workers/jobs/crawl.py:499` success; `:353`,`:804` partial-survival); `website.knowledge_status` reaches `ready` only at **embed** completion (`processor.py:726`). The "ready-for-chat" field is `knowledge_status`, but the dashboard's ready checks read `status`.
  **Exact files:** `apps/dashboard/src/features/dashboard/dashboard-home.tsx:93,139`; `apps/dashboard/src/features/websites/website-card.tsx:69`; backend writes `backend/workers/jobs/crawl.py:353,499,804`, `backend/services/knowledge/processor.py:726`.
  **Timeline:**

```
T0 crawl starts            website.status='crawling'   (crawl_service.py:112)
T1 crawl completes         job.status='completed', website.status='ready' (crawl.py:491,499)
T2 embedding fan-out       website.knowledge_status='processing' (processor.py:193)
   → API serializes status='ready' & knowledge_status='processing' (websites.py:59)
   → dashboard renders "Ready"     (congruent: status=='ready' at dashboard-home.tsx:93)
   → Knowledge page renders "processing" (knowledge_status at knowledge-page.tsx:248)
T3 all docs embedded       website.knowledge_status='ready' (processor.py:726) → only then truly ready
```

**Impact:** Misleading UI state ("Ready" while chat metadata still building), contradictory pages.

### FINDING-2 — P1 — Confirmed

**Symptom:** No embedding progress visible on crawl/sites/dashboard surfaces; the "Generating embeddings…" UI is dead end-to-end.
**Actual evidence:**

1. Worker **does not emit** embedding events: `publish_embedding` defined (`backend/core/crawl_events.py:96`) but has **zero call sites** (grep across `backend/` confirms only extract/completed/failed are published: `crawl.py:282`, `:495`).
2. Backend crawl stream **closes at terminal** (`backend/api/routes/crawl_jobs.py:88,123`), so no post-terminal events can arrive even if published.
3. Frontend **does not subscribe** to `crawl.extracting`/`crawl.embedding`: `useCrawlProgress` listeners are only snapshot/started/progress/fetching/completed/failed (`features/websites/hooks.ts:178-205`).
4. Progress bar **clears on completion**: `CrawlJobProgressBar` renders nothing once `job.status` is `completed`/`failed` (`crawl-job-progress-bar.tsx:13-23,84`); the `'embedding'` branch (`:51-55`, label "Generating embeddings…") is unreachable.
   **Root cause:** The embedding phase is only observable via `website.knowledge_status` + knowledge-document counts on the **Knowledge page**; the websites/dashboard surfaces have no renderer for it.
   **Exact files:** `apps/dashboard/src/features/websites/hooks.ts:178-205`; `crawl-job-progress-bar.tsx:13-23,51-55,84`; `backend/core/crawl_events.py:96`; `backend/api/routes/crawl_jobs.py:88,123`.
   **Impact:** During embedding the card shows a green "ready" badge + amber knowledge chip and nothing else — reinforcing FINDING-1's "Ready too early" perception and the "Worker still working but frontend appears finished" symptom.

### FINDING-3 — P1 — Confirmed

**Symptom:** New/updated conversations (and in-progress assistant answers) are invisible in `/conversations` and in the conversation detail until manual refresh or navigation.
**Actual evidence:** `useConversations` (`features/conversations/hooks.ts:33-37`) and `useConversation` (`:39-46`) are plain `useQuery` calls — **no `refetchInterval`**. Global defaults (`app/providers.tsx:20-23`) set `staleTime: 30s`, `refetchOnWindowFocus:false`, `retry:1`. The only refresh triggers are mount/navigation (page remount), the error-state `refetch()` (`conversations-page.tsx:125`), and `useDeleteConversation.onSuccess` invalidation (`hooks.ts:53-55`). `ConversationSummary.status` (`'answered'|'awaiting'`, `features/conversations/types.ts:5`) exists but is **not** used to drive any refresh. Conversation detail is a static transcript render (`conversation-detail.tsx`, no polling/streaming).
**Root cause:** No live subscription/poll for conversation state while the API exposes it (backend has no conversation SSE; a frontend poll is the only available mechanism and is absent).
**Exact files:** `apps/dashboard/src/features/conversations/hooks.ts:33-46`; `app/providers.tsx:20-23`; `conversations-page.tsx:30-35,125`.
**Impact:** "UI stale until refresh/navigation" for conversations — a direct match to the reported symptom.

### FINDING-4 — P2 — Confirmed

**Symptom:** "Answer gets cut in the middle."
**Actual evidence:** The widget intentionally collapses completed assistant messages longer than `LONG_MESSAGE_CHARS = 1200` (`apps/widget/src/ui/bubbles.ts:31`) behind `wc-long`/`wc-collapsed` classes toggled by `syncCollapse` (`bubbles.ts:350-373`). The collapse is **disabled while streaming** (`bubbles.ts:289`), so the long bubble renders fully during streaming and visibly "caps" to 1200 chars the moment the turn completes. There is no visual truncation cue (ellipsis/gradient) — only a `Show more`/`Show less` control appended at the end of the bubble.
**Classification:** This is option **F (intentional "show more" collapsing)**. Not transport/parse/state/persistence/CSS-cut truncation (see Non-Findings).
**Exact files:** `apps/widget/src/ui/bubbles.ts:31,289,350-373`.
**Impact:** The single most likely source of the "cut-in-the-middle" report for long index answers; also interacts with FINDING-3 (the dashboard shows the full transcript only after a refresh, so the collapse looks permanent).

### FINDING-5 — P3 — Confirmed

**Symptom:** If the Worker queues an embedding fan-out that does not flip `website.knowledge_status` to `processing` within 60 s of crawl completion, the dashboard permanently loses live tracking: the final `ready`/counts appear only after a manual refresh.
**Actual evidence:** `CrawlJobSync` terminate-watch finishes the sync when `knowledgeStatus !== 'processing'` after `KNOWLEDGE_START_GRACE_MS = 60_000` (`crawl-activity-context.tsx:226-239`). On finish it removes the `['crawl-job', id]` query (`:244-246`) and drops the site poll; embedding later completing (`processor.py:726`) triggers **no invalidation** on the frontend. Prod concurrency is `EMBEDDING_MAX_CONCURRENT_BATCHES=1` (`.env.production`, verified), so a site queued behind others can exceed 60 s before `knowledge_status='processing'`.
**Exact files:** `apps/dashboard/src/features/websites/crawl-activity-context.tsx:226-239,244-246`.
**Impact:** A genuine race window where "Worker still working; frontend stuck/Ready until refresh" (mechanism distinct from FINDING-1).

### FINDING-6 — P3 — Confirmed

**Symptom:** Dashboard stat cards (Conversations, Messages sent) never update while the user sits on `/`.
**Actual evidence:** `useUsage()` and `useConversations({page:1, perPage:1})` (`dashboard-home.tsx:82-83`) are static; `refetchOnWindowFocus:false` (`app/providers.tsx:22`).
**Exact files:** `apps/dashboard/src/features/dashboard/dashboard-home.tsx:82-83`.
**Impact:** Minor; reinforces the "stale until refresh" perception.

---

## 6. Non-Findings

Items actually investigated and disproved:

- **SSE parser truncation — NOT CONFIRMED.** `apps/widget/src/core/sse.ts` uses `TextDecoder('utf-8', {stream:true})`, CRLF normalization, buffered-frame splitting across chunk boundaries, and terminal-event idempotency; covered by `core/sse.test.ts`. No path drops committed stream bytes.
- **Transport truncation — NOT CONFIRMED.** Client stall watchdog is 45 s (`CHAT_STALL_TIMEOUT_MS`) while the backend per-call guard is 30 s (`config.py:456`) plus 15 s heartbeats (`api/sse.py:60-61`); a dead/backed-up connection produces an explicit error → fail turn, not silent truncation.
- **React-state / persistence truncation — NOT CONFIRMED.** Widget appends full deltas to the in-memory transcript; server persists the full answer at `done`; dashboard detail renders full `content` with no slice/LineClamp.
- **Worker state corruption — NOT CONFIRMED.** All `status`/`knowledge_status` transitions in section 3 are monotone and guarded by crawl-owner fencing (`update_if_crawl_owner`, `crawl.py:363`).
- **React Query write race on `['websites']` — NOT CONFIRMED.** Single watcher per website key; `setQueryData` overwrites are ordered by recency and always reflect the latest poll; no torn state observed.
- **`useStartCrawl` not invalidating `['website', id]` — NOT CONFIRMED as a defect.** The only consumer of the detail key is the self-healing `CrawlJobSync`; no user-visible staleness.
- **Active-crawl store on refresh — CONFIRMED CORRECT.** `sessionStorage webchat_active_crawl_jobs` restores tracking after reload (`active-crawl-store.ts`; `active-crawl-store.test.ts`).
- **Missing crawl-SSE heartbeat — NOT CONFIRMED as a defect.** No heartbeat, but the pub/sub event cadence keeps the stream alive during crawls and server idle timeout is 1800 s (`config.py:629`); client backoff (≤3 attempts) + 3 s job polling is the fallback (`hooks.ts:110-116,207-237`).
- **API field-name mismatch — NOT CONFIRMED.** Backend serializers match frontend TS types exactly (section 2).

---

## 7. Race Condition Analysis

| Race                                                               | Result                                                           | Evidence                                                                                                                                                                                                                                 | Severity |
| ------------------------------------------------------------------ | ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| R1 mutation → invalidation → store update ordering                 | Possible but harmless                                            | `startCrawl.onSuccess` sets crawl-job cache + invalidates websites list, then caller `activeCrawlStore.set` runs in the same handler (`website-list.tsx`); only a hard reload in the same millisecond loses the store entry              | —        |
| R2 SSE terminal vs polling ordering                                | Possible but harmless                                            | SSE closes on `crawl.completed/failed` (`hooks.ts:187-205`); job poll authoritative and idempotent; terminal handled once                                                                                                                | —        |
| R3 website polling vs knowledge polling ordering                   | Not present                                                      | Separate query keys/caches (`['website',id]` vs `['knowledge','documents',…]`); no dependency                                                                                                                                            | —        |
| R4 crawl completed → embedding starts → frontend stops polling     | **Confirmed**                                                    | Job terminal disarms SSE/job-poll; site poll continues only until `knowledge_status ∈ {ready, failed}` or the **60 s grace abort** (`crawl-activity-context.tsx:226-239`). If embedding starts >60 s late, tracking is lost → FINDDING-5 | P3       |
| R5 unmount → cleanup → late response                               | Possible but harmless                                            | Watchers clear intervals/EventSource on unmount; an in-flight refetch resolving late writes the same settled snapshot                                                                                                                    | —        |
| R6 60 s grace / watchdog timers                                    | **Confirmed**                                                    | `KNOWLEDGE_START_GRACE_MS=60_000` hard drop (FINDING-5); the 3 600 000 ms forced-stop is a dead cap                                                                                                                                      | P3       |
| R7 `staleTime` preventing fresh Worker state                       | Possible but harmless (websites) / **Confirmed (conversations)** | Live monitor bypasses staleness via `setQueryData` + invalidations; static queries (conversations, dashboard stats) never refetch → FINDING-3, FINDING-6                                                                                 | P1/P3    |
| R8 query removal before backend reaches final state                | **Confirmed**                                                    | `['crawl-job', id]` removed at `finish()` while knowledge may still reach `ready` after the grace gap; no re-invalidation (FINDING-5)                                                                                                    | P3       |
| R9 navigation/remount producing newer data while old cache remains | Not present (websites) / **Confirmed (conversations)**           | Websites share one invalidated cache; conversations degrade to mount-time snapshots (`staleTime` keeps old data for 30 s)                                                                                                                | P1       |

---

## 8. Browser Verification

- Tests attempted: none (local E2E requires a configured backend with live provider credentials).
- Tests passed: none.
- Tests blocked:
  1. **No embedding/chat provider keys in the local dev environment** — the `webchat-worker` container crash-loops on `ProviderConfigurationError`, so no crawl → embed → chat flow can run locally.
  2. **Audit is under a strict no-modification, no-configuration constraint** — activating the required provider/env state would itself change the environment.
- Actual observations: none fabricated. All conclusions are code-traced (sections 2–7) and supported by the existing automated suites (section 9).

---

## 9. Test Results

Read-only execution; nothing modified.

| Check                                  | Command                             | Result                                                          |
| -------------------------------------- | ----------------------------------- | --------------------------------------------------------------- |
| Dashboard unit tests                   | `pnpm test` (apps/dashboard)        | **52 files / 428 tests — PASS**                                 |
| Widget unit tests                      | `pnpm test` (apps/widget)           | **29 files / 322 tests — PASS**                                 |
| Dashboard typecheck                    | `pnpm typecheck` (tsc --noEmit)     | PASS                                                            |
| Widget typecheck                       | `pnpm typecheck` (tsc --noEmit)     | PASS                                                            |
| Dashboard lint                         | `pnpm lint` (eslint)                | PASS                                                            |
| Widget lint                            | `pnpm lint` (eslint)                | PASS                                                            |
| Backend suite (prior session evidence) | 2466 pytest / mypy 203 files / ruff | PASS — see `docs/WORKER_FINAL_VERIFICATION_AUDIT_2026-09-12.md` |
| Browser/E2E                            | —                                   | BLOCKED (section 8)                                             |

Coverage notes supporting the findings: existing tests assert the current (wrong) semantics — `website-list.test.tsx` fixtures use `status:'ready'` with `knowledge_status:'processing'` and expect "Start crawl" normal rendering; there is **no test** asserting "Ready requires `knowledge_status==='ready'`" (gap = FINDING-1), no embedding-phase UI test (gap = FINDING-2), no conversation-refresh test (gap = FINDING-3). Grace/settle/backoff paths ARE covered (`crawl-activity.test.tsx:337,392,421,477`; `hooks.test.tsx:169-294,431,461`).

---

## 10. Root-Cause Ranking

- **P1:** FINDING-1 (Ready keyed on `status` not `knowledge_status`), FINDING-2 (embedding progress dead end-to-end), FINDING-3 (static conversations). All three are **frontend-side** defects over an **intact** backend contract.
- **P2:** FINDING-4 (widget long-answer collapse read as truncation).
- **P3:** FINDING-5 (60 s embedding-start grace can strand tracking), FINDING-6 (static dashboard stats).

No P0. Worker-side logic is not the source of any confirmed issue.

---

## 11. Recommended Fix Scope

Documented for a later change only — **not implemented** (audit).

**Frontend-only (can be fixed without Worker changes):**

- FINDING-1: derive all "ready"/onboarding/widget states from `website.status === 'ready' && website.knowledge_status === 'ready'` (offer an embedding progress caption from `knowledge_documents`/`knowledge_chunks`); align DashboardHome with KnowledgePage's `knowledge_status` semantics. Add regression tests (fixture `{status:'ready', knowledge_status:'processing'}` must NOT be "Ready").
- FINDING-2 (partial): render the embedding state in `CrawlJobProgressBar`/card from the already-live site poll (`knowledge_status === 'processing'` after `job.status === 'completed'`), using `knowledge_documents` as progress. No Worker change required.
- FINDING-3: add a modest `refetchInterval` on `useConversations`, and on `useConversation` while `status === 'awaiting'`/non-terminal (mirror the knowledge-page polling pattern); optionally re-enable `refetchOnWindowFocus`. Add regression tests.
- FINDING-4: do not collapse the message that just finished streaming (or add an unmissable gradient/ellipsis cue); raise the threshold. Add a `>1200`-char completion regression test asserting full visibility or an explicit cue.
- FINDING-5: on grace expiry, perform one authoritative site refetch and, if knowledge is still non-terminal, downshift to a low-frequency watch instead of a hard drop; or raise the grace above a worst-case embedding queuing delay. Extend `crawl-activity.test.tsx` for the late-start case.
- FINDING-6: poll `useUsage`/aggregate conversations at low frequency or restore focus refetch.

**Backend/Worker dependency (frozen — required separately, NOT part of any frontend fix):**

- Emit and stream `crawl.embedding` (and `crawl.extracting`) events after crawl terminal if a real embedding progress stream is desired on the websites surface (`backend/core/crawl_events.py:96` currently unused; `backend/api/routes/crawl_jobs.py` closes at terminal).
- Widget chat gate `backend/services/widget/widget_service.py:317` currently allows chat at `website.status == ready` before `knowledge_status == ready` — if chat-before-embeds is undesirable, gate on `knowledge_status`.

**Runtime/deployment:** none required.

---

## 12. Final Decision

```
B. FRONTEND FIX REQUIRED
```

Frontend changes are required; the Worker/API contract is intact and no Worker change is necessary for the confirmed issues (optional embedding-event emission is a separate enhancement).

---

## Appendix — Git Safety

- Branch before: `main`
- HEAD before/after: `d024f2ad605084b422c1791f12d4d078af97c979`
- Working tree before: clean except pre-existing untracked docs (`docs/WORKER_*`, `MOBILE_REVIEW_REPORT.md`).
- Working tree after: identical — only this report file (`docs/FRONTEND_WORKER_INTEGRATION_FORENSIC_AUDIT_2026-09-13.md`) added/updated (untracked).
- No commits, pushes, resets, cleans, or restores performed.
- Browser verification status: BLOCKED (no provider keys; no-modification constraint).
- Frontend changes needed: YES (FINDING-1..FINDING-6).
- Worker changes needed: NO for confirmed issues.
