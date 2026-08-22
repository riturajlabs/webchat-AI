# Production Environment Credential & Configuration Audit Report

> Date: 2026-08-20 | Scope: Full-stack env var audit, .env.production update, validation

---

## Files Modified

| File                 | Change                                                                 |
| -------------------- | ---------------------------------------------------------------------- |
| `.env.production`    | Added 20 missing config keys (security, RAG optimization, AI provider) |
| `docker/compose.yml` | Added 20 missing forwarding entries to `x-backend-env`                 |

---

## Missing Variables Fixed

### Added to `.env.production` (SECURITY section)

| Variable                        | Value | Purpose                           |
| ------------------------------- | ----- | --------------------------------- |
| `LOGIN_MAX_ATTEMPTS`            | `5`   | Failed-login throttle (SEC-3)     |
| `LOGIN_LOCKOUT_MINUTES`         | `15`  | Account lockout duration (SEC-3)  |
| `REFRESH_RATE_LIMIT_PER_MINUTE` | `30`  | Refresh token abuse bound (SEC-7) |

### Added to `.env.production` (RAG PIPELINE section)

| Variable                             | Value   | Purpose                                         |
| ------------------------------------ | ------- | ----------------------------------------------- |
| `ENABLE_RERANKING`                   | `true`  | Post-retrieval reranking with stored embeddings |
| `RERANK_TOP_K`                       | `5`     | Top results after reranking                     |
| `HYBRID_SEARCH_CANDIDATE_LIMIT`      | `50`    | Bounded candidate loading (P1 optimization)     |
| `ENABLE_ADAPTIVE_RETRIEVAL`          | `false` | Opt-in query-adaptive retrieval                 |
| `ADAPTIVE_SIMPLE_TOP_K`              | `4`     | Simple query retrieval depth                    |
| `ADAPTIVE_SIMPLE_RERANK_TOP_K`       | `3`     | Simple query rerank depth                       |
| `ADAPTIVE_SIMPLE_MAX_CONTEXT_CHARS`  | `8000`  | Simple query context budget                     |
| `ADAPTIVE_COMPLEX_TOP_K`             | `12`    | Complex query retrieval depth                   |
| `ADAPTIVE_COMPLEX_RERANK_TOP_K`      | `8`     | Complex query rerank depth                      |
| `ADAPTIVE_COMPLEX_MAX_CONTEXT_CHARS` | `30000` | Complex query context budget                    |
| `ENABLE_FAITHFULNESS_CHECK`          | `true`  | Post-generation faithfulness warning            |
| `FAITHFULNESS_WARNING_THRESHOLD`     | `0.6`   | Min faithfulness score before warning           |
| `ENABLE_RAG_CONFIDENCE_CHECK`        | `false` | Opt-in pre-generation confidence gate           |
| `RAG_CONFIDENCE_THRESHOLD`           | `0.3`   | Min confidence to proceed with generation       |
| `ENABLE_CONTEXT_OPTIMIZATION`        | `false` | Opt-in near-dup removal + compression           |

### Added to `.env.production` (AI PROVIDERS section)

| Variable                              | Value | Purpose                       |
| ------------------------------------- | ----- | ----------------------------- |
| `AI_PROVIDER_RECOVERY_WINDOW_SECONDS` | `120` | Post-cooldown recovery window |

### Added to `docker/compose.yml` (x-backend-env)

All 20 variables above plus `REFRESH_RATE_LIMIT_PER_MINUTE` are now forwarded
to both `api` and `worker` containers. Previously these were silently falling
back to `Settings` defaults, which could diverge from `.env.production` values.

---

## Existing Variables Preserved

All secret values were preserved unchanged:

- `JWT_SECRET` (64-char hex)
- `MONGODB_URI` (Atlas connection string)
- `REDIS_URL` (Upstash TLS URL)
- `RESEND_API_KEY`
- `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`
- `JINA_API_KEY`, `COHERE_API_KEY`
- `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`
- `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`

---

## Coverage Audit

| Source                       | Variables | Status                                                                  |
| ---------------------------- | --------- | ----------------------------------------------------------------------- |
| `config.py` Settings fields  | 120       | All present in `.env.production` AND `docker/compose.yml`               |
| `.env.production` entries    | 137       | All unique keys accounted for                                           |
| `docker/compose.yml` entries | 138       | `NODE_ENV`, `PORT` = dashboard-only (correct)                           |
| `DOCKER_BRIDGE_MTU`          | 1         | Compose network config, not forwarded to containers (correct)           |
| Frontend build-time vars     | 2         | `NEXT_PUBLIC_API_URL`, `VITE_WIDGET_API_BASE_URL` (build args, correct) |

**Zero config.py fields missing from either `.env.production` or `docker/compose.yml`.**

---

## RAG Configuration Validation

