# WebChat AI — Complete Production Audit

**Date:** August 23, 2026 · **Branch:** `feature/widget-production-hardening`
**Mode:** Read-only audit (no code modified). Five parallel deep-dive audits: Streaming/SSE, RAG pipeline, Widget SDK, Backend API/Database, Config/Tests/Production-readiness.
**Verification baseline:** full suite 1615 passed / 3 skipped · ruff clean · mypy strict clean.

---

## 1. Executive Summary

WebChat AI is a multi-tenant, website-knowledge chatbot platform (crawl → chunk → embed → retrieve → generate → stream) with a self-hosted embeddable widget SDK. The system is **architecturally sound and unusually well-engineered in its guardrails**: tenant isolation is enforced at query level everywhere, the model is never invoked without retrieved context, XSS defense is dual-gated and regression-tested, auth internals follow best practice, and streaming teardown/cost-protection semantics are correct and tested.

However, the audit surfaced **~100 actionable findings — zero P0, ten P1** — clustered in five themes that would degrade production quality if shipped as-is:

| Theme                              | Headline problems                                                                                                                                                                                                                                                                                                                                                               |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Stale knowledge serving**        | Retrieval-cache invalidation after re-crawl is a silent NO-OP due to Redis prefix mismatch (**R-01**); pages removed from a site are never purged from the KB (**R-02**) — both produce confidently wrong answers with valid-looking citations.                                                                                                                                 |
| **Streaming latency & resilience** | Delta coalescing flushes lazily only when the _next_ token arrives, doubling perceived inter-token latency and extending silent windows (**S-18**); no SSE keepalives against 60s proxy idle timeouts (**S-03**); no reconnect/resume — network blips discard answers and duplicate turns (**S-12**); client watchdog (30s) fires before server chunk timeout (60s) (**S-16**). |
| **Scalability cliffs**             | Brute-force vector-search fallback runs O(N·D) Python cosine scoring inline on the event loop for non-Atlas deployments (**A-02/P-8/R-15**); analytics aggregations lack a supporting compound index and filter in memory (**A-01**); uncapped output tokens on Groq/OpenRouter failover paths (**P-10**).                                                                      |
| **Observability gaps**             | No gauge-type metric exists (**P-1**), no alerting hooks at all (**P-2**), Redis hard fail-closed dependency is invisible until customers call (**P-6**), dead-letter/quarantine ingest failures unobservable (**P-7**).                                                                                                                                                        |
| **Test blind spots**               | Real MongoDB aggregation pipelines never executed in CI (**T-1**); the Playwright e2e suite is structurally disabled (**T-2**) — CI green does not prove repository correctness or end-to-end health.                                                                                                                                                                           |

Widget-side defects are individually small (IME Enter-to-send breaks CJK input **W-13**, completed answers invisible to screen readers **W-12**, iOS keyboard occlusion **W-06**, futile unavailable-banner dismiss **W-02**) but collectively cap the UX score.

**Verdict:** Not production-ready at target scale until the ten P1s are fixed. All P1 fixes are small-to-moderate diffs; none require architectural change. Fixing the top six streaming items alone moves streaming from 7/10 to ~8.5/10.

---

## 2. Architecture Overview

```
┌────────────────────────── Browser ──────────────────────────┐
│  Widget SDK (vanilla TS, closed Shadow DOM, ~<100KB gzip)   │
│  fetch+ReadableStream SSE · DOMPurify dual-gate markdown    │
│  memory-only tokens · rAF-coalesced rendering               │
│  Dashboard (React) ── admin/analytics/billing UI            │
└──────────────┬──────────────────────────────┬───────────────┘
               │ POST /api/widget/v1/chat (SSE)│ REST /api/v1/*
┌──────────────▼──────────────────────────────▼───────────────┐
│  FastAPI backend (pure-ASGI middleware stack)               │
│  Auth: Argon2id · rotating hashed refresh tokens · RBAC     │
│  Rate limits (Redis, fail-closed) · CSRF double-submit      │
│  SSE pipeline: rag.stream_answer → ensure_terminal_done     │
│    → _metrics_events → _recording_events                    │
│    → buffered_stream_with_disconnect                        │
│  Metrics: Prometheus registry (counters+histograms) /metrics│
│  Circuit breakers: per-(role, provider), CLOSED/OPEN/HALF   │
└───────┬──────────────────┬───────────────────┬──────────────┘
        │                  │                   │
┌───────▼──────┐   ┌───────▼────────┐   ┌──────▼──────────────┐
│ MongoDB      │   │ Redis          │   │ AI provider chain   │
│ Atlas $vector│   │ rate limits,   │   │ Gemini → Groq →     │
│ Search + TTLs│   │ caches, ARQ    │   │ OpenRouter (+Cohere │
│ unique keys  │   │                │   │ /Jina embeddings)   │
└───────▲──────┘   └───────┬────────┘   └─────────────────────┘
        │                  │
┌───────┴──────────────────▼────────┐
│ ARQ workers                       │
│ crawl (Playwright + SSRF guard)   │
│ → clean/chunk → embed (identity   │
│ pinned+quarantined) → upsert      │
└───────────────────────────────────┘
```

**Key flows**

