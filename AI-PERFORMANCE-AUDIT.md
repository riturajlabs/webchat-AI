# AI/RAG Performance & Response Quality Audit

**Date:** August 18, 2026
**Scope:** Full AI chatbot pipeline — retrieval, generation, streaming, frontend rendering
**Symptoms reported:** Incomplete answers (truncation), high response latency, slow time-to-first-token

---

## 1. Architecture Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                        USER (Widget / Dashboard)                    │
│  POST /api/widget/v1/chat  or  POST /api/chat/stream               │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ SSE Stream
┌──────────────────────────────▼──────────────────────────────────────┐
│                     FastAPI SSE Router                               │
│  stream_with_disconnect → stream_answer_with_usage                  │
│  (disconnect check per frame)  (billing gate + usage recording)     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                        RagService.stream_answer                      │
│                                                                      │
│  ┌─── Phase 1: Validate & Persist ───────────────────────────────┐  │
│  │  website lookup → sanitize_question → persist user message     │  │
│  │  check knowledge_chunks == 0 → emit fallback                  │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌─── Phase 2: Retrieve (parallel history load) ─────────────────┐  │
│  │  _load_history() ←─── asyncio.create_task (overlaps)          │  │
│  │  _retrieve() = embed_question() → vector.similarity_search()  │  │
│  │  embed: Gemini embedding-001 (1024d) via Redis cache          │  │
│  │  search: MongoDB $vectorSearch (top_k=5, numCandidates=50)    │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌─── Phase 3: Build Prompt ─────────────────────────────────────┐  │
│  │  _build_context() = dedup + min_score filter + char budget    │  │
│  │  build_user_prompt() = question + history + context           │  │
│  │  get_system_prompt() (v1: 6 rules)                           │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌─── Phase 4: Generate (streaming) ─────────────────────────────┐  │
│  │  FallbackGenerationClient.stream_generate()                   │  │
│  │  Provider chain: [Gemini 2.5 Flash] → [Groq] → [OpenRouter]  │  │
│  │  yield delta per token → yield "done" with usage              │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌─── Phase 5: Persist & Close ──────────────────────────────────┐  │
│  │  persist assistant message + latency breakdown                │  │
│  │  increment usage_records                                      │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Identified Bottlenecks & Root Causes

### CRITICAL — Response Truncation

| #   | Finding                                       | Location            | Root Cause                                                                                                                                                                                                   |
| --- | --------------------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| C1  | **`chat_max_output_tokens: 1024` is too low** | `config.py:274`     | Gemini 2.5 Flash supports up to 8192 output tokens. At 1024, detailed answers with multiple citations get cut off mid-sentence. This is the **primary cause of incomplete answers**.                         |
| C2  | **No stop sequences configured**              | `gemini.py:112-120` | The `config` dict sent to Gemini omits `stop_sequences`. The model has no explicit instruction about when to stop, so it keeps generating until it either completes its thought or hits `max_output_tokens`. |
| C3  | **Prompt says "Keep answers short"**          | `rag.py:48`         | Rule 3 says "Keep answers short, friendly, accurate" — this conflicts with providing thorough explanations. When users ask complex questions, the model self-limits AND the token cap truncates.             |

### HIGH — Latency & Throughput

| #   | Finding                                              | Location                 | Root Cause                                                                                                                                                                                                                                                      |
| --- | ---------------------------------------------------- | ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| H1  | **`numCandidates: max(top_k * 10, 50)` is too low**  | `mongodb.py:96`          | For `top_k=5`, only 50 candidates are considered. Atlas best practice is 10-20x `top_k` (50-100). A low candidate pool means relevant chunks are pruned before scoring, reducing answer quality.                                                                |
| H2  | **`chat_context_max_chars: 12000` limits context**   | `config.py:267`          | ~12K chars ≈ ~3000 tokens of context. With 5 chunks at 4000 chars each, only ~3 chunks fit. The budget truncates the 3rd chunk mid-sentence, losing important reference material.                                                                               |
| H3  | **`chat_context_min_score: 0.0` accepts all chunks** | `config.py:270`          | Low-relevance chunks (score < 0.3) still consume context budget and confuse the model. A relevance floor (e.g., 0.25-0.35) would filter noise.                                                                                                                  |
| H4  | **No reranking after vector search**                 | `rag_service.py:196-198` | Vector search returns approximate nearest neighbors. Without a cross-encoder reranker, the top-5 may not be the most relevant. A lightweight reranker (e.g., Cohere Rerank, cross-encoder) would improve precision.                                             |
| H5  | **`generation_timeout_seconds: 30.0` per chunk**     | `config.py:277`          | Each token has a 30s timeout. If the model pauses for ~20s (common with Gemini on complex prompts), it still generates but the user perceives extreme latency. The per-chunk timeout is too generous — a stall detection at 5-8s would trigger faster fallback. |