| Setting                          | `.env.production` | `config.py` Default | Match                   |
| -------------------------------- | ----------------- | ------------------- | ----------------------- |
| `ENABLE_HYBRID_SEARCH`           | `true`            | `True`              | Yes                     |
| `ENABLE_RERANKING`               | `true`            | `True`              | Yes                     |
| `HYBRID_SEARCH_CANDIDATE_LIMIT`  | `50`              | `50`                | Yes                     |
| `RERANK_TOP_K`                   | `5`               | `5`                 | Yes                     |
| `ENABLE_ADAPTIVE_RETRIEVAL`      | `false`           | `False`             | Yes                     |
| `ENABLE_RAG_CONFIDENCE_CHECK`    | `false`           | `False`             | Yes                     |
| `RAG_CONFIDENCE_THRESHOLD`       | `0.3`             | `0.3`               | Yes                     |
| `ENABLE_CONTEXT_OPTIMIZATION`    | `false`           | `False`             | Yes                     |
| `ENABLE_FAITHFULNESS_CHECK`      | `true`            | `True`              | Yes                     |
| `FAITHFULNESS_WARNING_THRESHOLD` | `0.6`             | `0.6`               | Yes                     |
| `CHAT_TOP_K`                     | `5`               | `8`                 | Different (intentional) |
| `CHAT_MEMORY_TURNS`              | `8`               | `12`                | Different (intentional) |
| `CHAT_CONTEXT_MAX_CHARS`         | `12000`           | `20000`             | Different (intentional) |
| `CHAT_MAX_OUTPUT_TOKENS`         | `512`             | `4096`              | Different (intentional) |

The 4 intentional differences are production-tuned overrides (smaller context for
latency, lower output tokens for cost control). All match the documented
production rationale.

---

## Docker Validation

### Service Dependencies

| Service     | Depends On                           | Health Check        |
| ----------- | ------------------------------------ | ------------------- |
| `api`       | `mongo` (healthy), `redis` (healthy) | HTTP `/api/health`  |
| `worker`    | `mongo` (healthy), `redis` (healthy) | —                   |
| `dashboard` | `api` (healthy)                      | HTTP root           |
| `widget`    | —                                    | HTTP static asset   |
| `mongo`     | —                                    | `mongosh ping`      |
| `redis`     | —                                    | `redis-cli ping`    |
| `mailpit`   | —                                    | HTTP `/api/v1/info` |

### Environment Propagation

```
.env.production → docker compose → x-backend-env → api + worker containers
.env.production → docker compose → build args → dashboard (NEXT_PUBLIC_API_URL)
.env.production → docker compose → build args → widget (VITE_WIDGET_API_BASE_URL)
```

All 138 backend environment variables are forwarded through the `&backend-env`
anchor. No variable is dropped or silently overridden.

---

## Test Results

### Backend

| Check                        | Result                                                                                       |
| ---------------------------- | -------------------------------------------------------------------------------------------- |
| `pytest tests/ -x`           | **1409 passed, 2 skipped**                                                                   |
| `ruff check backend/ tests/` | **All checks passed**                                                                        |
| `mypy backend/`              | **262 pre-existing errors** (untyped decorators in admin.py, main.py — not from this change) |

### Frontend

| Check                            | Result                              |
| -------------------------------- | ----------------------------------- |
| `pnpm install --frozen-lockfile` | **Success** (already up to date)    |
| Widget `tsc --noEmit`            | **Success** (0 errors)              |
| Widget `vite build`              | **Success** (141.45 kB / 111.89 kB) |
| Dashboard `tsc --noEmit`         | **Success** (0 errors)              |
| Dashboard `next build`           | **Success** (all pages rendered)    |

---

## Remaining Warnings

| Item                                     | Severity | Notes                                                                                   |
| ---------------------------------------- | -------- | --------------------------------------------------------------------------------------- |
| `mypy` untyped decorator errors          | Low      | Pre-existing in `admin.py` / `main.py`. Not from this change.                           |
| `EMAIL_FROM=onboarding@resend.dev`       | Info     | Sandbox sender — only delivers to Resend account owner. Replace before real deployment. |
| `STRIPE_SECRET_KEY=YOUR_API_KEY`         | Info     | Placeholder — must be replaced before Railway deployment.                               |
| `RAZORPAY_WEBHOOK_SECRET=PLACEHOLDER...` | Info     | Placeholder — must be replaced before Railway deployment.                               |
| `ALLOWED_HOSTS=localhost,...`            | Info     | Localhost-only — must be replaced with public hostnames for Railway.                    |
| `LOCAL_PRODUCTION_TEST=true`             | Info     | Must be `false` or unset in real Railway deployment.                                    |

---

## Summary

- **20 missing variables** added to `.env.production` and `docker/compose.yml`
- **0 secrets exposed** — all secret values preserved as-is
- **120/120** config.py fields covered in `.env.production`
- **120/120** config.py fields forwarded in `docker/compose.yml`
- **1409 tests pass**, ruff clean, frontend builds clean
- Docker service dependencies and health checks verified
- All RAG optimization settings validated against `config.py` defaults

---

_End of report. No commits made. No Docker images built._
