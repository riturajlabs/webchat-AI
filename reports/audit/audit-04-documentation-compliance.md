# Documentation Compliance Audit — WebChat AI

**Date:** 2026-08-11
**Audit scope:** `00-AI-Development-Rules.md`, `docs/01-PRD.md`, `docs/02-TRD.md`, `docs/03-App-Flow.md`, `docs/04-UI-UX-Brief.md`, `docs/05-Backend-Schema.md`, `docs/06-Implementation-Plan.md`, `docs/07-Architecture-Decisions.md`.
**Baseline commit:** `78931b3` (head of `main`, working tree clean, 15 commits since `v0.6-rag-complete`).
**Source-of-truth hierarchy:** ADR (`07`) supersedes PRD/TRD/Plan where they conflict — see ADR-007/008 and §11 Reconciliation. Where this report cites a doc requirement, the ADR-modified version is the contract.
**Method:** static read of repo + docs (no code modifications); cross-checked against `reports/audit/audit-01/02/03`, `docs/Phase-5/6/7/8/8.1-Verification-Report.md`. Test counts from the latest committed run (Phase 8.1: 354 backend + 167 frontend + 1 E2E).

---

## 1. Completed features

### 1.1 Foundation & Architecture (Phase 1)

- Monorepo: `apps/dashboard` (Next.js 15 / React 19 / TS / Tailwind / shadcn) + `apps/widget` (vanilla TS / Vite) + `backend` (FastAPI / Python 3.13) — folder structure conforms to ADR-007.
- pnpm workspaces, uv venv, ruff + mypy + ESLint + Prettier + Husky pre-commit hooks configured.
- Docker: 4 Dockerfiles (api, worker, dashboard, widget) + `docker/compose.dev.yml` (7 services: mongo, redis, mailpit, api, worker, dashboard, widget).
- Dev scripts: `scripts/setup.sh`, `dev-api.sh`, `dev-worker.sh`, `docker-up.sh`, `check-backend.sh`, `e2e-widget.sh`.
- CI: `.github/workflows/ci.yml` (3 jobs: backend lint/typecheck/test, frontend lint/typecheck/build/test, docker build; `widget-e2e` job added in Phase 8.1, gated on `GEMINI_API_KEY`).
- Health endpoints: `GET /api/health` (liveness + dependency status), `GET /api/health/ready` (HTTP 503 on degraded, 200 on ready — Phase 8.1 fix).
- Settings via pydantic-settings; `.env` ≡ `.env.example` ≡ `config.py` reconciled (67/67 keys).

### 1.2 Authentication (Phase 2, ADR-003)

- Signup, login, logout, JWT (HS256 access + opaque SHA-256-hashed rotating refresh), Argon2id (memory 19 MiB, time 2, parallelism 1).
- Refresh token rotation with reuse detection (revokes all on reuse + `audit_log`).
- Double-submit CSRF (`csrf_token` cookie + `X-CSRF-Token` header on cookie-auth routes).
- Email verification + forgot/reset password via signed JWTs (ADR-001).
- Resend email provider (`backend/services/mail/providers.py`) + Mailpit for dev (`docker/compose.dev.yml`); ARQ `send_email` job ensures no blocking on SMTP.
- RBAC (`owner` | `admin`), rate limiters (login, register, forgot/reset/verify-email), audit logs for security events.
- Endpoints: `POST /api/auth/{register,login,refresh,logout,verify-email,forgot-password,reset-password}`, `GET /api/auth/me`.

### 1.3 Website management (Phase 3)

- `POST/GET/PATCH/DELETE /api/websites` + `GET/PATCH /api/websites/{id}/widget` + `POST /api/websites/{id}/crawl`.
- SSRF-safe URL validation (`backend/utils/url_validator.py`), duplicate detection, status lifecycle (pending → crawling → processing → ready/failed).
- Dashboard `apps/dashboard/src/features/websites/` (list, card, status badge, add-website dialog) — fully tested.

### 1.4 Ingestion engine (Phase 4)

- Playwright headless Chromium crawler (`backend/services/ingestion/crawler.py`, `browser.py`) with process-wide concurrency semaphore (`CRAWL_MAX_CONCURRENT=2`).
- Internal-link BFS crawl, configurable depth (default 3), per-job page cap (default 50).
- Readability extraction + HTML cleaning (`extractor.py`, `cleaner.py`); per-page metadata (title, language, checksum).
- SSRF guard (`ssrf_guard.py`): per-request DNS re-validation, private/loopback/link-local/CGNAT/metadata blocking.
- robots.txt compliance (`utils/robots.py`); URL normalization.
- Idempotent document upserts on `(tenant_id, website_id, url)` with SHA-256 content checksum.
- ARQ `crawl_website` job with retry/backoff, permanent failure on invalid seeds; `crawl_jobs` + `documents` tenant-scoped collections.
- Endpoints: `POST /api/websites/{id}/crawl` (returns 202), `GET /api/crawl-jobs/{id}`.

### 1.5 Knowledge processing (Phase 5)

- Chunking (`backend/services/knowledge/chunker.py`): dependency-free token chunker, TRD-aligned 700/100 defaults, sentence/paragraph-boundary alignment, guaranteed-forward window.
- Embedding (`backend/services/knowledge/embedding.py`): Google GenAI async SDK, batched (32) with exponential backoff + full jitter, 5 retries, per-request timeout; fail-fast on missing `GEMINI_API_KEY` (`EmbeddingUnavailableError`).
- Vector storage: `VectorRepository` Protocol + MongoDB Atlas `$vectorSearch` (tenant/website pre-filter, Top-5 cosine, `index: "default"`); unique `(tenant_id, website_id, document_id, chunk_index)` for idempotent writes; `KnowledgeChunk.to_out()` never exposes embeddings.
- Orchestration: `KnowledgeProcessor` binds only Protocols; `process_document` idempotent (skip when checksum unchanged + chunks exist, replace on change, mark `failed` + audit `KNOWLEDGE_FAILED` on embedding error).
- Worker: `process_document`, `process_website_documents` registered in ARQ task registry.
- Status surface: `WebsiteOut.knowledge_{status,documents,chunks}` + `last_knowledge_at` on dashboard cards.