- **Ingestion:** BFS crawler (robots-aware, SSRF-guarded, fresh-DNS anti-rebinding) → HTML cleaning → 700/100-token overlap chunking → embedding stamped with 4-tuple identity `(provider, model, dims, version)` → Atlas vector upsert; checksum-based skip for unchanged pages; mixed-space writes quarantined (BUG-1 guard).
- **Chat:** session/token mint (origin-validated) → prompt-injection screening → query rewrite → query embedding (identity-filtered) → `$vectorSearch` with mandatory `tenant_id`+`website_id` pre-filter → rerank (stored-vector cosine) → confidence gate (five independent never-generate-without-context guards) → streamed generation with citation markers, sources frame first, usage/billing recording best-effort.
- **Billing:** plan gates checked _before_ side effects; Stripe/Razorpay HMAC webhooks; idempotent activation on `payment_id`.

---

## 3. Current Production Score

### Headline scores (mandated dimensions)

| Dimension               | Score        | Basis                                                                                                                                                                                                                                                                                                 |
| ----------------------- | ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Widget UX**           | **7.5 / 10** | Excellent error/retry/stop/empty-state/focus work; held back by composer lockout during streaming, IME send bug (W-13), dead citation markers (W-09), mobile keyboard gaps (W-06), futile banner dismiss (W-02), no copy/regenerate (W-11).                                                           |
| **RAG Accuracy**        | **6.0 / 10** | Exemplary never-generate-without-context guards and identity quarantine, undermined by stale-serving paths (R-01, R-02), heuristic-only "faithfulness" (R-16), fabricatable citations (R-17), threshold miscalibration (R-12, R-22), rerank-only "hybrid" (R-11).                                     |
| **Backend Reliability** | **7.5 / 10** | Strong error taxonomy, guaranteed terminal frames, disconnect-aware streaming, layered retries; held back by event-loop-blocking vector fallback (A-02), crawl poison-job profile (A-08), races converting happy paths to 500s (A-10, A-14).                                                          |
| **Streaming**           | **7.0 / 10** | Spec-correct framing, tested terminal-frame contract, correct Stop/disconnect/cost semantics; kept below 8.5 by lazy coalescing flush (S-18), absent keepalives (S-03), no resume story (S-12), timeout inversion (S-16), unmapped error codes (S-21).                                                |
| **Security**            | **8.5 / 10** | Widget security 9/10 (dual-gate XSS corpus, memory-only tokens, zero postMessage surface); backend 8/10 (Argon2id + atomic refresh rotation, SSRF best-practice, strict RBAC, HMAC webhooks); deductions for Razorpay replay window (A-04), unvalidated checkout URLs (A-05), regex injection (A-09). |

### Full scorecard

| Area                                 | Score    |
| ------------------------------------ | -------- |
| Frame format & headers (SSE)         | 9 / 10   |
| Terminal-frame guarantee             | 8 / 10   |
| Heartbeats / idle management         | 3 / 10   |
| Disconnect lifecycle & cleanup       | 8 / 10   |
| Reconnection strategy                | 4 / 10   |
| Partial-response handling            | 9 / 10   |
| Timeout handling                     | 6.5 / 10 |
| Proxy/LB compatibility               | 6 / 10   |
| Error events / taxonomy              | 7 / 10   |
| Cancellation (Stop)                  | 9.5 / 10 |
| Delta coalescing                     | 5 / 10   |
| Browser transport choice             | 9.5 / 10 |
| RAG accuracy readiness               | 6.0 / 10 |
| Ingestion robustness                 | 6.5 / 10 |
| Retrieval quality                    | 6.0 / 10 |
| Generation safety                    | 7.5 / 10 |
| Widget security                      | 9 / 10   |
| Widget performance/accessibility     | 7.5 / 10 |
| Backend API reliability              | 7.5 / 10 |
| Backend security posture             | 8 / 10   |
| Database design                      | 6.5 / 10 |
| Config-system completeness           | 8 / 10   |
| Test coverage                        | 7 / 10   |
| Production observability/reliability | 6.5 / 10 |

**Overall production-readiness estimate: 7.2 / 10** — strong foundations, gated on P1 remediation.

---

## 4. Issues Table

Severity: **P1** = fix before next release · **P2** = significant risk/cost · **P3** = hardening/polish. No P0 (exploitable/critical) findings anywhere.

### Streaming / SSE (S)