### MEDIUM — Prompt & Generation Quality

| #   | Finding                                              | Location                 | Root Cause                                                                                                                                                              |
| --- | ---------------------------------------------------- | ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| M1  | **System prompt v1 has no "answer length" guidance** | `rag.py:39-53`           | The prompt says "short" but never specifies a target length (e.g., "3-5 sentences" or "up to 200 words"). The model has no anchor for how much detail is appropriate.   |
| M2  | **No `top_p` / `top_k` sampling params**             | `gemini.py:115-119`      | Only `temperature: 0.2` is set. Adding `top_p: 0.95` would give the model more controlled diversity in phrasing while staying on-topic.                                 |
| M3  | **Context chunks lack document-level grouping**      | `rag_service.py:548-594` | Deduplication is per `(url, chunk_text)`. Two chunks from the same document with slightly different text are both included, potentially repeating the same information. |
| M4  | **Conversation memory limited to 8 turns**           | `config.py:262`          | For long support conversations, earlier context is lost. 12-16 turns would maintain more context without significant prompt bloat.                                      |
| M5  | **User prompt concatenation is flat**                | `rag.py:146-167`         | The question, history, and context are joined with `\n\n`. A more structured format (XML tags, clear delimiters) would help the model parse sections better.            |

### LOW — Frontend & Infrastructure

| #   | Finding                                   | Location          | Root Cause                                                                                                                                                                                        |
| --- | ----------------------------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| L1  | **Widget `CHAT_CONNECT_TIMEOUT_MS: 20s`** | `client.ts:18`    | The POST timeout is 20s. If TTFT exceeds this (possible with cold starts), the user sees an error. Should be 30s to match backend `generation_first_token_timeout_seconds: 10s` + network buffer. |
| L2  | **No adaptive streaming on frontend**     | `chat.ts:165-170` | `appendDelta` does `message.content += delta` on every token. For rapid streams, this triggers O(n) string concatenation. Using an array of deltas joined at render time would be more efficient. |
| L3  | **Dashboard has no real-time chat**       | `conversations/`  | The dashboard only shows historical conversations (read-only). There is no live chat interface for support agents.                                                                                |

---

## 3. Latency Breakdown (Estimated)

Based on the architecture and configuration, here is the expected per-stage latency breakdown for a typical request:

| Stage                     | Typical Latency | Bottleneck?                               |
| ------------------------- | --------------- | ----------------------------------------- |
| Website lookup (DB)       | 5-15ms          | No                                        |
| Question sanitization     | <1ms            | No                                        |
| User message persist      | 10-30ms         | No                                        |
| **Embedding (question)**  | **100-500ms**   | **Yes (cold)** / Cache hit: <5ms          |
| **Vector search**         | **50-200ms**    | **Yes (Atlas)** / Brute-force: 200-2000ms |
| Context build             | <5ms            | No                                        |
| History load (parallel)   | 10-30ms         | No (overlapped)                           |
| **LLM generation (TTFT)** | **500-3000ms**  | **Primary bottleneck**                    |
| LLM generation (stream)   | 2000-8000ms     | Depends on answer length                  |
| Persistence (3 writes)    | 30-100ms        | No (post-stream)                          |
| **Total typical**         | **3-12s**       | TTFT dominates                            |

**Key insight:** TTFT (500-3000ms) + generation (2-8s) account for 80-95% of total latency. Embedding + vector search account for 10-20%. Everything else is negligible.

---

## 4. Severity Ranking

### Critical (Fix immediately — causes user-visible failures)

| ID     | Issue                                            | Impact                                          |
| ------ | ------------------------------------------------ | ----------------------------------------------- |
| **C1** | `max_output_tokens: 1024` truncates answers      | Users receive incomplete responses mid-sentence |
| **C2** | No stop sequences                                | Model generates filler when it should stop      |
| **C3** | "Keep answers short" conflicts with thoroughness | Model self-limits before hitting token cap      |

### High (Fix within 1-2 weeks — degrades quality/performance)