### 1.6 RAG pipeline (Phase 6)

- `POST /api/chat/stream` (SSE): tenant-filtered Top-5 retrieval → versioned prompt → Gemini 2.5 Flash streaming.
- Hallucination guard: model never called without retrieved context; empty knowledge base or zero hits return TRD §8 fixed fallback (`UNKNOWN_ANSWER_FALLBACK`).
- Conversation memory: `chat_sessions` (unique `session_id`, `expires_at` TTL) + `messages` (tenant/session index, `created_at` TTL); `CHAT_MEMORY_TURNS` last turns fed to prompt.
- Versioned prompts: `backend/prompts/rag.py` catalog keyed by `RAG_PROMPT_VERSION`; `sanitize_question` strips control chars; reference material delimited and labeled untrusted (prompt-injection defense).
- Token usage capture (ADR-005 §5.8): per-message `input_tokens`/`output_tokens` + atomic `$inc` rollups in `usage_records`.

### 1.7 Dashboard (Phase 7)

- Next.js 15 App Router with `(auth)` + `(dashboard)` route groups.
- Pages: login, signup, verify-email, forgot-password, reset-password, dashboard home, websites, knowledge, conversations (list + detail), analytics, widget (editor + builder + preview), api-keys, profile, settings.
- In-memory access token, silent single-retry refresh, CSRF header on mutations.
- Typed API client (`apps/dashboard/src/lib/api.ts`) covers every backend endpoint.
- Empty/loading/error/success states implemented; unsupported surfaces render production-grade empty states with no mock data.
- Theme toggle (light/dark/system), responsive sidebar + mobile nav.
- shadcn/ui primitives throughout.

### 1.8 Widget SDK (Phase 8, ADR-004)

- Vanilla-TS framework-independent SDK, ships as custom element `<webchat-widget>` with closed shadow root.
- Bundle: IIFE `gzip -9` = **23.41 kB** (hard limit 100 kB, warn 90 kB).
- Launcher, chat window, message bubbles, composer, suggested questions, markdown renderer, theme engine (CSS custom properties), accessibility (axe-core: 0 serious/critical violations).
- Visitor cookie (`wc_visitor`), session lifecycle (15-min widget-session JWT + 24 h sliding validity), SSE client with retryable/terminal error taxonomy (`WidgetError` codes), offline banner + Retry/Dismiss.
- Imperative SDK API: `init()`, `mount()`, controller (`updateConfig`, `open`, `close`, `destroy`, callbacks `onMessage`/`onSources`/`onOpen`/`onClose`/`onError`/`onStatusChange`).
- One-line embed: `<script src="…" data-widget-id="…" defer></script>` (auto-upgrades).

### 1.9 Public widget backend (Phase 8, ADR-004)

- `GET /api/widget/v1/config/{widget_id}` — public, Redis-cached 5 min; suspended tenant returns `enabled: false` rather than 403.
- `POST /api/widget/v1/sessions` — rate-limited token mint; returns `{session_token, expires_at}`.
- `POST /api/widget/v1/chat` — Bearer widget-session JWT, SSE; re-validates widget enabled + tenant active + website `ready` on every chat.
- Public CORS middleware (`WidgetCORSHeadersMiddleware`): `Access-Control-Allow-Origin: *` on widget namespace only; dashboard CORS stays strict.
- Per-widget (60/min) + per-visitor (20/min) + session-issue (30/min) rate limits via `WidgetRateLimitDependency` (keyed by `widget_id`/`visitor_id`).
- 50-message per-conversation cap; basic spam filter (`services/widget/spam_filter.py`: repeated punctuation, repeated chars, all-caps, URL-only).

### 1.10 Conversations API (added late)

- `GET /api/conversations` (paginated list, search + website filter), `GET /api/conversations/{session_id}` (detail with full message history), `DELETE /api/conversations/{session_id}` (soft + cascade).
- Tenant-scoped reads; rate-limited.
- Dashboard UI: `apps/dashboard/src/features/conversations/` (list, list-item, detail, status badge).

### 1.11 Analytics API + dashboard (Phase 9/11.3)

- `GET /api/analytics/summary` (conversations, messages, AI responses, input/output tokens, est. cost, avg response time).
- `GET /api/analytics/timeseries` (zero-filled daily series), `GET /api/analytics/top-websites`, `GET /api/analytics/performance` (avg/fastest/slowest response time).
- Service: `AnalyticsService` owns window math + zero-fill + estimated-cost model; all DB via `AnalyticsRepository` Protocol.
- Dashboard UI: `apps/dashboard/src/features/analytics/analytics-page.tsx` with charts/cards.

### 1.12 API Keys (Phase 11.x)

- `POST /api/keys` (create, raw secret returned exactly once), `GET /api/keys`, `DELETE /api/keys/{id}` (revoke).
- Argon2-hashed/SHA-256 storage; raw secret never persisted; `key_prefix` for display.
- Audit logging on create + revoke (`AUDIT_API_KEY_CREATED`, `AUDIT_API_KEY_REVOKED`).
- Dashboard UI: `apps/dashboard/src/app/(dashboard)/api-keys/page.tsx` (list, create dialog, revoke).

### 1.13 AI Provider Abstraction & Fallback (Phase 9, ADR-009)