| Priority | Area                         | Problem                                                                                                                                                  | Impact                                                                                                                              | Recommendation                                                                        |
| -------- | ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| P1       | Coalescing (S-18)            | Lazy timer-less buffer flush (`sse.py:196-206`) holds deltas until the _next_ delta arrives; project test documents extreme case (`test_sse.py:329`)     | Perceived inter-token latency doubles; TTFT degenerates to TT-second-token; extends silent windows tripping watchdog/proxy timeouts | True interval flush via `asyncio.wait_for(anext(...))` or background flusher          |
| P1       | Keepalives (S-03)            | No heartbeat/comment frames during silent phases (embedding+search+fallback chain can exceed 60s)                                                        | nginx `proxy_read_timeout` (60s default)/Cloudflare idle kills healthy streams; starves client watchdog                             | Emit `: ping` comment every ~15s; parsers already ignore comments                     |
| P2       | Terminal contract (S-04)     | Widget pre-stream rejections emit `error` without terminal `done` (`widget.py:155-166`), violating documented contract                                   | `WIDGET_DISABLED`, `LIMIT_REACHED`, `SESSION_NOT_FOUND`, etc. look like dropped connections to spec-following consumers             | Route through `ensure_terminal_done` or emit matched pair                             |
| P2       | Cleanup hazard (S-08)        | `yield` inside `finally` of `buffered_stream_with_disconnect` (`sse.py:214-219`) raises `RuntimeError` under GeneratorExit on mid-generation disconnects | Exception noise, masks real shutdown errors; client unaffected                                                                      | Track close-in-progress; drop tail buffer instead of yielding in `finally`            |
| P2       | Timeouts (S-16)              | Client stall watchdog 30s < prod server per-chunk timeout 60s (`.env.production:296`)                                                                    | Healthy-but-slow models killed client-side; hits slowest/fallback providers hardest                                                 | Client stall ≥ 75–90s, or ship keepalives so silence means dead                       |
| P2       | Resilience (S-12)            | No resume/backoff; network drop loses answer; manual retry duplicates user turn in history                                                               | Flaky-network users lose generated text, pay full latency again; duplicated turns                                                   | Auto-retry once when zero deltas received; persist partials labelled incomplete later |
| P2       | Error taxonomy (S-21)        | Emitted codes `LIMIT_REACHED`, `SESSION_NOT_FOUND`, `SERVICE_UNAVAILABLE`, `WEBSITE_NOT_FOUND` missing from client map (`errors.ts:133-153`)             | Visitors hitting plan caps told "please try again" — invites futile retries; triage harder                                          | Extend `BACKEND_CODE_MAP`; add map-pinning unit test                                  |
| P3       | Lifecycle (S-09, S-10, S-11) | Disconnect detection event-boundary only (~60s worst); orphaned `history_task`; narrow billing race window                                               | Bounded wasted generation/useless DB work; negligible overcount                                                                     | Race disconnect-poller; `finally: history_task.cancel()`; document race               |
| P3       | Deadline (S-17)              | No end-to-end request budget                                                                                                                             | Worst-case pre-first-byte ≈35–40s approaches client connect limit                                                                   | Explicit turn budget terminating in `done{failed}`                                    |
| P3       | UX semantics (S-14)          | Mid-stream provider failure marks whole turn failed though partial text delivered                                                                        | Cosmetic; retry regenerates from scratch                                                                                            | "Answer incomplete — regenerate?" affordance                                          |
| P3       | Ops (S-19, S-05)             | No reference reverse-proxy config for API; no `id:`/`retry:` fields                                                                                      | Operators must know SSE proxy settings; forecloses future resume                                                                    | Ship `nginx.api.conf` example; fields only alongside resume design                    |

### RAG pipeline (R)

