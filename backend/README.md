# WebChat AI — Backend

The FastAPI service behind WebChat AI: multi-tenant authentication, website
ingestion into a retrieval knowledge base, source-grounded RAG chat, the public
widget API, billing, and the ARQ background worker.

- **Language / runtime:** Python 3.13, managed with `uv`
- **Framework:** FastAPI, Pydantic v2
- **Data:** MongoDB via Motor (documents, vector search with `$vectorSearch`),
  Redis (caching, rate limiting, ARQ job queue, SSE fan-out), Mailpit/Resend (email)
- **Workers:** ARQ (`python -m backend.workers`)
- **Version:** 0.1.0

This README is the developer-facing orientation for the backend. The platform
overview and quick start live in the [root README](../README.md); the production
deployment path (GHCR images, compose, rollback) is documented in
[docs/deployment/README.md](../docs/deployment/README.md).

## Repository layout

````
backend/
├── main.py                FastAPI app factory: routers, CORS, middleware, lifespan
├── api/                   HTTP layer
│   ├── routes/            Feature routers (see below)
│   ├── middleware.py      Request-id, origin gate, security headers, tenant context
│   ├── deps.py            Dependency injection: tenant resolution, auth, quota
│   └── sse.py             Server-Sent-Events helpers (chat streaming, crawl progress)
├── ai/                    AI provider layer (ADR-009)
│   ├── registry.py        Provider name -> client factory registry + fallback chains
│   ├── router.py          Fallback generation/embedding clients
│   ├── circuit_breaker.py Provider circuit breaker
│   ├── gemini.py          Gemini generation client
│   ├── mock.py            Deterministic offline provider (never the default order)
│   └── providers/         groq, openrouter, openai_compat, jina, cohere clients
├── core/                  Cross-cutting concerns
│   ├── config.py          Settings (pydantic-settings); fail-fast production guards
│   ├── database.py        MongoDB connection + ping
│   ├── redis.py           Redis client (cache, rate limit, ARQ quiet_errors)
│   ├── cache.py           Caching helpers (retrieval cache, widget config cache)
│   ├── security.py        Crypto helpers (token/code generation)
│   ├── rate_limit.py      Sliding-window rate limiting
│   ├── quota.py           LLM token budget enforcement (daily/monthly)
│   ├── rbac.py            Role-based access checks for the super-admin console
│   ├── privacy.py         PII/redaction guard for prompts and logs
│   ├── prompt_guard.py    Prompt-injection symptom detection
│   ├── metrics.py         Prometheus text-format metrics (exposed at /metrics)
│   ├── errors.py          Domain error hierarchy + exception mapping
│   ├── logging.py         JSON logging setup, request-id propagation
│   └── embedding_identity.py  Embedding-space identity (+ migration helpers)
├── services/              Domain logic (one package per bounded context)
│   ├── account/           User / tenant / usage / subscription services
│   ├── admin/             Super-admin: tenants, users, revenue, crawl jobs, audit
│   ├── ai/                Adaptive provider routing + provider health store
│   ├── analytics/         Query-level usage analytics
│   ├── api_keys/          Developer API key issuance/validation
│   ├── auth/              Signup, login, JWT, refresh, verification, password reset
│   ├── billing/           Plan checkout, subscriptions, usage metering
│   ├── chat/              RAG orchestration (see below)
│   ├── conversations/     Session history
│   ├── crawl/             Website crawling orchestration (see below)
│   ├── feedback/          Watched source suggestions / corrective feedback
│   ├── ingestion/         HTTP-first crawler, extractor, chunker, SSRF guard
│   ├── knowledge/         Cleaning, chunking, embeddings, document processing
│   ├── mail/              Transactional email templates (Mailpit/Resend)
│   ├── website/           Website records + knowledge-base state machine
│   └── widget/            Public widget session tokens, config, limits
├── repositories/          Data-access layer; every query is tenant-scoped
├── models/                MongoDB document models
├── schemas/               Pydantic API schemas
├── workers/               ARQ worker (ADR-002)
│   ├── app.py             WorkerSettings (startup/shutdown, concurrency)
│   ├── tasks.py           Task registry: ping, send_email, crawl_website,
│   │                      process_document, process_website_documents
│   └── jobs/              Per-job modules (email, crawl, knowledge)
├── migrations/            Idempotent index/schema migrations (deploy step)
├── prompts/               LLM prompt templates (rag.py, `RAG_PROMPT_VERSION = 1`)
└── benchmark/             RAG accuracy + TTFT benchmark harness
```## API modules

All routes live under `/api` unless noted. Registered in `backend/main.py`:

| Router         | Purpose                                                                   |
| -------------- | ------------------------------------------------------------------------- |
| `auth`         | Signup, login, logout, refresh, email verification, password reset, delete account |
| `websites`     | Workspace websites: connect, re-crawl, state transitions                   |
| `crawl_jobs`   | Crawl lifecycle + job state                                                  |
| `knowledge`    | Knowledge-base browsing (documents/chunks per website)                      |
| `chat`         | Authenticated RAG chat; conversation history                                 |
| `conversations`| List/read sessions and messages                                              |
| `widget`       | Public v1 SDK contract (`/api/widget/v1/config`, `/sessions`, `/chat`, `/feedback`) |
| `feedback`     | User-session/rating feedback                                                  |
| `analytics`    | Usage dashboards (domain `analytics`), observability endpoints                |
| `billing`      | Plans, checkout, subscription management                                      |
| `webhooks`     | Payment provider webhooks (Stripe/Razorpay)                                   |
| `api_keys`     | Developer API key management                                                  |
| `admin`        | Super-admin console (tenants, users, revenue, crawl jobs, system, audit)       |
| `metrics`      | Prometheus scrape endpoint (root path `/metrics`, no `/api` prefix)            |
| `health`       | `/api/health/live`, `/api/health`, `/api/health/ready` probes                  |

Health semantics: `/api/health/live` is a pure liveness probe with no dependency
I/O; `/api/health/ready` additionally pings MongoDB and Redis and is
**fail-closed** (503 when a dependency is down) — it is what the production
compose stack polls.

### Authentication flow

Cookies are host-only (`SameSite=Strict`, no `Domain`), so a browser only sends
them to the backend origin. The dashboard therefore keeps all API calls
same-origin and proxies `/api/*` to the backend (see
[apps/dashboard/README.md](../apps/dashboard/README.md)); the widget mints
short-lived anonymous session tokens instead.

- JWT access token + opaque refresh cookie (`REFRESH_COOKIE_NAME`, default `refresh_token`)
- CSRF token cookie (`CSRF_COOKIE_NAME`, default `csrf_token`) + header check on mutation routes
- Email verification codes and password-reset tokens (`EMAIL_VERIFY_TOKEN_EXPIRE_MINUTES`,
  `PASSWORD_RESET_TOKEN_EXPIRE_MINUTES`)
- Account deletion requires the account password to be re-entered
- Login lockout / backoff via `LOGIN_MAX_ATTEMPTS` and `LOGIN_LOCKOUT_MINUTES`
- Argon2 password hashing (`argon2-cffi`)

### Multi-tenancy

Workspaces (tenants) never share data. `deps.py` resolves the current tenant from
the authenticated session; repositories scope every query by `tenant_id`, and the
knowledge-base (§vectorSearch` filters by corpus identity).
`core/rbac.py` gates the super-admin console (`SUPER_ADMIN_EMAILS`),
`core/quota.py` enforces per-tenant LLM token budgets, and `core/rate_limit.py`
applies per-workspace and per-visitor limits.

## AI providers (ADR-009)

`ai/registry.py` maps provider names to client factories. Keys missing are warned
and skipped; an unknown name in `*_PROVIDER_ORDER` is a configuration error that
fails fast.

| Role        | Provider names in the default registry                     | Required env key            |
| ----------- | ---------------------------------------------------------- | --------------------------- |
| Generation  | `gemini` (default), `groq`, `openrouter`, `mock`           | `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY` |
| Embedding   | `gemini` (default), `jina`, `cohere`, `mock`               | `GEMINI_API_KEY`, `JINA_API_KEY`, `COHERE_API_KEY`     |

- Chat builds a **fallback chain** (`FallbackGenerationClient`) that walks
  `GENERATION_PROVIDER_ORDER` on failure, with provider health tracking
  (`services/ai/provider_health.py`) and a circuit breaker
  (`ai/circuit_breaker.py`). Set `AI_PROVIDER_ROUTING_MODE` to enable the
  adaptive router, which re-orders providers per request from real-time health.
- Chat embeddings use a tight per-provider retry budget
  (`CHAT_EMBEDDING_MAX_RETRIES`) so a hung provider fails fast into the next.
- **Ingestion is embedding-space locked (BUG-1).** A website is locked to exactly
  one embedding provider for its whole life; every chunk stores the provider +
  model revision (`embedding_identity`), and retrieval refuses to serve a corpus
  whose identity no longer matches the configured provider. This is why a
  cross-provider (e.g. Gemini→Jina) failover never happens mid-corpus.

## Website ingestion → Knowledge Base

The pipeline that turns a website into a chunked, embedded knowledge base:

1. **Crawl** — HTTP-first crawler (respects `robots.txt`, sitemap, `Crawler-Priority`),
   BFS over `CRAWL_MAX_PAGES` pages with `CRAWL_PRIORITY_URL_PATHS` boosted,
   same-origin + SSRF guard (`services/ingestion/ssrf_guard.py`), then Playwright
   fallback for JS-rendered pages (`CRAWL_NO_SANDBOX`, `CRAWL_NAVIGATION_TIMEOUT_MS`).
2. **Clean + chunk** — HTML extraction and cleaning, chunking by
   `KNOWLEDGE_CHUNK_SIZE_TOKENS` with `KNOWLEDGE_CHUNK_OVERLAP_TOKENS`,
   dropping below-`KNOWLEDGE_MIN_CONTENT_CHARS` pages.
3. **Embed + store** — embeddings via the locked provider (batch + pacing in
   `services/knowledge/embedding.py`), chunks stored per-tenant with their
   embedding identity.
4. **Process** — `process_document` / `process_website_documents` ARQ jobs finalize
   batches, retry with `KNOWLEDGE_RETRY_BASE_DELAY_SECONDS` exponential backoff,
   and quarantine documents that exhaust retries instead of writing partial data.

Crawl progress streams to the dashboard over SSE (`backend/api/sse.py`); job
state is observable in the admin console.

## RAG chat pipeline

Entry point `services/chat/rag_service.py` (`stream_answer_with_usage`). Each turn:

1. **Classify** (`query_classifier.py`) — complexity/tone classification
   (`QueryComplexity` SIMPLE / MEDIUM / COMPLEX), gated by `ENABLE_ADAPTIVE_RETRIEVAL`.
   Complexity selects numbers of candidates, rerank top-k and context budget
   (`ADAPTIVE_SIMPLE_*` / `ADAPTIVE_COMPLEX_*`).
2. **Rewrite** (`query_rewrite.py`) — conversational rewrites when
   `ENABLE_CONVERSATIONAL_QUERY_REWRITE` is on.
3. **Retrieve** (`retrieval_strategy.py`) — default **hybrid** retrieval: vector
   (`$vectorSearch`) merged with keyword results by reciprocal-rank fusion
   (`HYBRID_RRF_K`), falling back to pure vector when `ENABLE_HYBRID_SEARCH` is
   off. Results are cached (`CHAT_RETRIEVAL_CACHE_*`) and diversified so no
   source monopolizes the context (`rerank_max_chunks_per_source`).
4. **Rerank** (`ENABLE_RERANKING`, `RERANK_TOP_K`) — lexical/LLM reranking of the
   candidate set.
5. **Assemble + generate** — context optimization (`ENABLE_CONTEXT_OPTIMIZATION`),
   streaming generation over SSE with `sources` / `message` / `done` / `error`
   events.
6. **Publish gate** — `assess_answerability()` refuses to answer with an empty
  /no-faithful retrieval; `assess_result_confidence()` scores
   `0.50·mean + 0.30·hit-ratio + 0.20·peak`; below `RAG_CONFIDENCE_THRESHOLD`
   (default 0.3) the response is downgraded to an abstention, and after
   generation a faithfulness check (`ENABLE_FAITHFULNESS_CHECK`) warns when
   `FAITHFULNESS_WARNING_THRESHOLD` is breached. `PRIVACY` / `PROMPT_GUARD` guard
   inputs.

Concurrency/streaming knobs (`SSE_BUFFER_MS`, `SSE_IDLE_TIMEOUT`,
`GENERATION_FIRST_TOKEN_TIMEOUT_SECONDS`, `GENERATION_TIMEOUT_SECONDS`) plus the
LLM budget (`LLM_DAILY_TOKEN_LIMIT`, `LLM_MONTHLY_TOKEN_LIMIT`,
`LLM_REQUEST_LIMIT_PER_MINUTE`) are in `core/config.py`.

## Worker (ARQ)

Run with `python -m backend.workers` (or `arq backend.workers.app.WorkerSettings`).
Registered tasks:

| Task                        | Purpose                                   |
| --------------------------- | ----------------------------------------- |
| `ping`                      | Worker health check                       |
| `send_email`                | Transactional email                       |
| `crawl_website`             | Run a crawl job                           |
| `process_document`          | Embed + persist one document              |
| `process_website_documents` | Finalize a website's batch                |

Concurrency: `max_tries = 3`, `job_timeout = 600s`, `max_jobs = 10`,
`keep_result = 3600s`. The worker shares the API's embedding provider
configuration and holds a single Playwright browser instance with a process-wide
lock (crawls serialize on it: `test_browser_lock.py`).

## Configuration

Settings live in `core/config.py` (pydantic-settings). All names + defaults are
documented in [`.env.example`](../.env.example) and enforced at boot:

- In production, weak values fail fast: loopback `ALLOWED_HOSTS`, short/missing
  `JWT_SECRET`, empty provider orders, mock payments, unauthenticated
  MongoDB/Redis, and placeholders all raise rather than boot.
- `LOCAL_PRODUCTION_TEST=true` explicitly permits loopback values for local
  production smoke tests.
- Provider health / circuit-breaker knobs: `AI_PROVIDER_*`
  (`AI_PROVIDER_ROUTING_MODE`, `AI_PROVIDER_TIMEOUT_SECONDS`,
  `AI_PROVIDER_HEALTH_CHECK_INTERVAL`, `AI_CIRCUIT_*`).
- Payments: `PAYMENT_PROVIDER` (`mock` | `stripe` | `razorpay`), currency in
  `PAYMENT_CURRENCY`; provider secrets in `STRIPE_SECRET_KEY`/`RAZORPAY_KEY_ID` etc.

## Development

Prerequisites: Python 3.13 (`uv`), a running MongoDB + Redis
(see [docker/README.md](../docker/README.md)).

```bash
uv sync                        # install backend deps + dev tooling (ruff, mypy, pytest)
scripts/dev-api.sh             # uvicorn backend.main:app --reload :8000
scripts/dev-worker.sh          # python -m backend.workers  (ARQ)
````

Environment: copy `.env.example` → `.env` (or `cp .env.development .env` for the
bundled development config that points at the Docker `mongo`/`redis`/`mailpit`
services).

### Tests

```bash
scripts/check-backend.sh       # ruff check . && mypy backend && pytest
uv run pytest tests/           # full backend suite
```

See [tests/README.md](../tests/README.md) for coverage areas and the Definition
of Done.

## Production

The backend runs as two containers — `api` (uvicorn) and `worker` (ARQ) — built
to immutable `sha-<git-sha>` GHCR images. Migrations run as a one-shot container
before rollout. Details, health probes, Prometheus alerting, and troubleshooting:
[docs/deployment/README.md](../docs/deployment/README.md).