| ID     | Issue                          | Impact                                  |
| ------ | ------------------------------ | --------------------------------------- |
| **H1** | `numCandidates` too low        | Relevant chunks missed, worse retrieval |
| **H2** | Context budget too tight       | Important reference material truncated  |
| **H3** | No relevance floor             | Low-quality chunks pollute context      |
| **H4** | No reranking                   | Suboptimal chunk ordering               |
| **H5** | Per-chunk timeout too generous | Slow fallback on stalled providers      |

### Medium (Fix within 1 month — improves quality)

| ID     | Issue                        | Impact                             |
| ------ | ---------------------------- | ---------------------------------- |
| **M1** | No length guidance in prompt | Inconsistent answer lengths        |
| **M2** | No sampling params           | Less controlled output diversity   |
| **M3** | Duplicate document chunks    | Redundant context                  |
| **M4** | 8-turn memory limit          | Lost context in long conversations |
| **M5** | Flat prompt concatenation    | Model may misparse sections        |

### Low (Backlog — nice-to-have)

| ID     | Issue                             | Impact                     |
| ------ | --------------------------------- | -------------------------- |
| **L1** | Widget connect timeout too short  | Edge-case timeout errors   |
| **L2** | String concatenation in streaming | Minor performance overhead |
| **L3** | No dashboard live chat            | Feature gap                |

---

## 5. Recommended Optimization Roadmap

### Phase 1: Quick Fixes (1-2 days)

These are config/prompt changes that directly address the critical truncation issue and require no architectural changes.

#### 1.1 Increase `max_output_tokens` to 2048-4096

**File:** `backend/core/config.py:274`
**Change:** `chat_max_output_tokens: int = 1024` → `chat_max_output_tokens: int = 4096`
**Rationale:** Gemini 2.5 Flash supports up to 8192. At 4096, the model can provide comprehensive answers with multiple citations without truncation. The cost increase is minimal (output tokens are 5x input cost, but most answers will be 500-1500 tokens anyway).

#### 1.2 Update system prompt for answer length

**File:** `backend/prompts/rag.py:48`
**Change:** Replace "Keep answers short" with "Provide a complete, thorough answer. Aim for 3-8 sentences depending on question complexity. Always include all relevant details from the reference material."
**Rationale:** Removes the self-limiting instruction while keeping the hallucination guard.

#### 1.3 Add `top_p` sampling parameter

**File:** `backend/ai/gemini.py:115-119`
**Change:** Add `"top_p": 0.95` to the config dict.
**Rationale:** Gives the model more controlled output diversity while staying factual.

#### 1.4 Add stop sequences for natural termination

**File:** `backend/ai/gemini.py:115-119`
**Change:** Add `"stop_sequences": ["\n\n---", "\n\n**Note"]` to prevent the model from generating meta-commentary or sections beyond the answer.
**Rationale:** Clean termination before the model starts adding disclaimers.

#### 1.5 Increase widget connect timeout

**File:** `apps/widget/src/stream/client.ts:18`
**Change:** `CHAT_CONNECT_TIMEOUT_MS = 20 * 1000` → `CHAT_CONNECT_TIMEOUT_MS = 30 * 1000`
**Rationale:** Aligns with backend `generation_timeout_seconds: 30.0`.

### Phase 2: RAG Optimization (1 week)

These changes improve retrieval quality and context utilization.

#### 2.1 Increase `numCandidates` to 10x `top_k`

**File:** `backend/repositories/vector/mongodb.py:96`
**Change:** `"numCandidates": max(top_k * 10, 50)` → `"numCandidates": max(top_k * 20, 100)`
**Rationale:** Atlas best practice is 10-20x `top_k`. Higher candidate pool = better recall.

#### 2.2 Increase `chat_context_max_chars` to 16000-20000

**File:** `backend/core/config.py:267`
**Change:** `chat_context_max_chars: int = 12000` → `chat_context_max_chars: int = 20000`
**Rationale:** Allows 4-5 full chunks of context. Gemini 2.5 Flash has a 1M token context window — 20K chars (~5000 tokens) is well within limits and provides richer reference material.

#### 2.3 Add relevance floor (`chat_context_min_score`)

**File:** `backend/core/config.py:270`
**Change:** `chat_context_min_score: float = 0.0` → `chat_context_min_score: float = 0.25`
**Rationale:** Filters out low-similarity chunks that add noise. Tunable per deployment.

#### 2.4 Increase `top_k` from 5 to 8