| Priority | Area                         | Problem                                                                                                                                                                                   | Impact                                                                                              | Recommendation                                                                                                 |
| -------- | ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| P1       | Cache invalidation (R-01)    | Crawl worker builds `RedisCacheStore(redis)` with default prefix `rag:` (`crawl.py:63-67`) while API uses `{redis_prefix}:rag` = `webchat_ai:rag` (`deps.py:235-238`); SCAN never matches | After every re-crawl, stale answers serve up to 15 min (TTL 900s) — silently, wrapped in try/except | Use same prefix factory in worker; regression test asserting delete matches API-written key                    |
| P1       | Stale KB (R-02)              | Incremental crawls never reconcile removed URLs; `delete_by_website` has no caller; `delete_website` orphans documents+chunks forever                                                     | Removed pricing/policy pages answered indefinitely; GDPR/retention concern on site deletion         | Diff stored-vs-crawled URLs post-crawl and purge; cascade deletion in `delete_website`; dashboard purge action |
| P2       | Embedding space drift (R-24) | Ingestion pins first provider; chat uses full fallback chain — primary outage yields query vectors from wrong space, strict identity check rejects every chunk                            | Embedding-provider blip ⇒ all chats error out despite "healthy" fallback                            | Constrain chat chain to ingestion identity; or fast typed degradation AppError                                 |
| P2       | Citations (R-17)             | Model can fabricate `[N]` markers; no range validation/clamping anywhere in serving path                                                                                                  | Widget renders `[5]` linking nowhere; direct citation-integrity/trust break                         | Clamp/drop out-of-range markers post-generation (renumber if dropping)                                         |
| P2       | Score semantics (R-12)       | Reranker overwrites Atlas scores with local cosine and truncates top_k 8→5 before min-score/confidence thresholds                                                                         | Threshold miscalibration differs per deployment/flag state; reduced source diversity                | Preserve both scores; pin thresholds to one documented scale; align `rerank_top_k`                             |
| P2       | Faithfulness theater (R-16)  | "Faithfulness check" is bag-of-words overlap ≥⅓, warning-only; real LLM eval exists offline only                                                                                          | Fabrications of common words pass; operators over-trust telemetry as hallucination guard            | Rename to grounding-overlap; add NLI/LLM-judge gating low-confidence answers                                   |
| P2       | History budget (R-18)        | 12 prior turns rendered verbatim; answers uncapped (~4096 tok ≈ 16KB each) vs 2000-char questions                                                                                         | Prompt ballooning in long sessions; attention dilution harms groundedness                           | Character/token budget with oldest-first eviction                                                              |
| P2       | Cache race (R-03)            | Invalidation runs at fan-out enqueue, before re-embedding completes                                                                                                                       | Post-fix queries racing the window repopulate cache with old chunks for full TTL                    | Invalidate after fan-out drains, or version keys with website checksum                                         |
| P2       | Crawl pacing (R-04)          | robots `Crawl-delay` parsed but never enforced; no 429/Retry-After handling                                                                                                               | Impolite crawling → bans mid-crawl → partial indexes (compounds R-02)                               | Honor crawl-delay capped; backoff on 429                                                                       |
| P2       | JS rendering (R-05)          | Navigation waits only for `domcontentloaded`; no settle/scroll pass                                                                                                                       | SPA docs yield thin/empty content → quarantine or weak answers                                      | Network-idle wait with timeout; optional scroll; per-site override                                             |
| P2       | SSRF TOCTOU (R-06)           | Guard resolves DNS fresh, then Chromium resolves independently — rebinding window remains                                                                                                 | Low likelihood/high severity: crafted sites could reach internal endpoints                          | Pin resolved IPs via routing/proxy layer owned by app                                                          |
| P2       | Content fidelity (R-07)      | `get_text(" ", strip=True)` flattens tables into word soup and destroys `<pre>` indentation                                                                                               | Wrong feature↔value pairing with genuine citation; unusable technical answers                       | Markdown pipe serialization for tables; exempt `<pre>` from collapse                                           |
| P2       | Hybrid reality (R-11)        | Keyword search restricted to ANN result set — re-ranking, not a second retrieval leg (`hybrid.py:306-309`, `all_chunks=None` always)                                                      | Exact-term matches (SKUs, error codes) unreachable whenever ANN misses; recall ceiling = top_k      | True second leg via Atlas `$search` fused by RRF, or rename honestly                                           |
| P3       | Index contract (R-13)        | Probe verifies `embedding` path only, not required filter fields                                                                                                                          | Mis-provisioned index surfaces as confusing runtime errors masked by brute-force cliff              | Assert filter-field paths; alert on first brute-force trigger                                                  |
| P3       | Embed cache (R-14)           | Query-embed cache keyed on text only; serves old-space vectors up to 1h post-migration                                                                                                    | Repeat questions hard-fail during migration validation windows                                      | Include identity tuple in cache key                                                                            |
| P3       | Fallback cost (R-15)         | Brute-force scan fetches full corpus including float arrays per failing query                                                                                                             | Memory/CPU cliff whenever Atlas degrades                                                            | Projection/bound scanned rows; metric on trigger                                                               |
| P3       | Chunk metadata (R-08)        | Extracted headings dropped; `ContextItem.heading` always None (dead prompt branch)                                                                                                        | Lost section-locality signals for grounding                                                         | Carry nearest heading/breadcrumb onto chunks+metadata                                                          |
| P3       | Embedding retry (R-09)       | Late-batch failure re-embeds whole document                                                                                                                                               | Cost/latency amplification on flaky providers                                                       | Persist per-batch vectors keyed checksum+batch                                                                 |
| P3       | Bookkeeping (R-10)           | Re-crawl overwrites `created_at`                                                                                                                                                          | Dashboard ordering lies                                                                             | Exclude `created_at` from update `$set`                                                                        |
| P3       | Prompt shape (R-19)          | History flattened as `[role]` text inside single user turn                                                                                                                                | Weaker adherence vs native alternation                                                              | Pass alternating messages where supported                                                                      |
| P3       | Truncation (R-20)            | Budget cuts final chunk at raw char boundary                                                                                                                                              | Answers citing cut-off clauses/half table rows                                                      | Cut at sentence boundary; drop slivers                                                                         |
| P3       | Query rewrite (R-21)         | Prepend-concat rewrite; English-only anaphora triggers                                                                                                                                    | Non-English follow-ups retrieve weakly                                                              | Multilingual cues or tiny LLM rewrite step                                                                     |
| P3       | Confidence (R-22)            | Formula substitutes average when min_score=0 (silent weight shift); 0.3 default rarely fires (worked example: marginal ⇒ 0.57)                                                            | Marginal retrievals proceed instead of honest fallback                                              | Calibrate per deployment; unify branches                                                                       |
| P3       | Quota fairness (R-23)        | Fallback answers consume same quota/counters as real answers                                                                                                                              | Users exhaust session budgets without value                                                         | Track separately; product policy decision                                                                      |
| P3       | Overlap dupes (R-26)         | ~100-token overlap enters context multiple times; near-dup removal flag off by default                                                                                                    | Wasted context budget; diluted embeddings; repetition pressure                                      | Enable context optimization after validation, or fingerprint-dedupe spans                                      |
| P3       | Migration tooling (R-25)     | No bulk re-embed job; identity conflict quarantines site until manual per-doc retry                                                                                                       | Migrations expensive/error-prone; websites stall in failed state                                    | Admin re-embed-website fan-out with force + purge-on-complete                                                  |

### Widget SDK (W)

