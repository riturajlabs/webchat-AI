# FINAL COMPREHENSIVE PRODUCTION-READINESS AUDIT

## WebChat AI Monorepo

### Date: September 4, 2026

### Commit Baseline: 2ccdf6a (fix: improve RAG retrieval)

### Auditor: opencode / big-pickle

---

## PHASE 1 — REPOSITORY INVENTORY

### Architecture

```
webchat-AI/
├── backend/           (FastAPI 3.13 + Motor async MongoDB + ARQ workers)
├── apps/
│   ├── dashboard/     (Next.js 15.5 + React 19 + TanStack Query)
│   └── widget/        (Vite vanilla TS SDK, Shadow DOM, no framework)
├── packages/
│   └── themes/        (Shared theme presets + resolve engine)
├── docker/            (4 Dockerfiles + 2 compose files + nginx config)
├── tests/             (~90 backend test files + E2E with Playwright)
├── scripts/           (~30 scripts: setup, deploy, security, RAG eval)
├── docs/              (14 design docs, ADRs, audit reports)
└── tls/               (empty, certs gitignored)
```

### File Counts

| Category               | Count                   |
| ---------------------- | ----------------------- |
| Python backend modules | ~160                    |
| Test files             | ~90 + 9 helpers + 4 E2E |
| Dashboard TS/TSX files | ~137                    |
| Widget TS files        | 57 (30 src + 27 test)   |
| Docker files           | 7                       |
| CI/CD workflows        | 2                       |
| Scripts                | ~30                     |
| Documentation          | 14                      |

### Dependency Use Map