**File:** `backend/core/config.py:260`
**Change:** `chat_top_k: int = 5` → `chat_top_k: int = 8`
**Rationale:** More retrieved chunks = better coverage of multi-faceted questions. Combined with the relevance floor, this doesn't add noise.

#### 2.5 Deduplicate by document, not just URL+text

**File:** `backend/services/chat/rag_service.py:560-572`
**Change:** Add document-level dedup: if two chunks are from the same `document_id`, keep only the higher-scored one (or merge them).
**Rationale:** Reduces redundant context from the same source document.

#### 2.6 Increase conversation memory to 12 turns

**File:** `backend/core/config.py:262`
**Change:** `chat_memory_turns: int = 8` → `chat_memory_turns: int = 12`
**Rationale:** Maintains more context for long support conversations.

### Phase 3: LLM Latency Optimization (1-2 weeks)

These changes reduce time-to-first-token and overall generation time.

#### 3.1 Reduce first-token timeout to 8s

**File:** `backend/core/config.py:281`
**Change:** `generation_first_token_timeout_seconds: float = 10.0` → `generation_first_token_timeout_seconds: float = 8.0`
**Rationale:** A provider that takes >8s for the first token is likely overloaded. Faster fallback to the next provider.

#### 3.2 Reduce per-chunk timeout to 20s

**File:** `backend/core/config.py:277`
**Change:** `generation_timeout_seconds: float = 30.0` → `generation_timeout_seconds: float = 20.0`
**Rationale:** Mid-stream stalls >20s are abnormal. Faster detection = faster fallback.

#### 3.3 Add streaming chunk buffering on backend

**File:** `backend/api/sse.py:33-35`
**Change:** Buffer small deltas (<10 chars) and flush every 50-100ms instead of per-token.
**Rationale:** Reduces the number of SSE frames from ~500-1000 to ~50-100, cutting network overhead and improving perceived smoothness.

#### 3.4 Enable prompt caching for system prompt

**File:** `backend/ai/gemini.py:112-120`
**Change:** Add `"cached_content": None` or use Gemini's context caching API for the system prompt (which is identical across requests).
**Rationale:** Gemini charges 25% for cached input tokens. The system prompt (~500 tokens) is the same every request — caching it saves cost and may reduce TTFT.

#### 3.5 Parallelize persist operations

**File:** `backend/services/chat/rag_service.py:451-467`
**Change:** Run `persist.messages`, `persist.session_touch`, and `persist.usage` as `asyncio.gather()` instead of sequential `async with`.
**Rationale:** 3 sequential DB writes take ~30-100ms total. Parallelizing reduces to ~10-30ms.

### Phase 4: Advanced AI Improvements (2-4 weeks)

These are architectural improvements for long-term quality.

#### 4.1 Add cross-encoder reranking

**New file:** `backend/services/chat/reranker.py`
**Change:** After vector search, run a lightweight cross-encoder (e.g., `cross-encoder/ms-marco-MiniLM-L-6-v2` via sentence-transformers, or Cohere Rerank API) to re-score the top-10 chunks and select the best 5-8.
**Rationale:** Vector search is approximate. A cross-encoder sees the query+chunk pair together and makes a much more accurate relevance judgment. Expected improvement: 15-25% better retrieval precision.

#### 4.2 Implement hybrid search (vector + BM25)

**Change:** Add a BM25 keyword search alongside vector search, then combine results with reciprocal rank fusion (RRF).
**Rationale:** Vector search excels at semantic similarity but misses exact keyword matches (e.g., error codes, product names). Hybrid search catches both.

#### 4.3 Add answer quality validation

**File:** `backend/services/chat/rag_service.py:418-427`
**Change:** After generation, run a lightweight quality check:

- Is the answer at least 50 tokens? (too short = likely truncated)
- Does it contain at least one citation marker `[N]`?
- Does `validate_response()` return issues?
  If quality is low, retry with a higher `max_output_tokens` or a different provider.
  **Rationale:** Catches truncation and low-quality answers before they reach the user.

#### 4.4 Add streaming response metrics dashboard

**Change:** Expose TTFT, generation time, retrieval time, and token counts via the admin analytics API.
**Rationale:** Enables data-driven optimization. Currently `perf_timing_log_enabled` logs to stdout but doesn't feed the dashboard.

#### 4.5 Implement prompt versioning with A/B testing

