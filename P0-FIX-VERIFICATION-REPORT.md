# P0 Fix Verification Report

**Date:** 2026-08-21 · **Scope:** verification of the P0 fixes documented in `AI-RAG-P0-FIX-REPORT.md` (audit BUG-1 and BUG-2 from `AI-RAG-COMPLETE-AUDIT-REPORT.md`) · No code was modified during this verification pass.

---

## Verification commands

| Command                    | Result                                                                                                               |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `ruff check tests/ --fix`  | All checks passed! (nothing to fix)                                                                                  |
| `uv run pytest tests/ -q`  | **1490 passed, 3 skipped**, 3 warnings (pre-existing, unrelated: `test_gemini_client.py` coroutine ResourceWarnings) |
| `uv run ruff check tests/` | All checks passed!                                                                                                   |
| `uv run mypy backend/`     | Success: no issues found in 183 source files                                                                         |

---

## 1. Original bug

### BUG-1 (P0 — retrieval correctness): mixed embedding space in one website corpus

During ingestion, when the primary embedding provider (Gemini) failed or was quota-limited, the provider fallback chain silently switched to Jina/Cohere. Because all providers were configured with matching dimensions (1024), the dimension gate passed and chunks were stored stamped with the _fallback_ provider's identity. A single website ended up containing vectors from two incompatible embedding spaces.

**Confirmed production evidence:** website `b57841fb…` (tenant `d98aefd7…`) held 67 chunks — 54 stamped `gemini`, 13 stamped `jina`. The `$vectorSearch` identity filter excluded the 13 jina chunks from every gemini query, making that page ("Test card numbers | Stripe Documentation") permanently unanswerable — a guaranteed false "could not find" fallback for card-testing questions.

### BUG-2 (P0 — availability/correctness of the empty-result path): broken Atlas search probe

`_probe_search_support` probed via `db.command({"listSearchIndexes": ...})`, which fails on the production deployment (`command not found (code 59)` / pymongo client-side `'list' object has no attribute 'update'`), while the `$listSearchIndexes` _aggregation stage_ works and reports the index READY/queryable. The probe therefore always returned `False`.

**Consequence:** every legitimate empty `$vectorSearch` result degraded to the O(N) brute-force cosine scan ("Atlas Search is unavailable… falling back to exact cosine scan" observed live). Combined with BUG-1, the brute-force scan raised `EmbeddingCompatibilityError` mid-scan and surfaced an error to users instead of a graceful "not found".

---

## 2. Root cause

- **BUG-1:** the ingestion worker (`backend/workers/app.py::startup`) injected the full cross-provider chain (`build_embedding_fallback()`). `FallbackEmbeddingClient.embed` (backend/ai/router.py) advances to the next provider on any `EmbeddingError`, and `KnowledgeProcessor._build_chunks` stamps stored chunks with whichever provider served. Dimension-equality validation in config could not catch this: equal dimensions ≠ equal vector spaces.
- **BUG-2:** the probe used the `listSearchIndexes` **command** form, which is rejected by the production host/driver combination, instead of the `$listSearchIndexes` **aggregation stage** which works.

---

## 3. Files changed

### BUG-1 fix

| File                                                 | Change                                                                                                                                                                                                                                                               |
| ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/ai/registry.py`                             | New `build_ingestion_embedding_client()`: resolves `EMBEDDING_PROVIDER_ORDER` via the existing chain builder (keyless providers skipped as before) but returns only the first available provider; raises `ProviderConfigurationError` at build time if none is keyed |
| `backend/workers/app.py`                             | `startup` injects `build_ingestion_embedding_client()` — ingestion physically cannot switch embedding spaces                                                                                                                                                         |
| `backend/repositories/knowledge_chunk_repository.py` | New `has_incompatible_identity(tenant_id, website_id, identity)` on Protocol + Mongo impl: projected `_id`-only `$or` query over the four identity fields; legacy unstamped chunks count as incompatible                                                             |
| `backend/services/knowledge/processor.py`            | Quarantine guard in `process_document` after embedding, before any write: foreign-identity corpus → permanent failure (`EmbeddingIdentityConflict`, reason `embedding_identity_conflict`), corpus untouched, structured log + audit record                           |

Same-provider retry required no code change: client batch retries with backoff/jitter + document-level deferred ARQ retries (5s/30s/180s) already retry the same provider; exhausted retries land in the dashboard failed list (= quarantine).

### BUG-2 fix

| File                                     | Change                                                                                                                                                                                                                                                                               |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `backend/repositories/vector/mongodb.py` | `_probe_search_support` rewritten to use the `$listSearchIndexes` aggregation stage; index usable when it indexes path `embedding` and (when reported) `status == "READY"` and `queryable != false`; any probe failure still returns `False` preserving graceful brute-force degrade |

### Test infrastructure

| File                                         | Change                                                                                                                                                                            |
| -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/fakes.py`                             | `FakeKnowledgeChunkRepository.has_incompatible_identity` mirroring Mongo semantics                                                                                                |
| `tests/test_vector_mongodb.py`               | `FakeCollection.aggregate` handles `$listSearchIndexes` (records pipelines, per-stage `probe_error`); `_FakeDb.command` now always raises, proving the command form is never used |
| `tests/test_ingestion_embedding_identity.py` | **New file** — ingestion identity regression tests                                                                                                                                |
| `tests/test_knowledge_processor.py`          | Quarantine guard tests appended                                                                                                                                                   |

