# AI RAG Embedding Compatibility Report

## 1. Audit Result

### Ingestion flow

1. The knowledge processor chunks crawled document text.
2. The configured embedding fallback client generates the batch.
3. The fallback client records which provider actually succeeded.
4. Each stored `KnowledgeChunk` now persists:
   - `embedding_provider`
   - `embedding_model`
   - `embedding_dimensions`
   - `embedding_version`
5. A batch with any malformed vector dimension fails before insertion.

### Query flow

1. The chat service embeds the normalized question.
2. The active provider identity is carried with the query vector, including embedding-cache entries.
3. MongoDB Atlas `$vectorSearch` receives tenant, website, and all four embedding identity filters.
4. Returned chunks are validated against the active query identity.
5. Legacy or incompatible chunks are rejected with `EMBEDDING_INCOMPATIBLE`; they are never silently compared with the query vector.
6. The local brute-force fallback applies the same identity validation.

## 2. Compatibility Contract

Two vectors are compatible only when all four values match exactly:

```text
provider + model + dimensions + version
```

Equal dimensions alone are insufficient. Gemini, Jina, and Cohere vectors with 1024 dimensions still represent different vector spaces and must not be compared.

## 3. Implemented Changes

- Added the shared `EmbeddingIdentity` value object.
- Added identity properties to Gemini, Jina, Cohere, mock, and fallback embedding clients.
- Added identity fields to `KnowledgeChunk` persistence.
- Added configurable `EMBEDDING_VERSION` with default version `1`.
- Persisted the identity of the provider that actually served ingestion.
- Added identity to embedding and retrieval cache payloads.
- Added identity filters to Atlas vector search.
- Added post-search and brute-force compatibility validation.
- Added clear `EMBEDDING_INCOMPATIBLE` failures with re-index guidance.
- Added Atlas filter-field requirements to the deployment documentation.

## 4. Existing Vector Migration Plan

Existing chunks created before this change do not have reliable identity fields. They must be treated as incompatible.

1. Stop or disable chat traffic for the affected website, or leave it in fail-safe mode.
2. Select one embedding provider, model, dimensions, and version for the corpus. Do not use cross-space fallbacks for the same corpus unless each result is identity-tagged and separately filtered.
3. Ensure the Atlas `default` vector index has:
   - vector field `embedding`
   - `numDimensions` equal to `EMBEDDING_DIMENSIONS` (currently 1024)
   - similarity `cosine`
   - filter fields for tenant, website, provider, model, dimensions, and version
4. Reprocess every document for the website. The processor deletes stale chunks and writes fresh vectors with all identity fields.
5. Verify that every chunk has the selected four-field identity and that no old chunks remain.
6. Run representative relevant and unrelated retrieval checks, including the database-password negative query.
7. Re-enable traffic and monitor compatibility errors, raw vector diagnostics, confidence metrics, and retrieval quality.

Do not backfill identity fields onto old vectors without re-embedding them. That would falsely label unknown vector spaces as compatible.

## 5. Tests Added

- Same provider/model/version/dimension is accepted.
- Different embedding model/provider is rejected.
- Dimension mismatch is rejected.
- Ingestion persists identity on every generated chunk.
- Query caches preserve identity together with vectors.
- Atlas and brute-force retrieval paths apply compatibility filtering/validation.

## 6. Validation

- `uv run pytest tests/`: run after this report change
- `uv run ruff check backend/`: run after this report change
- `uv run mypy backend/`: run after this report change

## 7. Operational Status

Embedding-space mixing is now fail-safe in application code. Production remains dependent on completing the existing-vector migration and configuring the Atlas filter fields before enabling retrieval against the migrated corpus.
