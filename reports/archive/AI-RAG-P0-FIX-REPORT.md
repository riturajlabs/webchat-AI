# AI RAG P0 Fix Report — BUG-1 & BUG-2

**Date:** 2026-08-21 · **Scope:** P0 fixes only, per `AI-RAG-COMPLETE-AUDIT-REPORT.md` · **Mode:** minimal-change implementation, no architecture/prompt/provider/schema changes

---

## Summary

| Bug                                     | Verdict                                                                                             |
| --------------------------------------- | --------------------------------------------------------------------------------------------------- |
| BUG-1 (P0, mixed embedding space)       | **FIXED** — ingestion is pinned to a single embedding provider and quarantines on identity conflict |
| BUG-2 (P0, broken search-support probe) | **FIXED** — probe uses the `$listSearchIndexes` aggregation stage with READY/queryable detection    |

Verification: `uv run pytest tests/` → **1490 passed, 3 skipped** · `uv run ruff check backend/` → clean · `uv run mypy backend/` → clean (183 files).

---

## Files changed

### P0-1 — Mixed embedding space (BUG-1)

1. **`backend/ai/registry.py`** — new `build_ingestion_embedding_client()`.
   Resolves `EMBEDDING_PROVIDER_ORDER` through the existing `ProviderRegistry.build_embedding_chain` (keyless providers skipped exactly as before) but returns **only the first available provider**. Raises `ProviderConfigurationError` at build time when no keyed provider exists (fail-fast instead of a mid-crawl surprise).
2. **`backend/workers/app.py`** (`startup`) — the ingestion worker now injects `build_ingestion_embedding_client()` instead of the full `FallbackEmbeddingClient` chain. Ingestion physically cannot switch embedding spaces anymore.
3. **`backend/repositories/knowledge_chunk_repository.py`** — new `has_incompatible_identity(tenant_id, website_id, identity)` on the `KnowledgeChunkRepository` Protocol and the Mongo implementation: a projected (`_id`-only), tenant/website-scoped `find_one` with `$or` over the four identity fields (`embedding_provider/model/dimensions/version`). Legacy chunks with missing stamps match `$ne` and therefore count as incompatible.
4. **`backend/services/knowledge/processor.py`** (`process_document`) — quarantine guard after embedding, **before any write**: if the website already holds chunks with a different embedding identity, the document fails permanently (`EmbeddingIdentityConflict`, `retryable=False`, reason `embedding_identity_conflict`), the existing corpus is left untouched, and a structured failure + audit record is emitted. No vectors from a second space can ever be stored.

   Retry-same-provider semantics required no code change; they already exist and are now the only path:
   - provider-level batch retries with exponential backoff + jitter (`GoogleEmbeddingClient._embed_batch`),
   - document-level retry schedule via `on_retry` (5s/30s/180s deferred ARQ jobs),
   - exhausted retries → permanent failure in the dashboard's failed list (= quarantine).

### P0-2 — Atlas search availability probe (BUG-2)

5. **`backend/repositories/vector/mongodb.py`** (`_probe_search_support`) — replaced the broken `db.command({"listSearchIndexes": ...})` call with the **`$listSearchIndexes` aggregation stage** on `knowledge_chunks`. An index counts as usable when it indexes the `embedding` path and — when the server reports them — has `status == "READY"` and `queryable != false`. Any probe failure still returns `False`, preserving the graceful brute-force degrade for community MongoDB / unavailable search tiers. The empty-result logic in `similarity_search` (empty + index → genuine no-match; empty + no index → exact cosine scan) is unchanged.

### Test infrastructure

6. **`tests/fakes.py`** — `FakeKnowledgeChunkRepository` implements `has_incompatible_identity` (mirrors the Mongo query semantics in memory).
7. **`tests/test_vector_mongodb.py`** — `FakeCollection.aggregate` now understands the `$listSearchIndexes` stage (records every pipeline, supports per-stage `probe_error`); `_FakeDb.command` now _always_ raises, proving the probe never depends on the broken command form.

---

## Bugs fixed