| Priority | Area                          | Problem                                                                                                     | Impact                                                                                             | Recommendation                                                          |
| -------- | ----------------------------- | ----------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| P2       | Input (W-13)                  | Enter-to-send lacks IME composition guard (`composer.ts:140-145`)                                           | CJK users' composition-confirm sends half-formed messages                                          | `if (event.isComposing                                                  |     | keyCode === 229) return;` |
| P2       | Accessibility (W-12)          | `aria-relevant="additions"` + innerHTML mutation ⇒ completed answers never announced (`bubbles.ts:439-442`) | SR users hear typing indicator then silence — WCAG 4.1.3 gap                                       | Push final answer into existing `wc-status-live` on turn end            |
| P2       | Mobile (W-06)                 | No `visualViewport` handling; iOS overlays keyboard on fixed layout                                         | Composer occluded mid-conversation — classic mobile chat failure                                   | Listen to `visualViewport.resize`; offset/shrink window                 |
| P2       | UX flow (composer lockout)    | Composer disabled while streaming (`composer.ts:167`, `mount.ts:573`)                                       | Can't pre-type next question                                                                       | Allow typing; queue/buffer next message                                 |
| P2       | Citations (W-09)              | Inline `[n]` markers not linked to source cards                                                             | Dead text; no claim→source navigation                                                              | Post-process `[n]` into anchors scrolling/highlighting cards            |
| P3       | Positioning (W-01)            | `normalizeConfig` does no enum validation; invalid `position` leaves shell unpositioned                     | Bad value renders widget at static flow position                                                   | Validate in normalizeConfig, default `bottom-right`                     |
| P3       | Banner (W-02)                 | Dismissing unavailable banner resurrects on every syncRenderer pass (`mount.ts:546-551`)                    | Looks broken to visitors                                                                           | Non-dismissible class or track dismissal state                          |
| P3       | Theme (W-03)                  | `theme:'auto'` evaluated once; no matchMedia change listener                                                | OS light/dark switch ignored until reload                                                          | Subscribe and re-run applyTheme                                         |
| P3       | auto_open (W-04)              | Suppressed by reduced-motion preference — conflated concerns                                                | Motion-preference users never get requested dialog                                                 | Always honor auto_open; CSS already disables animation                  |
| P3       | Escape (W-05)                 | Global capture Escape closes dialog even when focus outside widget                                          | Breaks host-page shortcuts (lightbox, sliders)                                                     | Scope to composedPath like Tab branch                                   |
| P3       | Chips (W-07)                  | Suggested chips enabled offline/unavailable; clicks silently no-op                                          | Zero feedback on tap                                                                               | Disable alongside composer or surface banner on tap                     |
| P3       | Launcher (W-08)               | No unread/new-message badge                                                                                 | Missed-message affordance absent                                                                   | Optional polish; pulse ring partially compensates                       |
| P3       | Actions (W-11)                | No copy-full-message; regenerate only for failed turns                                                      | Can't copy answers or re-roll successful-but-wrong ones                                            | Add Copy+Regenerate via existing delegation pattern                     |
| P3       | Highlighting (W-10)           | No syntax highlighting (deliberate budget trade-off)                                                        | Code readability slightly reduced                                                                  | Tiny regex highlighter if budget allows                                 |
| P3       | Perf render (W-15)            | Full parse+DOMPurify+innerHTML replace per animation frame on growing bubble                                | Main-thread burn on low-end devices for long replies                                               | Throttle stream renders to ~50–80ms                                     |
| P3       | Perf alloc (W-16, W-17, W-18) | State array shallow-copy per SSE delta; no DOM/history cap; module-scope Set grows unbounded                | GC churn on long sessions; gradual degradation                                                     | Frozen arrays/revision notifications; cap history ~200; clear per mount |
| P3       | Battery (W-19)                | Always-on decorative animations (pulse rings)                                                               | Continuous compositing/CPU on host pages                                                           | Cap cycles or gate play-state                                           |
| P3       | Teardown (W-20)               | Untracked timeout; unused unsubscribe return                                                                | None observable                                                                                    | Track/cancel for strictness                                             |
| P3       | Packaging (W-21)              | No TypeScript types published                                                                               | Implicit-any imports for framework consumers                                                       | Declaration emit + `"types"` export condition                           |
| P3       | Security (W-22)               | Avatar/logo URLs assigned to `img.src` without scheme validation                                            | `data:`/off-origin tracking pixels pass (XSS inert in modern img)                                  | Reuse http(s) allowlist for brand images                                |
| P3       | Defense-in-depth (W-23)       | Tenant CSS strings injected unvalidated into custom properties                                              | Cannot escape declaration scope; worst case absurd CSS scoped in shadow root                       | Validate formats at normalizeConfig                                     |
| P3       | Compliance doc (W-24)         | Privacy comment claims visitor_id "never sent to API" but `/sessions` posts it                              | Wrong compliance story for customer security reviews (id is random UUID; cookie stays first-party) | Fix comment/docs                                                        |

### Backend API / Database (A)