Deliberately unchanged: chat-path query embedding keeps its fallback chain (queries are never stored); prompts, retrieval algorithm, LLM providers, thresholds, and database schema untouched.

---

## 4. Tests passed

Full suite: **1490 passed, 3 skipped** (skips pre-existing). Regression tests added for the two P0 bugs:

**Provider fallback cannot create mixed identities** (`tests/test_ingestion_embedding_identity.py`):

- `test_ingestion_gets_only_the_primary_provider`
- `test_ingestion_skips_keyless_primary_but_stays_single_provider`
- `test_ingestion_without_any_available_provider_fails_fast`
- `test_primary_failure_never_switches_embedding_space`
- `test_recovered_primary_serves_with_its_own_identity`

**Same website cannot contain multiple embedding identities** (`tests/test_knowledge_processor.py`):

- `test_website_with_foreign_identity_quarantines_ingestion`
- `test_matching_identity_processes_normally`
- `test_legacy_unstamped_chunks_block_ingestion`

**Probe / empty vector search** (`tests/test_vector_mongodb.py`):

- `test_probe_detects_ready_vector_index` (READY detection via the aggregation stage while the command form raises)
- `test_probe_ignores_index_not_ready`
- `test_probe_ignores_unqueryable_index`
- `test_probe_failure_degrades_to_brute_force`
- `test_silent_zero_kept_empty_on_search_capable_deployment` (empty-result regression: READY index + zero hits → `[]`, never brute force)
- `test_falls_back_to_brute_force_when_vector_search_silently_returns_zero` (no index → brute-force degrade preserved)

Static checks: `ruff check tests/` clean · `mypy backend/` clean (183 files).

---

## 5. Production migration required

The code fixes prevent **new** mixing but do not heal existing data. One operational step is required:

1. **Re-index the affected website** (tenant `d98aefd7…`, website `b57841fb…`): delete its `knowledge_chunks` (13 jina-stamped chunks on "Test card numbers | Stripe Documentation") and reprocess the website so all chunks share one embedding identity.
   - Until done, card-testing questions on that page keep false-falling back (the 13 chunks remain invisible to gemini queries).
   - Conveniently, once chunks are wiped, the new quarantine guard no longer blocks re-ingestion.
2. **No schema migration** is needed — the identity fields already exist on `knowledge_chunks`.
3. **Future provider migrations** (changing `EMBEDDING_PROVIDER_ORDER` after a corpus exists): new ingestions will quarantine until the website is re-indexed under the new identity. This is intentional (loud failure over silent corruption). Trigger a full re-index per website when switching providers.

---

## 6. Remaining risks

1. **Existing mixed data until re-index (operational, high priority):** the 13 jina chunks stay invisible to gemini queries until the website above is re-indexed.
2. **Guard is read-before-write, not transactional:** two workers processing different documents of the same website concurrently under _different_ identities could theoretically interleave between check and insert. With the single-provider worker client this requires a config change mid-fan-out; a unique partial index on `(tenant_id, website_id, embedding_provider)` would close it fully (schema change, out of scope).
3. **Probe result cached per repository instance:** an Atlas index created later is only detected on process restart (pre-existing behavior, unchanged).
4. **Chat-path provider switch (audit BUG-5, P1) remains open:** a chat-side embedding fallback switch can produce queries whose identity misses the corpus filter for up to the embed-cache TTL (3600s). Does not affect ingestion correctness; tracked separately in the audit's P1 list.
5. **Single-provider ingestion availability:** if the primary provider has a prolonged outage, ingestion quarantines documents (visible in the dashboard failed list) rather than degrading to another space; recovery requires the provider to return or an operator-driven provider switch + re-index.