- `GenerationClient` + `EmbeddingClient` Protocols (Liskov-stable); application code unchanged.
- `backend/ai/registry.py` + `router.py`: provider registry + ordered fallback chains.
- Generation fallback: Gemini → Groq → OpenRouter; embedding fallback: Gemini → Ollama (with dimension-mismatch warning).
- OpenAI-compatible shared implementation (`backend/ai/providers/openai_compat.py`): one connection pool, single `build_chat_payload`, SSE parsing, HTTP status mapping.
- Env: `GENERATION_PROVIDER_ORDER`, `EMBEDDING_PROVIDER_ORDER`, `GROQ_*`, `OPENROUTER_*`, `AI_PROVIDER_TIMEOUT_SECONDS`, `EMBEDDING_DIMENSIONS`, `OLLAMA_*`.
- Unknown names fail fast; missing keys skipped with warning; pre-stream commitment for generation (no mid-stream restarts).

### 1.14 Schema updates (ADR-005)

- `users`: `onboarding_completed`, `onboarding_step`, `pwd_token_version`, `schema_version`.
- `widgets`: `accent_color`, `font_size`, `logo_url`, `avatar_url`, `placeholder`, `suggested_questions`, `dark_mode`, `auto_open`, `widget_secret_hash`, `schema_version`.
- New collections: `refresh_tokens`, `usage_records`, `feedback`.
- TTL indexes per ADR-005 §5.7: `audit_logs` 1 y, `chat_sessions` 90 d (configurable), `messages` 90 d, `crawl_jobs` 30 d, `refresh_tokens` 40 d, `usage_records` 3 y, `feedback` 2 y.
- Per-message `schema_version: 1` on websites, widgets, knowledge_chunks.

### 1.15 Security hardening (Phase 8.1, ongoing)

- Security headers middleware (`backend/api/middleware.py`): CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy.
- `WidgetCORSHeadersMiddleware` (public widget namespace) + dashboard strict CORS.
- Request-ID + Request-Timing middleware (Phase 12.1 instrumentation).
- Double-submit CSRF on cookie-auth routes.
- Rate limiters: auth (login, register, forgot/reset/verify-email), widget (per-widget, per-visitor, session-issue), chat, conversations, API key create — all sliding-window Redis-backed.
- Argon2id password hashing; SHA-256 opaque-token hashing.
- SSRF guard on crawler + URL validator; prompt-injection defense in prompt builder (`sanitize_question` + delimited untrusted context).
- Widget secrets never shipped to client (server-issued scoped session tokens).
- Audit logging for security events: LOGIN, LOGOUT, REFRESH_REUSE_DETECTED, API_KEY_CREATED, API_KEY_REVOKED, KNOWLEDGE_FAILED, etc.

### 1.16 Multi-tenant security

- Every tenant-owned query includes `tenant_id` (verified by review of `repositories/*`).
- `VectorRepository.search` filter is `tenant_id` + `website_id`; widget session tokens re-validated on every chat.
- Suspended tenants: login/refresh rejected; widget config returns `enabled: false`.

### 1.17 Testing (Phase 8.1 latest run)

- Backend pytest: **354 passed, 1 skipped, 0 failed** (`tests/e2e/test_widget_e2e.py` self-skips without `E2E_BASE_URL`).
- Widget E2E (live stack): **1 passed** (`test_widget_full_flow`, 30.6 s).
- Frontend vitest: **167 passed** (58 dashboard, 109 widget).
- Coverage gate configured (`pytest --cov=backend`); threshold not enforced yet.
- All frontend pages have component tests; widget has axe a11y + mount integration + SSE tests.

---

## 2. Partially completed features

### 2.1 Source citation in widget (PRD §11 "Cite source pages (Future)")

- **Status:** ✅ Complete — backend persists sources on `messages.metadata.sources`; the widget SSE consumer dispatches `sources` → `onSources` → `Conversation.setSources(turnId, sources)`; bubbles.ts renders them via `syncSources` / `renderSources` with safe-URL filtering (javascript:/data:/vbscript: rejected, `target="_blank"` + `rel="noopener noreferrer"` on safe URLs, DOM-only construction — no `innerHTML` on untrusted content). Closed during Phase 10 streaming UX commit `ea6d061`.
- **Verification:** `apps/widget/src/ui/bubbles.test.ts` covers source rendering, empty/undefined sources (no block emitted), unsafe-scheme rejection, multiple sources in order with citation prefix, and the "Sources" label landmark. Bundle: 23.41 kB gzip (under 100 kB cap).

### 2.2 Onboarding wizard (PRD §7 / UI/UX §7)

- **Status:** Partial — `users.onboarding_completed` + `onboarding_step` fields added per ADR-005; no wizard UI in dashboard (only the empty-state pattern guides first-time users).
- **Gap:** Multi-step onboarding (Welcome → Connect Website → Index Website → Embed Widget → Done) is not implemented as a flow.

### 2.3 Usage rollups for embeddings & crawl (ADR-005 §5.5)

- **Status:** ✅ Complete — `embeddings_created` is incremented by `KnowledgeProcessor._record_embeddings_created` (`backend/services/knowledge/processor.py`) after `vector.insert_chunks(...)` succeeds, by `len(chunks)`. `crawl_pages` is incremented by `_record_crawl_job` after `session.run()` returns, by the `stored` page count. Both reuse `UsageRecordRepository.increment(...)` (no new repo method), are best-effort (try/except + log), and stay tenant-scoped via `document.tenant_id` / `job.tenant_id`. Closed in commit `19ab1c5`.
- **Verification:** 10 new tests cover success / failure / unchanged / zero / cross-tenant / repo-outage for both counters. `pytest tests/test_knowledge_processor.py tests/test_crawl_worker.py` → 33 passed.

### 2.4 Cross-embedding duplicate detection (Phase 5/6 deferred)