| Priority | Area                       | Problem                                                                                                                       | Impact                                                                                                 | Recommendation                                                                    |
| -------- | -------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------- |
| P1       | Indexes (A-01)             | Analytics `$match {tenant_id, role, created_at}` served only by single-field `tenant_id` index (`database.py:279-282`)        | Every dashboard query scans tenant's entire message history; linear latency growth                     | Compound `(tenant_id, role, created_at)` index; longer term daily rollups         |
| P1       | Event loop (A-02)          | Brute-force fallback runs Python cosine inline over entire chunk corpus (`vector/mongodb.py:288-347`) — non-Atlas deployments | One large-KB tenant stalls ALL tenants sharing the process (noisy neighbor)                            | Offload via `asyncio.to_thread`/server-side scoring; cap corpus; alert on trigger |
| P2       | Ingest I/O (A-03)          | N+1 sequential chunk inserts; `$ne`-of-`$or` identity check scans sibling chunks per document                                 | Worker throughput degrades super-linearly with corpus size                                             | `insert_many` (unique index makes it idempotent); stamp identity on website doc   |
| P2       | Payments (A-04)            | Razorpay signature lacks timestamp/replay window (Stripe enforces 300s)                                                       | Captured payloads replay indefinitely today (idempotency contains); permanent hole for future handlers | Enforce freshness tolerance mirroring Stripe                                      |
| P2       | Payments (A-05)            | Checkout `success_url`/`cancel_url` free-form strings (`schemas/billing.py:73-78`)                                            | Attacker-influenced post-payment redirect — phishing vector against admins                             | HTTPS HttpUrl pinned to configured origins                                        |
| P2       | Retention (A-06)           | Website deletion orphans documents+chunks permanently (no TTL, no purge path)                                                 | Unbounded storage growth of largest documents; stale corpora survive re-registration                   | Purge on delete (incl. `delete_by_website`) or reaper job past grace period       |
| P2       | Write amplification (A-07) | Every API-key request: audit insert + unconditional `last_used_at` `$set`                                                     | Oplog pressure; bookkeeping becomes meaningful fraction of DB writes                                   | Throttle touch (≥1/min/key); sample routine-read audits                           |
| P2       | Workers (A-08)             | Crawl retries restart from scratch within fixed timeout; fan-out jobs not deduplicated; stats refreshed per-document          | Large sites burn 3× budget and still fail; duplicate processing wastes plan limits                     | Deterministic `_job_id`s; debounced/completion-time stats; resumable crawls       |
| P3       | Injection (A-09)           | Raw admin search interpolated into `$regex` (`user_repository.py:148-158`)                                                    | Pathological scans; admin-only, low traffic                                                            | `re.escape` or text index                                                         |
| P3       | Race (A-10)                | Feedback check-then-insert loses race → uncaught DuplicateKeyError → 500 instead of idempotent success                        | Double-submit converts happy path to error                                                             | Catch DuplicateKeyError; treat index as source of truth                           |
| P3       | Scoping (A-11)             | Session touch omits `tenant_id` (lone unscooped write)                                                                        | Breaks invariant; IDOR-class if uniqueness ever changes                                                | Thread tenant_id through touch                                                    |
| P3       | Bounds (A-12)              | Conversation detail loads unbounded; content search = tenant-wide regex scan                                                  | Bounded today by 50-msg cap; API-key chats could exceed                                                | Cap detail fetch; anchored/text search                                            |
| P3       | Headers (A-13)             | Inbound `X-Request-ID` reflected verbatim into responses/logs                                                                 | Nuisance log flooding (CRLF blocked by ASGI)                                                           | Accept `[A-Za-z0-9\-]{1,64}`, else regenerate                                     |
| P3       | Race (A-14)                | Crawl-start overlap gate is pre-check only (contrast: websites use partial unique index properly)                             | Concurrent duplicate crawls (bounded by limiter)                                                       | Unique partial index or atomic claim                                              |

### Configuration system (C)

| Priority | Area                         | Problem                                                                                    | Impact                                                                                                              | Recommendation                                                  |
| -------- | ---------------------------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| P2       | Cache staleness (C-7)        | Admin suspend/activate doesn't invalidate `wk:config:` entries                             | Visitor-facing "unavailable" delayed up to 300s post-suspension (chat calls still re-validate live — cosmetic only) | Fan out `invalidate_public_config` in suspend/activate          |
| P3       | Defaults (C-2, C-3)          | Accent/welcome/placeholder defaults differ backend vs SDK fallback                         | Fallback UI renders amber + different copy exactly during incidents                                                 | Single source of truth in shared themes package                 |
| P3       | Validation (C-6, C-10, W-22) | `font_family` free text into CSS var; logo/avatar accept `http://`                         | Impractical exploit; flaky broken images on HTTPS hosts (mixed-content upgrade-or-block)                            | Charset allowlist; https-only image URLs                        |
| P3       | Hygiene (C-4, C-5, C-9)      | Dead `--wc-font-size` var; 7 informational vars unconsumed; `Widget` model `extra="allow"` | Confusing affordances; schema-drift hygiene                                                                         | Remove/document vars; `extra="ignore"`                          |
| P3       | Product gaps (C-1, C-11)     | Custom-CSS field missing end-to-end; quotas invisible to SDK                               | Unbuilt advertised-class feature; opaque `LIMIT_REACHED` UX                                                         | Sanitized CSS-variable allowlist if planned; expose quota hints |
| P3       | Accepted tradeoff (C-8)      | Session validity/message-cap fail open during Redis outage (documented design)             | Caps unbounded during outage (bounded by fail-closed IP/entity limits)                                              | Runbook note + metric tying into P-6                            |

### Tests (T)