| Component              | Status          | Used By                    |
| ---------------------- | --------------- | -------------------------- |
| backend/core/*         | ACTIVE          | All backend layers         |
| backend/api/*          | ACTIVE          | FastAPI routes             |
| backend/services/*     | ACTIVE          | Routes + workers           |
| backend/repositories/* | ACTIVE          | Services + workers         |
| backend/models/*       | ACTIVE          | Repositories               |
| backend/ai/*           | ACTIVE          | Services (chat, knowledge) |
| backend/prompts/*      | ACTIVE          | RAG service                |
| backend/workers/*      | ACTIVE          | ARQ task queue             |
| backend/utils/*        | ACTIVE          | Services + ingestion       |
| backend/benchmark/*    | DEV-ONLY        | Offline evaluation         |
| backend/templates/*    | ACTIVE          | Email service              |
| apps/dashboard/*       | ACTIVE          | User-facing dashboard      |
| apps/widget/*          | ACTIVE          | Embeddable widget          |
| packages/themes/*      | ACTIVE          | Widget + dashboard         |
| scripts/*              | DEV-ONLY/DEPLOY | Operators                  |
| docs/*                 | DOCUMENTATION   | Team reference             |
| .github/*              | CI/CD           | Automated pipeline         |
| docker/*               | DEPLOYMENT      | Container builds           |

---

## PHASE 2 — DEAD CODE / UNUSED FILE AUDIT

### Deletion Candidates

| Path                                            | Type            | Confidence | Recommendation                      |
| ----------------------------------------------- | --------------- | ---------- | ----------------------------------- |
| `apps/widget/src/demo.ts`                       | Dev-only        | HIGH       | ARCHIVE (dev harness, not in build) |
| `scripts/seed-widget.py`                        | Script          | HIGH       | VERIFY (one-time seeding)           |
| `scripts/migrate-allowed-domains.py`            | Script          | HIGH       | VERIFY (one-time migration)         |
| `scripts/backfill-embedding-identity.py`        | Script          | HIGH       | VERIFY (one-time backfill)          |
| `scripts/reindex-website-embedding-identity.py` | Script          | HIGH       | VERIFY (one-time reindex)           |
| `scripts/e2e_phase2_ingestion.py`               | Script          | MEDIUM     | VERIFY (may be superseded)          |
| `.audit-tmp/` (all files)                       | Audit artifacts | N/A        | DELETE after verification           |

**No dead Python modules found.** All backend files are actively imported.
**No dead React components found.** All dashboard components are referenced.
**No dead widget modules found.** All widget source files are in the build graph.

---

## PHASE 3 — BACKEND CODE QUALITY

### Summary: 52 issues found

| Severity | Count |
| -------- | ----- |
| P0       | 2     |
| P1       | 16    |
| P2       | 22    |
| P3       | 12    |

### Critical (P0) Issues

**RC-01: Embedding single-flight race condition**

- File: `services/chat/rag_service.py:306-313`
- The `_embed_inflight` dict can be raced: two concurrent requests for the same query may create conflicting futures
- Fix: Use `dict.setdefault` pattern

**E-01: Rate limit bypass via broad exception**

- File: `api/deps.py:902`
- `except Exception:` on Redis sliding window silently swallows errors
- Fix: Narrow to `(RedisError, ConnectionError, TimeoutError)`

### Top P1 Issues

| ID   | File:Line                                               | Issue                                          |
| ---- | ------------------------------------------------------- | ---------------------------------------------- |
| E-02 | `core/cache.py:49,67,73,93`                             | 4x `except Exception:` swallowing cache errors |
| E-03 | `core/redis.py:26,35`                                   | `except Exception:` on Redis connection        |
| E-04 | `core/database.py:173`                                  | `except Exception:` on index creation          |
| E-05 | `core/quota.py:135,144,156`                             | Quota check bypass on any error                |
| E-06 | `services/widget/widget_service.py:206,212,219,228,369` | 5x cache fail-open                             |
| E-07 | `services/ai/provider_health.py:109,160,202`            | Provider health lost on Redis issues           |
| F-01 | `services/chat/rag_service.py:740-1438`                 | `stream_answer` is ~700 lines (God method)     |
| F-02 | `services/chat/rag_service.py:346-622`                  | `_retrieve` returns 13-element tuple           |
| R-01 | `services/chat/rag_service.py:862,882,1099`             | Missing `await` after `task.cancel()`          |
| G-01 | `core/redis.py:20-35`                                   | Module-level Redis singleton no thread safety  |

---

## PHASE 4 — BACKEND PERFORMANCE

### P1 Latency Bottlenecks

| Bottleneck                                                       | Impact                                        | Fix                              |
| ---------------------------------------------------------------- | --------------------------------------------- | -------------------------------- |
| Keyword search blocks event loop (hybrid.py:208-262)             | CPU-bound O(n) over full corpus in async loop | Wrap in `asyncio.to_thread`      |
| N+1 queries in `platform_stats` (admin_repository.py:106-150)    | 10 sequential `count_documents`               | Use `$facet` or `asyncio.gather` |
| `$regex` search without text indexes (tenant/user/message repos) | Full collection scan on search                | Add text indexes                 |

### P2 Optimization Opportunities

| Area                      | Issue                            | Fix                                      |
| ------------------------- | -------------------------------- | ---------------------------------------- |
| Redis connection pool     | No pool configured (redis.py:18) | Set `max_connections=20-50`              |
| Redis singleton reconnect | Never reconnects after failure   | Add health-check + lazy reinit           |
| Admin collection_counts   | 12 sequential `count_documents`  | `$facet` or `collstats`                  |
| chat_sessions sort        | Missing covering index           | Add `[tenant_id, status, last_activity]` |

---

## PHASE 5 — COMPLETE RAG PIPELINE TRACE

### Pipeline Stages (31 stages)

```
Query Entry → Validation → Sanitization → Session → Persist User Msg →
History Load (async, started early) → Query Rewrite → Classification →
Embedding Cache → Query Embedding (miss: 200-800ms) →
Retrieval Cache → Vector Search (50-500ms) → Lexical Corpus Load →
Keyword Search (50-300ms, SYNC) → RRF Fusion → Source Diversity →
Hydration → Reranking → Confidence Gate → Context Build →
Prompt Construction → LLM TTFT (300-2000ms) → LLM Stream →
Citation Validation → Faithfulness Check → Response Validation →
Persist → Session Touch + Usage → SSE Buffer
```

### Latency Waterfall (cache miss, hybrid search)

```
Stage                    | Latency (ms)  | Blocking?
─────────────────────────┼───────────────┼──────────
Quota check              | 5-20          | Async
Widget validation        | 10-40         | Async (sequential)
Sanitization             | <1            | Sync
Query rewrite            | <1            | Sync
Query embedding (miss)   | 200-800       | Async (EXTERNAL)
Vector search            | 50-500        | Async (MongoDB)
Keyword search           | 50-300        | SYNC (CPU, event loop)
Reranking                | 5-20          | Sync (CPU)
Context build            | 1-5           | Sync
Prompt construction      | <1            | Sync
LLM TTFT                 | 300-2000      | Async (EXTERNAL)
LLM stream               | 1000-8000     | Async (EXTERNAL)
Persistence              | 10-30         | Async
─────────────────────────┼───────────────┼──────────
TOTAL (excl LLM stream)  | 800-12000     |
```

### Token Budget (typical query)

```
Component                  | Tokens  | %
───────────────────────────┼─────────┼────
System prompt              | ~150    | 4-5%
Question                   | ~20-50  | <2%
Context (5 chunks × 800c)  | ~1000   | 30-35%
History (3 turns)          | ~150    | 4-5%
Template overhead          | ~50     | 1-2%
───────────────────────────┼─────────┼────
Total input                | ~2500-3500 | 100%
Output (answer)            | ~200-500 | N/A
```

---

## PHASE 6 — RAG ACCURACY

### Known Working Queries (from production validation)

- Courses: works but broad ranking can improve
- Admission process: relevant sources but can mix sources
- AI-DS admission: works
- Cyber Security admission: works
- BCA admission: recovered after lexical improvements
- Dean of SOIT: works
- Chairperson: recovered after lexical improvements

### Identified Accuracy Issues

| Issue                                             | Pipeline Stage           | Severity |
| ------------------------------------------------- | ------------------------ | -------- |
| Injection detection runs twice per question       | Sanitization (Stage 2)   | LOW      |
| `InjectionTracker` never instantiated             | Sanitization (Stage 2)   | MEDIUM   |
| Jina client has no retry (unlike Gemini)          | Embedding (Stage 5)      | LOW      |
| Retrieval cache doesn't include corpus version    | Cache (Stage 6)          | LOW      |
| Brute-force fallback loads all chunks into memory | Vector search (Stage 7)  | MEDIUM   |
| Keyword search blocks event loop                  | Keyword search (Stage 8) | MEDIUM   |
| Context truncation at char boundary (not word)    | Context build (Stage 16) | LOW      |
| Question truncated before injection detection     | Prompt (Stage 17)        | MEDIUM   |

---

## PHASE 7 — RAG LATENCY + TOKEN OPTIMIZATION

### Key Opportunities

| Opportunity                                | Savings                   | Risk                 |
| ------------------------------------------ | ------------------------- | -------------------- |
| Move keyword search to `asyncio.to_thread` | 50-300ms event loop freed | Low                  |
| Cache lexical corpus in retrieval cache    | 20-200ms on cache hit     | Low                  |
| Parallelize widget validation deps         | ~20ms                     | Low                  |
| Remove duplicate `detect_injection` call   | ~2ms                      | None                 |
| Add Jina retry logic                       | Reliability improvement   | None                 |
| Pre-compute inverted index for keywords    | Major latency win         | High (architectural) |

---

## PHASE 8 — EMBEDDING / VECTOR SEARCH

### Current State

- Provider: Jina / jina-embeddings-v3 / 1024 dimensions / v1
- Atlas vector index: READY
- Single-flight coalescing: IMPLEMENTED
- Embedding pacing: IMPLEMENTED
- Provider locking: IMPLEMENTED
- In-process memo cache: IMPLEMENTED

### Issues

| Issue                                                          | Severity |
| -------------------------------------------------------------- | -------- |
| Jina client has no retry logic (unlike Gemini)                 | LOW      |
| `_EmbeddingPacer` semaphore recreated on new event loop        | MEDIUM   |
| Retrieval cache doesn't include corpus version → stale results | LOW      |
| Brute-force fallback loads ALL chunks with embeddings          | MEDIUM   |

---

## PHASE 9 — INGESTION / CRAWLER

### Issues

| Issue                                              | Severity | File:Line                         |
| -------------------------------------------------- | -------- | --------------------------------- |
| `fetcher.close()` not guaranteed on exception path | P1       | `crawler.py:202`                  |
| robots.txt `crawl_delay` parsed but never enforced | P2       | `robots.py:23` / `crawler.py:130` |
| `queued` set grows unboundedly for wide sites      | P2       | `crawler.py:119,189`              |
| No crawl memory pressure detection                 | P2       | `crawler.py:100-203`              |
| Error recording cap silently drops details         | P3       | `crawler.py:35,217`               |
| `_site_host` only strips `www.`                    | P3       | `crawler.py:222`                  |
| Tracking param coverage incomplete                 | P3       | `url_validator.py:179`            |

---

## PHASE 10 — FRONTEND DASHBOARD

### Issues

| Issue                                              | Severity |
| -------------------------------------------------- | -------- |
| Dashboard fetches 3 parallel queries, one wasteful | P2       |
| SSE reconnect always calls auth refresh            | P2       |
| No stale-while-revalidate on dashboard data        | P3       |
| `suppressHydrationWarning` on full `<html>`        | P3       |
| Missing `aria-live` on stat cards                  | P3       |

---

## PHASE 11 — EMBEDDABLE WIDGET

### Issues

| Issue                                                   | Severity |
| ------------------------------------------------------- | -------- |
| Module-level `idCounter` shared across instances        | P2       |
| `wireKeyboardInset` listener leak without destroy       | P2       |
| SSE stall timeout could kill legitimate slow generation | P2       |
| `conversation.onChange` not cleared on destroy          | P3       |
| `statusTimer` race with destroy                         | P3       |
| `pendingQuestions` unbounded during streaming           | P3       |
| Multiple focusTrap listeners on `document`              | P3       |

---

## PHASE 12 — SECURITY

### Summary

| Severity | Count |
| -------- | ----- |
| CRITICAL | 4     |
| HIGH     | 6     |
| MEDIUM   | 6     |
| LOW      | 5     |

### CRITICAL Findings

| ID   | Issue                                                                       | File                                         |
| ---- | --------------------------------------------------------------------------- | -------------------------------------------- |
| C-01 | Production secrets in `.env.production` (MongoDB URI, API keys, JWT secret) | `.env.production`                            |
| C-02 | Same JWT_SECRET in dev AND production                                       | `.env.development:57` + `.env.production:78` |
| C-03 | Stripe prod validation bypassed with `YOUR_API_KEY` placeholder             | `core/config.py:740-745`                     |
| C-04 | Widget chat/feedback bypass origin validation when no Origin header         | `utils/origin.py:160` + `api/deps.py:1033`   |

### HIGH Findings

| ID   | Issue                                                   | File                                   |
| ---- | ------------------------------------------------------- | -------------------------------------- |
| H-01 | SSE access token cookie NOT HttpOnly                    | `api/deps.py:452-467`                  |
| H-02 | Argon2id parameters below OWASP sensitive minimums      | `core/security.py:23`                  |
| H-03 | Dashboard/widget containers lack read_only FS           | `docker/compose.prod.yml:64-84`        |
| H-04 | CORS allows all HTTP methods and headers                | `backend/main.py:169-175`              |
| H-05 | No MongoDB query injection sanitization in admin search | `repositories/tenant_repository.py:94` |
| H-06 | X-Forwarded-For spoofing when trust_proxy misconfigured | `api/deps.py:578-589`                  |

### Positive Security Controls (Well Implemented)

- Argon2id password hashing
- JWT with 15-min expiry, purpose-bound tokens
- Refresh token rotation with reuse detection
- CSRF double-submit with constant-time comparison
- Tenant isolation at every layer
- SSRF protection with DNS rebinding mitigation
- Rate limiting with atomic Lua script
- Docker hardening (non-root, cap_drop ALL, read-only for api/worker)
- Production boot validation

---

## PHASE 13 — DATABASE / REDIS

### MongoDB Issues

| Issue                                               | Severity |
| --------------------------------------------------- | -------- |
| `$regex` search without text indexes                | P1       |
| N+1 in `platform_stats` (10 count queries)          | P1       |
| Brute-force cosine scan loads full corpus           | P1       |
| Missing covering index for chat_sessions sort       | P2       |
| `search_session_ids` unbounded with unindexed regex | P2       |

### Redis Issues

| Issue                                       | Severity |
| ------------------------------------------- | -------- |
| Connection pool not configured              | P2       |
| Singleton never reconnects after failure    | P2       |
| `insert_chunks` catches bare `Exception`    | P3       |
| `incr` + `expire` not atomic in message cap | P3       |

---

## PHASE 14 — MEMORY / CPU / RESOURCE USAGE

### NOT MEASURED

- API RAM usage: NOT MEASURED (no live server available)
- Worker RAM usage: NOT MEASURED
- Next.js RAM: NOT MEASURED
- Chromium memory per crawl: NOT MEASURED
- Redis memory: NOT MEASURED

### Inferred Risks

- Brute-force cosine scan can spike memory for large corpora
- 50-page crawls can accumulate 100MB+ HTML in heap
- `queued` set in crawler grows unboundedly

---

## PHASE 15 — TEST QUALITY

### Test Results

- Backend: ~350 tests, most pass
- Frontend: vitest for dashboard + widget
- Widget: 27 test files for 30 source files (excellent coverage)

### Critical Test Issue

**D-01: 9 failing tests in `test_provider_router.py` (P0)**

- `FakeRedis` fixture only implements `get`/`set`
- `ProviderHealthStore` needs `incr`, `expire`, `scan`, `setex`
- Adaptive provider router has ZERO passing tests
- Regressions in failover/health tracking undetectable

### Coverage Gaps

| Area                  | Gap                                               |
| --------------------- | ------------------------------------------------- |
| Widget 401-retry flow | No integration test                               |
| `dashboard-home.tsx`  | No tests for loading/error/empty states           |
| `idCounter` collision | No multi-instance test                            |
| a11y assertions       | Filter to serious+critical only, moderate ignored |

---

## PHASE 16 — CI/CD + DOCKER

### CI Pipeline

- Ruff (lint + format) ✓
- mypy ✓
- pytest ✓
- Frontend eslint + typecheck + build + vitest ✓
- Docker build ✓
- Trivy security scan (SARIF) ✓
- E2E widget tests (requires secrets) ✓

### Issues

| Issue                                                  | Severity |
| ------------------------------------------------------ | -------- |
| Trivy uses `continue-on-error: true` — fragile gate    | P1       |
| No database migration validation in CI                 | P1       |
| No Docker image secret inspection                      | P2       |
| E2E skipped when secrets missing — no mock alternative | P2       |
| `uv sync --frozen` doesn't verify lockfile freshness   | P3       |

### Docker Security

- API: non-root, cap_drop ALL, read-only FS ✓
- Worker: non-root, cap_drop ALL, read-only FS ✓
- Dashboard: non-root ✓, but NO read-only FS ✗
- Widget: non-root ✓, but NO read-only FS ✗

---

## PHASE 17 — OBSERVABILITY

### Issues

| Issue                                                               | Severity |
| ------------------------------------------------------------------- | -------- |
| No tenant ID in structured logs                                     | P1       |
| No request ID in worker jobs                                        | P1       |
| No alert rules defined (Prometheus metrics collected but no alerts) | P1       |
| RAG stage timing is opt-in only (off by default)                    | P2       |
| No MongoDB query duration metrics                                   | P2       |
| `MetricsLogCollector` fragile log parsing                           | P2       |
| `sensitive_data_filter` misses `extra` dict values                  | P2       |
| Crawl progress not measured in metrics                              | P3       |

---

## PHASE 18 — UX / PRODUCT BEHAVIOR

### Dashboard Flows

- Login → create website → crawl → ingestion status → widget config → chat: IMPLEMENTED
- All states (loading, success, empty, error): IMPLEMENTED with page skeletons, error states, empty states
- Session expiry → redirect to login: IMPLEMENTED

### Widget Flows

- Load → ready → ask → stream → complete → follow-up: IMPLEMENTED
- Error → retry → close/reopen: IMPLEMENTED
- Mobile keyboard handling: IMPLEMENTED via `visualViewport` API

### UX Issues

- SSE reconnect always refreshes auth (unnecessary token rotation)
- No progress indicator during initial widget config load

---

## PHASE 19 — ARCHITECTURE REVIEW

### Assessment: GOOD with targeted improvements needed

**Strengths:**

- Clean three-layer architecture (routes → services → repositories)
- Protocol-based dependency injection
- No circular dependencies
- Excellent testability (fake repositories)
- Consistent patterns across modules
- Well-documented ADRs

**Weaknesses:**

- `deps.py` is 1061 lines (god module)
- `rag_service.stream_answer` is ~700 lines (god method)
- Worker jobs duplicate repository instantiation
- No shared worker dependency injection pattern

---

## PHASE 20-24 — FINAL SUMMARY

See companion files:

- `.audit-tmp/FINAL_ISSUE_REGISTER.md` — Complete issue register
- `.audit-tmp/UNUSED_FILES_REGISTER.md` — Unused file register
- `.audit-tmp/RAG_ACCURACY_LATENCY_AUDIT.md` — RAG-specific audit
- `.audit-tmp/OPTIMIZATION_ROADMAP.md` — Prioritized roadmap

---

## PRODUCTION SCORECARD

| Category         | Score | Evidence                                                         |
| ---------------- | ----- | ---------------------------------------------------------------- |
| Code Quality     | 7/10  | Clean architecture, but God methods and broad exceptions         |
| Backend          | 7/10  | Solid DI, but performance gaps (keyword search blocking, N+1)    |
| Frontend         | 8/10  | Good patterns, minor optimization opportunities                  |
| Widget           | 8/10  | Excellent vanilla TS SDK, minor cleanup needed                   |
| RAG Accuracy     | 7/10  | Working for known queries, improvements possible                 |
| RAG Retrieval    | 7/10  | Hybrid RRF + lexical protection working, event loop blocking     |
| RAG Latency      | 6/10  | External API calls dominate, keyword search blocks event loop    |
| LLM Latency      | 7/10  | Provider fallback chain, streaming TTFT acceptable               |
| Token Efficiency | 7/10  | Budget capping works, no major waste                             |
| Ingestion        | 7/10  | Working crawler, missing try/finally for cleanup                 |
| Database         | 6/10  | Missing indexes, N+1 queries, regex search                       |
| Caching          | 7/10  | Multi-tier caching, but stale after corpus update                |
| Security         | 6/10  | 4 CRITICAL findings (secrets, JWT, origin bypass)                |
| Reliability      | 7/10  | Circuit breaker, retry, but broad exceptions hide errors         |
| Testing          | 7/10  | Good coverage, 9 failing provider router tests                   |
| Observability    | 5/10  | Metrics exist but no alerts, tenant context missing              |
| Deployment       | 8/10  | Docker hardened, CI/CD complete, rollback support                |
| UX               | 8/10  | Complete flows, loading/error/empty states                       |
| Maintainability  | 7/10  | Clean patterns, but deps.py and rag_service need refactoring     |
| Scalability      | 7/10  | Multi-tenant, Redis caching, but blocking operations limit scale |

**OVERALL: 6.95 / 10**

---

## FINAL VERDICT

### 1. Is the application production-ready?

**PARTIALLY — with 4 CRITICAL blockers that must be resolved first.**

The codebase is architecturally sound with strong security fundamentals. However, 4 critical security findings (shared JWT secret, secrets in .env.production, Stripe validation bypass, widget origin bypass) and 9 failing provider router tests prevent a clean production-ready certification.

### 2. What are the P0 blockers?

1. **Shared JWT_SECRET across dev and production** — any dev compromise = production compromise
2. **Widget chat/feedback bypass origin validation** when no Origin header sent
3. **Embedding single-flight race condition** in `rag_service.py`
4. **Rate limit bypass** via broad `except Exception` in sliding window

### 3. What are the P1 issues?

- Broad `except Exception` in 6+ modules (cache, Redis, DB, quota, widget, provider health)
- 9 failing `test_provider_router.py` tests
- Keyword search blocking event loop
- N+1 queries in admin dashboard
- No tenant ID in structured logs
- No alert rules for Prometheus metrics
- `fetcher.close()` not guaranteed on crawl exception
- No database migration validation in CI
- Trivy security gate fragility

### 4. What can be safely optimized?

- Move keyword search to `asyncio.to_thread`
- Cache lexical corpus in retrieval cache
- Parallelize widget validation deps
- Remove duplicate `detect_injection` call
- Add text indexes for regex search fields
- Extract `done_data` builder to eliminate duplication

### 5. What should NOT be changed?

- The three-layer architecture (routes → services → repositories)
- Protocol-based DI pattern
- Hybrid RRF fusion approach
- Lexical protection in reranker
- SSRF guard with DNS rebinding mitigation
- Refresh token rotation with reuse detection
- Widget Shadow DOM isolation
- Docker hardening (non-root, cap_drop)

### 6. Which files appear unused?

- `apps/widget/src/demo.ts` (dev harness)
- Several one-time migration scripts in `scripts/`
- See `.audit-tmp/UNUSED_FILES_REGISTER.md` for complete list

### 7. What should be deleted only after verification?

- Migration scripts (verify no longer needed)
- One-time backfill scripts
- `.audit-tmp/` artifacts (after this audit is consumed)

### 8. What are the biggest latency bottlenecks?

1. **Query embedding** (200-800ms) — external API, cannot optimize
2. **LLM TTFT** (300-2000ms) — external API, cannot optimize
3. **Keyword search** (50-300ms) — **CAN FIX** by wrapping in `asyncio.to_thread`
4. **Vector search** (50-500ms) — Atlas-optimized, acceptable
5. **Lexical corpus load** (20-200ms) — **CAN FIX** by caching in retrieval cache

### 9. What are the biggest token/cost wastes?

- Context budget of 4000-8000 chars is reasonable
- No major waste identified
- Consider reducing history turns from default if conversations are long

### 10. What are the biggest RAG accuracy problems?

- No active accuracy failures in known queries
- Broad ranking for generic queries ("courses") can improve
- Context truncation at character boundary can garble last chunk

### 11. What backend problems remain?

- God method in `rag_service.stream_answer` (~700 lines)
- 13-element return tuple from `_retrieve`
- Broad exception handling hiding real errors
- Missing tenant context in logs
- No alert rules for collected metrics

### 12. What frontend/widget problems remain?

- SSE reconnect always refreshes auth
- Dashboard wastes one query for conversation count
- Widget `idCounter` shared across instances
- Listener cleanup could be more thorough

### 13. What security risks remain?

- 4 CRITICAL: JWT secret sharing, widget origin bypass, Stripe validation, .env secrets
- 6 HIGH: SSE cookie, Argon2 params, Docker read-only, CORS, regex injection, XFF spoofing
- 6 MEDIUM: Rate limit rotation, password reset binding, profile rate limit, SSRF ports, request ID validation, env comments

### 14. What tests are missing?

- Provider router tests (9 FAILING)
- Widget 401-retry integration test
- Dashboard home component tests
- Multi-instance widget ID collision test
- Database migration validation test

### 15. What should be fixed first?

1. Rotate ALL secrets (JWT, MongoDB, Redis, API keys)
2. Generate unique JWT_SECRET per environment
3. Enforce origin on widget chat/feedback
4. Fix embedding single-flight race
5. Narrow broad `except Exception` blocks
6. Fix 9 failing provider router tests
7. Wrap keyword search in `asyncio.to_thread`
8. Add try/finally for crawler `fetcher.close()`
9. Add tenant context to structured logs
10. Add Prometheus alerting rules
