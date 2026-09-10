# WebChat AI — Tests

The automated test suite for the whole platform. Quality gates and what "done"
means are defined below; CI runs the same commands (`.github/workflows/ci.yml`).

## Layers

| Layer            | Tool         | Location                             | What it covers                                                                              |
| ---------------- | ------------ | ------------------------------------ | ------------------------------------------------------------------------------------------- |
| Backend unit/API | pytest       | `tests/` (repo root)                 | Services, repositories, API routes, security, RAG, crawler, embeddings, workers, billing    |
| Dashboard        | Vitest + RTL | `apps/dashboard/src/**/*.test.ts(x)` | UI components, hooks, lib helpers, auth flows                                               |
| Widget SDK       | Vitest + RTL | `apps/widget/src/**/*.test.ts`       | Mount/embed, config resolution, markdown render, bubbles, feedback, styles, a11y (axe-core) |
| Themes           | Vitest       | `packages/themes/src/*.test.ts`      | Presets, resolution precedence, contrast                                                    |
| E2E (widget)     | Playwright   | `tests/e2e/`                         | Full widget flows against the running stack (provisioned via `tests/e2e/provision.py`)      |

## Running

```bash
scripts/check-backend.sh                       # ruff + mypy + full pytest (the backend gate)
uv run pytest tests/                           # backend only
uv run pytest tests/test_rag_service.py -k "confidence"   # one file / subset
uv run pytest tests/e2e/                       # Playwright widget e2e (requires running stack + E2E_* vars)
pnpm test                                      # dashboard + widget + themes (recursive)
pnpm --filter @webchat/dashboard test
pnpm --filter @webchat/widget test
```

E2E config comes from env: `E2E_BASE_URL`, `E2E_WIDGET_SCRIPT_URL`,
`E2E_MAILPIT_URL` (see `.env.example`), with the stack from
[docker/README.md](../docker/README.md) running.

## Backend suite — area map

Files in `tests/` cluster by concern (`*_helpers.py` hold per-area fixtures):

- **Auth & accounts:** `test_auth_api/service/repository`, `test_account_service`,
  logout/lockout, deletion re-auth, refresh/CSRF, rate limits, `test_*_helpers`.
- **Security:** `test_security`, `test_prompt_security`, `test_prompt_guard`,
  `test_ssrf_guard`, `test_spam_filter`, `test_privacy`, `test_sanitization`,
  `test_api_key_auth`, `test_middleware`, `test_rate_limit`, `test_rbac`.
- **Websites & ingestion:** `test_crawler`, `test_http_first_crawler`,
  `test_crawl_service/worker/api`, `test_crawl_events`, `test_crawler_priority`,
  `test_extractor`, `test_robots`, `test_url_validator`, `test_cleaner`,
  `test_chunker`, `test_knowledge_processor`.
- **Embeddings:** `test_embedding`, `test_embedding_fallback/pacing/compatibility`,
  `test_jina_embedding`, `test_cohere_embedding`, `test_ingestion_embedding_identity`,
  `test_ingestion_provider_lock` (BUG-1: single provider space, dimension mismatch).
- **RAG:** `test_rag_service`, `test_rag_validation`, `test_rag_answerability`,
  `test_query_classifier`, `test_confidence`, `test_context_optimizer`,
  `test_retrieval_strategy`, `test_hybrid_search`, `test_reranker_lexical`,
  `test_lexical_context_gate`, `test_source_diversity`, `test_vector_mongodb`,
  `test_retrieval_cache_invalidation`, `test_p0_hybrid_keyword_recall`.
- **AI providers:** `test_ai_registry`, `test_ai_router`, `test_ai_retry`,
  `test_ai_mock`, `test_gemini_client`, `test_groq_provider`,
  `test_openrouter_provider`, `test_provider_router`, `test_ai_circuit_breaker`.
- **RAG accuracy / benchmarks:** `test_rag_accuracy*`, `test_rag_baseline*`,
  `test_benchmark*`, `test_hybrid_llm_evaluation`, `test_retrieval_comparison`,
  `test_rag_perf07_parallel_retrieval`, `test_rag_perf_f02_cached_results`,
  `test_rag_perf_f03_offload_lexical` and the other `test_rag_perf*` suites.
- **Widget API:** `test_widget_api`, `test_widget_config_api`, `test_widget_security`,
  `test_widget_origin`, `test_widget_defaults`, `test_widget_service`.
- **Multi-tenancy:** `test_deps` (tenant scoping), `test_rbac`,
  `test_tenant_repository`, `test_tenant_purge_repository`, `test_website_service`,
  `test_document_repository`, `test_database`.
- **Billing & usage:** `test_billing_api/schemas`, `test_payment_providers`,
  `test_payment_webhooks`, `test_subscription_service`, `test_usage_service`,
  `test_quota`, `test_cost_tracking`.
- **API keys / analytics / feedback:** `test_api_keys_api/service`,
  `test_analytics_api/service`, `test_feedback_api/service/repository`,
  `test_conversations_api`, `test_chat_api/repository`.
- **Ops/infra:** `test_health`, `test_lifespan`, `test_config`,
  `test_production_readiness`, `test_worker_shutdown`, `test_browser_lock`,
  `test_metrics`, `test_mongo_metrics`, `test_alert_rules`, `test_database`,
  `test_db_cache_resilience`, `test_migrations`, `test_migrate_allowed_domains`,
  `test_logging`, `test_request_id`, `test_error_capture`.

## Hermeticity (backend)

`tests/conftest.py` makes the suite hermetic:

- MongoDB is stubbed — tests must never touch a real cluster
  (`MongoDB.db()` collections raise if actually queried); the URI is overridden
  to an unreachable endpoint as a belt-and-suspenders guard.
- pymongo/motor/gridfs loggers are silenced to WARNING.
- `os.environ` is snapshotted at session start so tests can be restored to a
  known-clean environment.
- Deterministic AI mock providers are used where a test needs generation/embedding.

## Definition of Done

A change ships only when **all** of these pass locally in CI:

1. `ruff` — zero findings (`uv run ruff check .`)
2. `mypy` — zero errors (`uv run mypy backend`) and `tsc --noEmit` clean for the
   frontends
3. Frontend lint: `eslint` clean in `apps/dashboard`, `apps/widget`
4. Full test matrix green — backend pytest, dashboard/widget/themes vitest,
   widget e2e where affected
5. `git diff --check` — no whitespace errors; no secrets tracked
   (`scripts/check-secrets.sh`)

A documentation-only change must at minimum keep the docs commands (link
targets, code blocks) accurate; see [`../docs/README.md`](../docs/README.md).