| Priority | Area                          | Problem                                                                                                                           | Impact                                                                    | Recommendation                                                                     |
| -------- | ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| P1       | Repositories (T-1)            | Real Mongo aggregation pipelines never execute — service tests run on hand-written fakes; analytics repo 38%, vector repo 33% cov | A wrong accumulator ships green; bucket/timezone math unverifiable        | Nightly testcontainers Mongo job exercising pipelines                              |
| P1       | E2E (T-2/T-W2)                | Only true browser→SDK→SSE→model proof env-gated off; CI never sets `E2E_BASE_URL`                                                 | CI green ≠ e2e healthy; injection-e2e/mobile/mixed-content live only here | Scheduled required Playwright job against staging                                  |
| P2       | Webhooks (T-3)                | Provider exception paths mid-processing untested; Razorpay flows thin                                                             | Partial-activation/500 semantics unverified                               | Fault-injection cases per provider                                                 |
| P2       | Workers (T-4)                 | `job_timeout=600`/retry semantics, partial-failure resume untested                                                                | Poison-job behavior unverified                                            | Integration tests with fake ARQ clock                                              |
| P2       | Pipeline security (T-5)       | Prompt-injection tested at unit level only; no HTTP-level hostile-corpus e2e                                                      | Composed crawl→embed→chat attack path unproven                            | API-level security test with hostile corpus                                        |
| P2       | Analytics (T-6)               | Aggregation correctness at DB layer untested (subset of T-1)                                                                      | Rate rounding/bucket boundaries unverifiable                              | Covered by T-1 job                                                                 |
| P3       | Isolation (T-7)               | Cross-tenant reads via super_admin impersonation untested (visitor-binding/conversations/websites isolation well covered)         | Residual IDOR risk in admin surface                                       | Add impersonation-scoped tests                                                     |
| P3       | Resilience (T-8)              | Redis flap storms (repeated 503 cycling) untested                                                                                 | Alerts can't distinguish flap vs outage                                   | Chaos tests + flap-specific metric                                                 |
| P3       | Weak tests (T-W1, T-W3, T-W4) | Smoke-only entry test; webhook tests assert status not side effects; over-mocked provider seams hide wire-format drift            | False confidence; usage accounting could silently zero (couples to P-10)  | Behavioral assertions; side-effect assertions; contract tests on provider payloads |

### Production observability / reliability / cost (P)

| Priority | Area                   | Problem                                                                                                                           | Impact                                                                                               | Recommendation                                                                                                      |
| -------- | ---------------------- | --------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| P1       | Metrics (P-1)          | Registry implements only counters+histograms — no Gauge type exists                                                               | Cannot measure queue depth, Redis availability, provider cooldown state, pool saturation             | Add Gauge + collectors (queue depth, DB latency/op, Redis ping, breaker state)                                      |
| P1       | Cost (P-10)            | Output-token caps applied ONLY on Gemini; Groq/OpenRouter/Cohere build payloads with no max_tokens                                | Runaway-spend exposure on exactly the providers used during a Gemini incident (failover = uncapped)  | Add `max_tokens` to `build_chat_payload`; pass `chat_max_output_tokens`                                             |
| P2       | Alerting (P-2)         | Prometheus exposition exists; nothing consumes it                                                                                 | Incidents require humans watching graphs                                                             | Alertmanager rules: 503-rate (Redis-down signature), provider failures, queue depth, TTFT p95, quarantine count     |
| P2       | Stale-serving (P-5)    | With Redis cold AND Mongo down, config GET raises instead of serving last-known-good                                              | Widgets can't fetch config during DB blips (SDK falls back to bundled defaults — partial mitigation) | Serve stale cached config with extended TTL on DB failure                                                           |
| P2       | SPOF visibility (P-6)  | Every rate limiter fails CLOSED on Redis loss ⇒ 503 across dashboard AND public widget surface (deliberate ADR-004)               | Total protected-endpoint outage visible only as 503 spikes (no gauge/alert)                          | Keep fail-closed for auth-sensitive limits; degraded local bucket for public chat limiter + dedicated health metric |
| P3       | Tracing (P-3)          | request_id correlation only; no OTEL                                                                                              | Cross-request causality (crawl→knowledge→chat) not traceable                                         | OTEL spans around RAG stages/AI calls when scale justifies                                                          |
| P3       | Metric coupling (P-4)  | Cache-hit metrics derive from optional timing payload rather than repository layer                                                | Visibility disappears silently if emission toggles                                                   | Record at repository layer directly                                                                                 |
| P3       | Dead letters (P-7)     | Exhausted ARQ jobs vanish into result TTL with log lines only; no quarantine counter                                              | Silent accumulation of permanently failed ingests discovered via complaints                          | Counter/gauge + alert threshold                                                                                     |
| P3       | Boot guard (P-9)       | Startup vector-dimension check samples only 5 chunks                                                                              | Mixed corpora beyond sample pass boot; failures surface later as skipped-chunk counts                | Validate via collection metadata/aggregation                                                                        |
| P3       | Billing leakage (P-11) | Usage writes best-effort; failed turns intentionally unbilled — no counter distinguishes "not billed (failed)" from "record lost" | Possible silent revenue leakage                                                                      | Metric + periodic reconciliation job                                                                                |

---

## 5. Quick Wins

Ranked by effort/payoff. First eight are minutes-to-an-hour diffs:

1. **R-01** — one-line prefix fix in `crawl.py:_build_cache()`; eliminates the 15-minute stale-answer window after every recrawl. Highest accuracy ROI per line changed.
2. **A-01** — add compound `(tenant_id, role, created_at)` index; biggest DB win, trivially safe.
3. **P-10** — thread `settings.chat_max_output_tokens` into `build_chat_payload` for Groq/OpenRouter/Cohere; closes uncapped failover spend.
4. **S-21** — extend client `BACKEND_CODE_MAP` (`LIMIT_REACHED→limit`, `SESSION_NOT_FOUND→session`, `SERVICE_UNAVAILABLE→ai_unavailable`) + pinning test; outsized UX payoff.
5. **S-04** — emit matched `error`+`done{failed}` pair on widget pre-stream rejections.
6. **S-08** — drop tail buffer instead of yielding in the disconnect `finally`.
7. **S-16** — raise client stall watchdog to 75–90s (config-level change).
8. **W-13 / W-02 / W-24** — IME guard (one line); non-dismissible unavailable banner; privacy-doc correction.
9. **C-7** — invalidate `wk:config:*` on admin suspend/activate.
10. **A-10 / A-13 / C-9 / C-2+C-3** — catch DuplicateKeyError in feedback; sanitize inbound request IDs; `extra="ignore"`; align backend↔SDK defaults.
11. Then the two highest-impact streaming items: **S-18** timer-based coalescing flush and **S-03** keepalive comments (hours) — together these move streaming 7/10 → ~8.5/10.

## 6. Long Term Improvements

1. **Observability maturity:** Gauge infrastructure (P-1) → Alertmanager rule pack (P-2) → OTEL tracing across ingest→chat stages (P-3). Without the first two, the Redis fail-closed design (P-6) stays undetectable until customers call.
2. **Retrieval architecture:** true two-legged hybrid search with RRF fusion (R-11); score-scale discipline through the rerank funnel (R-12); calibrated confidence thresholds per deployment (R-22); section-aware chunking using propagated headings (R-08 + R-26).
3. **Evaluation harness in the loop:** wire the existing offline benchmark (`benchmark/llm_evaluation.py`) into CI regression gates and low-confidence-path LLM-judge sampling; replace lexical faithfulness with NLI/judge gating (R-16).
4. **Knowledge lifecycle:** crawl reconciliation + purge tooling + admin bulk re-embed migrations (R-02, R-25, R-03); retention reaper for deleted-site corpora (A-06).
5. **Resumable streaming protocol:** sequence numbers + `Last-Event-ID` resumption, server-persisted partials (S-12, S-05), explicit end-to-end turn budget (S-17).
6. **Scale-out ingestion:** batch chunk writes with website-stamped identity equality checks (A-03); deterministic job IDs and debounced stats (A-08); resumable crawls and batch-checkpointed embedding (R-09).
7. **Analytics rollups:** mirror the `usage_records` daily-aggregate pattern for dashboard analytics so reads stop hitting raw messages (extends A-01).
8. **Mobile/resilience polish:** `visualViewport` keyboard handling (W-06); frontend coverage gate + auto_open/scroll/viewport test coverage; provider wire-format contract tests (T-W4).

## 7. Final Production Checklist

**Blocking before next release (P1):**

- [ ] R-01 retrieval-cache prefix mismatch fixed + regression test
- [ ] R-02 removed-page purge/reconciliation + website-delete cascade
- [ ] A-02 brute-force vector search off the event loop (+ trigger alert)
- [ ] A-01 analytics compound index deployed
- [ ] S-18 timer-based coalescing flush
- [ ] S-03 SSE keepalives (~15s cadence)
- [ ] P-10 output-token caps on all generation providers
- [ ] P-1 Gauge metrics (at minimum: Redis health, queue depth, breaker state)
- [ ] T-1 nightly real-Mongo pipeline job green
- [ ] T-2 scheduled required Playwright e2e run green

**Strongly recommended (P2):**

- [ ] R-24 chat embedding chain pinned to ingestion identity
- [ ] R-17 citation-marker clamping
- [ ] S-16 / S-12 / S-04 / S-08 / S-21 streaming consistency cluster
- [ ] R-12 / R-16 / R-18 score-scale, grounding-rename, history budget
- [ ] A-04 Razorpay replay window · A-05 checkout URL validation
- [ ] A-06 deleted-site corpus purge · A-03 batch inserts · A-07 touch throttling · A-08 crawl job hygiene
- [ ] W-12 / W-06 / composer-lockout widget fixes
- [ ] C-7 suspend cache invalidation · P-2 alert rules · P-5 stale-config serving · P-6 Redis-health visibility

**Verified strengths shipping as-is:** tenant-isolated filtered ANN with identity quarantine; never-generate-without-context fallback discipline; dual-gate XSS pipeline with regression corpus; atomic refresh-token rotation; SSRF anti-rebinding layering; guaranteed SSE terminal frames with disconnect-cancelled generation; circuit breakers + provider fallback chain; checksum-gated re-embedding spend control; graceful worker shutdown; content-hashed sub-100KB widget bundle with CI size/self-containment gates.

---

_Method note: findings and file:line citations above were produced by five parallel read-only exploration audits (streaming/SSE, RAG, widget SDK, backend API/DB, config/tests/prod) and cross-checked against Phase 3 (metrics) and Phase 4 (circuit-breaker) implementation work performed earlier on this branch. No production code was modified during this audit._
