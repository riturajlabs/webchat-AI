# OPTIMIZATION ROADMAP

## WebChat AI — Comprehensive Production-Readiness Audit

### Date: September 4, 2026

---

## QUICK WINS (Fix Immediately — Low Risk, High Impact)

| #     | Fix                                                                            | Benefit                                      | Risk | Effort | Validation                                       |
| ----- | ------------------------------------------------------------------------------ | -------------------------------------------- | ---- | ------ | ------------------------------------------------ |
| QW-1  | Rotate ALL production secrets (JWT, MongoDB, Redis, AI keys, Resend, Razorpay) | Prevents credential compromise               | None | Low    | Verify all services restart with new secrets     |
| QW-2  | Generate unique JWT_SECRET for dev vs production                               | Prevents cross-env token forgery             | None | Low    | Register in dev, verify cannot auth in prod      |
| QW-3  | Enforce origin validation on widget chat/feedback endpoints                    | Blocks unauthorized API access               | None | Low    | curl without Origin header should fail           |
| QW-4  | Fix embedding single-flight race (dict.setdefault)                             | Prevents concurrent request deadlock         | None | Low    | Concurrent identical requests coalesce correctly |
| QW-5  | Narrow `except Exception` in sliding window rate limiter                       | Prevents rate limit bypass                   | None | Low    | Redis errors propagate correctly                 |
| QW-6  | Wrap `fetcher.close()` in try/finally in crawler                               | Prevents Chromium context leak               | None | Low    | Crawl exception no longer leaks browser          |
| QW-7  | Fix 9 failing test_provider_router.py tests                                    | Restores test coverage for provider failover | None | Low    | All provider router tests pass                   |
| QW-8  | Narrow broad `except Exception` blocks (6 modules)                             | Prevents silent error swallowing             | None | Low    | Targeted exceptions caught, others propagate     |
| QW-9  | Remove duplicate `detect_injection` call                                       | Saves ~2ms per request                       | None | None   | Tests still pass                                 |
| QW-10 | Log only token hash in verification email                                      | Prevents token leak in logs                  | None | Low    | Verify log output has hash, not URL              |

---

## P0 FIXES (Production Blockers — Must Fix Before Launch)

| #    | Fix                                     | Benefit               | Risk | Effort | Dependencies | Validation              |
| ---- | --------------------------------------- | --------------------- | ---- | ------ | ------------ | ----------------------- |
| P0-1 | Rotate ALL secrets + unique JWT per env | **CRITICAL security** | None | Medium | None         | Full auth flow test     |
| P0-2 | Enforce origin on widget chat/feedback  | **CRITICAL security** | None | Low    | None         | Widget + curl tests     |
| P0-3 | Fix embedding single-flight race        | Prevents deadlock     | None | Low    | None         | Concurrent request test |
| P0-4 | Narrow rate limit exception handling    | Prevents bypass       | None | Low    | None         | Redis failure test      |

---

## P1 FIXES (Important — Should Fix Before Production)

| #     | Fix                                         | Benefit                            | Risk | Effort | Dependencies | Validation                                  |
| ----- | ------------------------------------------- | ---------------------------------- | ---- | ------ | ------------ | ------------------------------------------- |
| P1-1  | Wrap keyword search in `asyncio.to_thread`  | Frees event loop (50-300ms)        | Low  | Low    | None         | Latency test with large corpus              |
| P1-2  | Add tenant ID to structured logs            | Enables tenant-scoped debugging    | Low  | Medium | None         | Check log output for tenant_id              |
| P1-3  | Add request ID to worker jobs               | Enables crawl-to-request tracing   | Low  | Low    | None         | Check worker logs for request_id            |
| P1-4  | Add Prometheus alerting rules               | Notifies on errors/latency         | Low  | Medium | None         | Alert fires on test error spike             |
| P1-5  | Add try/finally for crawler browser cleanup | Prevents memory leak               | None | Low    | None         | Exception during crawl test                 |
| P1-6  | Add database migration validation in CI     | Prevents broken migrations in prod | Low  | Medium | None         | CI rejects invalid migration                |
| P1-7  | Cache lexical corpus in retrieval cache     | Saves 20-200ms on cache hit        | Low  | Medium | None         | Retrieval cache hit latency test            |
| P1-8  | Add MongoDB query duration metrics          | Enables DB latency diagnosis       | Low  | Medium | None         | Check /metrics for mongo histogram          |
| P1-9  | Extend FakeRedis for provider router tests  | Restores test coverage             | None | Low    | None         | All provider tests pass                     |
| P1-10 | Narrow all broad `except Exception` blocks  | Prevents silent error swallowing   | Low  | Low    | None         | Unit tests for error paths                  |
| P1-11 | Scrub `extra` dict in sensitive data filter | Prevents secret leak in logs       | Low  | Low    | None         | Log with extra={"key":"secret"} is redacted |
| P1-12 | Add text indexes for regex search fields    | Prevents full collection scan      | Low  | Low    | None         | Search performance test                     |
| P1-13 | Refactor platform_stats to use $facet       | Eliminates N+1 queries             | Low  | Low    | None         | Admin dashboard load test                   |
| P1-14 | Add dashboard/widget read_only FS in prod   | Prevents file write on compromise  | Low  | Low    | None         | Docker security check                       |

