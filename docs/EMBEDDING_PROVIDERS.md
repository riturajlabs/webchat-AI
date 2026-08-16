# Embedding Providers & Fallback (ADR-009)

How document/query embeddings are produced, how the cloud fallback chain
works, and how to configure a provider.

## Overview

Embeddings are produced by a single **fallback chain**: if the primary
provider fails, the next one in `EMBEDDING_PROVIDER_ORDER` is tried, and the
first provider to return a valid response serves the request.

```
EMBEDDING_PROVIDER_ORDER=["gemini", "jina", "cohere"]
        |
   Gemini (primary, gemini-embedding-001)
        |   API timeout / quota / rate limit / auth failure / unreachable
        v
   Jina (jina-embeddings-v3, free tier)
        |   same failure classes
        v
   Cohere (embed-multilingual-v3.0)
```

Only **cloud** providers are supported. There is no local/Ollama provider, so
every embed requires at least one API key in the order.

## Why every provider must agree on one dimension

The MongoDB `$vectorSearch` index is built for exactly
`EMBEDDING_DIMENSIONS` vectors. If a fallback provider returned a different
length, every insert after the switch would corrupt the index.

| Provider | Model                     | Native dims | Used dims                              |
| -------- | ------------------------- | ----------- | -------------------------------------- |
| Gemini   | `gemini-embedding-001`    | 3072        | `output_dimensionality` (default 1024) |
| Jina AI  | `jina-embeddings-v3`      | 1024        | 1024 (fixed max)                       |
| Cohere   | `embed-multilingual-v3.0` | 1024        | 1024 (fixed max)                       |

`EMBEDDING_DIMENSIONS` defaults to **1024** so all three providers agree.
Gemini truncates to the configured value via `output_dimensionality`, Jina and
Cohere are fixed at 1024 (set `JINA_EMBEDDING_DIMENSIONS`/`COHERE_EMBEDDING_DIMENSIONS`
to match). The config validator (`_validate_embedding_config`) rejects a chain
where a listed provider's dimension differs from `EMBEDDING_DIMENSIONS`.

> Existing deployments that index 3072-dim Gemini vectors are unaffected: the
> Gemini client sends `output_dimensionality` only when the configured dimension
> is **not** 3072, so a 3072 configuration produces byte-identical requests.

The dimension is also enforced **at runtime**: every returned vector is checked
against `EMBEDDING_DIMENSIONS` before it is committed. A mismatch is a
configuration error — it raises immediately (clear message, no fallback) rather
than trying the next provider.

## API keys

Keys come from environment variables (`.env.development`, `.env.production`,
docker-compose). Keys are never logged.

| Provider | Env var          | Where to get it                                       | Free tier                   |
| -------- | ---------------- | ----------------------------------------------------- | --------------------------- |
| Gemini   | `GEMINI_API_KEY` | Google AI Studio `https://aistudio.google.com/apikey` | limited daily free quota    |
| Jina AI  | `JINA_API_KEY`   | Jina Console `https://jina.ai/`                       | free API key (rate-limited) |
| Cohere   | `COHERE_API_KEY` | Cohere Dashboard `https://dashboard.cohere.com/`      | trial/free tier             |

A provider listed in `EMBEDDING_PROVIDER_ORDER` **without** its key is skipped
**gracefully** (a warning is logged when the chain is built) and the next
provider is tried. A missing key never crashes the application.

## When the chain falls back

The chain moves to the next provider only on `EmbeddingUnavailableError`
— a transient or provider-side problem worth retrying elsewhere:

- API timeout / network/transport failure
- Rate limit (429) or quota exhausted (402)
- Authentication/authorization failure (401/403)
- Invalid or unparseable response

Everything else — e.g. a 5xx server error or an empty/mis-shaped payload — is an
`EmbeddingError` and **does not** trigger a fallback, because the same failure
would recur on the next provider. Non-`EmbeddingError` exceptions propagate
without fallback.

## Logging

- `INFO` — `Embedding provider selected: <name>` (first successful provider)
- `WARNING` — `<name> embedding failed (<error>); switching to <next>`
- `WARNING` — `<name> embedding failed (<error>); no providers left`
- `ERROR` — `All embedding providers failed (<last error>)`

Structured timing is logged as `ai_embedding_request` when
`LOG_PERF_TIMING`/`perf_timing_log_enabled` is on.

## Changing providers

To change priority, edit `EMBEDDING_PROVIDER_ORDER` in the environment files
(e.g. `["jina", "gemini", "cohere"]`). To add a cloud provider, implement the
`EmbeddingClient` protocol (`backend/services/knowledge/embedding.py`), place it
under `backend/ai/providers/`, register it in `backend/ai/registry.py` with its
`required_key`, and add matching env vars. Keep its dimension equal to
`EMBEDDING_DIMENSIONS`.

## Related

- `backend/services/knowledge/embedding.py` — `EmbeddingClient` protocol,
  `ensure_vector_dimensions`, the Gemini client
- `backend/ai/providers/jina.py`, `backend/ai/providers/cohere.py` — cloud clients
- `backend/ai/registry.py` — provider registration & keyless skip
- `backend/ai/router.py` — `FallbackEmbeddingClient`, dimension gate, logging
- `backend/core/config.py` — provider/dimension config and validation