- **Status:** Documented deferred; not implemented. Phase 6 verification report §14 "cross-embedding duplicate detection remains open for the analytics phase."

### 2.5 Mypy strict typing (CI gate quality)

- **Status:** Partial — `mypy backend` green at locked mypy 2.3.0 (Phase 8.1); audit-01 baseline of 98 `untyped-decorator` errors is toolchain-dependent and not reproducible today.
- **Gap:** No `disallow_untyped_decorators = true`; strict mode not enforced.

### 2.6 Coverage threshold enforcement

- **Status:** Partial — `pytest --cov=backend --cov-report=term-missing` runs in CI; no `--cov-fail-under` value set (Phase 12 target ≥ 90% critical path not pinned).

### 2.7 Performance instrumentation (Phase 11)

- **Status:** Partial — `RequestTimingMiddleware` + `workers/timing.py::timed_job` measure latency; logging gated by `PERF_TIMING_LOG_ENABLED=true` (default false). No P50/P95/P99 dashboard; no Redis caching of hot reads beyond widget config (300 s).
- **Gap:** TRD §12 budgets (<500 ms API, <3 s first token, <100 KB widget) are not continuously measured; Phase 12.1 instrumentation in place but no SLO dashboard.

### 2.8 Duplicate detection across embeddings (Phase 5 deferred)

- **Status:** Documented; not implemented. Phase 5 completion notes §13 "cross-embedding duplicate detection remains open for the analytics phase."

---

## 3. Missing features

### 3.1 Admin panel (ADR-006, Phase 10)

- **Spec:** `/api/admin/*` with `role=admin` guard — list/search/suspend tenants, platform KPIs, global crawl queue, audit log viewer, user suspend/force-logout.
- **Implementation:** `apps/dashboard/src/features/admin/` contains only `.gitkeep`; no `backend/api/routes/admin/` directory; no admin UI page; `users.role = "admin"` field not used by any router.
- **Status:** 0% implemented.

### 3.2 Feedback endpoint + UI (ADR-005 §5.6, UI/UX §12 "User Satisfaction")

- **Spec:** `feedback` collection, 1–5 rating + category + comment, TTL 2 y, dashboard chart "User Satisfaction".
- **Implementation:** `feedback` model present in `models/usage_record.py` constants list only (no `models/feedback.py`); no repository; no route; no UI; widget does not surface a feedback widget.
- **Status:** Schema reserved, collection not created; no API or UI.

### 3.3 User satisfaction chart (UI/UX §12)

- No feedback data → no chart. Depends on §3.2.

### 3.4 "Active Visitors" + "Token Usage" live counters (UI/UX §12)

- **Status:** Schema exists (`usage_records`); dashboard shows aggregate totals + estimated cost but no live-active-visitors metric; no token-usage-per-day chart (only totals + est. cost in summary).

### 3.5 Future roadmap (PRD §13 / TRD §13) — explicitly out of scope for v1 but tracked

| Feature                                                                     | Doc                         | Status                                   |
| --------------------------------------------------------------------------- | --------------------------- | ---------------------------------------- |
| Billing / Payment Gateway                                                   | PRD §14 OoS, TRD §11 future | Not implemented                          |
| PDF / DOCX knowledge base                                                   | PRD §13                     | Not implemented                          |
| Image OCR                                                                   | PRD §13                     | Not implemented                          |
| Voice chat / WhatsApp / Slack / Notion / GitHub / Google Drive integrations | PRD §13                     | Not implemented                          |
| Multi-language support                                                      | PRD §13                     | Not implemented                          |
| Human handoff                                                               | PRD §13                     | Not implemented                          |
| AI Agent Workflows                                                          | PRD §13                     | Not implemented                          |
| Multi-model selection at user level                                         | PRD §14 OoS                 | Not implemented (provider fallback only) |
| Fine-tuning                                                                 | PRD §14 OoS                 | Not implemented                          |
| Custom AI models                                                            | PRD §14 OoS                 | Not implemented                          |
| Mobile application                                                          | PRD §14 OoS                 | Not implemented                          |
| Hybrid search (vector + keyword), reranking, context compression            | TRD §7 future               | Dense-only Top-5                         |

### 3.6 Source citation in widget UI (PRD §11 "Future")

- **Closed** in Phase 12.2 (commit `3287fc0`). Backend persists sources on `messages.metadata.sources`; SSE `sources` event reaches `Conversation.setSources` → `syncSources` → `renderSources`; rendered below the AI bubble with safe-URL filtering and citation labels. Covered by 5 widget tests.

### 3.7 Onboarding wizard (PRD §7)

- See §2.2.

### 3.8 Backup & recovery automation (TRD §15)

- Daily MongoDB backup + point-in-time restore + disaster recovery plan **not automated**. Atlas-managed backups are infrastructure-layer (deferred to deployment).

### 3.9 OpenTelemetry / Grafana / Prometheus / Sentry (TRD §14 future)

- **Status:** None integrated. `RequestTimingMiddleware` + structured logging exist; no OTel exporter; no Prometheus endpoint; no Sentry SDK.

### 3.10 Load testing / concurrent-user benchmark (TRD §12 "Minimum 500+ concurrent")

- Not run. Phase 12 target exists in plan; no load test harness committed.

---

## 4. Architecture deviations

### 4.1 Celery → ARQ (ADR-002, intentional supersede)

- TRD §3 listed Celery; ADR-002 swaps to ARQ for async-first fit with Motor + Playwright. Implemented. ✅ Aligned.

### 4.2 Widget "Signed Requests" → scoped session tokens (ADR-004)

- TRD §10 mentions "Signed Widget Requests." Since a public widget cannot hold a secret, ADR-004 implements server-issued scoped JWTs (widget_id + tenant_id + website_id + visitor_id). `widget_secret` (HMAC-SHA256) is generated per widget for future server-to-server integrations but is **never shipped in the client JS**. ✅ Aligned with ADR; deviates from TRD wording by design.