---

## P2 OPTIMIZATIONS (Performance — Fix When Capacity Allows)

| #     | Fix                                           | Benefit                        | Risk   | Effort | Dependencies | Validation                        |
| ----- | --------------------------------------------- | ------------------------------ | ------ | ------ | ------------ | --------------------------------- |
| P2-1  | Extract pipeline stages from stream_answer    | Maintainability                | Low    | High   | None         | All chat tests pass               |
| P2-2  | Return RetrielResult dataclass from _retrieve | Maintainability                | Low    | Medium | None         | All chat tests pass               |
| P2-3  | Split deps.py into domain modules             | Reduce merge conflicts         | Low    | Medium | None         | All imports resolve               |
| P2-4  | Add Redis connection pool configuration       | Prevent thundering herd        | Low    | Low    | None         | Concurrency test                  |
| P2-5  | Add Redis health-check + lazy reconnect       | Recover from transient failure | Low    | Medium | None         | Redis restart during traffic test |
| P2-6  | Add embedding API rate limiter/semaphore      | Prevent cascade on rate limit  | Low    | Medium | None         | Rapid crawl fan-out test          |
| P2-7  | Add crawl memory pressure detection           | Prevent worker OOM             | Low    | Medium | None         | Large crawl memory test           |
| P2-8  | Fix widget idCounter collision                | Prevent state corruption       | None   | Low    | None         | Multi-instance test               |
| P2-9  | Fix widget listener cleanup                   | Prevent memory leak            | Low    | Medium | None         | Open/close/reopen test            |
| P2-10 | Fix SSE reconnect to only refresh on 401      | Prevent token rotation cascade | Low    | Low    | None         | SSE reconnect test                |
| P2-11 | Enforce UUID format for visitor_id            | Prevent rate limit rotation    | None   | Low    | None         | Rate limit test                   |
| P2-12 | Add word-boundary context truncation          | Prevent garbled context        | Low    | Low    | None         | Context quality test              |
| P2-13 | Add phrase matching to keyword search         | Improve retrieval precision    | Low    | High   | None         | Retrieval recall test             |
| P2-14 | Pre-compute inverted index for keywords       | Major latency improvement      | Medium | High   | None         | Keyword search latency test       |

---

## P3 CLEANUP (Low Priority — Fix During Maintenance Windows)

| #    | Fix                                          | Benefit                    | Risk | Effort |
| ---- | -------------------------------------------- | -------------------------- | ---- | ------ |
| P3-1 | Remove one-time migration scripts            | Reduce repo clutter        | None | Low    |
| P3-2 | Archive old audit artifacts in .audit-tmp    | Reduce noise               | None | Low    |
| P3-3 | Fix suppressHydrationWarning scope           | Better hydration debugging | None | Low    |
| P3-4 | Add aria-live to dashboard stat cards        | Better a11y                | None | Low    |
| P3-5 | Fix done_data dict duplication               | Reduce code duplication    | None | Low    |
| P3-6 | Extract shared _cosine_similarity            | Reduce code duplication    | None | Low    |
| P3-7 | Add crawl progress metrics                   | Better observability       | None | Low    |
| P3-8 | Document crawl_delay enforcement gap         | Compliance                 | None | Low    |
| P3-9 | Add tracking param coverage (fb_*, _ga, _gl) | Better deduplication       | None | Low    |

---

## PRIORITIZED EXECUTION ORDER

### Phase 1: Security Hardening (Days 1-2)

1. Rotate ALL secrets (QW-1)
2. Separate JWT secrets (QW-2)
3. Enforce widget origin (QW-3)
4. Fix rate limit exception (QW-5)
5. Narrow broad exceptions (QW-8)
6. Fix Stripe validation (SEC-C03)
7. Fix CORS policy (SEC-H04)
8. Fix Argon2 params (SEC-H02)

### Phase 2: Reliability (Days 3-4)

1. Fix embedding race condition (QW-4)
2. Fix crawler cleanup (QW-6)
3. Fix provider router tests (QW-7)
4. Wrap keyword search in thread (P1-1)
5. Add try/finally for fetcher (P1-5)

### Phase 3: Observability (Days 5-6)

1. Add tenant context to logs (P1-2)
2. Add request ID to workers (P1-3)
3. Add alerting rules (P1-4)
4. Add MongoDB metrics (P1-8)
5. Fix sensitive data filter (P1-11)

### Phase 4: Performance (Days 7-10)

1. Cache lexical corpus (P1-7)
2. Add text indexes (P1-12)
3. Refactor platform_stats (P1-13)
4. Add Redis pool (P2-4)
5. Add embedding rate limiter (P2-6)

### Phase 5: Architecture (Days 11-15)

1. Extract rag_service pipeline stages (P2-1)
2. Split deps.py (P2-3)
3. Add RetrielResult dataclass (P2-2)

### Phase 6: Cleanup (Ongoing)

- P3 items during maintenance windows
- Remove unused scripts after verification
- Archive old audit artifacts