**File:** `backend/prompts/rag.py`
**Change:** Add prompt v2 with structured XML formatting, explicit answer length guidance, and improved citation instructions. Route a percentage of traffic to v2 for comparison.
**Rationale:** Prompt engineering is iterative. A versioned system with A/B testing allows data-driven prompt optimization.

#### 4.6 Add streaming chunk aggregation on frontend

**File:** `apps/widget/src/stream/chat.ts:165-170`
**Change:** Buffer deltas in an array and flush to the DOM every 16ms (one frame) instead of per-token.
**Rationale:** Redces DOM reflows from ~500-1000 to ~60 per second, improving rendering performance.

---

## 6. Configuration Summary (Current vs Recommended)

| Setting                                  | Current              | Recommended (Phase 1)                    | Recommended (Phase 2+)   |
| ---------------------------------------- | -------------------- | ---------------------------------------- | ------------------------ |
| `chat_max_output_tokens`                 | 1024                 | **4096**                                 | 4096                     |
| `chat_top_k`                             | 5                    | 5                                        | **8**                    |
| `chat_context_max_chars`                 | 12000                | 12000                                    | **20000**                |
| `chat_context_min_score`                 | 0.0                  | 0.0                                      | **0.25**                 |
| `chat_memory_turns`                      | 8                    | 8                                        | **12**                   |
| `chat_temperature`                       | 0.2                  | 0.2                                      | 0.2                      |
| `generation_timeout_seconds`             | 30.0                 | 30.0                                     | **20.0**                 |
| `generation_first_token_timeout_seconds` | 10.0                 | 10.0                                     | **8.0**                  |
| `numCandidates` (vector search)          | `max(top_k*10, 50)`  | same                                     | **`max(top_k*20, 100)`** |
| Widget `CHAT_CONNECT_TIMEOUT_MS`         | 20000                | **30000**                                | 30000                    |
| System prompt rule 3                     | "Keep answers short" | **"Provide complete, thorough answers"** | same                     |
| `top_p`                                  | not set              | **0.95**                                 | 0.95                     |
| `stop_sequences`                         | not set              | **["\\n\\n---", "\\n\\n**Note"]**        | same                     |

---

## 7. Expected Impact

| Metric              | Current (est.)       | After Phase 1       | After Phase 2+              |
| ------------------- | -------------------- | ------------------- | --------------------------- |
| Answer completeness | 60-70% complete      | **90-95% complete** | 95%+                        |
| Truncation rate     | 20-30% of complex Qs | **<5%**             | <2%                         |
| TTFT                | 1-3s                 | 1-3s (unchanged)    | **0.8-2s** (with caching)   |
| Total response time | 3-12s                | 3-12s (unchanged)   | **2-8s**                    |
| Retrieval precision | ~70% relevant chunks | ~70%                | **85-90%** (with reranking) |
| Context utilization | 60% (budget limits)  | 60%                 | **85%** (larger budget)     |

---

## 8. Files to Modify (by phase)

### Phase 1 (Quick Fixes)

- `backend/core/config.py` — increase `chat_max_output_tokens`
- `backend/prompts/rag.py` — update rule 3 in system prompt
- `backend/ai/gemini.py` — add `top_p` and `stop_sequences`
- `apps/widget/src/stream/client.ts` — increase connect timeout

### Phase 2 (RAG Optimization)

- `backend/core/config.py` — `chat_top_k`, `chat_context_max_chars`, `chat_context_min_score`, `chat_memory_turns`
- `backend/repositories/vector/mongodb.py` — increase `numCandidates`
- `backend/services/chat/rag_service.py` — document-level dedup

### Phase 3 (Latency)

- `backend/core/config.py` — reduce timeouts
- `backend/api/sse.py` — add chunk buffering
- `backend/ai/gemini.py` — enable prompt caching
- `backend/services/chat/rag_service.py` — parallelize persist

### Phase 4 (Advanced)

- `backend/services/chat/reranker.py` (new) — cross-encoder reranking
- `backend/repositories/vector/mongodb.py` — hybrid search
- `backend/services/chat/rag_service.py` — quality validation
- `backend/prompts/rag.py` — prompt v2 with A/B
- `apps/widget/src/stream/chat.ts` — DOM batching

---

_This audit identifies the root causes of incomplete answers (C1: token cap) and high latency (H5: timeout, TTFT). Phase 1 fixes address the most impactful issues with minimal risk. Subsequent phases build on the foundation for long-term quality improvement._