### 4.3 Token storage → in-memory access + httpOnly refresh cookie (ADR-003)

- TRD §10 mentions secure tokens; ADR-003 resolves access token to React state (no `localStorage` exposure). Implemented. ✅ Aligned.

### 4.4 Phase ordering — Widget SDK moved to Phase 8 (ADR-008 §8)

- ADR-008 lists Dashboard as Phase 7; docs/06 had Dashboard as Phase 7 and Widget as Phase 8. Implementation followed docs/06 ordering (Dashboard first). Documented in ADR-008 §8 and Phase 7 verification report header. ✅ Reconciled.

### 4.5 Folder structure — ADR-007 supersedes 00-AI-Development-Rules §5

- Canonical tree lives in ADR-007 §7. Implemented tree matches (apps/dashboard, apps/widget, backend/api, backend/core, backend/models, backend/schemas, backend/services, backend/repositories, backend/workers, backend/ai, backend/prompts, backend/templates, backend/utils, docs, docker, scripts, tests). ✅ Aligned.

### 4.6 Schema deltas — ADR-005 supersedes docs/05

- Widget fields, onboarding flags, `refresh_tokens`, `usage_records`, `feedback`, `schema_version`, TTL indexes per ADR-005 §5.7. `feedback` is reserved-but-not-created (§3.2 above). ⚠️ Partial deviation: 7/8 deltas applied.

### 4.7 Production hosting

- TRD §3 Hosting specifies Vercel / Render / Atlas / Upstash / Cloudinary. Local `docker-compose.dev.yml` runs all services locally. **No Render/Vercel deployment manifests committed** — Vercel/Render/Atlas provisioning is left to deployment phase. ⚠️ No IaC.

### 4.8 MongoDB Atlas `$vectorSearch` dependency

- Production requires Atlas Vector Search index. Local dev stack degrades to a brute-force cosine scan in `repositories/vector/mongodb.py` (Phase 8.1 carry-over delta). Production Atlas path is unchanged. ⚠️ Dev-only deviation; production behavior preserved.

### 4.9 Mypy strict typing

- ADR/Plan say "strict typing" but `mypy backend` uses defaults (not `--strict`); CI is green but not enforcing strict-mode. ⚠️ Drift from plan §16 coding standards.

### 4.10 Email provider — Resend (ADR-001)

- TRD didn't name a provider. ADR-001 picks Resend (prod) + Mailpit (dev). Implemented. ✅ Aligned.

---

## 5. Production readiness status

### 5.1 Verdict by axis

| Axis                      | Status                      | Notes                                                                                                               |
| ------------------------- | --------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Authentication            | **Production-ready**        | Argon2id, JWT access (15 min, in-memory), refresh rotation with reuse detection, CSRF double-submit, RBAC.          |
| Website management        | **Production-ready**        | SSRF-safe URL validation, lifecycle states, widget creation.                                                        |
| Ingestion engine          | **Production-ready**        | Playwright + SSRF guard + robots.txt + caps + idempotent documents + crawl → knowledge handoff.                     |
| Knowledge processing      | **Production-ready**        | Chunking, embedding, vector storage, idempotent re-embed on checksum change.                                        |
| RAG pipeline              | **Production-ready**        | Hallucination guard, streaming, memory, versioned prompts, token usage capture.                                     |
| Dashboard                 | **Production-ready**        | All pages with loading/empty/error/success; auth uses memory-only token with single-retry refresh.                  |
| Widget SDK                | **Production-ready**        | 20.42 kB gzip, axe a11y clean, error taxonomy, retry UX, offline banner.                                            |
| Public widget backend     | **Production-ready**        | Per-widget/visitor rate limits, scoped session tokens, public CORS, message cap, spam filter.                       |
| Conversations             | **Production-ready**        | List/detail/delete; tenant-scoped; rate-limited.                                                                    |
| Analytics                 | **Production-ready for v1** | Summary, timeseries, top-websites, performance, est. cost. All `USAGE_COUNTERS` populated (§2.3, commit `19ab1c5`). |
| API keys                  | **Production-ready**        | Argon2-hashed storage, one-time raw secret reveal, revoke, audit.                                                   |
| AI provider fallback      | **Production-ready**        | Gemini default, Groq/OpenRouter/Ollama fallbacks; fail-fast on unknown names.                                       |
| Multi-tenant security     | **Production-ready**        | `tenant_id` on every query; widget session re-validation; suspended-tenant semantics.                               |
| Observability             | **Partial**                 | Structured logging, request ID, request timing, worker timing. No OTel/Grafana/Prometheus/Sentry (§3.9).            |
| Deployment                | **Partial**                 | Dockerfiles + compose.dev complete; no Vercel/Render manifests; no IaC (§4.7).                                      |
| Admin panel               | **Not started**             | (§3.1)                                                                                                              |
| Feedback                  | **Not started**             | Schema reserved, no collection/route/UI (§3.2).                                                                     |
| E2E coverage              | **Partial**                 | Widget E2E happy-path exists; no admin E2E, no auth E2E.                                                            |
| Load / performance SLO    | **Partial**                 | Instrumented; budgets not measured end-to-end (§2.7).                                                               |
| Source citation in widget | **✅ Done**                 | SSE `sources` → `Conversation.setSources` → `syncSources`/`renderSources` (§2.1, commit `3287fc0`).                 |

### 5.2 Gate status (latest committed, Phase 8.1)