- **BUG-1:** Gemini→Jina/Cohere failover during ingestion could stamp one website with two vector identities (production evidence: 54 gemini + 13 jina chunks on website `b57841fb…`; the 13 jina chunks were invisible to every gemini query). Ingestion now uses exactly one provider per process, retries that same provider on failure, and refuses (quarantines) any write that would mix identities within a website corpus.
- **BUG-2:** `_probe_search_support` always returned `False` because the `listSearchIndexes` command fails on the production deployment, so every legitimate empty `$vectorSearch` result degraded to the O(N) brute-force scan (and, combined with BUG-1, surfaced `EmbeddingCompatibilityError` to users). The probe now uses the working aggregation stage and correctly recognizes the READY/queryable vector index, so an empty result on a search-capable cluster stays a graceful "no match".

## Deliberately unchanged

- Chat-path query embedding keeps its fallback chain (`api/deps.py`) — queries are never stored, so no mixed-space risk; changing it would alter retrieval behavior outside this fix's scope.
- Prompts, retrieval algorithm, LLM providers, thresholds, database schema: untouched.
- The affected production website still needs a one-time re-index (delete chunks for the website → reprocess) to clear the existing 13 jina chunks; this is an operational step, not a code change.

---

## Tests added

### Regression: provider fallback cannot create mixed identities (`tests/test_ingestion_embedding_identity.py`, new)

- `test_ingestion_gets_only_the_primary_provider` — fully keyed multi-provider order still yields ONE provider for ingestion (never a `FallbackEmbeddingClient`).
- `test_ingestion_skips_keyless_primary_but_stays_single_provider` — keyless primary skipped at build; next available becomes THE consistent space.
- `test_ingestion_without_any_available_provider_fails_fast` — no keyed provider → boot-time `ProviderConfigurationError`.
- `test_primary_failure_never_switches_embedding_space` — the BUG-1 scenario: primary fails, fallback provider is never called, error surfaces for same-provider retry.
- `test_recovered_primary_serves_with_its_own_identity` — transient failure then success keeps one consistent `embedding_identity`.

### Regression: same website cannot contain multiple embedding identities (`tests/test_knowledge_processor.py`)

- `test_website_with_foreign_identity_quarantines_ingestion` — foreign-stamped chunk in the website → document quarantined (`embedding_identity_conflict`, permanent, retry budget untouched), corpus byte-identical, failure audited.
- `test_matching_identity_processes_normally` — matching identity (including the document's own stale chunks on rebuild) processes normally.
- `test_legacy_unstamped_chunks_block_ingestion` — pre-stamp-era chunks without identity fields also block ingestion instead of silently joining a new space.

### Regression: probe + empty vector search (`tests/test_vector_mongodb.py`)

- `test_probe_detects_ready_vector_index` — READY/queryable `embedding` index detected via the `$listSearchIndexes` **stage** while the command form raises; asserts the recorded pipeline is exactly `[{"$listSearchIndexes": {}}]`.
- `test_probe_ignores_index_not_ready` — `status: "BUILDING"` → no support.
- `test_probe_ignores_unqueryable_index` — `queryable: false` → no support.
- `test_probe_failure_degrades_to_brute_force` — even the stage failing degrades gracefully to the exact cosine scan.
- `test_silent_zero_kept_empty_on_search_capable_deployment` (updated) — **empty-result regression**: zero `$vectorSearch` hits on a cluster with a READY index returns `[]` (never brute force).
- `test_falls_back_to_brute_force_when_vector_search_silently_returns_zero` (updated) — no index reported → brute-force degrade preserved.

---

## Remaining risks

1. **Production data still mixed (operational):** the guard prevents _new_ mixing, but website `b57841fb…` still carries 13 jina chunks. Re-index that website; until then, "Test card numbers" queries keep false-falling back.
2. **Identity change between runs is a deliberate migration:** if `EMBEDDING_PROVIDER_ORDER` is changed after a corpus exists, new ingestions quarantine until the website is re-indexed under the new identity. This is intentional (loud failure over silent corruption) but means provider migrations require a re-index step; there is no automated re-index workflow yet.
3. **Guard is read-before-write, not transactional:** two workers processing different documents of the same website concurrently with _different_ identities could theoretically interleave between check and insert. With the single-provider worker client this requires a config change mid-fan-out; a unique partial index on `(tenant_id, website_id, embedding_provider)` would close it fully (schema change, out of scope).
4. **Probe caching:** `_search_supported` is cached per repository instance; an index created later is only picked up on process restart (pre-existing behavior, unchanged).
5. **Chat-path provider switch (audit BUG-5)** remains open: a chat-side fallback switch can still produce queries whose identity misses the corpus filter for up to the embed-cache TTL. Unrelated to ingestion correctness; tracked as P1 in the audit.