| Gate                                                       | Status                                    |
| ---------------------------------------------------------- | ----------------------------------------- |
| Backend `ruff check .`                                     | ✅ Pass                                   |
| Backend `ruff format --check .`                            | ✅ Pass (164/164)                         |
| Backend `mypy backend` (CI)                                | ✅ Pass (97 files, locked mypy 2.3.0)     |
| Backend `mypy .` (from `backend/`)                         | ✅ Pass                                   |
| Backend `pytest`                                           | ✅ 354 passed, 1 skipped, 0 failed        |
| Widget E2E (`tests/e2e`, live stack)                       | ✅ 1 passed (30.6 s)                      |
| Frontend `pnpm lint`                                       | ✅ Pass                                   |
| Frontend `pnpm typecheck`                                  | ✅ Pass                                   |
| Frontend `pnpm test`                                       | ✅ 167 passed (58 dashboard + 109 widget) |
| Frontend `pnpm build`                                      | ✅ Pass                                   |
| Widget bundle (`pnpm --filter @webchat/widget build:size`) | ✅ 20.42 kB gzip (≤ 100 kB gate)          |
| `/api/health/ready` fail-closed                            | ✅ 503 when MongoDB or Redis down         |

### 5.3 Known caveats

- Widget E2E requires live infra (MongoDB, Redis, Mailpit, api, worker, widget) + `GEMINI_API_KEY`. Self-skips when `E2E_BASE_URL` is unset; CI runs only on secret availability.
- `python -m playwright install chromium` needed on fresh machines for E2E runner.
- `WIDGET_API_BASE_URL` documented but not consumed by widget build (supplied at embed/build time).
- mypy baseline is toolchain-version-dependent; locked mypy 2.3.0 in `uv.lock` resolves the audit-01 baseline (Phase 8.1 carry-over).

### 5.4 Bottom-line

The platform is **production-ready for the v1 feature set** that has been built (auth → websites → ingestion → knowledge → RAG → dashboard → widget → conversations → analytics → API keys → AI provider fallback). It is **not production-ready** for the v1 spec in full because the **Admin Panel (Phase 10 / ADR-006)** and **Feedback (ADR-005 §5.6)** are unimplemented, the **onboarding wizard (UI/UX §7)** is not a flow, and **observability** stops short of OTel/Prometheus/Sentry. Deployment to Render/Vercel is not IaC-automated.

---

## 6. Remaining implementation roadmap

### 6.1 To close PRD §15 Definition of Success

| #   | Item                                                                                             | Doc                        | Effort | Depends on                                                                        |
| --- | ------------------------------------------------------------------------------------------------ | -------------------------- | ------ | --------------------------------------------------------------------------------- |
| 1   | Admin panel backend (`/api/admin/*`)                                                             | ADR-006                    | M      | `users.role` field, `tenants.status`, `audit_logs`, `usage_records` already exist |
| 2   | Admin panel UI                                                                                   | ADR-006                    | M      | (1)                                                                               |
| 3   | Feedback collection + `POST /api/feedback` + widget rating widget + dashboard satisfaction chart | ADR-005 §5.6 / UI/UX §12   | M      | `feedback` collection create                                                      |
| 4   | Onboarding wizard (Welcome → Connect → Index → Embed → Done)                                     | UI/UX §7 / PRD §7          | M      | `onboarding_completed` / `onboarding_step` already on user                        |
| 5   | ~~Source citation as default widget UI (render below AI bubble)~~                                | PRD §11 future / UI/UX §16 | ~~S~~  | **Done** — Phase 12.2 commit `3287fc0` (5 tests, 23.41 kB gzip)                   |
| 6   | ~~`embeddings_created` + `crawl_pages` usage rollups~~                                           | ADR-005 §5.5               | ~~S~~  | **Done** — Phase 12.3 commit `19ab1c5` (10 tests, both counters tenant-scoped)    |
| 7   | Cross-embedding duplicate detection                                                              | Phase 5/6 deferred         | M      | None                                                                              |
| 8   | Performance SLO dashboard + Redis hot-read cache                                                 | TRD §12 / Phase 11         | M      | `RequestTimingMiddleware`, `timed_job` already instrumented                       |
| 9   | OTel exporter + Prometheus metrics endpoint + Sentry SDK                                         | TRD §14 future             | M      | Logging in place                                                                  |
| 10  | IaC: Render `render.yaml` / Vercel config / Atlas index scripts                                  | TRD §3 / Phase 13          | M      | Docker images already build                                                       |
| 11  | Coverage threshold (`--cov-fail-under=85`) in CI                                                 | Phase 12                   | XS     | Tests already green                                                               |
| 12  | Hybrid search (vector + keyword), reranking, context compression                                 | TRD §7 future              | L      | None                                                                              |
| 13  | Backup automation script + disaster recovery runbook                                             | TRD §15                    | S      | Atlas-native                                                                      |
| 14  | Auth-flow E2E (Playwright)                                                                       | Phase 12                   | M      | `e2e-widget.sh` exists                                                            |

### 6.2 Out-of-scope-for-v1 roadmap (PRD §13)

PDF/DOCX knowledge base, image OCR, voice chat, WhatsApp/Slack/Notion/GitHub/Google Drive integrations, multi-language support, human handoff, AI agent workflows, multi-model selection at user level, fine-tuning, custom AI models, mobile application, billing/payment gateway.

### 6.3 Documentation hygiene

- `docs/05-Backend-Schema.md` needs an ADR-005 reconciliation update (currently only referenced from ADR-007 §11 reconciliation table).
- `docs/06-Implementation-Plan.md` §13 (Deployment) needs concrete Vercel/Render steps once IaC exists.
- ADR-009 should be added to §10 Decision Register (already present).

---

## 7. Priority order (P0 / P1 / P2)

### P0 — Blockers for "production-ready" claim vs PRD §15

1. **Admin panel (backend + UI)** — ADR-006; PRD §6 explicitly lists Super Admin role; missing entirely. Without it, "Manage tenants / Suspend accounts / View logs" (PRD §6) are unmet.
2. **Feedback endpoint + widget + dashboard chart** — PRD §6 Visitor "Submit feedback" + UI/UX §12 "User Satisfaction" chart. Schema reserved but unused.
3. **IaC + staging deploy** — Phase 13 has no committed manifests. The "production-ready" claim is unverifiable without a deployable target.
4. ~~**Source citation in widget** — explicitly noted as deferred in Phase 8 verification; trivial to ship.~~ **Closed in Phase 12.2** (commit `3287fc0`).
5. **Coverage threshold enforcement** — pin `--cov-fail-under` in CI to protect the 354-test green.
6. **Onboarding wizard** — PRD §7 / UI/UX §7; reduces time-to-first-chat from "no flow" to <5 min (matches UI/UX target experience §3).

### P1 — Strengthens production quality (no block)

7. **OTel + Prometheus + Sentry** — TRD §14; without it, the platform has no observability beyond logs and `RequestTimingMiddleware`.
8. ~~**`embeddings_created` + `crawl_pages` rollups** — closes the last two empty `usage_records.counters` keys.~~ **Closed in Phase 12.3** (commit `19ab1c5`).
9. **Performance SLO dashboard** — measure TRD §12 budgets continuously.
10. **Cross-embedding duplicate detection** — Phase 5 deferred; closes the analytics chapter.
11. **Mypy strict mode** — gate against `untyped-decorator` regressions.
12. **Auth-flow Playwright E2E** — currently only the widget happy path is covered.

### P2 — Future roadmap (PRD §13 / TRD §7/§15)

13. **PDF / DOCX / image knowledge base** — extends ingestion.
14. **Multi-language / i18n** — UI/UX §21 currently responsive but not localized.
15. **Human handoff + AI agent workflows** — operator-grade extensions.
16. **Hybrid search + reranking + context compression** — TRD §7 future.
17. **Integrations: WhatsApp / Slack / Notion / GitHub / Google Drive** — channel expansion.
18. **Voice chat** — UX extension.
19. **Backup automation runbook** — operational hardening.
20. **Billing / payment gateway** — explicitly OoS v1.

---

## Appendix A — Spec coverage matrix (PRD → code)

| PRD section                    | Feature                                                                                               | Implemented?                                             | Evidence                                                               |
| ------------------------------ | ----------------------------------------------------------------------------------------------------- | -------------------------------------------------------- | ---------------------------------------------------------------------- |
| §6 Super Admin                 | Manage tenants, suspend, view logs                                                                    | **No**                                                   | §3.1                                                                   |
| §6 Tenant                      | Register, add website, manage chatbot, analytics, configure widget, API keys, conversations, re-index | **Yes**                                                  | auth + websites + widget + conversations + analytics + api_keys routes |
| §6 Visitor                     | Ask questions, view responses, submit feedback                                                        | Partial — chat yes, feedback **No**                      | §3.2                                                                   |
| §7 Authentication              | Secure signup, login, forgot, verify, JWT, refresh                                                    | **Yes**                                                  | `backend/api/routes/auth.py`                                           |
| §7 Website Mgmt                | Add, verify, edit, delete, multiple (Future)                                                          | **Yes** (multiple not yet)                               | `backend/api/routes/websites.py`                                       |
| §7 Knowledge Base              | Crawl, SPA, chunk, embed, vector, re-index                                                            | **Yes**                                                  | ingestion + knowledge modules                                          |
| §7 AI Chatbot                  | Streaming, context-aware, no-hallucination, source-aware (Future)                                     | **Yes** (source UI done Phase 12.2)                      | rag_service + Phase 12.2 commit `3287fc0`                              |
| §7 Widget                      | One-line embed, responsive, mobile, theme, position, branding                                         | **Yes**                                                  | widget SDK + ADR-004                                                   |
| §7 Dashboard                   | Status, crawl progress, analytics, widget config, conversations                                       | **Yes**                                                  | dashboard pages                                                        |
| §7 Analytics                   | Total chats, active users, avg response time, popular Q, failed Q, crawl status                       | Partial — popular Q + failed Q **not surfaced**          | analytics module                                                       |
| §10 RBAC                       | owner                                                                                                 | admin roles                                              | **Yes** (admin role unused, see §3.1)                                  | `users.role` |
| §10 Tenant isolation           | Every query has `tenant_id`                                                                           | **Yes**                                                  | repositories + widget session re-validation                            |
| §10 Attack Protection          | XSS, CSRF, SSRF, NoSQL injection, prompt injection, brute force, DDoS, API abuse                      | **Yes**                                                  | middleware + URL validator + sanitization + rate limits                |
| §11 Cite source pages (Future) | Cite source below AI response                                                                         | Partial — backend + renderSources; **not in default UI** | §2.1                                                                   |
| §13 Future Roadmap             | PDF, DOCX, image OCR, voice, integrations, handoff, agents, multi-language                            | **No**                                                   | §3.5                                                                   |
| §14 OoS v1                     | Billing, multi-model select, fine-tuning, custom models, voice, image gen, mobile                     | **No** (correctly deferred)                              | §3.5                                                                   |

## Appendix B — TRD coverage matrix

| TRD section              | Topic                                                                                                                                                            | Implemented?                                                                                                                                                           |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| §3 Frontend stack        | Next.js 15, React 19, TS, Tailwind, shadcn, React Query, RHF, Zod, Axios                                                                                         | **Yes**                                                                                                                                                                |
| §3 Backend stack         | FastAPI, Python 3.13, Uvicorn, Pydantic v2, Motor                                                                                                                | **Yes**                                                                                                                                                                |
| §3 Queue                 | ARQ (Celery supersede by ADR-002)                                                                                                                                | **Yes**                                                                                                                                                                |
| §3 AI stack              | LangGraph (not used — RAG service is hand-rolled), LangChain (not used), Gemini 2.5 Flash, text-embedding-004, MongoDB Vector Search                             | Partial — LangGraph + LangChain not used. Pure FastAPI + httpx async implementation. (ADR-009 allows direct provider clients; this is a stack deviation worth noting.) |
| §3 Crawling              | Playwright, BeautifulSoup, Readability, lxml                                                                                                                     | **Yes**                                                                                                                                                                |
| §3 Hosting               | Vercel, Render, Atlas, Upstash, Cloudinary (Future)                                                                                                              | Partial — IaC not committed (§4.7)                                                                                                                                     |
| §5 AI Pipeline           | URL → Playwright → Clean → Extract → Chunk → Embed → Vector                                                                                                      | **Yes**                                                                                                                                                                |
| §5 Chat Flow             | Q → Embed → Vector → Retrieve → Prompt → Gemini → Stream                                                                                                         | **Yes**                                                                                                                                                                |
| §6 Chunking              | 500–800 tokens, 100 overlap, semantic, metadata                                                                                                                  | **Yes** (700/100 defaults, configurable)                                                                                                                               |
| §7 Retrieval             | Dense, Top-5, cosine                                                                                                                                             | **Yes**                                                                                                                                                                |
| §7 Future                | Hybrid, reranking, compression                                                                                                                                   | **No**                                                                                                                                                                 |
| §8 Prompt Engineering    | System/dev prompts, fallback string                                                                                                                              | **Yes** (`backend/prompts/rag.py`)                                                                                                                                     |
| §9 API Architecture      | REST, response format, error format                                                                                                                              | **Yes** (consistent envelope)                                                                                                                                          |
| §10 Security             | JWT, refresh rotation, Argon2id, RBAC, tenant isolation, rate limit, signed requests, input sanitization                                                         | **Yes** (signed requests → scoped session tokens per ADR-004)                                                                                                          |
| §10 Web Security         | HTTPS, secure cookies, CORS, CSP, HSTS, X-Frame-Options, X-Content-Type-Options                                                                                  | **Yes** (`SecurityHeadersMiddleware`)                                                                                                                                  |
| §11 Multi-Tenant         | tenant_id + widget_id on every request                                                                                                                           | **Yes**                                                                                                                                                                |
| §12 Performance          | Dashboard <2 s, API <500 ms, AI first token <3 s, vector search <300 ms, 500+ concurrent                                                                         | Partial — instrumented, not continuously measured                                                                                                                      |
| §13 Scalability          | Horizontal, background workers, Redis queue, CDN, stateless API                                                                                                  | **Yes**                                                                                                                                                                |
| §14 Logging & Monitoring | API logs, error logs, auth logs, crawl logs; health, perf, queue, AI latency, DB metrics                                                                         | Partial — logs + health + queue timing; no metrics export                                                                                                              |
| §15 Backup & Recovery    | Daily, PIT, soft delete, audit logs                                                                                                                              | Partial — soft delete + audit logs implemented; backup automation not committed                                                                                        |
| §16 Coding Standards     | Frontend strict TS, backend async-first, modular, DI, repo pattern, SOLID/DRY/KISS                                                                               | **Yes**                                                                                                                                                                |
| §18 Definition of Done   | Frontend↔backend comms, crawl works, embeddings generated, RAG accurate, widget functional, multi-tenant, security passes, perf targets, all critical tests pass | **Yes** (perf targets not measured continuously; admin + feedback open)                                                                                                |

## Appendix C — Files inspected

- `00-AI-Development-Rules.md`, `docs/01-PRD.md`, `docs/02-TRD.md`, `docs/03-App-Flow.md`, `docs/04-UI-UX-Brief.md`, `docs/05-Backend-Schema.md`, `docs/06-Implementation-Plan.md`, `docs/07-Architecture-Decisions.md`
- `docs/Phase-5/6/7/8/8.1-Verification-Report.md`
- `reports/audit/audit-01-verification.md`, `audit-02-health-runtime.md`, `audit-03-testing-coverage.md`
- `backend/main.py`, `backend/api/routes/{auth,websites,crawl_jobs,chat,widget,conversations,analytics,api_keys,health}.py`, `backend/api/deps.py`, `backend/api/middleware.py`
- `backend/services/{auth,ingestion,knowledge,chat,crawl,conversations,analytics,api_keys,mail,widget,website}/*`
- `backend/ai/{gemini,registry,router,mock,providers/{groq,ollama,openrouter,openai_compat}}.py`
- `backend/workers/{app,tasks,jobs/{crawl,knowledge,email}}.py`
- `backend/repositories/*`, `backend/models/*`, `backend/core/*`, `backend/utils/{robots,url_validator}.py`, `backend/prompts/rag.py`, `backend/templates/emails/*`
- `apps/dashboard/src/app/(auth)/*`, `apps/dashboard/src/app/(dashboard)/*`, `apps/dashboard/src/features/**`
- `apps/widget/src/{core,ui,stream,markdown,theme,config}/*`, `apps/widget/README.md`
- `tests/test_*.py` (49 files), `tests/e2e/test_widget_e2e.py`
- `apps/dashboard/**/*.test.tsx` (17 files), `apps/widget/src/**/*.test.ts` (20 files)
- `docker/compose.dev.yml`, `docker/Dockerfile.{api,worker,dashboard,widget}`, `scripts/{setup,docker-up,check-backend,dev-api,dev-worker,e2e-widget}.sh`
- `.github/workflows/ci.yml`, `.env.example`, `pyproject.toml`, `package.json`, `pnpm-workspace.yaml`

---

**End of audit.** Working tree clean; no code changes were made during this audit. All findings reference existing verification reports; no new test runs were executed.
